"""PDF, born-digital or scanned: real redaction, not a rectangle on top.

The distinction is the whole point. Drawing a black box over a name leaves the
name in the content stream, selectable and copyable, which is how redaction
scandals happen. PyMuPDF's ``apply_redactions()`` deletes the glyphs from the
stream, so the characters stop existing rather than stop being visible. On a
scanned page there are no glyphs — the text *is* the image — and the same call
blanks the image pixels inside the rectangle, editing the image stream rather than
covering it. Re-running OCR on the output no longer reads the value.

Anchoring is per span, with a bounding box recorded for every single character.
That is what lets an arbitrary character range — the eleven digits inside a
longer line — be turned into an exact rectangle. Working from span bounding boxes
alone would redact whole spans and destroy text that was never confidential.

The decision to machine-read is taken **per page**, not per document, because a
real file mixes them: a contract exported from Word with a signed page scanned
back in. PyMuPDF drives Tesseract itself and returns a text page in the page's own
coordinate system with the same structure as the text layer, so extraction,
anchoring and redaction are one code path for both kinds of page.

OCR is a reading, not the text. A codice fiscale with one character misread fails
its checksum, is therefore never detected, and survives. That is inherent to
redacting a scan, and every OCR'd page is named in a warning for exactly that
reason.

Two behaviours of the underlying library shape this module and are worth knowing
before changing anything here:

* Replacement text is appended to the end of the page content stream, so a naive
  extraction of the output reports it out of reading order. Extracting with
  ``sort=True`` restores the correct order. This is a property of how redaction
  annotations are filled in, not something this module can avoid.
* If the replacement text does not fit the rectangle it is silently dropped.
  Removal still happens, so the file is safe, but the placeholder disappears
  without a word. :meth:`PdfTextHandler.write_back` shrinks the font to fit and
  records a warning when even that is not enough.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.errors import InputTooLarge, MalformedDocument, MissingDependency
from ..core.limits import refuse_too_many_pages
from ..core.stream import AnchorEdit, TextStream, TextStreamBuilder
from .base import FormatHandler, HiddenItem

if TYPE_CHECKING:  # pragma: no cover
    import pymupdf

#: Base-14 font used for every placeholder. The original typeface is usually an
#: embedded subset that has no glyphs for the characters a placeholder needs, so
#: substituting it is not an option; the mismatch is cosmetic and reported.
PLACEHOLDER_FONT = "helv"

#: Stop shrinking here. Below this a placeholder is unreadable anyway, and
#: dropping it with a warning beats pretending it is legible.
MIN_FONT_SIZE = 4.0

#: A page with less than this much text is treated as having no text layer.
#: Scanned pages often carry a stray character or two from a stamp or a header.
MIN_CHARS_PER_PAGE = 8

#: Reported by PyMuPDF alongside real metadata but describing the file rather
#: than its author, so listing them as removed confidential content is noise.
NON_SENSITIVE_METADATA_KEYS = frozenset({"format", "encryption"})

#: Languages requested from Tesseract, all at once: the document's language is
#: not known, and a scrubber that has to guess it before it can read the page has
#: an extra way to fail silently. Nine of them, one per language spoken in the
#: countries whose identifiers this build confirms — twelve countries need nine
#: languages, not twelve.
#:
#: Asking for more is close to free in time. Measured on one page: 248 ms for a
#: single language, 298 ms for four, so roughly 17 ms per extra language. The real
#: cost is on disk, at 14 to 15 MB of language data each, which is why this list
#: tracks the supported countries rather than everything Tesseract offers.
DEFAULT_OCR_LANGUAGE = "ita+deu+fra+eng+spa+nld+por+pol+swe"

#: Rasterisation resolution for OCR. 200 is the usual floor for reliable
#: recognition of body text; 72 loses characters and 300 costs time for little
#: gain on documents rather than photographs.
DEFAULT_OCR_DPI = 200

#: The repository's own copy, holding the four corpus languages. Checked before
#: the system's, because a Homebrew install of Tesseract ships English only and a
#: checkout that has bothered to download Italian should get Italian.
_PROJECT_TESSDATA = Path(__file__).resolve().parent.parent.parent / "models" / "tessdata"


def _windows_roots(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Where Windows installs Tesseract, read from the environment, not ``C:\\``.

    The two literal paths in the lists below covered only a machine-wide install
    on the system drive, and a real Windows machine reported OCR missing after a
    manual install: the UB Mannheim installer offers "install just for me", which
    lands under ``%LOCALAPPDATA%``, ``Program Files`` need not be on ``C:``, and
    Scoop keeps its own tree. None of the three puts anything on ``PATH`` by
    default, which is the whole reason these lists exist.

    Read once, at import, into ``_WINDOWS_ROOTS``: these name where the host keeps
    programs, which does not change while a process runs - unlike
    ``FREEDOCS_TESSERACT``, which a caller sets mid-session and is read per call.
    Empty off Windows, where none of the variables exist.
    """
    roots: list[str] = []
    # Machine-wide first: an administrator's install is the one a managed fleet
    # expects to be used. `ProgramW6432` is the 64-bit directory even from a
    # 32-bit process, where `ProgramFiles` is redirected to the x86 one.
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        if environ.get(variable):
            roots.append(os.path.join(environ[variable], "Tesseract-OCR"))
    local = environ.get("LOCALAPPDATA")
    if local:
        # The per-user default of an NSIS multi-user installer, then a flatter
        # path some per-user installs use. Neither has been observed on a
        # Windows machine from here; a wrong guess costs one `stat`.
        roots.append(os.path.join(local, "Programs", "Tesseract-OCR"))
        roots.append(os.path.join(local, "Tesseract-OCR"))
    scoop = environ.get("SCOOP") or (
        os.path.join(environ["USERPROFILE"], "scoop") if environ.get("USERPROFILE") else None
    )
    if scoop:
        # The app directory and not `shims\`: a shim is a launcher reading a
        # sidecar file, and PyMuPDF should run the program itself.
        roots.append(os.path.join(scoop, "apps", "tesseract", "current"))
    # Ordered and deduplicated: on a 64-bit process the first two variables agree.
    return tuple(dict.fromkeys(roots))


_WINDOWS_ROOTS = _windows_roots(os.environ)

#: Where each platform's package manager puts language data. Listed rather than
#: shelled out for, because asking Tesseract costs a subprocess and this runs on
#: every PDF. Every path is checked for actual ``.traineddata`` before it counts,
#: so a stale entry is harmless.
_SYSTEM_TESSDATA = (
    # macOS: Homebrew on Apple silicon, then Intel, then MacPorts.
    "/opt/homebrew/share/tessdata",
    "/usr/local/share/tessdata",
    "/opt/local/share/tessdata",
    # Debian and Ubuntu version the directory; Fedora and Arch do not.
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tesseract-ocr/tessdata",
    "/usr/share/tessdata",
    "/usr/local/share/tesseract-ocr/tessdata",
    # Windows: wherever this host keeps programs, then the literal defaults in
    # case the environment was stripped by whoever started the process.
    *(os.path.join(root, "tessdata") for root in _WINDOWS_ROOTS),
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
)

#: Where each platform's package manager puts the executable, checked when
#: ``PATH`` does not answer. Deliberately parallel to ``_SYSTEM_TESSDATA``, and
#: the reason the two halves need the same treatment is that the *launch context*
#: varies rather than the installation: a macOS ``.app`` started from Finder or
#: ``open`` inherits launchd's environment, so its ``PATH`` is
#: ``/usr/bin:/bin:/usr/sbin:/sbin`` and a Homebrew install can never be on it,
#: whatever the user installs next. That produced a bundle reporting "the
#: Tesseract executable is not on PATH" on a machine where `brew install
#: tesseract` had already succeeded — accurate, and advice that fixes nothing.
#: The tessdata half was immune because it was already a list.
_SYSTEM_BINARIES = (
    # macOS: Homebrew on Apple silicon, then Intel, then MacPorts.
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/local/bin/tesseract",
    # Already on the minimal PATH above, and free to list.
    "/usr/bin/tesseract",
    # Windows for the same class of bug, not for symmetry: the UB Mannheim
    # installer's "add to PATH" checkbox is optional, so an ordinary install is
    # invisible to `shutil.which` there too. See `_WINDOWS_ROOTS` for where.
    *(os.path.join(root, "tesseract.exe") for root in _WINDOWS_ROOTS),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


#: What PyMuPDF will actually look for on ``PATH``. Not this module's choice:
#: nothing here runs Tesseract, and the process that does resolves it by bare name
#: and takes no argument for it. So a candidate whose filename is not this cannot
#: be adopted, however runnable it is - see :func:`_resolvable_by_name`.
_BINARY_NAME = "tesseract.exe" if os.name == "nt" else "tesseract"


def _tessdata_candidates() -> list[str]:
    return [
        candidate
        for candidate in (
            # An explicit choice always wins.
            os.environ.get("FREEDOCS_TESSDATA"),
            os.environ.get("TESSDATA_PREFIX"),
            # Beside the executable, which is where a packaged build would put it.
            str(Path(sys.executable).resolve().parent / "tessdata"),
            # And inside it, which is where PyInstaller actually puts it. The spec
            # adds the `.traineddata` with destination "tessdata"; with no
            # `contents_directory` set, PyInstaller 6 places datas under
            # `_internal/`, so the candidate above looks one level too high. Both
            # are listed rather than one being corrected, because the spec's
            # layout is PyInstaller's to change and a directory with no
            # `.traineddata` in it costs a `glob` to reject.
            str(Path(getattr(sys, "_MEIPASS", sys.prefix)) / "tessdata"),
            str(_PROJECT_TESSDATA),
            *_SYSTEM_TESSDATA,
        )
        if candidate
    ]


def tesseract_binary() -> str | None:
    """Where the Tesseract executable is, or None.

    PyMuPDF does not link Tesseract, it shells out to it — `subprocess.run
    ("tesseract --list-langs")` — so the language data is only half of what OCR
    needs. This exists because the two halves are installed separately and a
    packaged build ships one of them: bundling the `.traineddata` files without
    checking for the binary made `capabilities.ocr_available` true on every
    machine, so the window promised OCR and the first scan failed.

    ``FREEDOCS_TESSERACT`` wins when it names an executable file. A portable build
    is the one shape that cannot rely on ``PATH``: it is unzipped onto a machine
    that installed nothing, so this is how a caller supplies the half that cannot
    be bundled. It is validated rather than trusted, because a path that does not
    resolve must leave :func:`ocr_unavailable_reason` saying OCR is unavailable —
    an override that could bypass that check would let the capability and the
    refusal disagree, which is the bug this module already shipped once.

    ``PATH`` comes next, so a caller who put a chosen build on it still gets that
    one. ``_SYSTEM_BINARIES`` is the last resort and exists because ``PATH`` is a
    property of how the process was started: see that constant for the Finder
    launch that reported no Tesseract on a machine that had one.
    """
    override = _adopted_override()
    if override is not None:
        return override
    # No adoption needed on this branch: a binary found through PATH is on PATH,
    # which is the only thing PyMuPDF will consult.
    found = shutil.which("tesseract")
    if found is not None:
        return found
    for candidate in _SYSTEM_BINARIES:
        path = Path(candidate)
        if not _is_executable(path):
            continue
        # Bound and tested rather than returned, because `_adopt` can refuse: a
        # `return _adopt(path)` would let one unadoptable leftover in an early
        # location end the scan and hide a real install in a later one.
        adopted = _adopt(path)
        if adopted is not None:
            return adopted
    return None


def _is_executable(path: Path) -> bool:
    """Can this file actually be run, asked the way each platform answers it.

    ``os.access(path, os.X_OK)`` is the POSIX answer and is *not* an answer on
    Windows, where it is true for any file that exists — execution there is
    decided by the extension, not by a permission bit. Accepting whatever it said
    would let a path pass validation here and fail inside PyMuPDF, which is the
    one thing this module must not do; the Windows job caught it.
    """
    if not path.is_file():
        return False
    if os.name != "nt":
        return os.access(path, os.X_OK)
    # PATHEXT is what the shell itself consults. Split on a literal `;` and not
    # `os.pathsep`: this branch is already the Windows one, where the two happen
    # to agree, so `os.pathsep` reads as portable while being the separator of
    # whatever host is running the code. That is exactly wrong for a test that
    # exercises this branch from macOS — where it is `:`, and PATHEXT then never
    # splits at all.
    extensions = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    known = {part.strip().upper() for part in extensions.split(";") if part.strip()}
    return path.suffix.upper() in known


def _resolvable_by_name(candidate: Path) -> bool:
    """Would PyMuPDF find *this* file when it looks up ``tesseract``?

    :func:`_adopt` puts a candidate's **directory** on ``PATH`` and PyMuPDF then
    resolves the bare name, so the file that gets executed is whichever one in
    that directory is called ``tesseract``. For every caller that existed before
    a person could choose the path that was the same file by construction:
    ``_SYSTEM_BINARIES`` names it, and ``FREEDOCS_TESSERACT`` is set by a script
    that knows the name.

    A file picker breaks that assumption, and it breaks it in the worst
    direction. ``/opt/mine/tesseract-5.3.4`` is runnable, so it passes
    :func:`_is_executable`; ``tesseract_binary`` returns it and
    :func:`ocr_unavailable_reason` therefore says OCR is available - and PyMuPDF
    then resolves ``tesseract`` in that directory, finds a different build or
    nothing, and the first scan fails. That is the capability and the refusal
    disagreeing, which is the one thing this module exists to prevent.

    Compared case-insensitively on Windows for the same reason
    :func:`_is_executable` branches there: ``PATH`` lookup is case-insensitive on
    that platform and is not on this one.
    """
    if os.name == "nt":
        return candidate.name.casefold() == _BINARY_NAME.casefold()
    return candidate.name == _BINARY_NAME


def _adopt(candidate: Path) -> str | None:
    """Report a binary found off ``PATH``, having first put it on ``PATH``.

    None when the candidate is not named what PyMuPDF looks for, decided
    *before* the side effect - see :func:`_resolvable_by_name`. Refusing here
    rather than at each call site is the same argument the side effect itself
    carries: two copies of a load-bearing rule is one copy that gets forgotten.

    The side effect is the point, and reporting the path without it would be the
    lie this function exists to avoid: nothing here runs Tesseract.
    :meth:`PdfTextHandler` asks PyMuPDF, PyMuPDF shells out, and it resolves
    ``tesseract`` through ``PATH`` — it has no argument for the executable, only
    for the language data. So a binary that merely satisfied
    :func:`ocr_unavailable_reason` would report OCR available and then fail on the
    first scan, which is precisely the shape of the bug that made
    ``ocr_unavailable_reason`` the single authority in the first place.

    Shared by the two routes that can name a binary ``PATH`` does not — the
    override and ``_SYSTEM_BINARIES`` — because two copies of a load-bearing side
    effect is one copy that gets forgotten.

    Idempotent: called from a getter that several callers reach on every page.
    """
    if not _resolvable_by_name(candidate):
        return None
    directory = str(candidate.parent)
    path = os.environ.get("PATH") or ""
    if directory not in path.split(os.pathsep):
        os.environ["PATH"] = f"{directory}{os.pathsep}{path}" if path else directory
    return str(candidate)


def _adopted_override() -> str | None:
    """``FREEDOCS_TESSERACT``, validated and adopted, or None."""
    configured = os.environ.get("FREEDOCS_TESSERACT")
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    if not _is_executable(candidate):
        return None
    return _adopt(candidate)


#: Why a Tesseract somebody chose was not adopted. Enum-shaped, unlike
#: :func:`ocr_unavailable_reason`, which is a sentence: a caller can translate
#: these, and the two values are kept apart because the next move differs - pick a
#: different file, versus rename or symlink this one.
TESSERACT_NOT_EXECUTABLE = "not_executable"
TESSERACT_WRONG_NAME = "wrong_name"


def adopt_tesseract(candidate: Path) -> str | None:
    """Point this process at a Tesseract somebody chose. None when it took.

    Writes ``FREEDOCS_TESSERACT`` rather than adopting the path directly, because
    :func:`_adopted_override` reads that variable on *every* call: the variable is
    what makes a choice survive the next question instead of the next line, and it
    means there is no second place holding "which Tesseract" - the override
    already was that place.

    Restores the previous value when the choice is refused. A rejected path left
    in the environment is state nobody chose, and it would leave ``doctor``
    naming an override that is not being used.

    This is the one function in this module a caller on the other end of a pipe
    can reach, so the authority it grants is worth stating rather than implying.
    :func:`_adopt` puts a directory on this process's ``PATH`` and PyMuPDF
    executes ``tesseract`` out of it, so this is exec-adjacent: it is strictly
    less than the arbitrary file read and write ``rpc`` already hands its caller
    by design, and it is a different class beside it. Two facts bound it. The
    target must already carry the executable bit - :func:`_is_executable` decides,
    and nothing here ever chmods - and it must already be *named* ``tesseract``,
    which is :func:`_resolvable_by_name` and is why that check is not optional
    politeness. Nothing reachable over the pipe writes a file satisfying both.
    """
    previous = os.environ.get("FREEDOCS_TESSERACT")
    if not _is_executable(candidate):
        return TESSERACT_NOT_EXECUTABLE
    if not _resolvable_by_name(candidate):
        return TESSERACT_WRONG_NAME
    os.environ["FREEDOCS_TESSERACT"] = str(candidate)
    if _adopted_override() is None:  # pragma: no cover - both refusals above
        # Belt and braces, and it restores rather than leaving the variable set:
        # the two checks above are the same ones `_adopted_override` applies, so
        # reaching here means they disagreed and the environment must not keep a
        # path this function did not vouch for.
        if previous is None:
            del os.environ["FREEDOCS_TESSERACT"]
        else:
            os.environ["FREEDOCS_TESSERACT"] = previous
        return TESSERACT_NOT_EXECUTABLE
    return None


def ocr_unavailable_reason() -> str | None:
    """What is missing, or None when OCR can actually run.

    One place decides, so the capability the window shows and the refusal the
    engine raises cannot disagree about whether a scan is readable.
    """
    missing = []
    if tesseract_binary() is None:
        missing.append(
            "no Tesseract executable was found on PATH or in the usual install locations"
        )
    if tessdata_path() is None:
        missing.append("no directory with .traineddata files was found")
    if not missing:
        return None
    return " and ".join(missing)


def tessdata_path() -> str | None:
    """The first usable Tesseract language directory, or None if there is none.

    A directory only counts if it actually holds ``.traineddata``. PyMuPDF's
    ``get_tessdata()`` echoes ``TESSDATA_PREFIX`` without checking it exists, so
    trusting it produces a confusing failure deep inside Tesseract instead of a
    clear "OCR is not available" here.
    """
    for candidate in _tessdata_candidates():
        directory = Path(candidate)
        if directory.is_dir() and any(directory.glob("*.traineddata")):
            return candidate
    return None


def missing_languages() -> list[str]:
    """Which of ``DEFAULT_OCR_LANGUAGE`` the directory OCR would use lacks.

    Not part of :func:`ocr_unavailable_reason`, whose contract is "can a scan be
    read at all" - changing that is recorded as its own piece of work. This
    answers a narrower question for one caller: whether an install needs to bring
    languages, or only the binary. Homebrew's ``tesseract-lang`` is every language
    Tesseract has, over a gigabyte, and an installer that already carries the nine
    should not make somebody download it to read a scan.
    """
    wanted = DEFAULT_OCR_LANGUAGE.split("+")
    directory = tessdata_path()
    if directory is None:
        return wanted
    return [
        language
        for language in wanted
        if not (Path(directory) / f"{language}.traineddata").is_file()
    ]


def _count_chars(raw: dict) -> int:
    return sum(
        len(span.get("chars", ()))
        for block in raw.get("blocks", ())
        for line in block.get("lines", ())
        for span in line.get("spans", ())
    )


class ScannedPdfNotSupported(RuntimeError):
    """The PDF has no usable text layer, so there is nothing to redact.

    Raised rather than returning the file untouched. A scan that comes back
    "clean" having never been examined is the most dangerous possible output:
    the user believes it was processed.
    """


def _pymupdf() -> Any:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise MissingDependency(
            "PyMuPDF is required for PDF support; install the 'pdf' extra"
        ) from exc
    return pymupdf


@dataclass(frozen=True)
class PdfSpanLocator:
    """Where a span's characters live on the page.

    ``char_boxes`` holds one bounding box per character of the anchored text, in
    order, so any sub-range can be turned back into a rectangle.
    """

    page: int
    char_boxes: tuple[tuple[float, float, float, float], ...]
    font_size: float


#: Exceptions this module refuses to let escape as themselves. PyMuPDF raises
#: `FzErrorBase` subclasses for a malformed file and plain `RuntimeError` through
#: some of its older paths, and both mean "the document is broken" rather than
#: "FreeDocs is broken" - which is what they read as when they reach a caller.
#:
#: Not `except Exception`: that would file a genuine bug in this code as a bad
#: document, which is the worse diagnosis. Our own errors are re-raised first,
#: because `MissingDependency` and `ModelNotFound` are `RuntimeError` subclasses.
_OURS = (MalformedDocument, InputTooLarge, MissingDependency, ScannedPdfNotSupported)


@contextlib.contextmanager
def _translating(name: str, doing: str) -> Iterator[None]:
    """Turn a library's account of a broken PDF into this engine's.

    Wrapped around every entry point rather than only the constructor, which is
    where the first version of this stopped. `scripts/fuzz.py` found the rest in
    its first four hundred cases: twenty escapes from `scrub()`, twelve from
    reading a page's contents, one from loading a page at all. Same class of
    defect each time, and none of them reachable by reasoning about which inputs
    to try.
    """
    try:
        yield
    except _OURS:
        raise
    except Exception as exc:
        if not _is_library_error(exc):
            raise
        raise MalformedDocument(f"{name}: PyMuPDF could not {doing}: {exc}") from exc


def _is_library_error(exc: BaseException) -> bool:
    """Whether this came out of MuPDF rather than out of us."""
    module = type(exc).__module__ or ""
    return module.startswith(("pymupdf", "fitz")) or type(exc) is RuntimeError


class PdfTextHandler(FormatHandler):
    name = "pdf-text"
    extensions = (".pdf",)

    #: Requested from Tesseract when a page has to be machine-read.
    ocr_language: str = DEFAULT_OCR_LANGUAGE
    ocr_dpi: int = DEFAULT_OCR_DPI
    #: Machine-read every page carrying an image, not only those whose text layer
    #: looks empty. Set by :meth:`harden_for_verification`; off during extraction
    #: because OCRing a born-digital page is pure cost.
    ocr_every_imaged_page: bool = False

    def __init__(self, path: Path, data: bytes) -> None:
        super().__init__(path, data)
        self._fitz = _pymupdf()
        # MuPDF's own errors are translated here rather than left to escape.
        # A page tree whose kids are all one object comes back as
        # `RuntimeError: code=7: Invalid number of pages`, which is a true
        # sentence about MuPDF and a useless one to a caller: from the CLI it is
        # a traceback, and `rpc.handle` renders an unexpected exception straight
        # into a response. The library being right about the file is not the same
        # as the caller being told about it.
        try:
            self._doc = self._fitz.open(stream=data, filetype="pdf")
            pages = self._doc.page_count
        except Exception as exc:
            raise MalformedDocument(f"{path.name} is not a readable PDF: {exc}") from exc
        # Before a page is touched. The cost of reading a PDF is not bounded by
        # its size - 200 000 distinct pages fit in 21 MB - and with OCR on, at a
        # measured 24 ms a page, `harden_for_verification` then reads them all
        # again.
        refuse_too_many_pages(path.name, pages)
        self.ocr_pages: list[int] = []

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> bool:
        # Trust the magic bytes over the extension: a PDF is still a PDF when
        # someone has renamed it.
        return head.startswith(b"%PDF-")

    # -- extraction ------------------------------------------------------------

    def extract(self) -> TextStream:
        with _translating(self.path.name, "read this PDF"):
            return self._extract()

    def _extract(self) -> TextStream:
        builder = TextStreamBuilder()
        #: Pages that were machine-read. Reported, because an OCR misreading is a
        #: character this tool cannot detect.
        self.ocr_pages: list[int] = []
        unreadable: list[int] = []

        for page_index, page in enumerate(self._doc):
            part = f"page:{page_index + 1}"
            # sort=True gives reading order even when the content stream is in a
            # different sequence, which matters for the detector's context window.
            raw = page.get_text("rawdict", sort=True)
            count = _count_chars(raw)

            # A page with no text is either a scan or genuinely blank, and the two
            # need opposite treatment: OCR the first, ignore the second. An image
            # is what distinguishes them. In verification mode every imaged page is
            # read, however much text it already has: a redacted scan carries the
            # placeholders that replaced its content, which is enough text to look
            # like an ordinary page while the pixels go unchecked.
            if page.get_images() and (count < MIN_CHARS_PER_PAGE or self.ocr_every_imaged_page):
                ocr = self._ocr(page)
                if ocr is None:
                    unreadable.append(page_index + 1)
                else:
                    raw = page.get_text("rawdict", sort=True, textpage=ocr)
                    self.ocr_pages.append(page_index + 1)
                    if _count_chars(raw) < MIN_CHARS_PER_PAGE:
                        self.warn(
                            f"page {page_index + 1} carries an image that OCR found no "
                            "text in; if it holds text this tool cannot see, nothing on "
                            "it was redacted"
                        )

            self._add_page(builder, raw, part, page_index)

            # Every page, not only the machine-read ones. Reporting only the OCR
            # pages of a mixed document makes the bar fly through the
            # born-digital pages and then appear to stall, which reads as a
            # hang on the one stage that really does take minutes.
            self.report_progress(
                page_index + 1,
                self._doc.page_count,
                "read by OCR" if page_index + 1 in self.ocr_pages else "",
            )

        if unreadable:
            raise ScannedPdfNotSupported(
                f"{self.path.name} has no usable text layer on page(s) "
                f"{', '.join(str(number) for number in unreadable)}, and OCR is not "
                f"available: {ocr_unavailable_reason()}. Install Tesseract and point "
                "FREEDOCS_TESSDATA or TESSDATA_PREFIX at its language data. This "
                "build will not pretend to have processed a scan it could not read."
            )

        if self.ocr_pages:
            # OCR is a reading, not the text. A codice fiscale with one character
            # misread fails its checksum and is therefore never detected, so it
            # survives. That is a limitation of scanned-document redaction, not a
            # bug, and the user has to know which pages it applies to.
            self.warn(
                "page(s) "
                + ", ".join(str(number) for number in self.ocr_pages)
                + " were read by OCR. A value OCR misreads cannot be detected, so "
                "check those pages by eye before sending the file"
            )
        return builder.build()

    def _add_page(self, builder: TextStreamBuilder, raw: dict, part: str, page: int) -> None:
        for block in raw.get("blocks", ()):
            # Image blocks have no "lines". On an OCR'd page the recognised text
            # arrives as ordinary text blocks alongside them.
            for line in block.get("lines", ()):
                for span in line.get("spans", ()):
                    chars = span.get("chars", ())
                    text = "".join(char["c"] for char in chars)
                    if not text:
                        continue
                    builder.add(
                        text,
                        part=part,
                        locator=PdfSpanLocator(
                            page=page,
                            char_boxes=tuple(tuple(char["bbox"]) for char in chars),
                            font_size=float(span.get("size", 11.0)),
                        ),
                    )
                # One newline per line, so the detector sees line boundaries
                # rather than words fused across them.
                builder.add_filler("\n")
            builder.add_filler("\n")

    def _ocr(self, page: pymupdf.Page) -> object | None:
        """Machine-read one page, or None if OCR is unavailable.

        PyMuPDF drives Tesseract itself and hands back a text page in the *page's*
        coordinate system, with a bounding box per character. That is the same
        shape the text layer produces, so everything downstream — anchoring,
        detection, the rectangle a redaction covers — works unchanged. Rasterising
        and mapping pixel coordinates by hand would have been the same result with
        an extra chance to get the transform wrong.
        """
        tessdata = tessdata_path()
        if tessdata is None or tesseract_binary() is None:
            return None
        try:
            return page.get_textpage_ocr(
                flags=0, language=self.ocr_language, dpi=self.ocr_dpi, full=True, tessdata=tessdata
            )
        except Exception as exc:
            self.warn(f"OCR failed on page {page.number + 1} ({exc}); nothing on it was redacted")
            return None

    def harden_for_verification(self) -> None:
        """OCR every imaged page when checking output, whatever text it carries.

        A redacted scan holds the placeholders that replaced its content, which is
        enough text for the ordinary heuristic to skip OCR. Verification would
        then have inspected the placeholders and never the image pixels, which is
        the only place the confidential data ever was: a failed pixel redaction
        would have passed.
        """
        self.ocr_every_imaged_page = True

    # -- hidden content --------------------------------------------------------

    def scrub_hidden(self) -> list[HiddenItem]:
        with _translating(self.path.name, "strip this PDF's hidden content"):
            return self._scrub_hidden()

    def _scrub_hidden(self) -> list[HiddenItem]:
        """Strip everything the reader never sees, and say what went.

        Inventory first, then remove: the library's ``scrub()`` reports nothing
        about what it did, and a report that cannot name what was removed teaches
        the user nothing about where their leaks live.
        """
        removed = self._inventory_hidden()

        self._doc.scrub(
            attached_files=True,
            clean_pages=True,
            embedded_files=True,
            # Deliberately kept: invisible text is exactly what an OCR layer over
            # a scan is made of. Deleting it blind would throw away content this
            # pipeline is able to detect and redact properly.
            hidden_text=False,
            javascript=True,
            metadata=True,
            # Our own redactions are added later, in write_back; scrub must not
            # consume or interfere with them.
            redactions=False,
            remove_links=True,
            reset_fields=True,
            reset_responses=True,
            thumbnails=True,
            xml_metadata=True,
        )

        # Outlines survive scrub() and routinely carry names and case numbers.
        if self._doc.get_toc():
            self._doc.set_toc([])

        # Annotations also survive scrub(): it has no flag for them, only for
        # links and annotation responses. A sticky note holding "cliente moroso"
        # was still in the output until this was added, while the report claimed
        # the annotation had been removed. Delete them for real.
        for page in self._doc:
            annot = page.first_annot
            while annot:
                annot = page.delete_annot(annot)

        return removed

    def _inventory_hidden(self) -> list[HiddenItem]:
        items: list[HiddenItem] = []

        populated = sorted(
            key
            for key, value in (self._doc.metadata or {}).items()
            if value and key not in NON_SENSITIVE_METADATA_KEYS
        )
        if populated:
            items.append(HiddenItem(part="document", kind="metadata", detail=", ".join(populated)))

        if self._doc.get_xml_metadata():
            items.append(HiddenItem(part="document", kind="xmp-metadata", detail="XMP packet"))

        embedded = self._doc.embfile_names()
        if embedded:
            items.append(
                HiddenItem(
                    part="document",
                    kind="embedded-files",
                    # The count, never the names. An attachment is routinely called
                    # after the person or the case it concerns, and this reaches
                    # `build_report`, which is written to disk beside the scrubbed
                    # document.
                    detail=f"{len(embedded)} file(s) attached to the document",
                )
            )

        toc = self._doc.get_toc()
        if toc:
            items.append(
                HiddenItem(part="document", kind="outline", detail=f"{len(toc)} bookmark(s)")
            )

        if self._doc.is_form_pdf:
            items.append(
                HiddenItem(part="document", kind="form-fields", detail="AcroForm values reset")
            )

        ocgs = self._doc.get_ocgs()
        if ocgs:
            # Reported, not removed: layers can hold the whole visible content of
            # a page, so deleting them would destroy the document. The user needs
            # to know they exist.
            items.append(
                HiddenItem(
                    part="document",
                    kind="optional-content-layers",
                    detail=f"{len(ocgs)} layer(s) present and left in place - inspect manually",
                )
            )

        for page_index, page in enumerate(self._doc):
            annots = [annot.type[1] for annot in page.annots()]
            if annots:
                items.append(
                    HiddenItem(
                        part=f"page:{page_index + 1}",
                        kind="annotations",
                        detail=f"{len(annots)}: {', '.join(sorted(set(annots)))}",
                    )
                )
            widgets = list(page.widgets())
            if widgets:
                items.append(
                    HiddenItem(
                        part=f"page:{page_index + 1}",
                        kind="form-widgets",
                        detail=f"{len(widgets)} field(s)",
                    )
                )
        return items

    # -- write-back ------------------------------------------------------------

    def write_back(self, edits: list[AnchorEdit]) -> bytes:
        with _translating(self.path.name, "write this PDF back"):
            return self._write_back(edits)

    def _write_back(self, edits: list[AnchorEdit]) -> bytes:
        touched_pages: set[int] = set()

        for edit in edits:
            locator = edit.anchor.locator
            if not isinstance(locator, PdfSpanLocator):
                raise TypeError(f"expected a PdfSpanLocator, got {type(locator).__name__}")
            boxes = locator.char_boxes[edit.local_start : edit.local_end]
            if not boxes:
                continue

            rect = self._fitz.Rect(boxes[0])
            for box in boxes[1:]:
                rect.include_rect(box)

            page = self._doc[locator.page]
            touched_pages.add(locator.page)
            self._add_redaction(page, rect, edit.replacement, locator.font_size)

        for page_index in sorted(touched_pages):
            self._doc[page_index].apply_redactions()

        if touched_pages:
            # Worth saying out loud, because the next thing this file meets is
            # usually a text extractor feeding an LLM: placeholders are appended
            # to the end of the page content stream, so an extractor that does
            # not sort by position reports them after the body text instead of
            # in place. Most tools have a sort option; PyMuPDF's is sort=True.
            self.warn(
                "placeholders are appended to the end of each page's content "
                "stream, so extract the output with reading-order sorting enabled "
                "or they will appear detached from their context"
            )

        # Full rewrite, never an incremental save: an incremental update appends
        # the new version and leaves the original objects, redacted values
        # included, earlier in the same file.
        return self._doc.tobytes(garbage=4, clean=True, deflate=True)

    def _add_redaction(
        self, page: pymupdf.Page, rect: pymupdf.Rect, replacement: str, font_size: float
    ) -> None:
        if not replacement:
            # A later slice of a multi-anchor edit: remove the characters, add no
            # text. The replacement went into the first slice.
            page.add_redact_annot(rect, fill=(1, 1, 1), cross_out=False)
            return

        size = self._fit_font_size(replacement, rect.width, font_size)
        if size is None:
            self.warn(
                f"placeholder {replacement!r} does not fit the space its original "
                f"occupied ({rect.width:.0f}pt) even at {MIN_FONT_SIZE:g}pt, so the "
                "text was removed without a visible marker"
            )
            page.add_redact_annot(rect, fill=(1, 1, 1), cross_out=False)
            return

        if size < font_size:
            self.warn(
                f"placeholder {replacement!r} was shrunk from {font_size:g}pt to "
                f"{size:g}pt to fit the original's width"
            )
        page.add_redact_annot(
            rect,
            text=replacement,
            fontname=PLACEHOLDER_FONT,
            fontsize=size,
            fill=(1, 1, 1),
            text_color=(0, 0, 0),
            cross_out=False,
        )

    def _fit_font_size(self, text: str, width: float, preferred: float) -> float | None:
        """Largest size at or below ``preferred`` that fits, or None if none does."""
        size = max(preferred, MIN_FONT_SIZE)
        while size >= MIN_FONT_SIZE:
            if self._fitz.get_text_length(text, fontname=PLACEHOLDER_FONT, fontsize=size) <= width:
                return size
            size -= 0.5
        return None

"""The contract every file format implements.

Extraction and write-back are mirror images: one flattens the document into an
anchored :class:`~freedocs.core.stream.TextStream`, the other pushes edits back
through those same anchors. Everything between them — detection, policy, verify —
never learns what format it is working on.

Adding a format means implementing three methods and nothing else. That is the
whole point of the anchor abstraction, and it is what makes covering docx, xlsx,
pptx and two flavours of PDF tractable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..core.stream import AnchorEdit, TextStream


@dataclass(frozen=True)
class HiddenItem:
    """Something removed that the user never saw on screen.

    Metadata, tracked changes, speaker notes, pivot caches. Reported separately
    from text findings because it is the leak users do not expect, and a report
    that buries it teaches nothing.

    **``detail`` is a description, never a value.** Every one of these reaches
    ``report.build_report``, which is written to disk beside the scrubbed
    document, so a detail that quotes the document undoes the removal for anyone
    who reads either file. Two of them did: a hidden sheet's name and a PDF's
    embedded filenames, both of which are exactly the identifying strings the
    scrub exists to take out. Say how many, say where, say what kind - and let the
    reader open the output, where whatever survived is visible anyway.

    ``part`` and ``kind`` are structural: a part name is the package's own
    vocabulary and a kind comes from a closed set, so neither can carry a value.
    """

    part: str
    kind: str
    detail: str

    def __post_init__(self) -> None:
        # The window translates ``kind`` by key, so a kind outside the set
        # reaches a reader as a raw slug. Refused here, where the handler author
        # is, rather than discovered on somebody's screen.
        if self.kind not in HIDDEN_KINDS:
            raise ValueError(f"unknown hidden-content kind {self.kind!r}; add it to HIDDEN_KINDS")


#: Every ``HiddenItem.kind`` a handler may report. Closed because it is a
#: vocabulary the desktop window translates into four languages; a test in
#: ``tests/test_readable.py`` checks each one has a label there.
HIDDEN_KINDS = frozenset(
    {
        # Document properties
        "metadata",
        "extended-metadata",
        "custom-properties",
        "xmp-metadata",
        "titles-of-parts",
        "hyperlink-cache",
        "page-thumbnail",
        "custom-xml-store",
        "printer-settings",
        "macro-project",
        "data-connections",
        # Comments and revisions
        "comments",
        "comment-anchors",
        "comment-ids",
        "comment-metadata",
        "comment-shapes",
        "comment-threading",
        "commenter-directory",
        "revision-markup",
        "revision-save-ids",
        "revision-save-id-table",
        "tracked-deletions",
        "tracked-insertions",
        # Things hidden from view
        "hidden-cells",
        "hidden-sheet",
        "hidden-slide",
        "offscreen-shape",
        "pivot-cache",
        "external-link-cache",
        # PDF
        "annotations",
        "embedded-files",
        "form-fields",
        "form-widgets",
        "optional-content-layers",
        "outline",
    }
)


#: Where in a document a piece of text sits, in the words a reader uses. Closed,
#: for the reason ``HIDDEN_KINDS`` is: the window translates it.
REGION_KINDS = frozenset(
    {
        "body",
        "header",
        "footer",
        "footnote",
        "endnote",
        "comment",
        "link",
        "metadata",
        "sheet",
        "chart",
        "slide",
        "notes",
        "page",
        "other",
    }
)


@dataclass(frozen=True)
class Region:
    """A part of a document named for a person rather than for the package.

    ``word/footnotes.xml`` and ``page:3`` are the engine's vocabulary; "a
    footnote" and "page 3" are the reader's. ``number`` is set only where the
    format really has one a reader could find - a PDF page, a slide, a sheet's
    position - and never invented: a Word document has no pages until Word lays
    it out, so nothing here can say which page a word is on.
    """

    kind: str
    number: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in REGION_KINDS:
            raise ValueError(f"unknown region kind {self.kind!r}")


class FormatHandler(ABC):
    """Reads one document, exposes its text, writes a scrubbed copy."""

    #: Human-readable name, used in reports.
    name: str = "unknown"
    #: Extensions this handler claims, lowercase and dot-prefixed.
    extensions: tuple[str, ...] = ()

    def __init__(self, path: Path, data: bytes) -> None:
        self.path = path
        self.data = data
        #: Degradations the handler had to accept, in plain language.
        #:
        #: A format cannot always honour a request exactly: a placeholder may not
        #: fit the space the original occupied, a font may not be substitutable.
        #: Removal is still guaranteed, but the compromise has to reach the user
        #: rather than being swallowed, so the report surfaces whatever lands
        #: here.
        self.warnings: list[str] = []
        #: Where to report extraction progress, when anyone is listening.
        self._progress: Callable[[int, int, str], None] | None = None

    def warn(self, message: str) -> None:
        """Record a degradation. The message is a description, never a value.

        Same rule as :class:`HiddenItem`, and for the same reason: this list
        reaches ``report.build_report`` and lands on disk. The trap here is
        subtler, because a handler's natural phrasing is to quote the text it
        could not write - ``XlsxHandler`` named the sheets it had renamed, which
        are the identifying names the rename existed to remove. Where a name is
        genuinely the useful part, report what the thing is called *now*: a
        placeholder is a label the scrubbed output already publishes.

        The one exception is not an exception to this rule but a consequence of
        it: on the restore path a placeholder's replacement *is* the original
        value, so ``build_restore_report`` carries these as a count and leaves the
        sentences on the console and the pipe.
        """
        if message not in self.warnings:
            self.warnings.append(message)

    def set_progress(self, report: Callable[[int, int, str], None] | None) -> None:
        """Take somewhere to report progress to, or nowhere.

        The handler learns nothing about stages, notifications or JSON: it counts
        the unit it actually has — pages, mostly — and the pipeline decides what
        that means to a caller.
        """
        self._progress = report

    def report_progress(self, done: int, of: int, detail: str = "") -> None:
        """Say how far reading has got, when the handler can count it honestly.

        Optional on purpose. A handler with no countable unit calls nothing
        rather than inventing a denominator, and a caller that sees no counts
        knows only that the stage is running — which is the truth.
        """
        if self._progress is not None:
            self._progress(done, of, detail)

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> bool:
        """Whether this handler can process the file.

        Extension-based by default. Handlers whose formats share a container
        (every OOXML file is a zip) override this to look inside.
        """
        return path.suffix.lower() in cls.extensions

    @abstractmethod
    def extract(self) -> TextStream:
        """Flatten the document into anchored text."""

    @abstractmethod
    def write_back(self, edits: list[AnchorEdit]) -> bytes:
        """Return the document bytes with ``edits`` applied through the anchors."""

    def scrub_hidden(self) -> list[HiddenItem]:
        """Remove metadata and non-visible content, reporting what went.

        Default is a no-op: plain text has nowhere to hide anything. Every
        container format overrides this, and for those formats it matters more
        than the visible text.
        """
        return []

    def harden_for_verification(self) -> None:
        """Reconfigure this handler to re-read output as adversarially as possible.

        Called by :mod:`freedocs.verify` on the handler it builds over the
        scrubbed bytes, never on the one that produced them. A format may read
        less than everything for speed during extraction; when the question is
        "did anything survive", the cheap reading is not good enough.

        The case that forced this: a scanned page is machine-read only when its
        text layer looks empty. After redaction that page carries a couple of
        placeholder strings, which is enough text to look like a normal page, so
        verification checked the placeholders and never looked at the image
        pixels — the only place the confidential data had ever been.

        Default is a no-op: for most formats one reading is the reading.
        """
        return None

    def region_of(self, part: str) -> Region:
        """Name the part an anchor came from in the reader's words.

        The default suits a format with one undivided body, which is plain text.
        """
        return Region("body")

    def verification_extras(self, stream: TextStream) -> str:
        """Text in the output that ``extract`` does not read, for stage 6 alone.

        Verification searches what a handler extracts, so anything else in the
        container is invisible to it. ``docProps/app.xml`` held a second copy of
        every hyperlink address on a real document, the scrub had removed each
        one from the body, and verification passed. This hook is where a format
        hands over the rest - text nothing is meant to edit and nothing should
        have left a value in.

        Only parts ``stream`` does not already anchor: an anchored part is
        already in the search, and counting it twice would break the per-value
        allowance a kept occurrence earns. Never fed to detection or write-back.
        Default is empty: a plain-text file has no rest.
        """
        return ""

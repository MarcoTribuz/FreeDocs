"""How big a thing may be before this engine refuses to read it.

One module because the answer is asked in four unrelated places - the router, the
OOXML container, the PDF handler and the key file - and four answers is four
things to keep current. It is the shape ``core/text.py`` took for diacritic
folding, and for the same reason: the bug that motivated that one was two copies
of a function disagreeing.

**Why any of this exists.** Every input is hostile by definition: this tool is
pointed at documents from outside and parses them with C libraries in a process
holding the user's own privileges. Before these limits, ``router.handler_for``
read the whole file with ``read_bytes()`` and ``OoxmlPackage.open`` read *every*
entry into a dict, both with no ceiling of any kind. A 0.20 MB container built
from four compressible parts took 334 MB of resident memory, which is a ratio of
about 1000:1 - so a 20 MB attachment is 20 GB. The engine is single-threaded with
no cancel by design, so exhausting it is exhausting the session, and the Tauri
side then waits out a ten-minute timeout while the sidecar keeps allocating.

**The numbers are generous on purpose, and each one is a measurement.** A limit
that refuses a document somebody actually has is a regression, not a hardening -
so these are set well above the largest realistic input rather than snugly above
the corpus, and the reasoning is recorded beside each so the next person can move
one without re-deriving it.

**No inflation-ratio check, and that was measured away.** The obvious rule -
refuse when inflated bytes over container bytes exceeds some multiple - was
written into the plan and then not built. Real Office files sit at 22 to 24:1, so
any ratio loose enough to pass them is loose enough to pass a bomb of the same
shape, and the absolute ceilings below already refuse that bomb without needing
to guess. The ratio would only have added a way to refuse a legitimate
text-heavy spreadsheet.

**The declared size is trusted, and that is sound rather than lazy.** A pre-check
on ``ZipInfo.file_size`` looks naive, because the header is attacker-controlled.
Measured: ``ZipExtFile`` decompresses at most the declared number of bytes and
then fails the CRC, so a header claiming 1 KB for a 20 MB payload yields *no*
bytes rather than 20 MB of them. That is what makes it safe to decide from
``infolist()`` before reading anything, and it is why the size-counting stream
wrapper this was going to need is absent. ``tests/test_hostile_input.py`` pins
the behaviour, because it is somebody else's implementation detail.
"""

from __future__ import annotations

from .errors import InputTooLarge

#: The whole file, read into memory by ``router.handler_for`` before anything
#: looks at it. 512 MB is far above the largest realistic input: a 200-page
#: colour scan is around 100 MB, and the biggest thing in this repository's own
#: examples is 37 KB.
MAX_INPUT_BYTES = 512 * 1024 * 1024

#: One OOXML part, inflated. Separate from the total because they are different
#: attacks: a single ceiling of 512 MB lets one 400 MB part through, and a part
#: that large is not a document either way.
MAX_ENTRY_BYTES = 256 * 1024 * 1024

#: Every part of one container added up, embedded packages included. A chart's
#: workbook is a zip inside a zip, so nesting is a second place the same bytes
#: can arrive from and it spends the same budget - otherwise the nesting *is*
#: the way past this.
MAX_INFLATED_BYTES = 512 * 1024 * 1024

#: Pages in a PDF. Measured rather than guessed, and the number that matters is
#: not the one you would expect: 200 000 distinct empty pages fit in 21 MB and
#: extract in eleven seconds, which alone would be survivable. What is not is the
#: same count with OCR, at a measured 24 ms a page - eighty minutes - after which
#: ``harden_for_verification`` reads every page again. 10 000 is several times the
#: largest realistic bundle.
MAX_PDF_PAGES = 10_000

#: A key file. A few hundred bytes an entry puts this at thousands of them, so
#: nothing this tool writes can reach it and a file that does is not a key file.
#: Read before ``read_text``, which takes the whole thing into memory and hands
#: it to ``json.loads`` to take again.
MAX_MAP_BYTES = 8 * 1024 * 1024

#: Entries in a term list. A firm's client register runs to hundreds or a few
#: thousand; 10 000 is several times that. The cost that bounds it is matching,
#: not storage: every entry is a substring search over the whole extraction, on
#: every inspect and every scrub, and every kept occurrence in the preview
#: re-inspects. Measured: 10 000 entries against 600 000 characters - about two
#: hundred pages - is 1.3 s of ``Override.apply``, linear in both, so a list of
#: five hundred costs 65 ms on the same document. Past this ceiling a click in
#: the preview starts to feel like a scan being read.
MAX_TERMS = 10_000

#: One entry. A client or matter name is tens of characters; a value this long
#: is a pasted paragraph, and matching a paragraph literally finds nothing.
MAX_TERM_CHARS = 500

#: A sealed term list on disk, read before ``read_text``. At the two ceilings
#: above and base64's 4/3 the largest legitimate file is about 7 MB, so this is
#: the key file's ceiling again.
MAX_TERMS_BYTES = 8 * 1024 * 1024

#: A plaintext list offered for import. The same reason as the sealed file, and
#: generous: an export from a CRM carries columns this reader ignores.
MAX_TERMS_IMPORT_BYTES = 16 * 1024 * 1024

#: Pasted text, in characters. The pipe is not what bounds it: a request is one
#: JSON line, and ``json.loads`` of a 5 MB line costs 0.01 s. Detection is.
#: Measured on the densest realistic paste, one IBAN a line: 1 MB is 8 s and
#: 47 MB resident, 5 MB is 14 s and 121 MB. Two million characters is about six
#: hundred pages - past anything anyone pastes - and a wait a person will sit
#: through. A document that size belongs in a file, where the preview is cached.
MAX_TEXT_CHARS = 2_000_000


def refuse_oversized_input(name: str, size: int) -> None:
    """Refuse a file too large to be a document, before it is read."""
    if size > MAX_INPUT_BYTES:
        raise InputTooLarge(
            f"{name} is {_mb(size)} and this build reads a document of up to {_mb(MAX_INPUT_BYTES)}"
        )


def refuse_oversized_archive(name: str, sizes: list[int], *, already: int = 0) -> None:
    """Refuse a container whose parts do not fit, from the sizes alone.

    ``already`` carries what a parent package has spent, so an embedded workbook
    is charged against the same budget as the presentation that holds it.

    Read at call time from the module attributes above rather than captured as
    defaults, which is what lets a test lower a ceiling instead of allocating
    half a gigabyte to prove one exists. The same trap ``DEFAULT_LABELS`` carries
    for the NER backend.
    """
    for size in sizes:
        if size > MAX_ENTRY_BYTES:
            raise InputTooLarge(
                f"{name} holds a part of {_mb(size)}; this build reads a part of up "
                f"to {_mb(MAX_ENTRY_BYTES)}"
            )
    total = already + sum(sizes)
    if total > MAX_INFLATED_BYTES:
        raise InputTooLarge(
            f"{name} expands to {_mb(total)}; this build reads a container that "
            f"expands to at most {_mb(MAX_INFLATED_BYTES)}"
        )


def refuse_too_many_pages(name: str, pages: int) -> None:
    """Refuse a PDF longer than any document, before a page is touched."""
    if pages > MAX_PDF_PAGES:
        raise InputTooLarge(
            f"{name} declares {pages} pages; this build reads up to {MAX_PDF_PAGES}"
        )


def refuse_too_many_terms(name: str, count: int) -> None:
    """Refuse a term list longer than any client register, before it is used."""
    if count > MAX_TERMS:
        raise InputTooLarge(
            f"{name} holds {count} entries; this build reads a term list of up to {MAX_TERMS}"
        )


def refuse_oversized_text(count: int) -> None:
    """Refuse a paste longer than any paste, naming only its length."""
    if count > MAX_TEXT_CHARS:
        raise InputTooLarge(
            f"the pasted text is {count} characters and this build reads up to "
            f"{MAX_TEXT_CHARS}; save it as a file and scrub that instead"
        )


def _mb(size: int) -> str:
    """Sizes in the unit a person refusing a document thinks in."""
    return f"{size / (1024 * 1024):.1f} MB"

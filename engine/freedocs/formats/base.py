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

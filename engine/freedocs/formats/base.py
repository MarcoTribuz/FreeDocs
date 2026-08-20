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
from dataclasses import dataclass
from pathlib import Path

from ..core.stream import AnchorEdit, TextStream


@dataclass(frozen=True)
class HiddenItem:
    """Something removed that the user never saw on screen.

    Metadata, tracked changes, speaker notes, pivot caches. Reported separately
    from text findings because it is the leak users do not expect, and a report
    that buries it teaches nothing.
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

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

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

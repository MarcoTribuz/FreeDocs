"""Picks the handler for a file.

Sniffing beats trusting the extension: OOXML files are zips, a ``.pdf`` may
actually be a scan needing OCR, and users rename things. Handlers are asked in
registration order and the first to claim the file wins, so more specific
handlers must register before more general ones.
"""

from __future__ import annotations

from pathlib import Path

from .base import FormatHandler
from .ooxml.docx import DocxHandler
from .ooxml.xlsx import XlsxHandler
from .pdf_text import PdfTextHandler
from .plaintext import PlainTextHandler

#: Registration order is significance order. PlainTextHandler stays last: it
#: claims a broad set of extensions and would shadow anything after it.
#:
#: PdfTextHandler is registered even though PyMuPDF is an optional extra. A
#: missing dependency then produces "install the pdf extra" rather than
#: "unsupported format", which is the difference between a fixable message and a
#: misleading one.
HANDLERS: list[type[FormatHandler]] = [
    DocxHandler,
    XlsxHandler,
    PdfTextHandler,
    PlainTextHandler,
]

#: How many bytes of the file the sniffers get to look at.
HEAD_BYTES = 4096


class UnsupportedFormat(RuntimeError):
    """No registered handler claimed the file."""


def register(handler: type[FormatHandler], *, first: bool = False) -> None:
    """Add a handler. Milestones that add a format call this at import time."""
    if first:
        HANDLERS.insert(0, handler)
    else:
        # Before PlainTextHandler, which is the deliberate catch-all.
        HANDLERS.insert(max(0, len(HANDLERS) - 1), handler)


def handler_for(path: Path, data: bytes | None = None) -> FormatHandler:
    """Return an initialised handler for ``path``.

    Reads the file once and passes the bytes to the handler, so a scrub never
    re-reads from disk and cannot see the file change underneath it.
    """
    payload = path.read_bytes() if data is None else data
    head = payload[:HEAD_BYTES]
    for candidate in HANDLERS:
        if candidate.sniff(path, head):
            return candidate(path, payload)
    raise UnsupportedFormat(
        f"no handler for {path.name!r}; supported extensions: "
        + ", ".join(sorted({ext for h in HANDLERS for ext in h.extensions}))
    )

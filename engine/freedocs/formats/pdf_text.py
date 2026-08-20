"""PDF with a text layer: real redaction, not a rectangle on top.

The distinction is the whole point. Drawing a black box over a name leaves the
name in the content stream, selectable and copyable, which is how redaction
scandals happen. PyMuPDF's ``apply_redactions()`` deletes the glyphs from the
stream, so the characters stop existing rather than stop being visible.

Anchoring is per span, with a bounding box recorded for every single character.
That is what lets an arbitrary character range — the eleven digits inside a
longer line — be turned into an exact rectangle. Working from span bounding boxes
alone would redact whole spans and destroy text that was never confidential.

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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


class MissingDependency(RuntimeError):
    """PyMuPDF is not installed."""


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


class PdfTextHandler(FormatHandler):
    name = "pdf-text"
    extensions = (".pdf",)

    def __init__(self, path: Path, data: bytes) -> None:
        super().__init__(path, data)
        self._fitz = _pymupdf()
        self._doc = self._fitz.open(stream=data, filetype="pdf")

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> bool:
        # Trust the magic bytes over the extension: a PDF is still a PDF when
        # someone has renamed it.
        return head.startswith(b"%PDF-")

    # -- extraction ------------------------------------------------------------

    def extract(self) -> TextStream:
        builder = TextStreamBuilder()
        total_chars = 0

        for page_index, page in enumerate(self._doc):
            part = f"page:{page_index + 1}"
            # sort=True gives reading order even when the content stream is in a
            # different sequence, which matters for the detector's context window.
            raw = page.get_text("rawdict", sort=True)
            for block in raw.get("blocks", ()):
                # Image blocks have no "lines"; nothing to extract until M6.
                for line in block.get("lines", ()):
                    for span in line.get("spans", ()):
                        chars = span.get("chars", ())
                        text = "".join(char["c"] for char in chars)
                        if not text:
                            continue
                        total_chars += len(text)
                        builder.add(
                            text,
                            part=part,
                            locator=PdfSpanLocator(
                                page=page_index,
                                char_boxes=tuple(tuple(char["bbox"]) for char in chars),
                                font_size=float(span.get("size", 11.0)),
                            ),
                        )
                    # One newline per line, so the detector sees line boundaries
                    # rather than words fused across them.
                    builder.add_filler("\n")
                builder.add_filler("\n")

        if total_chars < MIN_CHARS_PER_PAGE * max(1, self._doc.page_count):
            raise ScannedPdfNotSupported(
                f"{self.path.name} has {total_chars} extractable characters across "
                f"{self._doc.page_count} page(s), which means it has no usable text "
                "layer. Redacting a scan needs OCR, which arrives in M6; this build "
                "will not pretend to have processed it."
            )
        return builder.build()

    # -- hidden content --------------------------------------------------------

    def scrub_hidden(self) -> list[HiddenItem]:
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
                    detail=f"{len(embedded)} file(s): {', '.join(embedded)}",
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

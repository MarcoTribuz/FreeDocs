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

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.errors import MissingDependency
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

#: Languages requested from Tesseract. All four corpus languages at once: the
#: document's language is not known, and a scrubber that has to guess it before it
#: can read the page has an extra way to fail silently.
DEFAULT_OCR_LANGUAGE = "ita+deu+fra+eng"

#: Rasterisation resolution for OCR. 200 is the usual floor for reliable
#: recognition of body text; 72 loses characters and 300 costs time for little
#: gain on documents rather than photographs.
DEFAULT_OCR_DPI = 200

#: The repository's own copy, holding the four corpus languages. Checked before
#: the system's, because a Homebrew install of Tesseract ships English only and a
#: checkout that has bothered to download Italian should get Italian.
_PROJECT_TESSDATA = Path(__file__).resolve().parent.parent.parent / "models" / "tessdata"

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
    # Windows, both the UB Mannheim installer's default and the 32-bit path.
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
)


def _tessdata_candidates() -> list[str]:
    return [
        candidate
        for candidate in (
            # An explicit choice always wins.
            os.environ.get("FREEDOCS_TESSDATA"),
            os.environ.get("TESSDATA_PREFIX"),
            # Beside the executable, which is where a packaged build would put it.
            str(Path(sys.executable).resolve().parent / "tessdata"),
            str(_PROJECT_TESSDATA),
            *_SYSTEM_TESSDATA,
        )
        if candidate
    ]


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
        self._doc = self._fitz.open(stream=data, filetype="pdf")
        self.ocr_pages: list[int] = []

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> bool:
        # Trust the magic bytes over the extension: a PDF is still a PDF when
        # someone has renamed it.
        return head.startswith(b"%PDF-")

    # -- extraction ------------------------------------------------------------

    def extract(self) -> TextStream:
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

        if unreadable:
            raise ScannedPdfNotSupported(
                f"{self.path.name} has no usable text layer on page(s) "
                f"{', '.join(str(number) for number in unreadable)}, and OCR is not "
                "available. Install Tesseract and point FREEDOCS_TESSDATA or "
                "TESSDATA_PREFIX at its language data. This build will not pretend "
                "to have processed a scan it could not read."
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
        if tessdata is None:
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

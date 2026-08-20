"""Word documents, edited in place at run level.

This is the format the anchor design was built for. Word splits text across
``<w:r>`` runs whenever formatting changes — and often when it does not, after a
spell-check or an edit — so ``Mario Rossi`` routinely lives in three separate
elements. A detector needs it joined; a writer must put characters back into
those same three elements or the formatting is gone.

``extract()`` flattens every ``<w:t>`` into one stream, remembering the element
each character came from. ``write_back()`` sets ``.text`` on those same elements.
Nothing is rebuilt, no run is merged or invented, and every part nobody touched
is copied through as bytes.

Two details that are easy to get wrong and expensive to notice later:

* ``xml:space="preserve"`` has to be added when a replacement gains leading or
  trailing whitespace, or Word silently eats it and words fuse together.
* ``<w:instrText>`` is treated as text too. A HYPERLINK field holds its target
  there, so ``mailto:mario.rossi@example.com`` hides in a place no amount of
  reading the visible document would reveal.
"""

from __future__ import annotations

from pathlib import Path

from ...core.stream import AnchorEdit, TextStream, TextStreamBuilder
from ..base import FormatHandler, HiddenItem
from .common import add_relationship_targets, apply_ooxml_edits
from .docx_hidden import scrub_docx_hidden
from .zip_part import OoxmlPackage, qn

#: The part holding the document body.
DOCUMENT = "word/document.xml"

#: Parts whose text is part of the document and must be scrubbed as well.
#: Headers and footers are where the client name sits on every page, and
#: footnotes are where the caveat naming the person tends to live.
TEXT_PART_PREFIXES = (
    "word/header",
    "word/footer",
    "word/footnotes",
    "word/endnotes",
)

#: Elements whose ``.text`` is document content.
TEXT_TAGS = frozenset({qn("w:t"), qn("w:instrText")})

#: Structural elements that separate text. Emitted as filler so the detector sees
#: a boundary instead of two words fused across a cell or a line break.
PARAGRAPH_TAG = qn("w:p")
TAB_TAG = qn("w:tab")
BREAK_TAGS = frozenset({qn("w:br"), qn("w:cr")})


class DocxHandler(FormatHandler):
    name = "docx"
    extensions = (".docx", ".docm")

    def __init__(self, path: Path, data: bytes) -> None:
        super().__init__(path, data)
        self.package = OoxmlPackage.open(data)
        if not self.package.has(DOCUMENT):
            raise ValueError(f"{path.name} is an OOXML container but has no {DOCUMENT}")

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> bool:
        if not head.startswith(b"PK\x03\x04"):
            return False
        # The extension is the reliable signal for which OOXML format this is;
        # xlsx and pptx are the same container. The document part is verified in
        # __init__, so a mislabelled file fails with a clear message rather than
        # being processed as the wrong format.
        return path.suffix.lower() in cls.extensions

    # -- parts -----------------------------------------------------------------

    def text_parts(self) -> list[str]:
        """Every part contributing document text, in a stable order.

        Body first, then the rest sorted, so two files differing only in zip
        ordering produce the same stream and therefore the same offsets.
        """
        parts = [DOCUMENT]
        for prefix in TEXT_PART_PREFIXES:
            parts.extend(self.package.matching(prefix))
        return parts

    # -- extraction ------------------------------------------------------------

    def extract(self) -> TextStream:
        builder = TextStreamBuilder()
        for part in self.text_parts():
            tree = self.package.tree(part)
            # A single document-order pass over the whole part. Iterating
            # paragraphs and then their descendants would visit the contents of a
            # text box twice, once as the outer paragraph's descendants and once
            # as its own paragraph.
            for element in tree.iter():
                tag = element.tag
                if tag in TEXT_TAGS:
                    builder.add(element.text or "", part=part, locator=element)
                elif tag == PARAGRAPH_TAG:
                    # Emitted before the paragraph's own content, which is what
                    # makes nesting work without special cases.
                    builder.add_filler("\n")
                elif tag == TAB_TAG:
                    builder.add_filler("\t")
                elif tag in BREAK_TAGS:
                    builder.add_filler("\n")
            builder.add_filler("\n")

        # Hyperlink addresses live in the rels parts, not in the body: redacting
        # the visible link text would leave mailto:someone@example.com behind.
        add_relationship_targets(self.package, builder, "word/_rels")
        return builder.build()

    # -- hidden content --------------------------------------------------------

    def scrub_hidden(self) -> list[HiddenItem]:
        return scrub_docx_hidden(self.package)

    # -- write-back ------------------------------------------------------------

    def write_back(self, edits: list[AnchorEdit]) -> bytes:
        apply_ooxml_edits(self.package, edits)
        return self.package.to_bytes()

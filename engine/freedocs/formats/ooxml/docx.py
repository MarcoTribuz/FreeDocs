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

from dataclasses import dataclass
from pathlib import Path

from ...core.stream import AnchorEdit, TextStream, TextStreamBuilder, apply_anchor_edits
from ..base import FormatHandler, HiddenItem
from .hidden import RELATIONSHIP_TAG, scrub_docx_hidden
from .zip_part import NS, OoxmlPackage, qn

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

XML_SPACE = f"{{{NS['xml']}}}space"


@dataclass(frozen=True)
class AttributeLocator:
    """An anchor that points at an XML attribute rather than element text.

    Used for external relationship targets. A hyperlink's address lives in
    ``document.xml.rels``, not in the body, so redacting the visible link text
    leaves ``mailto:mario.rossi@example.com`` sitting in the file. Making the
    target an ordinary anchor means the normal detectors and the normal policy
    apply to it, instead of this module needing its own idea of what an email
    looks like.
    """

    element: object
    name: str


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

        self._add_relationship_targets(builder)
        return builder.build()

    def _add_relationship_targets(self, builder: TextStreamBuilder) -> None:
        """Expose external hyperlink targets to the detectors.

        Internal targets are skipped: they point at other parts of the same
        document and hold no addresses.
        """
        for part in self.package.matching("word/_rels", ".rels"):
            tree = self.package.tree(part)
            for relationship in tree.iter(RELATIONSHIP_TAG):
                if relationship.get("TargetMode") != "External":
                    continue
                target = relationship.get("Target") or ""
                if not target:
                    continue
                builder.add(target, part=part, locator=AttributeLocator(relationship, "Target"))
                # Filler between targets, so two adjacent URLs are never read as
                # one string by the detectors.
                builder.add_filler("\n")

    # -- hidden content --------------------------------------------------------

    def scrub_hidden(self) -> list[HiddenItem]:
        return scrub_docx_hidden(self.package)

    # -- write-back ------------------------------------------------------------

    def write_back(self, edits: list[AnchorEdit]) -> bytes:
        by_element: dict[int, list[AnchorEdit]] = {}
        for edit in edits:
            by_element.setdefault(id(edit.anchor.locator), []).append(edit)

        for element_edits in by_element.values():
            locator = element_edits[0].anchor.locator
            if isinstance(locator, AttributeLocator):
                self._edit_attribute(locator, element_edits)
            else:
                self._edit_text(locator, element_edits)

        return self.package.to_bytes()

    def _edit_text(self, element: object, edits: list[AnchorEdit]) -> None:
        original = element.text or ""  # type: ignore[attr-defined]
        replaced = apply_anchor_edits(original, edits)
        if replaced == original:
            return
        element.text = replaced  # type: ignore[attr-defined]
        _preserve_space(element, replaced)
        self.package.mark_dirty(edits[0].part)

    def _edit_attribute(self, locator: AttributeLocator, edits: list[AnchorEdit]) -> None:
        original = locator.element.get(locator.name) or ""  # type: ignore[attr-defined]
        replaced = apply_anchor_edits(original, edits)
        if replaced == original:
            return
        locator.element.set(locator.name, replaced)  # type: ignore[attr-defined]
        self.package.mark_dirty(edits[0].part)


def _preserve_space(element: object, text: str) -> None:
    """Keep leading and trailing whitespace from being stripped by Word.

    Without ``xml:space="preserve"`` a ``<w:t> paga.</w:t>`` loses its leading
    space and the previous word runs into this one. Only ever added, never
    removed: a document that already declared it meant it.
    """
    if text != text.strip() and element.get(XML_SPACE) != "preserve":  # type: ignore[attr-defined]
        element.set(XML_SPACE, "preserve")  # type: ignore[attr-defined]

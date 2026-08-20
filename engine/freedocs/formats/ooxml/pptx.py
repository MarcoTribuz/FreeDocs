"""PowerPoint presentations.

A deck hides text in more places than it shows it:

* **Speaker notes** are a separate part per slide. Nobody sees them on screen and
  everybody writes the sensitive version of the sentence there.
* **Hidden slides** (``<p:sld show="0">``) are skipped when presenting and are
  fully present in the file. So is the slide someone dragged off the canvas
  instead of deleting: a shape at ``x="-4000000"`` on a 9144000-wide slide is
  invisible and intact.
* **Charts embed their whole source workbook.** ``ppt/embeddings/*.xlsx`` is a
  complete OOXML package — sheets, string table, metadata — inside this one. A
  chart of three bars can carry a workbook of five hundred rows.
* **Alt text** on a picture is a description someone typed, and it is common for
  it to name what the picture shows.
* **SmartArt keeps its own data model** in ``ppt/diagrams/``, duplicating the
  text of the shapes it renders.

The embedded workbooks are handled by nesting a real
:class:`~freedocs.formats.ooxml.xlsx.XlsxHandler` inside this one and folding its
anchors into this stream. The whole detection and policy stack then applies to
the workbook inside the chart exactly as it would to a workbook on its own —
which is the point of anchors being independent of format.
"""

from __future__ import annotations

from pathlib import Path

from ...core.stream import AnchorEdit, TextStream, TextStreamBuilder
from ..base import FormatHandler, HiddenItem
from .common import add_attribute, add_relationship_targets, apply_ooxml_edits
from .pptx_hidden import scrub_pptx_hidden
from .xlsx import XlsxHandler
from .zip_part import NS, OoxmlPackage, qn

PRESENTATION = "ppt/presentation.xml"

#: Parts carrying slide text, in a stable order. Layouts and masters are included
#: because a customised layout holds real text, not just "Click to add title".
TEXT_PART_PREFIXES = (
    "ppt/slides/slide",
    "ppt/notesSlides/notesSlide",
    "ppt/slideLayouts/slideLayout",
    "ppt/slideMasters/slideMaster",
    "ppt/notesMasters/notesMaster",
    "ppt/diagrams/",
)

#: DrawingML holds all the text in a presentation, whatever shape contains it.
TEXT_TAG = qn("a:t")
PARAGRAPH_TAG = qn("a:p")
BREAK_TAG = qn("a:br")

#: Non-visual shape properties: ``name`` is the shape's name in the selection
#: pane, ``descr`` is its alt text.
SHAPE_PROPERTIES_TAGS = (qn("p:cNvPr"), qn("a:cNvPr"))

#: Chart caches, as in xlsx.
CHART_VALUE_TAG = f"{{{NS['c']}}}v"

#: Embedded packages we can scrub recursively. Presentations are excluded on
#: purpose: a deck embedding a deck would recurse, and one level is enough for
#: every real file.
NESTABLE_SUFFIXES = (".xlsx", ".xlsm")


class PptxHandler(FormatHandler):
    name = "pptx"
    extensions = (".pptx", ".pptm", ".potx", ".ppsx")

    def __init__(self, path: Path, data: bytes) -> None:
        super().__init__(path, data)
        self.package = OoxmlPackage.open(data)
        if not self.package.has(PRESENTATION):
            raise ValueError(f"{path.name} is an OOXML container but has no {PRESENTATION}")
        self._nested: dict[str, FormatHandler] | None = None
        #: ``id(locator)`` of every anchor belonging to an embedded package, so
        #: write-back can route its edits to the right handler. Keyed by identity
        #: rather than by a prefixed part name: no string to parse, nothing to
        #: get wrong when a part name happens to contain a separator.
        self._nested_locators: dict[int, str] = {}

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> bool:
        if not head.startswith(b"PK\x03\x04"):
            return False
        return path.suffix.lower() in cls.extensions

    # -- embedded packages -----------------------------------------------------

    def nested_handlers(self) -> dict[str, FormatHandler]:
        """Handlers for the OOXML packages embedded in this one, built once."""
        if self._nested is None:
            self._nested = {}
            for name in self.package.matching("ppt/embeddings/", ""):
                if not name.lower().endswith(NESTABLE_SUFFIXES):
                    continue
                try:
                    self._nested[name] = XlsxHandler(Path(name), self.package.raw(name))
                except Exception as exc:
                    # A malformed embedding must not take down the whole scrub,
                    # but it must not pass silently either: its contents stay in
                    # the file and the user has to know.
                    self.warn(
                        f"the workbook embedded at {name} could not be opened "
                        f"({exc}), so its contents were NOT scrubbed"
                    )
        return self._nested

    # -- extraction ------------------------------------------------------------

    def extract(self) -> TextStream:
        builder = TextStreamBuilder()
        for part in self._text_parts():
            tree = self.package.tree(part)
            for element in tree.iter():
                tag = element.tag
                if tag == TEXT_TAG:
                    builder.add(element.text or "", part=part, locator=element)
                elif tag in (PARAGRAPH_TAG, BREAK_TAG):
                    builder.add_filler("\n")
                elif tag in SHAPE_PROPERTIES_TAGS:
                    # Alt text and shape names, which no amount of reading the
                    # slide reveals. Filler first as well as after: these sit
                    # between one shape's text and the next, and without a
                    # boundary the detector reads "Clienti riservatiContent
                    # Placeholder 2" as one string.
                    builder.add_filler("\n")
                    add_attribute(builder, element, "descr", part=part)
                    add_attribute(builder, element, "name", part=part)
            builder.add_filler("\n")

        self._add_charts(builder)
        add_relationship_targets(self.package, builder, "ppt/")
        add_relationship_targets(self.package, builder, "_rels")
        self._add_embedded(builder)
        return builder.build()

    def _text_parts(self) -> list[str]:
        parts: list[str] = []
        for prefix in TEXT_PART_PREFIXES:
            parts.extend(self.package.matching(prefix))
        return parts

    def _add_charts(self, builder: TextStreamBuilder) -> None:
        for part in self.package.matching("ppt/charts/"):
            tree = self.package.tree(part)
            for element in tree.iter(CHART_VALUE_TAG):
                if element.text:
                    builder.add(element.text, part=part, locator=element)
                    builder.add_filler("\n")
            builder.add_filler("\n")

    def _add_embedded(self, builder: TextStreamBuilder) -> None:
        """Fold each embedded workbook's own stream into this one.

        The nested handler does the format-specific work; this only re-anchors
        its chunks at the parent's offsets. Filler between chunks rather than the
        nested stream's own separators: the offsets differ, and the detectors only
        need boundaries.
        """
        for name, handler in self.nested_handlers().items():
            nested = handler.extract()
            for anchor in nested.anchors:
                builder.add(
                    nested.text[anchor.start : anchor.end],
                    # The nested part name is kept unprefixed on purpose. It is
                    # what the nested package calls the part, and write-back uses
                    # it to mark that part dirty *in that package*. Prefixing it
                    # for readability meant mark_dirty was handed a name the
                    # nested package had never heard of, so the edit was made on
                    # the element and then thrown away in favour of the original
                    # bytes. Which embedding it came from is reported separately.
                    part=anchor.part,
                    locator=anchor.locator,
                )
                self._nested_locators[id(anchor.locator)] = name
                builder.add_filler("\n")

    # -- hidden content --------------------------------------------------------

    def scrub_hidden(self) -> list[HiddenItem]:
        removed = scrub_pptx_hidden(self.package)
        for name, handler in self.nested_handlers().items():
            for item in handler.scrub_hidden():
                removed.append(
                    HiddenItem(part=f"{name} :: {item.part}", kind=item.kind, detail=item.detail)
                )
        return removed

    # -- write-back ------------------------------------------------------------

    def write_back(self, edits: list[AnchorEdit]) -> bytes:
        own: list[AnchorEdit] = []
        nested: dict[str, list[AnchorEdit]] = {}
        for edit in edits:
            name = self._nested_locators.get(id(edit.anchor.locator))
            if name is None:
                own.append(edit)
            else:
                nested.setdefault(name, []).append(edit)

        apply_ooxml_edits(self.package, own)

        handlers = self.nested_handlers()
        for name, handler in handlers.items():
            # Re-serialised even with no edits of its own: its metadata was
            # scrubbed in scrub_hidden, and those changes live in the nested
            # package until they are written back into this one.
            rewritten = handler.write_back(nested.get(name, []))
            self.package.replace(name, rewritten)
            self.warn(
                f"the workbook embedded at {name} was scrubbed as a document in "
                "its own right; its chart still works, but its metadata is gone"
            )

        return self.package.to_bytes()

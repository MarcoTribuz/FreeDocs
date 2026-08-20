"""Excel workbooks.

Spreadsheets scatter their text more widely than any other format, and most of
the places are not cells:

* **The string table.** Excel deduplicates every string into
  ``xl/sharedStrings.xml`` and cells reference it by index. Redacting there fixes
  every cell at once. Other producers — ``openpyxl`` among them — write inline
  strings instead, so both have to be handled or half the real files are missed.
* **Sheet names appear twice.** Once in ``xl/workbook.xml`` and again in
  ``docProps/app.xml`` as ``TitlesOfParts``. Redacting one leaves the other, and a
  sheet called "Stipendi Rossi" is as identifying as a cell.
* **Caches hold copies of the data.** A pivot cache stores its own copy of the
  source rows. A chart stores its category labels. An external link stores the
  last-seen values of the workbook it points at. All three survive redacting
  every cell on every sheet.
* **Formulas contain literals**, and a formula's last computed string result is
  cached in the cell next to it.

The caches are redacted rather than deleted. Dropping a pivot cache leaves the
pivot table blank until someone refreshes it, and dropping a chart cache empties
the chart; editing the values in place removes the data and keeps the document
working. That is only possible because they are attributes and text nodes like
any other, reachable through :class:`~freedocs.formats.ooxml.common.AttributeLocator`.

Numeric cells are anchored only when they are long enough to be an identifier.
A spreadsheet is mostly numbers, and an eleven-digit partita IVA check passes on
roughly one in ten arbitrary numbers of that length — anchoring every amount
would turn the ledger into placeholders.
"""

from __future__ import annotations

from pathlib import Path

from ...core.stream import AnchorEdit, TextStream, TextStreamBuilder
from ..base import FormatHandler, HiddenItem
from .common import (
    AttributeLocator,
    add_attribute,
    add_relationship_targets,
    apply_ooxml_edits,
)
from .xlsx_hidden import scrub_xlsx_hidden
from .zip_part import NS, OoxmlPackage, qn

WORKBOOK = "xl/workbook.xml"
SHARED_STRINGS = "xl/sharedStrings.xml"

#: Shortest numeric cell value anchored as possibly-confidential. An AHV number
#: is 13 digits, a partita IVA 11, a codice fiscale is text; invoice totals and
#: quantities are shorter than this in any realistic sheet.
MIN_NUMERIC_LENGTH = 9

#: ``<t>`` in the spreadsheet namespace covers shared strings, inline strings and
#: comment text. ``<f>`` is a formula's source, which can hold string literals.
TEXT_TAG = qn("s:t")
FORMULA_TAG = qn("s:f")
VALUE_TAG = qn("s:v")
CELL_TAG = qn("s:c")
ROW_TAG = qn("s:row")
STRING_ITEM_TAG = qn("s:si")

#: Chart caches keep their labels here.
CHART_VALUE_TAG = f"{{{NS['c']}}}v"

#: ``docProps/app.xml`` lists every sheet name in these.
LPSTR_TAG = f"{{{NS['vt']}}}lpstr"

#: Cell types whose ``<v>`` holds text: a cached formula result, or an error.
TEXT_CELL_TYPES = frozenset({"str", "e"})

#: Excel rejects these in a sheet name, and a workbook containing one will not
#: open at all. The placeholder form ``[PERSONA_1]`` contains two of them.
ILLEGAL_NAME_CHARS = str.maketrans({character: "_" for character in r"[]:*?/\\"})

#: Excel's hard limit on a sheet name.
MAX_NAME_LENGTH = 31


def sanitise_name(value: str) -> str:
    """Make a redacted value legal as an Excel sheet or table name."""
    cleaned = value.translate(ILLEGAL_NAME_CHARS).strip("'")[:MAX_NAME_LENGTH]
    return cleaned or "_"


def _is_attribute(edit: AnchorEdit) -> bool:
    return isinstance(edit.anchor.locator, AttributeLocator)


class XlsxHandler(FormatHandler):
    name = "xlsx"
    extensions = (".xlsx", ".xlsm", ".xltx", ".xltm")

    def __init__(self, path: Path, data: bytes) -> None:
        super().__init__(path, data)
        self.package = OoxmlPackage.open(data)
        if not self.package.has(WORKBOOK):
            raise ValueError(f"{path.name} is an OOXML container but has no {WORKBOOK}")
        #: ``(kind, original name)`` for every sheet, table, column and defined
        #: name anchored. Used to warn about the references a rename breaks.
        self._named_entities: list[tuple[str, str]] = []

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> bool:
        if not head.startswith(b"PK\x03\x04"):
            return False
        return path.suffix.lower() in cls.extensions

    # -- extraction ------------------------------------------------------------

    def extract(self) -> TextStream:
        builder = TextStreamBuilder()
        self._add_shared_strings(builder)
        self._add_sheets(builder)
        self._add_workbook_names(builder)
        self._add_app_titles(builder)
        self._add_tables(builder)
        self._add_pivot_caches(builder)
        self._add_charts(builder)
        self._add_external_links(builder)
        add_relationship_targets(self.package, builder, "xl/")
        add_relationship_targets(self.package, builder, "_rels")
        return builder.build()

    def _add_shared_strings(self, builder: TextStreamBuilder) -> None:
        """The string table, one entry per distinct string in the workbook.

        A single edit here fixes every cell that references the entry, which is
        both correct and the reason a workbook with a name repeated in a thousand
        rows costs one replacement rather than a thousand.
        """
        if not self.package.has(SHARED_STRINGS):
            return
        tree = self.package.tree(SHARED_STRINGS)
        for item in tree.iter(STRING_ITEM_TAG):
            # Rich text splits one string into several <r><t> runs, exactly as
            # Word splits a paragraph into runs.
            for text_element in item.iter(TEXT_TAG):
                builder.add(text_element.text or "", part=SHARED_STRINGS, locator=text_element)
            builder.add_filler("\n")

    def _add_sheets(self, builder: TextStreamBuilder) -> None:
        for part in self.package.matching("xl/worksheets/sheet"):
            tree = self.package.tree(part)
            for row in tree.iter(ROW_TAG):
                for cell in row.iter(CELL_TAG):
                    self._add_cell(builder, cell, part)
                    builder.add_filler("\t")
                builder.add_filler("\n")
            builder.add_filler("\n")

    def _add_cell(self, builder: TextStreamBuilder, cell: object, part: str) -> None:
        cell_type = cell.get("t")  # type: ignore[attr-defined]
        for element in cell.iter():  # type: ignore[attr-defined]
            if element.tag == TEXT_TAG:
                # An inline string, written by producers that skip the table.
                builder.add(element.text or "", part=part, locator=element)
            elif element.tag == FORMULA_TAG:
                builder.add(element.text or "", part=part, locator=element)
            elif element.tag == VALUE_TAG:
                self._add_value(builder, element, cell_type, part)

    def _add_value(
        self, builder: TextStreamBuilder, element: object, cell_type: str | None, part: str
    ) -> None:
        text = element.text or ""  # type: ignore[attr-defined]
        if not text:
            return
        if cell_type == "s":
            # An index into the string table, not text. Redacting "42" here would
            # repoint the cell at an unrelated string.
            return
        if cell_type not in TEXT_CELL_TYPES and len(text) < MIN_NUMERIC_LENGTH:
            return
        builder.add(text, part=part, locator=element)

    def _add_workbook_names(self, builder: TextStreamBuilder) -> None:
        """Sheet names and defined names.

        A defined name's text is a formula reference, but its ``name`` attribute
        is user-chosen and routinely describes what the range holds.
        """
        tree = self.package.tree(WORKBOOK)
        for sheet in tree.iter(qn("s:sheet")):
            add_attribute(builder, sheet, "name", part=WORKBOOK, sanitise=sanitise_name)
            self._named_entities.append(("sheet", sheet.get("name") or ""))
        for defined in tree.iter(qn("s:definedName")):
            add_attribute(builder, defined, "name", part=WORKBOOK, sanitise=sanitise_name)
            self._named_entities.append(("defined name", defined.get("name") or ""))
            if defined.text:
                builder.add(defined.text, part=WORKBOOK, locator=defined)
                builder.add_filler("\n")

    def _add_app_titles(self, builder: TextStreamBuilder) -> None:
        """``TitlesOfParts`` in ``docProps/app.xml``: the sheet names, again.

        Redacting ``workbook.xml`` alone leaves a full list of sheet names in the
        metadata, which is the sort of half-measure this whole project exists to
        avoid.
        """
        part = "docProps/app.xml"
        if not self.package.has(part):
            return
        tree = self.package.tree(part)
        for element in tree.iter(LPSTR_TAG):
            if element.text:
                builder.add(element.text, part=part, locator=element)
                builder.add_filler("\n")

    def _add_tables(self, builder: TextStreamBuilder) -> None:
        for part in self.package.matching("xl/tables/"):
            tree = self.package.tree(part)
            for attribute in ("name", "displayName"):
                add_attribute(builder, tree, attribute, part=part, sanitise=sanitise_name)
            if tree.get("displayName"):
                self._named_entities.append(("table", tree.get("displayName")))
            for column in tree.iter(qn("s:tableColumn")):
                add_attribute(builder, column, "name", part=part, sanitise=sanitise_name)
                self._named_entities.append(("table column", column.get("name") or ""))

    def _add_pivot_caches(self, builder: TextStreamBuilder) -> None:
        """The pivot cache: Excel's own copy of the source rows.

        ``sharedItems`` lists every distinct value of every source field, so a
        pivot over a staff table contains the staff table. Redacting the cache
        keeps the pivot working; deleting it would leave it blank until refreshed.
        """
        for part in self.package.matching("xl/pivotCache/"):
            tree = self.package.tree(part)
            for element in tree.iter(qn("s:s")):
                add_attribute(builder, element, "v", part=part, separator="\t")
            builder.add_filler("\n")

    def _add_charts(self, builder: TextStreamBuilder) -> None:
        """Chart caches, which hold the category labels as plain text."""
        for part in self.package.matching("xl/charts/"):
            tree = self.package.tree(part)
            for element in tree.iter(CHART_VALUE_TAG):
                if element.text:
                    builder.add(element.text, part=part, locator=element)
                    builder.add_filler("\t")
            builder.add_filler("\n")

    def _add_external_links(self, builder: TextStreamBuilder) -> None:
        """Values cached from another workbook, plus its sheet names."""
        for part in self.package.matching("xl/externalLinks/"):
            tree = self.package.tree(part)
            for element in tree.iter(qn("s:sheetName")):
                add_attribute(builder, element, "val", part=part)
            for element in tree.iter(VALUE_TAG):
                if element.text:
                    builder.add(element.text, part=part, locator=element)
                    builder.add_filler("\t")
            builder.add_filler("\n")

    # -- hidden content --------------------------------------------------------

    def scrub_hidden(self) -> list[HiddenItem]:
        return scrub_xlsx_hidden(self.package)

    # -- write-back ------------------------------------------------------------

    def write_back(self, edits: list[AnchorEdit]) -> bytes:
        renamed = self._renamed_entities(edits)
        apply_ooxml_edits(self.package, edits)
        if renamed:
            # Excel stores a cross-sheet reference as the sheet's *name*
            # ('Clienti'!A1), and a structured reference as the table's name, so
            # redacting a name and leaving the formulas alone breaks them. The
            # alternative was to leave identifying names in the file, which the
            # leak check would rightly reject. Safety wins, and the cost is said
            # out loud rather than discovered later.
            self.warn(
                "renamed "
                + ", ".join(sorted(renamed))
                + "; formulas referring to them by name will need updating, and "
                "characters Excel forbids in a name were replaced with '_'"
            )
        return self.package.to_bytes()

    def _renamed_entities(self, edits: list[AnchorEdit]) -> set[str]:
        """Which named entities an edit actually touches."""
        touched = {edit.anchor.locator.read() for edit in edits if _is_attribute(edit)}
        return {f"{kind} {name!r}" for kind, name in self._named_entities if name in touched}

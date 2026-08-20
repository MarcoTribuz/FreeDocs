"""Builds .xlsx files containing the parts openpyxl will not produce.

openpyxl writes inline strings, no pivot cache, no external links and no
``TitlesOfParts``. Excel writes all four, and they are where a workbook's copies
of its own data live, so they have to be built by hand to be tested at all.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ODREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"

DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


@dataclass
class Sheet:
    name: str
    #: Each row is a list of cell values. Strings become shared-string
    #: references, numbers stay numeric.
    rows: list[list[str | int]] = field(default_factory=list)
    state: str = "visible"
    hidden_rows: tuple[int, ...] = ()
    hidden_columns: tuple[str, ...] = ()


@dataclass
class XlsxSpec:
    sheets: list[Sheet] = field(default_factory=list)
    creator: str = "Marco Tribuzio"
    title: str = "Riservato"
    company: str = "Realise Consulting SA"
    #: Blankable so a genuinely clean workbook can be built for the tests.
    total_time: str = "91"
    #: Emitted as ``TitlesOfParts``, which is where Excel repeats sheet names.
    app_titles: bool = True
    #: ``(name, reference)`` defined names.
    defined_names: list[tuple[str, str]] = field(default_factory=list)
    #: Distinct values to place in a pivot cache's ``sharedItems``.
    pivot_items: list[str] = field(default_factory=list)
    #: Values cached from another workbook, plus its sheet name.
    external_values: list[str] = field(default_factory=list)
    external_sheet: str = "Estratto"
    external_target: str | None = None
    #: Category labels cached inside a chart.
    chart_labels: list[str] = field(default_factory=list)
    #: A connection string, as Power Query and ODBC connections carry.
    connection: str | None = None
    #: Whether to include a binary macro project.
    macros: bool = False
    #: An external hyperlink target on the first sheet.
    hyperlink: str | None = None


def _shared_strings(spec: XlsxSpec) -> tuple[str, dict[str, int]]:
    """Collect every string in the sheets into a deduplicated table."""
    index: dict[str, int] = {}
    for sheet in spec.sheets:
        for row in sheet.rows:
            for value in row:
                if isinstance(value, str) and value not in index:
                    index[value] = len(index)
    items = "".join(f"<si><t>{_escape(text)}</t></si>" for text in index)
    xml = f'{DECL}\n<sst xmlns="{S}" count="{len(index)}" uniqueCount="{len(index)}">{items}</sst>'
    return xml, index


def _sheet_xml(sheet: Sheet, index: dict[str, int]) -> str:
    columns = "".join(
        f'<col hidden="1" min="{ord(letter) - 64}" max="{ord(letter) - 64}"/>'
        for letter in sheet.hidden_columns
    )
    rows = []
    for number, row in enumerate(sheet.rows, start=1):
        hidden = ' hidden="1"' if number in sheet.hidden_rows else ""
        cells = []
        for position, value in enumerate(row):
            reference = f"{chr(65 + position)}{number}"
            if isinstance(value, str):
                cells.append(f'<c r="{reference}" t="s"><v>{index[value]}</v></c>')
            else:
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
        rows.append(f'<row r="{number}"{hidden}>{"".join(cells)}</row>')
    cols = f"<cols>{columns}</cols>" if columns else ""
    return (
        f'{DECL}\n<worksheet xmlns="{S}">{cols}<sheetData>{"".join(rows)}</sheetData></worksheet>'
    )


def build_xlsx(spec: XlsxSpec) -> bytes:
    shared, index = _shared_strings(spec)
    parts: dict[str, str | bytes] = {}
    overrides: list[str] = []
    workbook_rels: list[str] = []

    sheet_entries = []
    for number, sheet in enumerate(spec.sheets, start=1):
        part = f"xl/worksheets/sheet{number}.xml"
        parts[part] = _sheet_xml(sheet, index)
        sheet_entries.append(
            f'<sheet name="{_escape(sheet.name)}" sheetId="{number}" '
            f'state="{sheet.state}" r:id="rIdS{number}"/>'
        )
        workbook_rels.append(
            f'<Relationship Id="rIdS{number}" Type="{ODREL}/worksheet" '
            f'Target="worksheets/sheet{number}.xml"/>'
        )
        overrides.append(
            f'<Override PartName="/{part}" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )

    parts["xl/sharedStrings.xml"] = shared
    workbook_rels.append(
        f'<Relationship Id="rIdSS" Type="{ODREL}/sharedStrings" Target="sharedStrings.xml"/>'
    )

    defined = "".join(
        f'<definedName name="{_escape(name)}">{_escape(reference)}</definedName>'
        for name, reference in spec.defined_names
    )
    parts["xl/workbook.xml"] = (
        f'{DECL}\n<workbook xmlns="{S}" xmlns:r="{ODREL}">'
        f"<sheets>{''.join(sheet_entries)}</sheets>"
        + (f"<definedNames>{defined}</definedNames>" if defined else "")
        + "</workbook>"
    )

    if spec.pivot_items:
        items = "".join(f'<s v="{_escape(value)}"/>' for value in spec.pivot_items)
        parts["xl/pivotCache/pivotCacheDefinition1.xml"] = (
            f'{DECL}\n<pivotCacheDefinition xmlns="{S}" recordCount="'
            f'{len(spec.pivot_items)}"><cacheFields count="1"><cacheField name="Nome">'
            f"<sharedItems>{items}</sharedItems></cacheField></cacheFields>"
            "</pivotCacheDefinition>"
        )
        workbook_rels.append(
            f'<Relationship Id="rIdPC" Type="{ODREL}/pivotCacheDefinition" '
            'Target="pivotCache/pivotCacheDefinition1.xml"/>'
        )

    if spec.external_values:
        cells = "".join(
            f'<cell r="A{number}" t="str"><v>{_escape(value)}</v></cell>'
            for number, value in enumerate(spec.external_values, start=1)
        )
        parts["xl/externalLinks/externalLink1.xml"] = (
            f'{DECL}\n<externalLink xmlns="{S}"><externalBook>'
            f'<sheetNames><sheetName val="{_escape(spec.external_sheet)}"/></sheetNames>'
            f'<sheetDataSet><sheetData sheetId="0">{cells}</sheetData></sheetDataSet>'
            "</externalBook></externalLink>"
        )
        workbook_rels.append(
            f'<Relationship Id="rIdEL" Type="{ODREL}/externalLink" '
            'Target="externalLinks/externalLink1.xml"/>'
        )
        if spec.external_target:
            parts["xl/externalLinks/_rels/externalLink1.xml.rels"] = (
                f'{DECL}\n<Relationships xmlns="{REL}">'
                f'<Relationship Id="rIdX" Type="{ODREL}/externalLinkPath" '
                f'Target="{_escape(spec.external_target)}" TargetMode="External"/>'
                "</Relationships>"
            )

    if spec.chart_labels:
        points = "".join(
            f'<c:pt idx="{number}"><c:v>{_escape(label)}</c:v></c:pt>'
            for number, label in enumerate(spec.chart_labels)
        )
        parts["xl/charts/chart1.xml"] = (
            f'{DECL}\n<c:chartSpace xmlns:c="{CHART}"><c:chart><c:plotArea>'
            f"<c:barChart><c:ser><c:cat><c:strRef><c:strCache>{points}"
            "</c:strCache></c:strRef></c:cat></c:ser></c:barChart>"
            "</c:plotArea></c:chart></c:chartSpace>"
        )

    if spec.connection:
        parts["xl/connections.xml"] = (
            f'{DECL}\n<connections xmlns="{S}"><connection id="1" name="Origine">'
            f'<dbPr connection="{_escape(spec.connection)}"/></connection></connections>'
        )

    if spec.macros:
        parts["xl/vbaProject.bin"] = b"\x00CMG=macro con dati riservati\x00"

    if spec.hyperlink:
        parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
            f'{DECL}\n<Relationships xmlns="{REL}">'
            f'<Relationship Id="rIdH" Type="{ODREL}/hyperlink" '
            f'Target="{_escape(spec.hyperlink)}" TargetMode="External"/>'
            "</Relationships>"
        )

    titles = ""
    if spec.app_titles:
        entries = "".join(f"<vt:lpstr>{_escape(sheet.name)}</vt:lpstr>" for sheet in spec.sheets)
        titles = (
            f'<TitlesOfParts><vt:vector size="{len(spec.sheets)}" '
            f'baseType="lpstr">{entries}</vt:vector></TitlesOfParts>'
        )
    parts["docProps/app.xml"] = (
        f'{DECL}\n<Properties xmlns="{EP}" xmlns:vt="{VT}">'
        f"<Company>{_escape(spec.company)}</Company>"
        f"<TotalTime>{_escape(spec.total_time)}</TotalTime>"
        f"{titles}</Properties>"
    )
    parts["docProps/core.xml"] = (
        f"{DECL}\n<cp:coreProperties "
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{_escape(spec.creator)}</dc:creator>"
        f"<dc:title>{_escape(spec.title)}</dc:title></cp:coreProperties>"
    )

    parts["xl/_rels/workbook.xml.rels"] = (
        f'{DECL}\n<Relationships xmlns="{REL}">{"".join(workbook_rels)}</Relationships>'
    )
    parts["_rels/.rels"] = (
        f'{DECL}\n<Relationships xmlns="{REL}">'
        f'<Relationship Id="rId1" Type="{ODREL}/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
        'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        f'<Relationship Id="rId3" Type="{ODREL}/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    parts["[Content_Types].xml"] = (
        f"{DECL}\n"
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{''.join(overrides)}</Types>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def write_xlsx(path: Path, spec: XlsxSpec) -> Path:
    path.write_bytes(build_xlsx(spec))
    return path


def part_text(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if name not in archive.namelist():
            return ""
        return archive.read(name).decode("utf-8", errors="replace")


def part_names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return sorted(archive.namelist())


def survives_anywhere(data: bytes, value: str) -> bool:
    """Search inside the parts. The container is compressed, so its bytes lie."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return any(value.encode() in archive.read(name) for name in archive.namelist())

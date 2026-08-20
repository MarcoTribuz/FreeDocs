"""The xlsx handler against a workbook openpyxl produced and can read back.

``tests/xlsx_builder.py`` covers the parts openpyxl will not write — the shared
string table, pivot caches, external links, ``TitlesOfParts``. This file covers
the opposite risk: that the handler only works on XML we wrote ourselves. It also
confirms the output is still a workbook, which is the half of the promise a leak
test cannot check.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl", reason="openpyxl is a dev dependency")
pytest.importorskip("lxml")

from freedocs.pipeline import Scrubber, build_registry  # noqa: E402

from .conftest import CANARIES, l1_scrubber  # noqa: E402
from .xlsx_builder import part_names, survives_anywhere  # noqa: E402


def build_realistic(path: Path) -> Path:
    from openpyxl.chart import BarChart, Reference
    from openpyxl.comments import Comment
    from openpyxl.worksheet.table import Table

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Clienti"
    sheet.append(["Nome", "CF", "IBAN", "Importo"])
    sheet.append(["Mario Rossi", CANARIES["IT_CODICE_FISCALE"], CANARIES["IBAN"], 1500])
    sheet.append(["Anna Bianchi", "MRTMTT25D09F205Z", CANARIES["IBAN"], 2300])
    sheet.append(["Mario Rossi", CANARIES["IT_CODICE_FISCALE"], CANARIES["IBAN"], 900])

    # A formula, a comment, a table and a chart: the features a redactor is most
    # likely to break.
    sheet["F1"] = '=CONCATENATE(A2," - ",B2)'
    sheet["A2"].comment = Comment(f"verificare con {CANARIES['EMAIL']}", "Marco Tribuzio")
    sheet.add_table(Table(displayName="TabellaClienti", ref="A1:D4"))
    chart = BarChart()
    chart.add_data(Reference(sheet, min_col=4, min_row=1, max_row=4), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=4))
    sheet.add_chart(chart, "H2")

    # A veryHidden sheet: not in the sheet-tab menu, needs the VBA editor.
    hidden = workbook.create_sheet("Sorgente")
    hidden.sheet_state = "veryHidden"
    hidden.append(["AVS", CANARIES["CH_AHV"]])

    sheet.row_dimensions[3].hidden = True
    sheet.column_dimensions["C"].hidden = True

    workbook.properties.creator = "Marco Tribuzio"
    workbook.properties.title = "Riservato"
    workbook.save(path)
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return build_realistic(tmp_path / "reale.xlsx")


@pytest.fixture
def scrubbed(source: Path) -> bytes:
    return l1_scrubber().scrub_file(source).output


def cells(data: bytes, title: str) -> list[tuple]:
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    return list(workbook[title].iter_rows(values_only=True))


# -- the input is genuinely realistic ----------------------------------------


def test_the_fixture_uses_inline_strings_not_a_shared_table(source: Path):
    """openpyxl writes inline strings, which is the path the builder never takes.

    If this ever stops being true the fixture has stopped covering the second
    string representation, and the test is no longer worth its runtime.
    """
    names = part_names(source.read_bytes())
    assert "xl/sharedStrings.xml" not in names
    assert "xl/charts/chart1.xml" in names
    assert "xl/tables/table1.xml" in names


# -- output integrity ---------------------------------------------------------


def test_the_scrubbed_workbook_still_opens(scrubbed: bytes):
    workbook = openpyxl.load_workbook(io.BytesIO(scrubbed))
    assert workbook.sheetnames == ["Clienti", "Sorgente"]


def test_numbers_are_left_alone(scrubbed: bytes):
    """A ledger of placeholders is a scrubbed file nobody can use."""
    amounts = [row[3] for row in cells(scrubbed, "Clienti")[1:]]
    assert amounts == [1500, 2300, 900]


def test_headers_are_left_alone(scrubbed: bytes):
    assert cells(scrubbed, "Clienti")[0][:4] == ("Nome", "CF", "IBAN", "Importo")


def test_the_hidden_sheet_keeps_its_state(scrubbed: bytes):
    workbook = openpyxl.load_workbook(io.BytesIO(scrubbed))
    assert workbook["Sorgente"].sheet_state == "veryHidden"


def test_the_hidden_row_and_column_stay_hidden(scrubbed: bytes):
    """Redacting content must not rearrange the sheet."""
    workbook = openpyxl.load_workbook(io.BytesIO(scrubbed))
    sheet = workbook["Clienti"]
    assert sheet.row_dimensions[3].hidden
    assert sheet.column_dimensions["C"].hidden


def test_the_chart_and_table_survive(scrubbed: bytes):
    names = part_names(scrubbed)
    assert "xl/charts/chart1.xml" in names
    assert "xl/tables/table1.xml" in names


def test_styles_and_theme_are_untouched(source: Path, scrubbed: bytes):
    import zipfile

    original = zipfile.ZipFile(io.BytesIO(source.read_bytes()))
    result = zipfile.ZipFile(io.BytesIO(scrubbed))
    for name in ("xl/styles.xml", "xl/theme/theme1.xml"):
        assert result.read(name) == original.read(name), name


# -- redaction ----------------------------------------------------------------


def test_inline_strings_are_redacted(scrubbed: bytes):
    rows = cells(scrubbed, "Clienti")
    assert rows[1][1] == "[CF_1]"
    assert rows[1][2] == "[IBAN_1]"


def test_the_same_value_gets_the_same_placeholder_in_every_row(scrubbed: bytes):
    """Otherwise the sheet reads as three different clients."""
    rows = cells(scrubbed, "Clienti")
    assert rows[1][1] == rows[3][1]
    assert rows[1][1] != rows[2][1]


def test_the_hidden_sheet_is_redacted_too(scrubbed: bytes):
    assert cells(scrubbed, "Sorgente")[0] == ("AVS", "[AVS_1]")


# -- leaks --------------------------------------------------------------------


@pytest.mark.leak
@pytest.mark.parametrize(
    "value",
    [CANARIES["IT_CODICE_FISCALE"], CANARIES["IBAN"], CANARIES["CH_AHV"], CANARIES["EMAIL"]],
)
def test_no_canary_survives_in_any_part(scrubbed: bytes, value: str):
    assert not survives_anywhere(scrubbed, value)


@pytest.mark.leak
def test_the_comment_and_its_author_do_not_survive(source: Path, scrubbed: bytes):
    """Redacting cells does nothing to the comments part."""
    assert any("comment" in name for name in part_names(source.read_bytes()))
    assert not survives_anywhere(scrubbed, "Marco Tribuzio")
    assert not survives_anywhere(scrubbed, "verificare con")


@pytest.mark.leak
def test_metadata_does_not_survive(scrubbed: bytes):
    workbook = openpyxl.load_workbook(io.BytesIO(scrubbed))
    assert not workbook.properties.creator
    assert not workbook.properties.title


def test_the_full_stack_also_removes_the_names(source: Path):
    """L1 cannot see "Mario Rossi"; the default stack must."""
    pytest.importorskip("gliner2", reason="the 'ner' extra is required")
    output = Scrubber(registry=build_registry("all")).scrub_file(source).output
    assert not survives_anywhere(output, "Mario Rossi")
    assert not survives_anywhere(output, "Anna Bianchi")
    rows = cells(output, "Clienti")
    assert rows[1][0] == rows[3][0], "one client, one placeholder"

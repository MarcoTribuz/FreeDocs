"""Excel workbooks: every copy of the data, not just the visible cells.

A spreadsheet keeps more duplicates of its own content than any other format —
the string table, the pivot cache, the chart cache, the external-link cache, the
sheet names in two places — and each one survives redacting every cell. These
tests exist because "the cells are clean" is not the same as "the file is clean".
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("lxml", reason="lxml is required for Office formats")

from freedocs.core.findings import Span
from freedocs.core.stream import Edit
from freedocs.formats.ooxml.xlsx import (
    MAX_NAME_LENGTH,
    MIN_NUMERIC_LENGTH,
    WORKBOOK,
    XlsxHandler,
    sanitise_name,
)
from freedocs.formats.router import handler_for

from .conftest import CANARIES, l1_scrubber
from .xlsx_builder import (
    Sheet,
    XlsxSpec,
    part_names,
    part_text,
    survives_anywhere,
    write_xlsx,
)

BASE_ROWS = [
    ["Nome", "CF", "IBAN", "Importo"],
    ["Mario Rossi", CANARIES["IT_CODICE_FISCALE"], CANARIES["IBAN"], 1500],
    ["Anna Bianchi", "MRTMTT25D09F205Z", CANARIES["IBAN"], 2300],
]


def make(path: Path, **overrides) -> Path:
    sheets = overrides.pop("sheets", [Sheet(name="Clienti", rows=list(BASE_ROWS))])
    return write_xlsx(path, XlsxSpec(sheets=sheets, **overrides))


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return make(tmp_path / "clienti.xlsx")


# -- routing ------------------------------------------------------------------


def test_router_picks_the_xlsx_handler(source: Path):
    assert isinstance(handler_for(source), XlsxHandler)


def test_a_workbook_without_the_workbook_part_is_refused(tmp_path: Path):
    path = tmp_path / "vuoto.xlsx"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    with pytest.raises(Exception):  # noqa: B017 - any failure beats silent success
        handler_for(path)


# -- extraction ---------------------------------------------------------------


def test_shared_strings_are_extracted(source: Path):
    """Excel deduplicates every string here; openpyxl writes inline instead."""
    stream = handler_for(source).extract()
    assert "Mario Rossi" in stream.text
    assert CANARIES["IT_CODICE_FISCALE"] in stream.text


def test_a_repeated_string_is_anchored_once(source: Path):
    """The IBAN appears in two rows but is one table entry, so one edit fixes both."""
    stream = handler_for(source).extract()
    assert stream.text.count(CANARIES["IBAN"]) == 1


def test_rows_are_separated_so_cells_do_not_fuse(tmp_path: Path):
    path = make(
        tmp_path / "s.xlsx",
        sheets=[Sheet(name="Dati", rows=[["alfa", "beta"], ["gamma", "delta"]])],
    )
    stream = handler_for(path).extract()
    assert "alfabeta" not in stream.text
    assert "betagamma" not in stream.text


def test_sheet_names_are_extracted_from_both_places(tmp_path: Path):
    """workbook.xml and docProps/app.xml each hold a full list of sheet names."""
    path = make(tmp_path / "s.xlsx", sheets=[Sheet(name="Stipendi", rows=[["x"]])])
    stream = handler_for(path).extract()
    assert stream.text.count("Stipendi") == 2


def test_hidden_sheet_content_is_extracted(tmp_path: Path):
    """A veryHidden sheet needs the VBA editor to reveal, so people forget it."""
    path = make(
        tmp_path / "s.xlsx",
        sheets=[
            Sheet(name="Report", rows=[["totale", 10]]),
            Sheet(name="Sorgente", rows=[[CANARIES["CH_AHV"]]], state="veryHidden"),
        ],
    )
    stream = handler_for(path).extract()
    assert CANARIES["CH_AHV"] in stream.text


def test_defined_names_are_extracted(tmp_path: Path):
    path = make(tmp_path / "s.xlsx", defined_names=[("IBAN_Rossi", "Clienti!$C$2")])
    stream = handler_for(path).extract()
    assert "IBAN_Rossi" in stream.text


def test_pivot_cache_items_are_extracted(tmp_path: Path):
    """A pivot over a staff table contains the staff table."""
    path = make(tmp_path / "s.xlsx", pivot_items=["Mario Rossi", CANARIES["CH_AHV"]])
    stream = handler_for(path).extract()
    assert CANARIES["CH_AHV"] in stream.text


def test_chart_cache_labels_are_extracted(tmp_path: Path):
    path = make(tmp_path / "s.xlsx", chart_labels=["Mario Rossi", "Anna Bianchi"])
    stream = handler_for(path).extract()
    assert "Anna Bianchi" in stream.text


def test_external_link_cache_is_extracted(tmp_path: Path):
    """The last-seen values of another workbook, kept so formulas still compute."""
    path = make(
        tmp_path / "s.xlsx",
        external_values=[CANARIES["EMAIL"]],
        external_sheet="Estratto HR",
    )
    stream = handler_for(path).extract()
    assert CANARIES["EMAIL"] in stream.text
    assert "Estratto HR" in stream.text


def test_external_hyperlink_targets_are_extracted(tmp_path: Path):
    path = make(tmp_path / "s.xlsx", hyperlink=f"mailto:{CANARIES['EMAIL']}")
    stream = handler_for(path).extract()
    assert f"mailto:{CANARIES['EMAIL']}" in stream.text


def test_formula_text_is_extracted(tmp_path: Path):
    path = make(
        tmp_path / "s.xlsx",
        sheets=[Sheet(name="Calcoli", rows=[['=CONCATENATE("x",A1)', "b"]])],
    )
    stream = handler_for(path).extract()
    assert "CONCATENATE" in stream.text


# -- numeric cells ------------------------------------------------------------


def test_short_numbers_are_not_anchored(tmp_path: Path):
    """A sheet is mostly numbers; anchoring every amount would redact the ledger."""
    path = make(tmp_path / "s.xlsx", sheets=[Sheet(name="Importi", rows=[[1500, 2300]])])
    stream = handler_for(path).extract()
    assert "1500" not in stream.text


def test_long_numbers_are_anchored(tmp_path: Path):
    """An identifier typed into a numeric cell is still an identifier."""
    long_number = 12345678903
    assert len(str(long_number)) >= MIN_NUMERIC_LENGTH
    path = make(tmp_path / "s.xlsx", sheets=[Sheet(name="Dati", rows=[[long_number]])])
    stream = handler_for(path).extract()
    assert str(long_number) in stream.text


def test_a_shared_string_index_is_never_anchored(source: Path):
    """<c t="s"><v>3</v></c> is a table index; editing it repoints the cell."""
    stream = handler_for(source).extract()
    for anchor in stream.anchors:
        value = stream.text[anchor.start : anchor.end]
        assert value not in {"0", "1", "2", "3"}, "an index was anchored as text"


# -- name sanitisation --------------------------------------------------------


@pytest.mark.parametrize("character", list(r"[]:*?/\\"))
def test_illegal_name_characters_are_replaced(character: str):
    assert character not in sanitise_name(f"Foglio{character}uno")


def test_sanitised_names_are_never_empty():
    assert sanitise_name("[]") == "__"
    assert sanitise_name("") == "_"


def test_names_are_truncated_to_excels_limit():
    assert len(sanitise_name("x" * 60)) == MAX_NAME_LENGTH


def test_a_redacted_sheet_name_stays_legal(tmp_path: Path):
    """The placeholder form contains brackets, which Excel rejects outright."""
    path = make(
        tmp_path / "s.xlsx",
        sheets=[Sheet(name=f"IBAN {CANARIES['IBAN']}", rows=[["x"]])],
    )
    output = l1_scrubber().scrub_file(path).output
    workbook = part_text(output, WORKBOOK)
    assert "[IBAN_1]" not in workbook
    assert "_IBAN_1_" in workbook


def test_renaming_a_sheet_is_reported(tmp_path: Path):
    """Formulas reference sheets by name, so a rename breaks them. Say so."""
    path = make(
        tmp_path / "s.xlsx",
        sheets=[Sheet(name=f"IBAN {CANARIES['IBAN']}", rows=[["x"]])],
    )
    result = l1_scrubber().scrub_file(path)
    assert any("formulas referring to them" in warning for warning in result.warnings)


def test_nothing_is_reported_when_no_name_was_touched(source: Path):
    assert l1_scrubber().scrub_file(source).warnings == []


# -- fidelity -----------------------------------------------------------------


def test_an_unedited_write_back_leaves_every_part_byte_identical(tmp_path: Path):
    path = make(tmp_path / "s.xlsx", pivot_items=["Mario Rossi"], chart_labels=["Q1"])
    source_bytes = path.read_bytes()
    output = handler_for(path).write_back([])
    for name in part_names(source_bytes):
        assert part_text(output, name) == part_text(source_bytes, name), name


def test_editing_one_cell_leaves_the_others_alone(source: Path):
    handler = handler_for(source)
    stream = handler.extract()
    start = stream.text.index("Mario Rossi")
    output = handler.write_back(
        stream.plan_edits([Edit(Span(start, start + len("Mario Rossi")), "[PERSONA_1]")])
    )
    shared = part_text(output, "xl/sharedStrings.xml")
    assert "[PERSONA_1]" in shared
    assert "Anna Bianchi" in shared
    assert CANARIES["IT_CODICE_FISCALE"] in shared


# -- leaks --------------------------------------------------------------------


@pytest.mark.leak
def test_no_canary_survives_in_any_part(tmp_path: Path):
    path = make(
        tmp_path / "carico.xlsx",
        sheets=[
            Sheet(name="Clienti", rows=list(BASE_ROWS)),
            Sheet(name="Sorgente", rows=[[CANARIES["CH_AHV"]]], state="veryHidden"),
        ],
        pivot_items=[CANARIES["CH_UID"]],
        chart_labels=[CANARIES["IT_PARTITA_IVA"]],
        external_values=[CANARIES["EMAIL"]],
        hyperlink=f"mailto:{CANARIES['EMAIL']}",
    )
    result = l1_scrubber().scrub_file(path)
    for value in (
        CANARIES["IT_CODICE_FISCALE"],
        CANARIES["IBAN"],
        CANARIES["CH_AHV"],
        CANARIES["CH_UID"],
        CANARIES["EMAIL"],
    ):
        assert not survives_anywhere(result.output, value), value


@pytest.mark.leak
def test_a_canary_in_the_pivot_cache_does_not_survive(tmp_path: Path):
    path = make(tmp_path / "s.xlsx", pivot_items=[CANARIES["CH_AHV"], "Totale"])
    result = l1_scrubber().scrub_file(path)
    assert not survives_anywhere(result.output, CANARIES["CH_AHV"])


def test_the_pivot_cache_is_redacted_not_deleted(tmp_path: Path):
    """Deleting it would leave the pivot table blank until someone refreshes."""
    path = make(tmp_path / "s.xlsx", pivot_items=[CANARIES["CH_AHV"], "Totale"])
    output = l1_scrubber().scrub_file(path).output
    cache = part_text(output, "xl/pivotCache/pivotCacheDefinition1.xml")
    assert cache, "the cache part must still exist"
    assert "[NATIONAL_ID_1]" in cache
    assert 'v="Totale"' in cache, "non-confidential cache values must be left alone"


@pytest.mark.leak
def test_a_canary_in_the_external_link_cache_does_not_survive(tmp_path: Path):
    path = make(tmp_path / "s.xlsx", external_values=[CANARIES["IBAN"]])
    result = l1_scrubber().scrub_file(path)
    assert not survives_anywhere(result.output, CANARIES["IBAN"])


@pytest.mark.leak
def test_verification_passes(source: Path):
    result = l1_scrubber().scrub_file(source)
    assert result.verify.ok, result.verify.summary()
    assert result.verify.checked_values >= 2


# -- hidden content -----------------------------------------------------------


@pytest.fixture
def loaded(tmp_path: Path) -> Path:
    return make(
        tmp_path / "carico.xlsx",
        sheets=[
            Sheet(
                name="Clienti",
                rows=list(BASE_ROWS),
                hidden_rows=(3,),
                hidden_columns=("C",),
            ),
            Sheet(name="Sorgente", rows=[["x"]], state="veryHidden"),
        ],
        pivot_items=["Mario Rossi"],
        external_values=["x"],
        external_target="\\\\server\\utenti\\mtribuzio\\hr.xlsx",
        connection="Provider=SQLOLEDB;Data Source=hr-db;User ID=mtribuzio",
        macros=True,
    )


def test_hidden_content_is_inventoried(loaded: Path):
    kinds = {item.kind for item in l1_scrubber().scrub_file(loaded).hidden_removed}
    assert {
        "data-connections",
        "macro-project",
        "metadata",
        "extended-metadata",
        "hidden-sheet",
        "hidden-cells",
        "pivot-cache",
        "external-link-cache",
    } <= kinds


def test_a_very_hidden_sheet_is_named_in_the_report(loaded: Path):
    items = [
        item
        for item in l1_scrubber().scrub_file(loaded).hidden_removed
        if item.kind == "hidden-sheet"
    ]
    assert items and "very hidden" in items[0].detail


def test_hidden_sheets_are_reported_but_kept(loaded: Path):
    """Deleting a sheet breaks every formula that references it."""
    output = l1_scrubber().scrub_file(loaded).output
    assert "xl/worksheets/sheet2.xml" in part_names(output)


@pytest.mark.leak
def test_connection_strings_do_not_survive(loaded: Path):
    """They carry server names, paths and sometimes credentials."""
    output = l1_scrubber().scrub_file(loaded).output
    assert "xl/connections.xml" not in part_names(output)
    assert not survives_anywhere(output, "User ID=mtribuzio")


@pytest.mark.leak
def test_the_macro_project_does_not_survive(loaded: Path):
    """Opaque binary: it cannot be redacted, only removed."""
    output = l1_scrubber().scrub_file(loaded).output
    assert "xl/vbaProject.bin" not in part_names(output)
    assert not survives_anywhere(output, "macro con dati riservati")


@pytest.mark.leak
def test_metadata_does_not_survive(loaded: Path):
    output = l1_scrubber().scrub_file(loaded).output
    for value in ("Marco Tribuzio", "Riservato", "Realise Consulting SA"):
        assert not survives_anywhere(output, value), value


def test_a_clean_workbook_reports_nothing_hidden(tmp_path: Path):
    path = write_xlsx(
        tmp_path / "pulito.xlsx",
        XlsxSpec(
            sheets=[Sheet(name="Dati", rows=[["totale", 10]])],
            creator="",
            title="",
            company="",
            total_time="",
        ),
    )
    assert l1_scrubber().scrub_file(path).hidden_removed == []

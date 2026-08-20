"""Word documents: does the text leave, and does the document survive?

Two failure modes matter equally here and pull in opposite directions. A scrubber
that misses the deleted paragraph still in ``word/document.xml`` is unsafe. A
scrubber that returns a file Word opens with the formatting gone is useless, and
that is the one every competing tool trips over, because rebuilding a paragraph
is so much easier than editing the runs inside it.

So the leak checks look inside every zip part, and the fidelity checks assert the
XML tree comes back the same shape it went in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("lxml", reason="lxml is required for Office formats")

from lxml import etree

from freedocs.core.findings import Span
from freedocs.core.stream import Edit
from freedocs.formats.ooxml.common import AttributeLocator
from freedocs.formats.ooxml.docx import DOCUMENT, DocxHandler
from freedocs.formats.router import handler_for

from .conftest import CANARIES, l1_scrubber
from .docx_builder import DocxSpec, all_part_text, part_names, part_text, write_docx

#: A name deliberately split across three runs, the case that breaks naive tools.
SPLIT_NAME_PARAGRAPH = ["Cliente: ", "Mario", " Rossi"]

BASE_PARAGRAPHS = [
    ["Scheda cliente - RISERVATA"],
    SPLIT_NAME_PARAGRAPH,
    [f"Codice fiscale: {CANARIES['IT_CODICE_FISCALE']}"],
    [f"IBAN: {CANARIES['IBAN']}"],
    ["Note: contratto annuale, rinnovo automatico"],
]

#: Ignored when comparing structure: these are added on purpose when a
#: replacement gains surrounding whitespace.
IGNORED_ATTRIBUTES = frozenset({"{http://www.w3.org/XML/1998/namespace}space"})


def make(path: Path, **overrides) -> Path:
    spec = DocxSpec(paragraphs=overrides.pop("paragraphs", list(BASE_PARAGRAPHS)), **overrides)
    return write_docx(path, spec)


def structure(data: bytes, part: str) -> list[tuple[int, str, tuple[tuple[str, str], ...]]]:
    """The shape of a part: depth, tag and attributes, in document order.

    Text is deliberately excluded — that is what a scrub is supposed to change.
    Everything else must come back untouched.
    """
    root = etree.fromstring(part_text(data, part).encode("utf-8"))
    out = []

    def walk(element, depth: int) -> None:
        attributes = tuple(
            sorted(
                (key, value)
                for key, value in element.attrib.items()
                if key not in IGNORED_ATTRIBUTES
            )
        )
        out.append((depth, element.tag, attributes))
        for child in element:
            walk(child, depth + 1)

    walk(root, 0)
    return out


def texts(data: bytes, part: str = DOCUMENT) -> str:
    """Concatenated ``w:t`` content of a part."""
    root = etree.fromstring(part_text(data, part).encode("utf-8"))
    tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    return "".join(element.text or "" for element in root.iter(tag))


def survives_anywhere(data: bytes, value: str) -> bool:
    """Search inside the parts, not the container: the zip is compressed."""
    return value in all_part_text(data)


# -- routing ------------------------------------------------------------------


def test_router_picks_the_docx_handler(tmp_path: Path):
    assert isinstance(handler_for(make(tmp_path / "scheda.docx")), DocxHandler)


def test_a_zip_that_is_not_a_word_file_is_not_claimed(tmp_path: Path):
    path = tmp_path / "archivio.docx"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    with pytest.raises(Exception):  # noqa: B017 - any failure beats silent success
        handler_for(path)


# -- extraction ---------------------------------------------------------------


def test_a_name_split_across_runs_reads_as_one_string(tmp_path: Path):
    """The whole reason the anchor design exists."""
    stream = handler_for(make(tmp_path / "s.docx")).extract()
    assert "Cliente: Mario Rossi" in stream.text


def test_every_anchor_maps_back_to_its_element(tmp_path: Path):
    stream = handler_for(make(tmp_path / "s.docx")).extract()
    for anchor in stream.anchors:
        assert stream.text[anchor.start : anchor.end] == (
            anchor.locator.text
            if not isinstance(anchor.locator, AttributeLocator)
            else anchor.locator.element.get(anchor.locator.name)
        )


def test_header_and_footer_text_is_extracted(tmp_path: Path):
    """Where the client name sits on every page, and where tools forget to look."""
    path = make(tmp_path / "s.docx", header="Realise Consulting SA", footer="Pagina 1")
    stream = handler_for(path).extract()
    assert "Realise Consulting SA" in stream.text
    assert "Pagina 1" in stream.text


def test_table_cells_are_separated(tmp_path: Path):
    """Without a boundary, two cells fuse and produce phantom matches."""
    path = make(tmp_path / "s.docx", table_cell="prima cella")
    stream = handler_for(path).extract()
    assert "prima cella" in stream.text
    assert "prima cellaseconda" not in stream.text


def test_text_box_content_is_extracted_exactly_once(tmp_path: Path):
    """A text box nests a paragraph inside a run; a naive walk visits it twice."""
    path = make(tmp_path / "s.docx", textbox="Nota interna riservata")
    stream = handler_for(path).extract()
    assert stream.text.count("Nota interna riservata") == 1


def test_external_hyperlink_targets_are_extracted(tmp_path: Path):
    """The address lives in the rels part, not in the body anyone can read."""
    path = make(
        tmp_path / "s.docx", hyperlink=("scrivi al referente", f"mailto:{CANARIES['EMAIL']}")
    )
    stream = handler_for(path).extract()
    assert f"mailto:{CANARIES['EMAIL']}" in stream.text


def test_internal_relationships_are_not_extracted(tmp_path: Path):
    """They point at other parts of the same file and hold no addresses."""
    stream = handler_for(make(tmp_path / "s.docx")).extract()
    assert "settings.xml" not in stream.text


# -- fidelity -----------------------------------------------------------------


def test_an_unedited_write_back_leaves_every_part_byte_identical(tmp_path: Path):
    """Nothing dirty means nothing re-serialised. The baseline for every format."""
    path = make(tmp_path / "s.docx", header="Intestazione", footer="Piede")
    source = path.read_bytes()
    output = handler_for(path).write_back([])
    for name in part_names(source):
        assert part_text(output, name) == part_text(source, name), name


def test_editing_preserves_the_xml_structure(tmp_path: Path):
    """The formatting regression competing tools ship: runs merged or rebuilt."""
    path = make(tmp_path / "s.docx", table_cell="AVS: 756.1234.5678.97")
    source = path.read_bytes()
    handler = handler_for(path)
    stream = handler.extract()
    start = stream.text.index("Mario Rossi")
    output = handler.write_back(
        stream.plan_edits([Edit(Span(start, start + len("Mario Rossi")), "[PERSONA_1]")])
    )
    assert structure(output, DOCUMENT) == structure(source, DOCUMENT)


def test_the_three_runs_of_a_split_name_all_survive(tmp_path: Path):
    """The replacement goes in the first run; the others only lose characters."""
    path = make(tmp_path / "s.docx")
    handler = handler_for(path)
    stream = handler.extract()
    start = stream.text.index("Mario Rossi")
    output = handler.write_back(
        stream.plan_edits([Edit(Span(start, start + len("Mario Rossi")), "[PERSONA_1]")])
    )
    assert texts(output).count("Cliente: ") == 1
    assert "[PERSONA_1]" in texts(output)
    assert "Mario" not in texts(output)


def test_run_properties_are_not_disturbed(tmp_path: Path):
    """Bold stays bold: the run keeps its own rPr because it is never replaced."""
    from .docx_builder import runs_xml

    assert "<w:b/>" in runs_xml(["grassetto", " normale"], bold_first=True)

    path = make(tmp_path / "s.docx")
    source = path.read_bytes()
    handler = handler_for(path)
    stream = handler.extract()
    start = stream.text.index(CANARIES["IBAN"])
    output = handler.write_back(
        stream.plan_edits([Edit(Span(start, start + len(CANARIES["IBAN"])), "[IBAN_1]")])
    )
    assert structure(output, DOCUMENT) == structure(source, DOCUMENT)


def test_leading_space_survives_a_replacement(tmp_path: Path):
    """Without xml:space="preserve" Word eats it and the words fuse."""
    path = make(tmp_path / "s.docx", paragraphs=[["Saldo: ", "1000", " EUR"]])
    handler = handler_for(path)
    stream = handler.extract()
    start = stream.text.index("1000")
    output = handler.write_back(stream.plan_edits([Edit(Span(start, start + 4), "[IMPORTO]")]))
    assert "Saldo: [IMPORTO] EUR" in texts(output)


def test_the_output_is_still_a_readable_container(tmp_path: Path):
    path = make(tmp_path / "s.docx", header="Intestazione")
    output = l1_scrubber().scrub_file(path).output
    names = part_names(output)
    assert "[Content_Types].xml" in names
    assert DOCUMENT in names
    for name in names:
        if name.endswith((".xml", ".rels")):
            etree.fromstring(part_text(output, name).encode("utf-8"))


# -- leaks --------------------------------------------------------------------


@pytest.mark.leak
@pytest.mark.parametrize(
    "value",
    [
        CANARIES["IT_CODICE_FISCALE"],
        CANARIES["IBAN"],
        CANARIES["CH_AHV"],
        CANARIES["EMAIL"],
    ],
)
def test_no_canary_survives_in_any_part(tmp_path: Path, value: str):
    path = make(
        tmp_path / "s.docx",
        paragraphs=[
            *BASE_PARAGRAPHS,
            [f"AVS: {CANARIES['CH_AHV']}"],
            [f"Contatto: {CANARIES['EMAIL']}"],
        ],
    )
    result = l1_scrubber().scrub_file(path)
    assert not survives_anywhere(result.output, value)


@pytest.mark.leak
def test_a_canary_in_the_header_does_not_survive(tmp_path: Path):
    path = make(tmp_path / "s.docx", header=f"IBAN {CANARIES['IBAN']}")
    result = l1_scrubber().scrub_file(path)
    assert not survives_anywhere(result.output, CANARIES["IBAN"])


@pytest.mark.leak
def test_a_canary_in_a_hyperlink_target_does_not_survive(tmp_path: Path):
    """Redacting the visible link text would leave the address in the rels part."""
    path = make(tmp_path / "s.docx", hyperlink=("scrivi", f"mailto:{CANARIES['EMAIL']}"))
    result = l1_scrubber().scrub_file(path)
    assert not survives_anywhere(result.output, CANARIES["EMAIL"])
    assert "[EMAIL_1]" in part_text(result.output, "word/_rels/document.xml.rels")


@pytest.mark.leak
def test_a_canary_in_a_text_box_does_not_survive(tmp_path: Path):
    path = make(tmp_path / "s.docx", textbox=f"UID {CANARIES['CH_UID']}")
    result = l1_scrubber().scrub_file(path)
    assert not survives_anywhere(result.output, CANARIES["CH_UID"])


@pytest.mark.leak
def test_verification_passes(tmp_path: Path):
    result = l1_scrubber().scrub_file(make(tmp_path / "s.docx"))
    assert result.verify.ok, result.verify.summary()
    assert result.verify.checked_values >= 2


# -- hidden content -----------------------------------------------------------


@pytest.fixture
def loaded(tmp_path: Path) -> Path:
    return make(
        tmp_path / "carico.docx",
        deleted="Il precedente referente era Anna Bianchi",
        inserted="Nuovo referente confermato",
        comment="verificare con il titolare",
        header="Realise Consulting SA",
        footer="Pagina 1",
    )


def test_hidden_content_is_inventoried(loaded: Path):
    kinds = {item.kind for item in l1_scrubber().scrub_file(loaded).hidden_removed}
    assert {
        "comments",
        "commenter-directory",
        "metadata",
        "extended-metadata",
        "tracked-deletions",
        "tracked-insertions",
        "comment-anchors",
        "revision-save-ids",
        "revision-save-id-table",
    } <= kinds


@pytest.mark.leak
def test_tracked_deleted_text_does_not_survive(loaded: Path):
    """It was removed from view but left in the file, verbatim, with the author."""
    output = l1_scrubber().scrub_file(loaded).output
    assert not survives_anywhere(output, "Il precedente referente era Anna Bianchi")
    assert not survives_anywhere(output, "delText")


def test_a_tracked_insertion_keeps_its_text_and_loses_its_author(loaded: Path):
    """Insertions are visible content; only the markup around them identifies."""
    output = l1_scrubber().scrub_file(loaded).output
    assert "Nuovo referente confermato" in texts(output)
    assert not survives_anywhere(output, "w:ins")


@pytest.mark.leak
def test_comment_parts_and_their_authors_do_not_survive(loaded: Path):
    output = l1_scrubber().scrub_file(loaded).output
    assert "word/comments.xml" not in part_names(output)
    assert "word/people.xml" not in part_names(output)
    assert not survives_anywhere(output, "verificare con il titolare")
    assert not survives_anywhere(output, "a.bianchi@example.com")


@pytest.mark.leak
def test_metadata_values_do_not_survive(loaded: Path):
    output = l1_scrubber().scrub_file(loaded).output
    for value in ("Marco Tribuzio", "Giuseppe Conti", "mtribuzio", "Riservato.dotx"):
        assert not survives_anywhere(output, value), value


def test_revision_save_ids_are_stripped(loaded: Path):
    """They fingerprint the editing session and link documents to one author."""
    output = l1_scrubber().scrub_file(loaded).output
    assert "rsidR" not in part_text(output, DOCUMENT)
    assert "w:rsids" not in part_text(output, "word/settings.xml")


def test_a_document_with_nothing_hidden_reports_nothing_removed(tmp_path: Path):
    """The inventory must not invent findings for a clean file."""
    path = make(
        tmp_path / "pulito.docx",
        paragraphs=[["Verbale di riunione"], ["Preventivo approvato."]],
        creator="",
        last_modified_by="",
        title="",
        subject="",
        keywords="",
        company="",
        manager="",
        template="",
        revision="",
        total_time="",
        rsid=None,
        rsid_table=False,
    )
    assert l1_scrubber().scrub_file(path).hidden_removed == []

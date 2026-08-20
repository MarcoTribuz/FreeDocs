"""The docx handler against a package Word itself would recognise.

``tests/docx_builder.py`` gives precise control but only ever hands the handler
XML we wrote ourselves, which proves nothing about real files. ``python-docx``
produces a full package — styles, theme, font table, a custom XML store, a page
thumbnail — and reads the result back, so these tests check both that the scrub
works on a realistic input and that the output is still a document.

Two leaks were found here and nowhere else: the rendered page thumbnail, and the
dangling relationships left behind by removing a part.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from pathlib import Path

import pytest

# The distribution is python-docx; the module it installs is `docx`.
docx_module = pytest.importorskip("docx", reason="python-docx is a dev dependency")
pytest.importorskip("lxml")

from freedocs.pipeline import Scrubber, build_registry  # noqa: E402

from .conftest import CANARIES, l1_scrubber  # noqa: E402


def build_realistic(path: Path) -> Path:
    document = docx_module.Document()
    document.core_properties.author = "Marco Tribuzio"
    document.core_properties.title = "Scheda riservata"
    document.core_properties.comments = CANARIES["EMAIL"]

    document.add_heading("Scheda cliente", level=1)
    # A name split across three runs, which is what breaks naive tools. L1 alone
    # cannot see it, so the formatting assertions use the bold run below.
    paragraph = document.add_paragraph("Cliente: ")
    paragraph.add_run("Mario")
    paragraph.add_run(" Rossi")

    # An identifier inside a bold run: the checksum layer finds it without a
    # model, so the run's formatting can be checked after the replacement.
    fiscal = document.add_paragraph("Codice fiscale: ")
    bold_run = fiscal.add_run(CANARIES["IT_CODICE_FISCALE"])
    bold_run.bold = True

    document.add_paragraph(f"IBAN: {CANARIES['IBAN']}")

    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = f"AVS: {CANARIES['CH_AHV']}"
    table.rows[0].cells[1].text = "seconda cella"

    section = document.sections[0]
    section.header.paragraphs[0].text = "Realise Consulting SA"
    section.footer.paragraphs[0].text = "Pagina 1"

    document.save(path)
    return path


def names_in(data: bytes) -> list[str]:
    return sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())


def dangling_relationships(data: bytes) -> list[tuple[str, str]]:
    """Relationships pointing at parts that are not in the package.

    A dangling reference makes Word offer to repair the file, and a strict
    consumer reject it. Removing a part means removing what points at it.
    """
    names = names_in(data)
    archive = zipfile.ZipFile(io.BytesIO(data))
    out: list[tuple[str, str]] = []
    for rels in [name for name in names if name.endswith(".rels")]:
        base = posixpath.dirname(posixpath.dirname(rels))
        body = archive.read(rels).decode("utf-8")
        for element in re.findall(r"<Relationship\b[^>]*>", body):
            if 'TargetMode="External"' in element:
                continue
            match = re.search(r'Target="([^"]+)"', element)
            if not match:
                continue
            resolved = posixpath.normpath(posixpath.join(base, match.group(1))).lstrip("/")
            if resolved not in names:
                out.append((rels, resolved))
    return out


def orphan_content_types(data: bytes) -> list[str]:
    names = names_in(data)
    body = zipfile.ZipFile(io.BytesIO(data)).read("[Content_Types].xml").decode("utf-8")
    return [name for name in re.findall(r'PartName="/([^"]+)"', body) if name not in names]


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return build_realistic(tmp_path / "reale.docx")


@pytest.fixture
def scrubbed(source: Path) -> bytes:
    return l1_scrubber().scrub_file(source).output


# -- the input is genuinely realistic ----------------------------------------


def test_the_fixture_really_contains_the_awkward_parts(source: Path):
    """If the fixture stops carrying these, the tests below stop meaning anything."""
    names = names_in(source.read_bytes())
    assert any("thumbnail" in name for name in names)
    assert any(name.startswith("customXml/") for name in names)
    assert "word/styles.xml" in names
    assert "word/theme/theme1.xml" in names


# -- output integrity ---------------------------------------------------------


def test_the_scrubbed_file_still_opens(scrubbed: bytes):
    document = docx_module.Document(io.BytesIO(scrubbed))
    assert next(p.text for p in document.paragraphs) == "Scheda cliente"


def test_no_dangling_relationships(scrubbed: bytes):
    assert dangling_relationships(scrubbed) == []


def test_no_orphan_content_type_overrides(scrubbed: bytes):
    assert orphan_content_types(scrubbed) == []


def test_styles_and_theme_are_untouched(source: Path, scrubbed: bytes):
    """Parts nobody edited must come through as the bytes they arrived as."""
    original = zipfile.ZipFile(io.BytesIO(source.read_bytes()))
    result = zipfile.ZipFile(io.BytesIO(scrubbed))
    for name in ("word/styles.xml", "word/theme/theme1.xml", "word/fontTable.xml"):
        assert result.read(name) == original.read(name), name


# -- formatting ---------------------------------------------------------------


def test_the_placeholder_inherits_the_formatting_of_the_run_it_replaced(scrubbed: bytes):
    """Editing the run's text rather than rebuilding it is what keeps bold bold."""
    document = docx_module.Document(io.BytesIO(scrubbed))
    paragraph = next(p for p in document.paragraphs if p.text.startswith("Codice fiscale:"))
    assert paragraph.text == "Codice fiscale: [CF_1]"
    bold = [run for run in paragraph.runs if run.bold]
    assert [run.text for run in bold] == ["[CF_1]"], (
        "the replacement must stay in the bold run that held the original"
    )


def test_a_name_split_across_runs_keeps_its_runs(scrubbed: bytes):
    """L1 leaves the name alone, so the runs must come back exactly as they were."""
    document = docx_module.Document(io.BytesIO(scrubbed))
    paragraph = next(p for p in document.paragraphs if p.text.startswith("Cliente:"))
    assert [run.text for run in paragraph.runs] == ["Cliente: ", "Mario", " Rossi"]


def test_table_and_header_text_is_scrubbed(scrubbed: bytes):
    document = docx_module.Document(io.BytesIO(scrubbed))
    assert "[AVS_1]" in document.tables[0].rows[0].cells[0].text
    assert document.tables[0].rows[0].cells[1].text == "seconda cella"


# -- leaks --------------------------------------------------------------------


@pytest.mark.leak
@pytest.mark.parametrize(
    "value",
    [CANARIES["IT_CODICE_FISCALE"], CANARIES["IBAN"], CANARIES["CH_AHV"], CANARIES["EMAIL"]],
)
def test_no_canary_survives_in_any_part(scrubbed: bytes, value: str):
    archive = zipfile.ZipFile(io.BytesIO(scrubbed))
    for name in archive.namelist():
        body = archive.read(name)
        assert value.encode() not in body, f"{value!r} survives in {name}"


@pytest.mark.leak
def test_the_page_thumbnail_is_removed(source: Path, scrubbed: bytes):
    """It is a rendered picture of the unredacted first page."""
    assert any("thumbnail" in name for name in names_in(source.read_bytes()))
    assert not any("thumbnail" in name for name in names_in(scrubbed))


@pytest.mark.leak
def test_the_custom_xml_store_is_removed(source: Path, scrubbed: bytes):
    assert any(name.startswith("customXml/") for name in names_in(source.read_bytes()))
    assert not any(name.startswith("customXml/") for name in names_in(scrubbed))


@pytest.mark.leak
def test_metadata_does_not_survive(scrubbed: bytes):
    document = docx_module.Document(io.BytesIO(scrubbed))
    assert not document.core_properties.author
    assert not document.core_properties.title


def test_the_full_stack_also_removes_the_name(source: Path):
    """L1 cannot see "Mario Rossi"; the default stack must."""
    pytest.importorskip("gliner2", reason="the 'ner' extra is required")
    output = Scrubber(registry=build_registry("all")).scrub_file(source).output
    document = docx_module.Document(io.BytesIO(output))
    body = "\n".join(p.text for p in document.paragraphs)
    assert "Mario Rossi" not in body
    assert "[PERSONA_1]" in body

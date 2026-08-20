"""PDF handling: does the text actually leave the file?

The tests that matter here look past ``get_text()``. A redaction that only
removes the visible glyph while leaving the characters in a compressed content
stream would pass a naive check and fail the user, so the leak tests decompress
every object in the output and search there too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF is required for PDF support")

from freedocs.core.findings import Span  # noqa: E402
from freedocs.core.stream import Edit  # noqa: E402
from freedocs.formats.pdf_text import (  # noqa: E402
    MIN_FONT_SIZE,
    PdfSpanLocator,
    PdfTextHandler,
    ScannedPdfNotSupported,
)
from freedocs.formats.router import handler_for  # noqa: E402

from .conftest import CANARIES, l1_scrubber  # noqa: E402

LINES = [
    "Scheda cliente - RISERVATA",
    "Cliente: Mario Rossi",
    f"Codice fiscale: {CANARIES['IT_CODICE_FISCALE']}",
    f"Partita IVA: {CANARIES['IT_PARTITA_IVA']}",
    f"IBAN per il rimborso: {CANARIES['IBAN']}",
    f"Numero AVS: {CANARIES['CH_AHV']}",
    f"UID azienda: {CANARIES['CH_UID']}",
    f"Contatto: {CANARIES['EMAIL']}",
    "Note: contratto annuale, rinnovo automatico",
]

#: What the L1 layer finds in the fixture above. "Mario Rossi" is deliberately
#: absent: these tests pin the registry to L1 so they measure PDF write-back
#: rather than model behaviour. Name detection is covered by the benchmark.
EXPECTED = [
    CANARIES["IT_CODICE_FISCALE"],
    CANARIES["IT_PARTITA_IVA"],
    CANARIES["IBAN"],
    CANARIES["CH_AHV"],
    CANARIES["CH_UID"],
    CANARIES["EMAIL"],
]


def make_pdf(
    path: Path,
    lines: list[str] | None = None,
    *,
    pages: int = 1,
    metadata: dict[str, str] | None = None,
    xmp: str | None = None,
    toc: list | None = None,
    annotation: str | None = None,
    attachment: tuple[str, bytes] | None = None,
) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        y = 80
        for line in lines if lines is not None else LINES:
            page.insert_text((60, y), line, fontname="helv", fontsize=11)
            y += 20
        if annotation:
            page.add_text_annot((400, 90), annotation)
    if metadata:
        doc.set_metadata(metadata)
    if xmp:
        doc.set_xml_metadata(xmp)
    if toc:
        doc.set_toc(toc)
    if attachment:
        doc.embfile_add(attachment[0], attachment[1])
    doc.save(str(path), garbage=4, clean=True, deflate=True)
    doc.close()
    return path


def decompressed_objects(data: bytes) -> list[bytes]:
    """Every object stream in the file, decompressed.

    Searching the raw bytes alone is not enough: content streams are usually
    Flate-compressed, so a surviving canary would be invisible to a plain
    substring search over the file.
    """
    doc = pymupdf.open(stream=data, filetype="pdf")
    chunks: list[bytes] = []
    for xref in range(1, doc.xref_length()):
        try:
            stream = doc.xref_stream(xref)
        except Exception:
            continue
        if stream:
            chunks.append(stream)
    return chunks


def survives_anywhere(data: bytes, value: str) -> bool:
    needle = value.encode()
    if needle in data:
        return True
    return any(needle in chunk for chunk in decompressed_objects(data))


def text_of(data: bytes) -> str:
    doc = pymupdf.open(stream=data, filetype="pdf")
    # sort=True because redaction replacement text is appended to the end of the
    # content stream; without sorting the output reads out of order.
    return "\n".join(page.get_text(sort=True) for page in doc)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "scheda.pdf")


# -- routing ------------------------------------------------------------------


def test_router_picks_the_pdf_handler(source: Path):
    assert isinstance(handler_for(source), PdfTextHandler)


def test_sniff_uses_magic_bytes_not_the_extension(tmp_path: Path):
    """A renamed PDF is still a PDF, and must not be shredded as plain text."""
    renamed = make_pdf(tmp_path / "documento.txt")
    assert isinstance(handler_for(renamed), PdfTextHandler)


# -- extraction ---------------------------------------------------------------


def test_extracted_text_contains_the_document_lines(source: Path):
    stream = handler_for(source).extract()
    for line in LINES:
        assert line in stream.text


def test_extraction_records_one_box_per_character(source: Path):
    stream = handler_for(source).extract()
    for anchor in stream.anchors:
        locator = anchor.locator
        assert isinstance(locator, PdfSpanLocator)
        assert len(locator.char_boxes) == len(anchor), (
            "a character range cannot be turned into a rectangle unless every "
            "character has its own box"
        )


def test_multi_page_documents_are_flattened_in_order(tmp_path: Path):
    stream = handler_for(make_pdf(tmp_path / "due.pdf", pages=2)).extract()
    parts = [anchor.part for anchor in stream.anchors]
    assert "page:1" in parts and "page:2" in parts
    assert parts.index("page:1") < parts.index("page:2")


# -- scanned documents --------------------------------------------------------


def test_a_pdf_without_a_text_layer_is_refused(tmp_path: Path):
    """Returning a scan untouched but reported as scrubbed is the worst outcome."""
    doc = pymupdf.open()
    page = doc.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(pymupdf.Rect(50, 50, 250, 150), pixmap=pixmap)
    path = tmp_path / "scansione.pdf"
    doc.save(str(path))
    doc.close()

    with pytest.raises(ScannedPdfNotSupported, match="no usable text layer"):
        handler_for(path).extract()


# -- redaction ----------------------------------------------------------------


@pytest.mark.leak
@pytest.mark.parametrize("value", EXPECTED)
def test_canary_does_not_survive_anywhere_in_the_output(source: Path, value: str):
    """The real test: not merely invisible, but absent from every stream."""
    result = l1_scrubber().scrub_file(source)
    assert not survives_anywhere(result.output, value)


@pytest.mark.leak
def test_verification_passes(source: Path):
    result = l1_scrubber().scrub_file(source)
    assert result.verify.ok, result.verify.summary()
    assert result.verify.checked_values == len(EXPECTED)


def test_placeholders_are_written_into_the_page(source: Path):
    text = text_of(l1_scrubber().scrub_file(source).output)
    for placeholder in ("[CF_1]", "[PIVA_1]", "[IBAN_1]", "[AVS_1]", "[UID_1]", "[EMAIL_1]"):
        assert placeholder in text


def test_surrounding_text_is_left_alone(source: Path):
    """Character-level boxes exist so that neighbouring text is never touched."""
    text = text_of(l1_scrubber().scrub_file(source).output)
    assert "Scheda cliente - RISERVATA" in text
    assert "Note: contratto annuale, rinnovo automatico" in text
    assert "Codice fiscale:" in text
    assert "IBAN per il rimborso:" in text


def test_output_is_a_readable_pdf(source: Path):
    result = l1_scrubber().scrub_file(source)
    doc = pymupdf.open(stream=result.output, filetype="pdf")
    assert doc.page_count == 1
    assert not doc.is_repaired


def test_a_clean_pdf_keeps_all_of_its_text(tmp_path: Path):
    lines = ["Verbale di riunione", "Approvato il preventivo per il progetto."]
    result = l1_scrubber().scrub_file(make_pdf(tmp_path / "pulito.pdf", lines))
    text = text_of(result.output)
    assert not result.removed
    for line in lines:
        assert line in text


# -- hidden content -----------------------------------------------------------


@pytest.fixture
def loaded(tmp_path: Path) -> Path:
    return make_pdf(
        tmp_path / "carico.pdf",
        metadata={
            "author": "Marco Tribuzio",
            "title": "Riservato",
            "subject": CANARIES["EMAIL"],
            "keywords": CANARIES["IBAN"],
        },
        xmp="<x:xmpmeta xmlns:x='adobe:ns:meta/'><nome>Mario Rossi</nome></x:xmpmeta>",
        toc=[[1, "Dossier Mario Rossi", 1]],
        annotation="nota interna: cliente moroso",
        attachment=("allegato.txt", f"IBAN interno {CANARIES['IBAN']}".encode()),
    )


def test_hidden_content_is_inventoried(loaded: Path):
    kinds = {item.kind for item in l1_scrubber().scrub_file(loaded).hidden_removed}
    assert kinds == {
        "metadata",
        "xmp-metadata",
        "embedded-files",
        "outline",
        "annotations",
    }


def test_metadata_and_xmp_are_gone(loaded: Path):
    doc = pymupdf.open(stream=l1_scrubber().scrub_file(loaded).output, filetype="pdf")
    populated = {key: value for key, value in (doc.metadata or {}).items() if value}
    # "format" describes the file version, not its author.
    assert set(populated) <= {"format"}
    assert not doc.get_xml_metadata()


def test_outline_attachments_and_annotations_are_gone(loaded: Path):
    doc = pymupdf.open(stream=l1_scrubber().scrub_file(loaded).output, filetype="pdf")
    assert doc.get_toc() == []
    assert doc.embfile_names() == []
    assert [annot for page in doc for annot in page.annots()] == []


@pytest.mark.leak
def test_annotation_text_does_not_survive(loaded: Path):
    """scrub() has no flag for annotations; they are deleted explicitly.

    This regressed once: the report claimed the annotation had been removed while
    the note was still sitting in the file.
    """
    output = l1_scrubber().scrub_file(loaded).output
    assert not survives_anywhere(output, "cliente moroso")


@pytest.mark.leak
def test_metadata_values_do_not_survive(loaded: Path):
    output = l1_scrubber().scrub_file(loaded).output
    for value in ("Marco Tribuzio", "Riservato", CANARIES["EMAIL"]):
        assert not survives_anywhere(output, value)


@pytest.mark.leak
def test_attachment_contents_do_not_survive(loaded: Path):
    output = l1_scrubber().scrub_file(loaded).output
    assert not survives_anywhere(output, CANARIES["IBAN"])
    assert not survives_anywhere(output, "allegato.txt")


# -- placeholder fitting ------------------------------------------------------


#: Enough text for the document to have a credible text layer, so that these
#: tests exercise the fitting logic rather than the scanned-PDF guard.
FILLER_LINES = [
    "Verbale della riunione trimestrale del comitato",
    "Approvato il preventivo per il progetto interno",
]


def _replace(handler: PdfTextHandler, needle: str, replacement: str) -> bytes:
    """Redact the first occurrence of ``needle``, whatever offset it lands at."""
    stream = handler.extract()
    start = stream.text.index(needle)
    edit = Edit(Span(start, start + len(needle)), replacement)
    return handler.write_back(stream.plan_edits([edit]))


def test_placeholder_too_wide_is_shrunk_and_reported(tmp_path: Path):
    """A placeholder wider than its original still gets drawn, just smaller."""
    path = make_pdf(tmp_path / "corto.pdf", ["ab@c.it", *FILLER_LINES])
    handler = handler_for(path)
    output = _replace(handler, "ab@c.it", "[EMAIL_1]")

    text = text_of(output)
    assert "[EMAIL_1]" in text
    assert "ab@c.it" not in text
    assert any("shrunk" in warning for warning in handler.warnings)


def test_placeholder_that_cannot_fit_is_dropped_but_reported(tmp_path: Path):
    """The library drops unfittable text silently. That must not stay silent.

    Removal is still guaranteed; only the visible marker is lost, and the user is
    told so rather than left to notice a blank gap.
    """
    path = make_pdf(tmp_path / "strettissimo.pdf", ["Riferimento Xy interno", *FILLER_LINES])
    handler = handler_for(path)
    output = _replace(handler, "Xy", "[UN_SEGNAPOSTO_MOLTO_LUNGO_1]")

    text = text_of(output)
    assert "[UN_SEGNAPOSTO_MOLTO_LUNGO_1]" not in text
    assert "Riferimento Xy" not in text, "the original must be gone even so"
    assert "Riferimento" in text, "and only the original, not its neighbours"
    assert any("does not fit" in warning for warning in handler.warnings)
    assert f"{MIN_FONT_SIZE:g}pt" in " ".join(handler.warnings)


def test_warnings_reach_the_scrub_result(source: Path):
    """The channel has to be wired end to end or a degradation goes unnoticed."""
    result = l1_scrubber().scrub_file(source)
    assert any("reading-order sorting" in warning for warning in result.warnings)


def test_a_document_with_nothing_to_redact_warns_about_nothing(tmp_path: Path):
    path = make_pdf(tmp_path / "pulito.pdf", FILLER_LINES)
    assert l1_scrubber().scrub_file(path).warnings == []

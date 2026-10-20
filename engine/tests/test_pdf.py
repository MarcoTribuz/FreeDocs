"""PDF handling: does the text actually leave the file?

The tests that matter here look past ``get_text()``. A redaction that only
removes the visible glyph while leaving the characters in a compressed content
stream would pass a naive check and fail the user, so the leak tests decompress
every object in the output and search there too.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF is required for PDF support")

from freedocs.core.findings import Span  # noqa: E402
from freedocs.core.stream import Edit  # noqa: E402
from freedocs.formats.pdf import (  # noqa: E402
    MIN_FONT_SIZE,
    PdfSpanLocator,
    PdfTextHandler,
    ScannedPdfNotSupported,
    ocr_unavailable_reason,
    tessdata_path,
)
from freedocs.formats.router import handler_for  # noqa: E402

from .conftest import CANARIES, l1_scrubber  # noqa: E402


def pdf_ocr_unavailable() -> bool:
    """OCR needs Tesseract and its language data, neither of which pip installs."""
    return ocr_unavailable_reason() is not None


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


def make_blank_image_pdf(path: Path) -> Path:
    """A page carrying an image with no text in it at all."""
    doc = pymupdf.open()
    page = doc.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(pymupdf.Rect(50, 50, 250, 150), pixmap=pixmap)
    doc.save(str(path))
    doc.close()
    return path


def make_scan(path: Path, lines: list[str] | None = None, *, pages: int = 1) -> Path:
    """A genuine scan: a born-digital page rasterised, with no text layer left.

    Built by rendering rather than by omitting text, so the fixture is a real
    picture of words and OCR has to actually read it.
    """
    source = pymupdf.open(
        stream=make_pdf(path.with_suffix(".src.pdf"), lines, pages=pages).read_bytes(),
        filetype="pdf",
    )
    scan = pymupdf.open()
    for page in source:
        pixmap = page.get_pixmap(dpi=200)
        target = scan.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, pixmap=pixmap)
    scan.save(str(path))
    scan.close()
    return path


def test_a_rasterised_page_really_has_no_text_layer(tmp_path: Path):
    """If it had one, every OCR test below would be testing the wrong thing."""
    path = make_scan(tmp_path / "scansione.pdf")
    doc = pymupdf.open(str(path))
    assert doc[0].get_text().strip() == ""


def test_a_pdf_without_a_text_layer_is_refused_when_ocr_is_unavailable(tmp_path: Path, monkeypatch):
    """Returning a scan untouched but reported as scrubbed is the worst outcome."""
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: None)
    path = make_scan(tmp_path / "scansione.pdf")
    with pytest.raises(ScannedPdfNotSupported, match="no usable text layer on page"):
        handler_for(path).extract()


def test_the_refusal_names_the_pages_and_what_to_install(tmp_path: Path, monkeypatch):
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: None)
    path = make_scan(tmp_path / "due.pdf", pages=2)
    with pytest.raises(ScannedPdfNotSupported) as caught:
        handler_for(path).extract()
    assert "1, 2" in str(caught.value)
    assert "Tesseract" in str(caught.value)


def test_a_blank_image_page_is_not_refused(tmp_path: Path):
    """A separator page with a logo on it is not a scan of anything."""
    if pdf_ocr_unavailable():
        pytest.skip("OCR is not configured")
    handler = handler_for(make_blank_image_pdf(tmp_path / "vuota.pdf"))
    handler.extract()
    assert any("OCR found no text" in warning for warning in handler.warnings)


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
    for placeholder in (
        "[TAX_ID_1]",
        "[VAT_ID_1]",
        "[IBAN_1]",
        "[NATIONAL_ID_1]",
        "[COMPANY_ID_1]",
        "[EMAIL_1]",
    ):
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


# -- OCR ----------------------------------------------------------------------

ocr = pytest.mark.skipif(pdf_ocr_unavailable(), reason="Tesseract language data not configured")


def reocr(data: bytes) -> str:
    """Read the output the way an attacker would: machine-read the picture again.

    Checking the text layer is not enough for a scan. After redaction the page
    carries the placeholders, which looks like ordinary text while the pixels —
    the only place the data ever was — go unexamined.
    """
    doc = pymupdf.open(stream=data, filetype="pdf")
    out = []
    for page in doc:
        textpage = page.get_textpage_ocr(
            flags=0, language="ita+eng", dpi=200, full=True, tessdata=tessdata_path()
        )
        out.append(page.get_text("text", textpage=textpage))
    return "\n".join(out)


@ocr
def test_ocr_hands_mupdf_an_ascii_name_under_an_accented_install(tmp_path: Path, monkeypatch):
    """MuPDF opens the language data with a narrow `fopen`.

    On Windows that reads a UTF-8 path in the ANSI code page, so a per-user
    install under `C:\\Users\\JürgMüller\\` found no `.traineddata` and every
    scan was refused. macOS cannot reproduce that failure, so this pins the
    shape of the call instead: an ASCII name, resolved from the right directory,
    and the working directory put back afterwards.
    """
    from freedocs.formats import pdf as pdf_module

    accented = tmp_path / "Jürg Müller - Réalise" / "tessdata"
    shutil.copytree(pdf_module.tessdata_path(), accented)
    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: str(accented))
    seen: list[tuple[str, Path]] = []
    original = pymupdf.Page.get_textpage_ocr

    def spy(page, *args, **kwargs):
        seen.append((kwargs["tessdata"], Path.cwd()))
        return original(page, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", spy)
    before = Path.cwd()

    stream = handler_for(make_scan(tmp_path / "scansione.pdf")).extract()

    assert "Scheda cliente" in stream.text
    assert seen and all(name.isascii() for name, _ in seen)
    assert all(where.resolve() == accented.resolve() for _, where in seen)
    assert Path.cwd() == before


def test_a_failed_ocr_is_not_reported_as_a_missing_one(tmp_path: Path, monkeypatch):
    """The refusal used to read "OCR is not available: None".

    OCR was available and had failed, so the advice to install Tesseract sent
    the reader after the one thing that was not wrong.
    """
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: str(tmp_path))
    monkeypatch.setattr(pdf_module, "tesseract_binary", lambda: "tesseract")
    monkeypatch.setattr(pdf_module, "ocr_unavailable_reason", lambda: None)

    def broken(page, *args, **kwargs):
        raise RuntimeError("Tesseract language initialisation failed")

    monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", broken)
    before = Path.cwd()
    with pytest.raises(ScannedPdfNotSupported) as caught:
        handler_for(make_scan(tmp_path / "scansione.pdf")).extract()
    message = str(caught.value)
    assert "OCR failed on it: Tesseract language initialisation failed" in message
    assert "None" not in message
    assert Path.cwd() == before


@ocr
def test_ocr_reads_a_scanned_page(tmp_path: Path):
    stream = handler_for(make_scan(tmp_path / "scansione.pdf")).extract()
    assert CANARIES["IT_CODICE_FISCALE"] in stream.text
    assert "Scheda cliente" in stream.text


@ocr
def test_ocr_gives_a_box_per_character(tmp_path: Path):
    """Same structure as the text layer, so redaction is one code path."""
    stream = handler_for(make_scan(tmp_path / "scansione.pdf")).extract()
    assert stream.anchors
    for anchor in stream.anchors:
        assert isinstance(anchor.locator, PdfSpanLocator)
        assert len(anchor.locator.char_boxes) == len(anchor)


@ocr
def test_ocr_boxes_are_inside_the_page(tmp_path: Path):
    """PyMuPDF returns page coordinates, not pixels; a pixel bbox would overflow."""
    path = make_scan(tmp_path / "scansione.pdf")
    doc = pymupdf.open(str(path))
    width, height = doc[0].rect.width, doc[0].rect.height
    for anchor in handler_for(path).extract().anchors:
        for x0, y0, x1, y1 in anchor.locator.char_boxes:
            assert -1 <= x0 <= x1 <= width + 1
            assert -1 <= y0 <= y1 <= height + 1


@ocr
def test_the_page_is_reported_as_machine_read(tmp_path: Path):
    """An OCR misreading is a value this tool cannot detect. Say so."""
    result = l1_scrubber().scrub_file(make_scan(tmp_path / "scansione.pdf"))
    assert any("read by OCR" in warning for warning in result.warnings)
    assert any("check those pages by eye" in warning for warning in result.warnings)


@ocr
def test_a_born_digital_page_is_not_reported_as_machine_read(source: Path):
    result = l1_scrubber().scrub_file(source)
    assert not any("read by OCR" in warning for warning in result.warnings)


@ocr
@pytest.mark.leak
def test_a_canary_on_a_scanned_page_is_no_longer_readable(tmp_path: Path):
    """The redaction that matters here is to the pixels: there are no glyphs."""
    result = l1_scrubber().scrub_file(make_scan(tmp_path / "scansione.pdf"))
    recognised = reocr(result.output)
    assert CANARIES["IT_CODICE_FISCALE"] not in recognised
    assert "CH93" not in recognised


@ocr
@pytest.mark.leak
def test_the_rest_of_a_scanned_page_is_still_readable(tmp_path: Path):
    """Blanking the whole image would leak nothing and be useless."""
    recognised = reocr(l1_scrubber().scrub_file(make_scan(tmp_path / "scansione.pdf")).output)
    assert "Scheda cliente" in recognised


@ocr
@pytest.mark.leak
def test_verification_re_reads_the_pixels(tmp_path: Path, monkeypatch):
    """A failed pixel redaction must fail the run, not pass on the placeholders.

    Without harden_for_verification the check inspected the two placeholder
    strings the redaction had just written and never looked at the image.
    """
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module.PdfTextHandler, "write_back", lambda self, edits: self.data)
    from freedocs.verify import LeakDetected

    with pytest.raises(LeakDetected):
        l1_scrubber().scrub_file(make_scan(tmp_path / "scansione.pdf"))


@ocr
def test_verification_hardening_is_off_during_extraction(source: Path):
    """OCRing a born-digital page's own text is pure cost, so it is opt-in.
    Its pictures are read either way - see the tests below."""
    handler = handler_for(source)
    assert handler.ocr_every_imaged_page is False
    handler.harden_for_verification()
    assert handler.ocr_every_imaged_page is True


@ocr
def test_a_mixed_document_ocrs_only_the_scanned_page(tmp_path: Path):
    """Real files mix the two: a Word export with a signed page scanned back in."""
    native = pymupdf.open(str(make_pdf(tmp_path / "nativo.pdf")))
    scanned = pymupdf.open(str(make_scan(tmp_path / "scansione.pdf", ["Allegato firmato"])))
    merged = pymupdf.open()
    merged.insert_pdf(native)
    merged.insert_pdf(scanned)
    path = tmp_path / "misto.pdf"
    merged.save(str(path))

    handler = handler_for(path)
    stream = handler.extract()
    assert handler.ocr_pages == [2]
    assert CANARIES["IBAN"] in stream.text
    assert "Allegato firmato" in stream.text


def make_pasted_picture(path: Path) -> Path:
    """A born-digital page with a picture of text on it: a table pasted as a
    screenshot, a logo with a name in it. The page's own text is long enough
    that nothing treats it as a scan."""
    picture = pymupdf.open(
        stream=make_pdf(
            path.with_suffix(".src.pdf"), [f"IBAN per il rimborso: {CANARIES['IBAN']}"]
        ).read_bytes(),
        filetype="pdf",
    )
    pixmap = picture[0].get_pixmap(dpi=200, clip=pymupdf.Rect(50, 60, 450, 90))
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 80), "Verbale di riunione - allegato", fontname="helv", fontsize=11)
    page.insert_image(pymupdf.Rect(60, 120, 460, 150), pixmap=pixmap)
    doc.save(str(path))
    doc.close()
    return path


@ocr
def test_text_inside_a_picture_on_a_born_digital_page_is_read(tmp_path: Path):
    """Extraction read only the text layer of such a page while verification
    OCRs every imaged page, so a value in a picture was never redacted. Stage 6
    noticed only when the same value was also removed from the text."""
    handler = handler_for(make_pasted_picture(tmp_path / "allegato.pdf"))
    stream = handler.extract()
    assert CANARIES["IBAN"] in stream.text
    assert handler.ocr_image_pages == [1]
    assert handler.ocr_pages == []


@ocr
def test_a_picture_does_not_fuse_with_the_page_text(tmp_path: Path):
    """In reading order MuPDF interleaves OCR words with native lines -
    `CANTONImpression` on a real report. The text layer must come through
    exactly as it would without the picture."""
    stream = handler_for(make_pasted_picture(tmp_path / "allegato.pdf")).extract()
    assert "Verbale di riunione - allegato\n" in stream.text
    assert stream.text.count("Verbale di riunione") == 1


@ocr
@pytest.mark.leak
def test_a_canary_inside_a_picture_is_no_longer_readable(tmp_path: Path):
    result = l1_scrubber().scrub_file(make_pasted_picture(tmp_path / "allegato.pdf"))
    assert result.verify.ok, result.verify.summary()
    assert "CH93" not in reocr(result.output)
    assert "Verbale di riunione" in text_of(result.output)
    assert any("text inside the images on page(s) 1" in w for w in result.warnings)


def test_a_picture_on_a_born_digital_page_is_not_refused_without_ocr(tmp_path: Path, monkeypatch):
    """Verification OCRs every imaged page, and without OCR it treated a page
    with a logo on it as an unreadable scan: every PDF with a picture in it was
    refused on a machine without Tesseract, after the scrub, with a sentence
    claiming the page had no text layer. The text layer is real; the pictures
    are stated as unread."""
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: None)
    result = l1_scrubber().scrub_file(make_pasted_picture(tmp_path / "allegato.pdf"))
    assert result.verify.ok
    assert any(
        "carry images that were not read" in w and "not redacted" in w for w in result.warnings
    )


# -- what "OCR is available" has to mean --------------------------------------


def test_ocr_is_not_reported_available_without_the_binary(monkeypatch):
    """The language data is only half of what OCR needs.

    PyMuPDF shells out to the `tesseract` executable, and the two halves are
    installed separately: a packaged build carries the `.traineddata` files
    beside its executable and cannot carry the binary. Reporting availability
    from the data alone made the capability true on every machine, so the window
    promised OCR and the first scan failed inside Tesseract.
    """
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tesseract_binary", lambda: None)
    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: "/somewhere/tessdata")
    reason = pdf_module.ocr_unavailable_reason()
    assert reason is not None
    assert "PATH" in reason


def test_ocr_is_not_reported_available_without_the_language_data(monkeypatch):
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tesseract_binary", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: None)
    reason = pdf_module.ocr_unavailable_reason()
    assert reason is not None
    assert "traineddata" in reason


def test_the_refusal_says_which_half_is_missing(tmp_path: Path, monkeypatch):
    """Naming it is the difference between a fixable message and a dead end."""
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tesseract_binary", lambda: None)
    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: None)
    path = make_scan(tmp_path / "scansione.pdf")
    with pytest.raises(ScannedPdfNotSupported) as caught:
        handler_for(path).extract()
    assert "PATH" in str(caught.value)


def test_the_requested_languages_cover_the_supported_countries():
    """Nine languages for twelve countries, and the list has to track them.

    A country added to SUPPORTED_COUNTRIES whose language nobody requested reads
    its scans through the wrong alphabet's model, which is a silent quality loss
    rather than an error.
    """
    from freedocs.formats import pdf as pdf_module

    requested = set(pdf_module.DEFAULT_OCR_LANGUAGE.split("+"))
    assert requested == {"ita", "deu", "fra", "eng", "spa", "nld", "por", "pol", "swe"}

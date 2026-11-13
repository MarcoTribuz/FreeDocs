"""What the window needs to say a result in the reader's words.

Two things the desktop window used to quote as English engine prose: the
hidden-content list (``custom-xml-store``, ``revision-save-ids``, one line per
part) and the inside-a-word warning ("a PERSON value found by gliner2:person
... still appears 7x inside longer words"). Both now reach the window as closed
vocabularies plus counts, and the inside-a-word case also carries the words
themselves and where they stand - down the pipe only, never into the report.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.registry import DetectorRegistry
from freedocs.formats.base import HIDDEN_KINDS, REGION_KINDS, HiddenItem, Region
from freedocs.formats.ooxml.regions import ooxml_region
from freedocs.formats.pdf import PdfTextHandler
from freedocs.formats.plaintext import PlainTextHandler
from freedocs.pipeline import Scrubber
from freedocs.report import build_report
from freedocs.rpc import _inside_words, _pipe_warnings
from freedocs.verify import EmbeddedWord, verify_output

APP_I18N = Path(__file__).resolve().parents[2] / "app" / "src" / "lib" / "i18n"


def person(text: str) -> Finding:
    return Finding(
        span=Span(0, len(text)),
        entity=EntityType.PERSON,
        text=text,
        layer=Layer.NER,
        detector="gliner2:person",
    )


class _Finds:
    """A detector that finds one whole word, as the model did on the real file."""

    def __init__(self, value: str) -> None:
        self.value = value

    def detect(self, text: str):
        return [
            Finding(
                span=Span(match.start(), match.end()),
                entity=EntityType.PERSON,
                text=self.value,
                layer=Layer.NER,
                detector="gliner2:person",
            )
            for match in re.finditer(rf"\b{self.value}\b", text)
        ]


def scrub(path: Path, value: str):
    return Scrubber(registry=DetectorRegistry(detectors=[_Finds(value)])).scrub_file(path)


# -- the vocabularies ---------------------------------------------------------


def test_an_unknown_hidden_kind_is_refused_where_it_is_written():
    with pytest.raises(ValueError, match="HIDDEN_KINDS"):
        HiddenItem(part="x", kind="something-new", detail="")


def test_an_unknown_region_is_refused():
    with pytest.raises(ValueError):
        Region("chapter")


@pytest.mark.parametrize("locale", ["en", "it", "de", "fr"])
def test_every_kind_and_region_has_words_in_every_window_language(locale: str):
    """The window translates by key; a kind it has no words for shows a slug.

    svelte-check proves the four catalogues agree with each other. This proves
    they agree with the engine, which nothing on the TypeScript side can see.
    """
    catalogue = (APP_I18N / f"{locale}.ts").read_text(encoding="utf-8")
    assert _keys(catalogue, "hiddenKind") == HIDDEN_KINDS, locale
    assert _keys(catalogue, "region") == REGION_KINDS, locale


def _keys(catalogue: str, block: str) -> set[str]:
    """The keys of one top-level ``block: { ... }`` object in a catalogue."""
    body = re.search(rf"^\t{block}: \{{\n(.*?)^\t\}}", catalogue, re.M | re.S)
    assert body, block
    return set(re.findall(r"^\t\t'?([a-z-]+)'?:", body.group(1), re.M))


# -- regions ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("part", "kind"),
    [
        ("word/document.xml", "body"),
        ("word/header2.xml", "header"),
        ("word/footer1.xml", "footer"),
        ("word/footnotes.xml", "footnote"),
        ("word/endnotes.xml", "endnote"),
        ("word/comments.xml", "comment"),
        ("word/_rels/document.xml.rels", "link"),
        ("docProps/app.xml", "metadata"),
        ("xl/sharedStrings.xml", "sheet"),
        ("xl/charts/chart1.xml", "chart"),
        ("ppt/slides/slide4.xml", "slide"),
        ("ppt/notesSlides/notesSlide4.xml", "notes"),
        ("ppt/slideLayouts/slideLayout1.xml", "other"),
    ],
)
def test_an_office_part_is_named_for_a_reader(part: str, kind: str):
    assert ooxml_region(part) == Region(kind)


def test_a_pdf_page_keeps_the_number_a_viewer_shows():
    handler = PdfTextHandler.__new__(PdfTextHandler)
    assert handler.region_of("page:3") == Region("page", 3)
    assert handler.region_of("document") == Region("other")


def test_a_slide_is_numbered_by_its_position_not_its_file_name(tmp_path: Path):
    """PowerPoint keeps ``slide1.xml`` as its name when the slide is moved."""
    pptx = pytest.importorskip("pptx")
    from freedocs.formats.ooxml.pptx import PptxHandler

    deck = pptx.Presentation()
    for _ in range(3):
        deck.slides.add_slide(deck.slide_layouts[6])
    ids = deck.slides._sldIdLst
    first = ids[0]
    ids.remove(first)
    ids.append(first)  # slide1.xml is now shown third
    buffer = io.BytesIO()
    deck.save(buffer)

    handler = PptxHandler(Path("deck.pptx"), buffer.getvalue())
    assert handler.region_of("ppt/slides/slide1.xml") == Region("slide", 3)
    assert handler.region_of("ppt/slides/slide2.xml") == Region("slide", 1)


def test_a_sheet_is_numbered_by_its_tab_position():
    openpyxl = pytest.importorskip("openpyxl")
    from freedocs.formats.ooxml.xlsx import XlsxHandler

    book = openpyxl.Workbook()
    book.create_sheet("Second")
    buffer = io.BytesIO()
    book.save(buffer)

    handler = XlsxHandler(Path("book.xlsx"), buffer.getvalue())
    assert handler.region_of("xl/worksheets/sheet2.xml") == Region("sheet", 2)
    # Shared strings belong to no one sheet: a region, no number.
    assert handler.region_of("xl/sharedStrings.xml") == Region("sheet")


# -- the words left inside longer words ---------------------------------------


def test_the_words_are_named_with_where_they_stand():
    result = verify_output(
        PlainTextHandler,
        Path("out.txt"),
        b"Les facteurs, des Facteurs et la limite.",
        [person("Acteurs")],
    )
    (item,) = result.embedded
    assert item.words == (EmbeddedWord(word="facteurs", region=Region("body"), occurrences=2),)


def test_a_word_in_a_header_is_said_to_be_in_the_header(tmp_path: Path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Acteurs : voir la grille.")
    document.sections[0].header.paragraphs[0].text = "Les facteurs du projet"
    path = tmp_path / "note.docx"
    document.save(path)

    result = scrub(path, "Acteurs")
    (item,) = result.verify.embedded
    assert [(word.word, word.region.kind) for word in item.words] == [("facteurs", "header")]


def test_the_pipe_carries_the_words_and_the_report_does_not(tmp_path: Path):
    source = tmp_path / "note.txt"
    source.write_bytes(b"Acteurs : voir la grille des facteurs.\n")
    result = scrub(source, "Acteurs")

    words = _inside_words(result)
    assert words == [
        {
            "entity": "PERSON",
            "value": "Acteurs",
            "detector": "gliner2:person",
            "occurrences": 1,
            "words": [
                {
                    "word": "facteurs",
                    "region": {"kind": "body", "number": None},
                    "occurrences": 1,
                }
            ],
        }
    ]
    # Said once, in structured form: the English sentence is not repeated.
    assert not any("inside longer words" in warning for warning in _pipe_warnings(result))
    # The report still says it, value-free, and names no word.
    report = build_report(result)
    assert any("inside longer words" in warning for warning in report["warnings"])
    assert "facteurs" not in str(report).casefold()
    assert "acteurs" not in str(report).casefold()


# -- on the wire ----------------------------------------------------------------


def _rpc(method: str, **params):
    import json

    from freedocs.rpc import Session, handle

    params.setdefault("detectors", "l1")
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = handle(Session(out=io.StringIO()), json.dumps(request))
    assert response is not None and "error" not in response, response
    return response["result"]


def test_a_scrub_response_carries_the_structured_fields(tmp_path: Path):
    source = tmp_path / "note.txt"
    source.write_text("Nothing to find here.\n", encoding="utf-8")
    (result,) = _rpc("scrub", paths=[str(source)], output_dir=str(tmp_path / "out"))["results"]
    assert result["inside_words"] == []
    assert result["key_respelled"] == 0


def test_the_preview_names_each_part_for_a_reader(tmp_path: Path):
    source = tmp_path / "note.txt"
    source.write_text("Une ligne.\n", encoding="utf-8")
    found = _rpc("inspect", path=str(source), include_text=True)
    assert [part["region"] for part in found["parts"]] == [{"kind": "body", "number": None}]


def test_the_respelled_sentence_becomes_a_count_on_the_wire():
    from types import SimpleNamespace

    from freedocs.core.mapping import respelled_note
    from freedocs.rpc import _restore_payload

    result = SimpleNamespace(
        ok=True,
        restored=(),
        unused=(),
        unknown=(),
        problems=(),
        warnings=["a handler compromise", respelled_note(3)],
        respelled=3,
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("freedocs.rpc.build_restore_report", lambda _: {})
        payload = _restore_payload(result)
    assert payload["respelled"] == 3
    assert payload["warnings"] == ["a handler compromise"]

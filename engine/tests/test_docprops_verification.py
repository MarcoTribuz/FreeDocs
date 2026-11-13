"""What stage 6 reads in ``docProps/`` beyond the extracted stream.

Three ways it went blind on the first version, each pinned here: a part was
skipped whole because one element in it was anchored, only element text was
read, and a pptx's embedded workbook - which names its parts exactly as the
deck does - excluded the deck's own ``app.xml``.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("lxml")

from freedocs.core.stream import Anchor
from freedocs.formats.ooxml.docprops import unextracted_properties_text
from freedocs.formats.ooxml.zip_part import OoxmlPackage, qn

APP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
    ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    "<Application>Microsoft Excel</Application>"
    '<TitlesOfParts><vt:vector size="1" baseType="lpstr">'
    "<vt:lpstr>Clienti</vt:lpstr></vt:vector></TitlesOfParts>"
    '<HLinks><vt:vector size="1" baseType="variant">'
    "<vt:variant><vt:lpwstr>http://intranet.invalid/rossi</vt:lpwstr></vt:variant>"
    "</vt:vector></HLinks>"
    '<Custom note="attribute-bianchi"/>'
    "<!-- comment-verdi -->"
    "</Properties>"
)


def package() -> OoxmlPackage:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("docProps/app.xml", APP)
    return OoxmlPackage.open(buffer.getvalue())


def titles_anchor(pkg: OoxmlPackage) -> Anchor:
    element = next(pkg.tree("docProps/app.xml").iter(qn("vt:lpstr")))  # type: ignore[attr-defined]
    return Anchor(part="docProps/app.xml", locator=element, start=0, end=7)


def test_an_anchored_element_does_not_hide_the_rest_of_its_part():
    """A workbook anchors TitlesOfParts; HLinks beside it must still be read."""
    pkg = package()
    text = unextracted_properties_text(pkg, [titles_anchor(pkg)])
    assert "http://intranet.invalid/rossi" in text
    assert "Clienti" not in text  # in the stream already: counting it twice breaks allowances


def test_attributes_and_comments_are_searched():
    text = unextracted_properties_text(package(), [])
    assert "attribute-bianchi" in text
    assert "comment-verdi" in text


def test_the_producer_is_not_searched():
    assert "Microsoft Excel" not in unextracted_properties_text(package(), [])


def test_a_deck_reads_its_own_app_xml_beside_an_embedded_workbook(tmp_path: Path):
    """Nested anchors name ``docProps/app.xml`` too, and must not exclude the deck's."""
    pytest.importorskip("pptx", reason="python-pptx is a dev dependency")
    from freedocs.formats.ooxml.pptx import PptxHandler

    from .test_pptx import build_deck

    deck = build_deck(tmp_path / "deck.pptx")
    marked = io.BytesIO()
    with zipfile.ZipFile(deck) as source, zipfile.ZipFile(marked, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "docProps/app.xml":
                marker = b"<Manager>deck-marker</Manager></Properties>"
                data = data.replace(b"</Properties>", marker)
            target.writestr(item, data)

    handler = PptxHandler(deck, marked.getvalue())
    stream = handler.extract()
    assert any(anchor.part == "docProps/app.xml" for anchor in stream.anchors), (
        "the embedded workbook no longer anchors its TitlesOfParts; this test needs a new trigger"
    )
    assert "deck-marker" in handler.verification_extras(stream)

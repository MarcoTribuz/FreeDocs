"""Plain text handler: exact round-trip, then correct splicing."""

from __future__ import annotations

from pathlib import Path

import pytest

from freedocs.core.findings import Span
from freedocs.core.stream import Edit
from freedocs.formats.plaintext import PlainTextHandler
from freedocs.formats.router import UnsupportedFormat, handler_for


def handler(text: str, name: str = "doc.txt", encoding: str = "utf-8") -> PlainTextHandler:
    return PlainTextHandler(Path(name), text.encode(encoding))


@pytest.mark.parametrize(
    "text",
    [
        "una riga sola",
        "riga uno\nriga due\n",
        "senza newline finale\nultima",
        "windows\r\nline\r\nendings\r\n",
        "vuota in mezzo\n\nfine\n",
        "",
        "accenti: perché città Zürich\n",
    ],
)
def test_unedited_round_trip_is_byte_identical(text: str):
    """The baseline every other format handler is held to."""
    source = text.encode("utf-8")
    instance = PlainTextHandler(Path("doc.txt"), source)
    instance.extract()
    assert instance.write_back([]) == source


def test_extracted_text_equals_the_file_text():
    text = "riga uno\nriga due\n"
    assert handler(text).extract().text == text


def test_bom_is_preserved():
    source = "con bom\n".encode("utf-8-sig")
    instance = PlainTextHandler(Path("doc.txt"), source)
    instance.extract()
    assert instance.write_back([]) == source


def test_cp1252_file_round_trips_in_its_own_encoding():
    source = "società anonima\n".encode("cp1252")
    instance = PlainTextHandler(Path("doc.txt"), source)
    instance.extract()
    assert instance.write_back([]) == source


def test_edit_is_applied_at_the_right_offset():
    instance = handler("Cliente: Mario Rossi\nSaldo: 100\n")
    stream = instance.extract()
    edits = stream.plan_edits([Edit(span=Span(9, 20), replacement="[PERSONA_1]")])
    assert instance.write_back(edits).decode("utf-8") == "Cliente: [PERSONA_1]\nSaldo: 100\n"


def test_two_edits_on_the_same_line():
    instance = handler("a@b.test e c@d.test\n")
    stream = instance.extract()
    edits = stream.plan_edits(
        [
            Edit(span=Span(0, 8), replacement="[EMAIL_1]"),
            Edit(span=Span(11, 19), replacement="[EMAIL_2]"),
        ]
    )
    assert instance.write_back(edits).decode("utf-8") == "[EMAIL_1] e [EMAIL_2]\n"


def test_edits_on_different_lines():
    instance = handler("prima a@b.test\nseconda c@d.test\n")
    stream = instance.extract()
    edits = stream.plan_edits(
        [
            Edit(span=Span(6, 14), replacement="[EMAIL_1]"),
            Edit(span=Span(23, 31), replacement="[EMAIL_2]"),
        ]
    )
    assert instance.write_back(edits).decode("utf-8") == "prima [EMAIL_1]\nseconda [EMAIL_2]\n"


def test_router_picks_the_plaintext_handler(tmp_path: Path):
    path = tmp_path / "note.md"
    path.write_text("# titolo\n", encoding="utf-8")
    assert isinstance(handler_for(path), PlainTextHandler)


def test_router_rejects_an_unknown_extension(tmp_path: Path):
    path = tmp_path / "archivio.zip"
    path.write_bytes(b"PK\x03\x04")
    with pytest.raises(UnsupportedFormat):
        handler_for(path)

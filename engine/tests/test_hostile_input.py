"""Documents built to break the reader rather than to be read.

Every input this tool sees is hostile by definition: it exists to be pointed at
files from outside, and it parses them with C libraries - MuPDF, libxml2, zlib -
in a process holding the user's own privileges. So the standing question here is
not "is the answer right" but **"is there an answer at all"**: a refusal that
names the file, never a traceback out of a library and never a wait that ends the
session.

Written before the limits they check, and two of them then said not to build a
rule. That is the point of writing them first, and it is the second time it has
happened here - the chunk-artifact defence was measured away the same way.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from freedocs.core import limits
from freedocs.core.errors import InputTooLarge, MalformedDocument
from freedocs.formats.router import handler_for

from .conftest import l1_scrubber


def _zip(entries: dict[str, bytes], compress: bool = True) -> bytes:
    buf = io.BytesIO()
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, "w", mode) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buf.getvalue()


def _docx(tmp_path: Path, entries: dict[str, bytes], compress: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "hostile.docx"
    path.write_bytes(_zip(entries, compress))
    return path


#: The real WordprocessingML namespace, not a placeholder. With a made-up one the
#: handler finds no `w:t` at all, so the entity test below would pass by
#: extracting nothing - which is the wrong reason for it to pass.
W = b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

MINIMAL_DOCX = {
    "[Content_Types].xml": (
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    ),
    "_rels/.rels": (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    ),
    "word/document.xml": b"<w:document " + W + b"><w:body><w:p><w:r><w:t>ok</w:t>"
    b"</w:r></w:p></w:body></w:document>",
}


# --- the zip bomb -------------------------------------------------------------


def test_a_container_that_inflates_far_beyond_itself_is_refused(tmp_path: Path, monkeypatch):
    """Measured before it was fixed: a 0.20 MB container took 334 MB of RSS.

    `OoxmlPackage.open` read every entry into a dict with no cap of any kind, so
    the ratio is whatever zlib will give - and at 1000:1 a 20 MB attachment is
    20 GB. The limit is lowered here rather than building a real one: the point is
    the refusal, and a test that allocates half a gigabyte to prove a limit exists
    is a test nobody runs twice.
    """
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    monkeypatch.setattr(limits, "MAX_INFLATED_BYTES", 4 * 1024 * 1024)

    path = _docx(tmp_path, {**MINIMAL_DOCX, "word/blob.bin": b"\0" * (8 * 1024 * 1024)})
    assert path.stat().st_size < 100_000, "the container itself must stay small"

    with pytest.raises(InputTooLarge):
        handler_for(path).extract()


def test_one_enormous_part_is_refused_even_when_the_total_would_pass(tmp_path: Path, monkeypatch):
    """Two limits, because one part and the sum of many are different attacks and
    a single total lets one 400 MB part through under a 512 MB budget."""
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    monkeypatch.setattr(limits, "MAX_ENTRY_BYTES", 1024 * 1024)
    monkeypatch.setattr(limits, "MAX_INFLATED_BYTES", 64 * 1024 * 1024)

    path = _docx(tmp_path, {**MINIMAL_DOCX, "word/blob.bin": b"\0" * (4 * 1024 * 1024)})
    with pytest.raises(InputTooLarge):
        handler_for(path).extract()


def test_a_lying_header_cannot_smuggle_bytes_past_the_check(tmp_path: Path):
    """Why checking `ZipInfo.file_size` before reading is enough, pinned.

    The obvious objection to a pre-check is that the declared size is
    attacker-controlled metadata. Measured: `ZipExtFile` decompresses at most the
    declared number of bytes and then fails the CRC, so a header claiming 1 KB
    for a 20 MB payload yields *no* bytes rather than 20 MB of them. That is what
    makes the cheap check sound - and it is why the streaming size-counter this
    was going to need is not here.

    What the file gets is a refusal rather than `zipfile`'s own exception, which
    would have reached an RPC caller as `BadZipFile: Bad CRC-32 for ...`.
    """
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    payload = b"A" * (2 * 1024 * 1024)
    raw = bytearray(_zip({**MINIMAL_DOCX, "word/blob.bin": payload}))
    truthful = struct.pack("<I", len(payload))
    assert raw.count(truthful) == 2, "the size is recorded in the local header and the directory"
    raw = bytearray(bytes(raw).replace(truthful, struct.pack("<I", 1024)))

    path = tmp_path / "lying.docx"
    path.write_bytes(bytes(raw))
    with pytest.raises(MalformedDocument):
        handler_for(path).extract()


# --- the XML the container holds ----------------------------------------------


def test_an_entity_is_not_expanded(tmp_path: Path):
    """`resolve_entities=False` is already the defence. This asserts it.

    A nested-entity document is the classic way to turn a few hundred bytes of
    XML into gigabytes of string inside the parser. Measured against the parser
    as configured: the entity yields zero characters, so there is nothing to
    limit and no rule to add here.
    """
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    bomb = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE d [ <!ENTITY a "aaaaaaaaaa">\n'
        b' <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        b' <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
        b' <!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;"> ]>\n'
        b"<w:document " + W + b"><w:body><w:p><w:r><w:t>&d;</w:t></w:r></w:p>"
        b"</w:body></w:document>"
    )
    path = _docx(tmp_path, {**MINIMAL_DOCX, "word/document.xml": bomb})
    stream = handler_for(path).extract()
    assert "aaaaaaaaaa" not in stream.text
    assert len(stream.text) < 1000

    # The control: with the same namespace and no entity, the text *is* found.
    # Without this the assertions above pass on a document nothing could read.
    plain = _docx(tmp_path / "control", MINIMAL_DOCX)
    assert "ok" in handler_for(plain).extract().text


def test_a_content_type_override_naming_a_part_that_is_not_there_is_survivable(
    tmp_path: Path,
):
    """Also measured rather than assumed, and it needed no rule either.

    `[Content_Types].xml` is read for what it declares, and a declaration whose
    part is absent is simply a declaration about nothing. Kept as a standing case
    because the obvious way to write a package reader is to trust that file and
    then `KeyError` on the first missing part.
    """
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    entries = dict(MINIMAL_DOCX)
    entries["[Content_Types].xml"] = (
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Override PartName="/word/absent.xml" ContentType="application/xml"/></Types>'
    )
    path = _docx(tmp_path, entries)
    assert "ok" in handler_for(path).extract().text


def test_an_embedded_workbook_spends_the_same_budget(tmp_path: Path, monkeypatch):
    """A chart's workbook is a zip inside a zip, so its parts are a second place
    the same bytes can arrive from. One budget, or the nesting is the way past
    it."""
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    monkeypatch.setattr(limits, "MAX_INFLATED_BYTES", 4 * 1024 * 1024)

    inner = _zip(
        {
            "xl/workbook.xml": (
                b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
                b'2006/main"><sheets/></workbook>'
            ),
            "xl/blob.bin": b"\0" * (8 * 1024 * 1024),
        }
    )
    path = tmp_path / "hostile.pptx"
    path.write_bytes(
        _zip(
            {
                "[Content_Types].xml": (
                    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
                ),
                "ppt/presentation.xml": (
                    b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/'
                    b'presentationml/2006/main"/>'
                ),
                "ppt/embeddings/chart.xlsx": inner,
            }
        )
    )
    assert path.stat().st_size < 100_000
    with pytest.raises(InputTooLarge):
        handler_for(path).extract()


# --- the file itself ----------------------------------------------------------


def test_a_file_too_large_to_be_a_document_is_refused_before_it_is_read(
    tmp_path: Path, monkeypatch
):
    """`router.handler_for` called `path.read_bytes()` with no cap at all, so the
    first thing that happened to any input was allocating all of it."""
    monkeypatch.setattr(limits, "MAX_INPUT_BYTES", 4096)
    path = tmp_path / "huge.txt"
    path.write_bytes(b"x" * 8192)
    with pytest.raises(InputTooLarge):
        handler_for(path)


# --- PDF ----------------------------------------------------------------------


def _pdf_declaring_pages(path: Path, count: int) -> Path:
    """A real PDF with `count` distinct, empty pages, built by hand.

    By hand because `pymupdf`'s own `new_page()` takes minutes at this scale,
    while the file it would produce is a couple of megabytes - which is the whole
    point: the cost of *reading* a document is not bounded by its size.
    """
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{3 + i} 0 R" for i in range(count))
            + f"] /Count {count} >>"
        ).encode(),
    }
    for index in range(count):
        objects[3 + index] = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for number in sorted(objects):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(out))
    return path


def test_a_pdf_with_more_pages_than_a_document_has_is_refused(tmp_path: Path):
    """Refused at the real limit, not a lowered one, because a hostile PDF is
    cheap to write: 200 000 pages fit in 21 MB.

    Empty pages extract in 11 seconds, which alone would be survivable. What is
    not is the same count with an OCR pass - measured at about 24 ms a page, so
    eighty minutes - and `harden_for_verification` then reads every page again.
    The engine is single-threaded with no cancel, so that is the session.
    """
    pytest.importorskip("pymupdf", reason="PyMuPDF is required for PDF support")
    path = _pdf_declaring_pages(tmp_path / "many.pdf", limits.MAX_PDF_PAGES + 1000)
    with pytest.raises(InputTooLarge):
        handler_for(path).extract()


def test_a_document_of_ordinary_length_is_not_refused(tmp_path: Path):
    """The other half, and the one a limit gets wrong. A limit that refuses a
    document somebody actually has is a regression, not a hardening."""
    pytest.importorskip("pymupdf", reason="PyMuPDF is required for PDF support")
    path = _pdf_declaring_pages(tmp_path / "normal.pdf", 500)
    assert handler_for(path).extract() is not None


def test_a_pdf_the_library_refuses_is_reported_rather_than_raised(tmp_path: Path):
    """A page tree whose kids are all the same object.

    MuPDF catches it - and says so as `RuntimeError: code=7: Invalid number of
    pages`, which escaped `scrub_file` untranslated. From the CLI that is a
    traceback; over the pipe `rpc.handle` renders an unexpected exception into a
    response as `f"{type(exc).__name__}: {exc}"`, so the caller was handed a
    sentence about MuPDF's internals. The library being right is not the same as
    the caller being told.
    """
    pytest.importorskip("pymupdf", reason="PyMuPDF is required for PDF support")
    count = 5000
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Kids ["
            + " ".join("3 0 R" for _ in range(count))
            + f"] /Count {count} >>"
        ).encode(),
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for number in sorted(objects):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n"
    ).encode()

    path = tmp_path / "cyclic.pdf"
    path.write_bytes(bytes(out))
    with pytest.raises(MalformedDocument):
        l1_scrubber().scrub_file(path)


# --- the key file, whose limit lives in the same module -----------------------


def test_a_key_file_is_bounded_by_the_same_module(tmp_path: Path):
    """`core/limits.py` is the one place a size ceiling is written down.

    The hostile *content* of a key file - a work factor built to grind - is
    `test_mapping.py`'s question and is not repeated here. This is only the claim
    that the ceiling comes from the same module the document limits do, so there
    is one answer to "how big may a thing be".
    """
    pytest.importorskip("cryptography", reason="the restore extra is required")
    from freedocs.core.mapping import MalformedMap, read_key_map

    path = tmp_path / "huge.fdmap"
    path.write_bytes(b"{" + b" " * (limits.MAX_MAP_BYTES + 1))
    with pytest.raises(MalformedMap, match="bytes"):
        read_key_map(path, "correct horse battery")


# --- what the two adapters do with one ------------------------------------------
#
# Asserted on both, because they are two adapters over one engine and `15ee0e1`
# was an entire commit about the same thing being missing on the untested side.


def test_an_ooxml_container_that_is_not_the_format_it_claims_is_reported(tmp_path: Path):
    """A zip with the right extension and none of the right parts.

    It raised a bare `ValueError`, which is in `REFUSALS` nowhere: from the CLI a
    traceback, and over the pipe `f"ValueError: ..."` rendered into a response by
    the generic handler. The file is malformed, the caller can be told so, and
    every other file in the batch can still be scrubbed.
    """
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    path = _docx(tmp_path, {"[Content_Types].xml": b"<Types/>"})
    with pytest.raises(MalformedDocument):
        handler_for(path)


def test_the_cli_names_the_file_and_keeps_going(tmp_path: Path, monkeypatch, capsys):
    """One refused document must not end a batch. The exit code says something
    was refused; the other file is still scrubbed and written."""
    from freedocs import cli

    monkeypatch.setattr(limits, "MAX_INPUT_BYTES", 4096)
    hostile = tmp_path / "huge.txt"
    hostile.write_bytes(b"x" * 8192)
    ordinary = tmp_path / "small.txt"
    ordinary.write_text("Contatto: mario.rossi@example.com\n", encoding="utf-8", newline="")

    out = tmp_path / "out"
    status = cli.main(["scrub", "--detectors", "l1", str(hostile), str(ordinary), "-o", str(out)])
    assert status == cli.EXIT_UNSUPPORTED
    assert "huge.txt" in capsys.readouterr().err
    assert (out / "small.txt").is_file()
    assert not (out / "huge.txt").exists()


def test_the_pipe_answers_with_a_code_rather_than_a_traceback(tmp_path: Path, monkeypatch):
    """`rpc.handle` renders an unexpected exception as `f"{type(exc).__name__}:
    {exc}"`, so anything untranslated reaches a caller as a sentence about
    Python. A code is what lets the window say something useful instead."""
    import io
    import json

    from freedocs.rpc import INPUT_TOO_LARGE, Session, handle

    monkeypatch.setattr(limits, "MAX_INPUT_BYTES", 4096)
    hostile = tmp_path / "huge.txt"
    hostile.write_bytes(b"x" * 8192)

    # A real sink: `scrub` emits progress notifications, which is the half of the
    # protocol a failing file still takes part in.
    session = Session(out=io.StringIO())
    response = handle(
        session,
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "scrub",
                "params": {
                    "paths": [str(hostile)],
                    "output_dir": str(tmp_path / "out"),
                    "detectors": "l1",
                },
            }
        ),
    )
    assert response is not None
    failure = response["result"]["results"][0]
    assert failure["error"]["code"] == INPUT_TOO_LARGE
    assert "huge.txt" in failure["error"]["message"]

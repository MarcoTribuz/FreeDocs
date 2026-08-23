"""The command line, which had no tests at all.

That absence is the reason for most of what this file asserts. ``cli.py`` and
``rpc.py`` are two calling adapters over the same engine, and every asymmetry
found between them was on this side: the RPC layer is exercised by 1 095 lines
in ``test_rpc.py`` and drifted toward correctness, while the terminal answered a
different question and nothing noticed.

So these tests are about the *wiring* of the adapter, not about detection
quality — which is measured by ``freedocs benchmark`` against the corpus, and
would be wrong to pin here. Everything runs pinned to L1 for the reason in
``conftest.l1_scrubber``: a model in the loop makes an adapter test slow and
threshold-sensitive without testing anything more of the adapter.

Exit codes are asserted, wording is not. ``EXIT_OK``/``USAGE``/``LEAK``/
``UNSUPPORTED`` are the command's contract with a shell script; the layout of a
line is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from freedocs import cli
from freedocs.diagnostics import engine_version

from .docx_builder import DocxSpec, write_docx

L1 = ["--detectors", "l1"]


@pytest.fixture
def document(tmp_path: Path) -> Path:
    """A plain text file carrying one identifier L1 is certain about."""
    path = tmp_path / "offerta.txt"
    path.write_text(
        "Fattura per Realise Consulting SA.\n"
        "IBAN CH93 0076 2011 6238 5295 7 entro trenta giorni.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def docx(tmp_path: Path) -> Path:
    """A Word file whose confidential text is not all in the body.

    The default ``DocxSpec`` carries metadata, a thumbnail, an rsid table and a
    custom XML store — the categories a reader cannot see by opening the file,
    and the ones the old ``inspect`` reported none of.
    """
    return write_docx(
        tmp_path / "scheda.docx",
        DocxSpec(
            paragraphs=[["Cliente ", "Realise Consulting SA"]],
            comment="cliente moroso",
            deleted="sconto riservato 40%",
        ),
    )


def entity_lines(out: str) -> list[str]:
    """The finding rows of an `inspect` run, without their offsets.

    Offsets are deliberately dropped: `inspect` prints spans and `scrub` prints
    counts, so the comparable part is which entities were decided on.
    """
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0][:1].isdigit() and "-" in parts[0]:
            rows.append(parts[1])
    return sorted(rows)


# --- One read-and-detect path, used by the preview and the scrub -------------
#
# The failure these three guard is the one the engine already fixed once, on the
# other adapter: `rpc.inspect` goes through `Scrubber`, and its docstring says
# why — "a second copy of those stages is how a preview comes to show findings
# the scrub that follows it does not agree with". The copy lived on in the CLI.


def test_inspect_and_scrub_agree_on_what_they_found(docx, tmp_path, capsys):
    assert cli.main(["inspect", *L1, str(docx)]) == cli.EXIT_OK
    inspected = entity_lines(capsys.readouterr().out)

    out_dir = tmp_path / "out"
    assert cli.main(["scrub", *L1, str(docx), "-o", str(out_dir)]) == cli.EXIT_OK
    scrubbed = capsys.readouterr().out

    # The scrub reports counts per entity; expand them back into a sorted list
    # so the two answers are comparable at all.
    removed: list[str] = []
    for line in scrubbed.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isupper() and parts[1].isdigit():
            removed.extend([parts[0]] * int(parts[1]))

    assert inspected == sorted(removed)
    assert inspected, "the fixture must find something, or this asserts nothing"


def test_inspect_reports_the_hidden_content_the_scrub_removes(docx, capsys):
    """The category a reader does not expect, which `inspect` used to omit.

    Without `scrub_hidden` in the preview path this printed nothing at all, so
    the read-only command that exists to answer "is there anything in here" was
    silent about the comment, the tracked deletion and the metadata — none of
    which a reader finds by opening the document.
    """
    assert cli.main(["inspect", *L1, str(docx)]) == cli.EXIT_OK
    out = capsys.readouterr().out

    assert "hidden content found:" in out
    for part in ("word/comments.xml", "docProps/core.xml", "word/document.xml"):
        assert part in out, part
    assert "tracked-deletions" in out

    # The values themselves must not be printed: this listing says where and
    # what kind, never what it said. `deleted="sconto riservato 40%"` and
    # `comment="cliente moroso"` are in the fixture for exactly this check.
    assert "sconto riservato" not in out
    assert "cliente moroso" not in out


def test_inspect_says_when_a_layer_is_missing(document, capsys):
    """A narrowed run must say so, as the scrub does.

    `Inspection.warnings` carries the registry's notes, and printing findings
    without them let a build report reduced coverage in silence — which
    `pipeline` calls the one outcome worse than refusing.
    """
    assert cli.main(["inspect", *L1, "--countries", "ch", str(document)]) == cli.EXIT_OK
    assert "warning:" in capsys.readouterr().out


def test_inspect_writes_nothing(document, tmp_path):
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["inspect", *L1, str(document)]) == cli.EXIT_OK
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


# --- A batch is not abandoned at the first refusal ---------------------------


def test_inspect_looks_at_every_file_even_after_a_refusal(document, tmp_path, capsys):
    """`inspect` used to `return` where `scrub` `continue`s.

    So `freedocs inspect scan.pdf report.docx` never looked at the docx, and the
    exit code was the same either way — the second file simply went unmentioned.
    """
    unsupported = tmp_path / "picture.heic"
    unsupported.write_bytes(b"not a document")

    status = cli.main(["inspect", *L1, str(unsupported), str(document)])

    assert status == cli.EXIT_UNSUPPORTED
    assert document.name in capsys.readouterr().out


# --- A threshold outside [0, 1] is refused, not silently obeyed --------------


@pytest.mark.parametrize("floor", ["1.5", "-0.1"])
def test_a_confidence_floor_outside_the_range_is_refused(floor, document, tmp_path):
    """The one kind of wrong that looks exactly like working.

    `--min-confidence 1.5` put every finding below the floor, so all of them
    became KEEP, the scrub wrote an untouched copy, verification passed
    vacuously — there was nothing in `removed` to search for — and the command
    exited 0. The RPC layer refused the same value; the CLI built the same
    `Policy` unguarded.
    """
    out_dir = tmp_path / "out"

    scrub = ["scrub", *L1, str(document), "-o", str(out_dir), "--min-confidence", floor]
    assert cli.main(scrub) == cli.EXIT_USAGE
    assert not (out_dir / document.name).exists()
    assert cli.main(["inspect", *L1, str(document), "--min-confidence", floor]) == cli.EXIT_USAGE


@pytest.mark.parametrize("floor", ["0", "0.5", "1"])
def test_the_ends_of_the_range_are_allowed(floor, document, tmp_path):
    out_dir = tmp_path / "out"
    status = cli.main(["scrub", *L1, str(document), "-o", str(out_dir), "--min-confidence", floor])
    assert status == cli.EXIT_OK


# --- The adapters must answer the same version -------------------------------


def test_the_engine_names_a_version_rather_than_shrugging():
    """There were two mechanisms, and they disagreed where it mattered.

    The CLI asked `importlib.metadata` and fell back to "unknown"; the RPC layer
    read `__version__`. A PyInstaller one-dir bundle does not reliably carry the
    dist-info, so one executable could report both.
    """
    version = engine_version()
    assert version and version != "unknown"


def test_both_adapters_report_the_same_version():
    from freedocs import rpc

    session = rpc.Session(out=None)  # type: ignore[arg-type]
    assert session.capabilities()["version"] == engine_version()

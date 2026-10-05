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

import os
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


# --- the key file and the reverse path ---------------------------------------
#
# What these guard is the shape of the opt-in rather than the cipher, which
# `test_mapping.py` owns. The adapter's job here is to refuse before it writes:
# a key file aimed at the output directory, a passphrase with nowhere to come
# from, or an incomplete restore reported as a success are all failures of wiring.


@pytest.fixture
def passphrase_file(tmp_path: Path) -> Path:
    path = tmp_path / "pass.txt"
    # A trailing newline on purpose: an editor adds one, and a passphrase that
    # works from one editor and not another is the worst kind of intermittent.
    path.write_text("correct horse battery staple\n", encoding="utf-8")
    return path


def test_no_key_file_is_written_unless_it_is_asked_for(document, tmp_path):
    """The default is unchanged and must stay unchanged. Every file in the tree,
    not just the output directory: a key file appearing anywhere is the failure."""
    out_dir = tmp_path / "out"
    assert cli.main(["scrub", *L1, str(document), "-o", str(out_dir)]) == cli.EXIT_OK
    assert list(tmp_path.rglob("*.fdmap")) == []


def test_a_key_file_is_written_where_it_was_asked_for(document, tmp_path, passphrase_file):
    keys = tmp_path / "keys"
    status = cli.main(
        [
            "scrub",
            *L1,
            str(document),
            "-o",
            str(tmp_path / "out"),
            "--map",
            str(keys),
            "--map-passphrase-file",
            str(passphrase_file),
        ]
    )
    assert status == cli.EXIT_OK
    # Named after the document, not after the run: one key file per document.
    assert (keys / "offerta.fdmap").is_file()


def test_a_key_file_aimed_at_the_output_directory_is_refused(
    document, tmp_path, passphrase_file, capsys
):
    """Refused *before* anything is written, so the user is not left undoing a
    directory by hand."""
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        cli.main(
            [
                "scrub",
                *L1,
                str(document),
                "-o",
                str(out_dir),
                "--map",
                str(out_dir / "keys"),
                "--map-passphrase-file",
                str(passphrase_file),
            ]
        )
    assert list(tmp_path.rglob("*.fdmap")) == []


def test_the_refusal_can_be_overridden_deliberately(document, tmp_path, passphrase_file):
    out_dir = tmp_path / "out"
    status = cli.main(
        [
            "scrub",
            *L1,
            str(document),
            "-o",
            str(out_dir),
            "--map",
            str(out_dir),
            "--map-in-output-dir",
            "--map-passphrase-file",
            str(passphrase_file),
        ]
    )
    assert status == cli.EXIT_OK
    assert (out_dir / "offerta.fdmap").is_file()


def test_an_empty_passphrase_file_is_a_usage_error(document, tmp_path):
    empty = tmp_path / "pass.txt"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(
            [
                "scrub",
                *L1,
                str(document),
                "-o",
                str(tmp_path / "out"),
                "--map",
                str(tmp_path / "keys"),
                "--map-passphrase-file",
                str(empty),
            ]
        )


def test_the_passphrase_can_come_from_the_environment(document, tmp_path, monkeypatch):
    monkeypatch.setenv(cli.PASSPHRASE_ENV, "correct horse battery staple")
    keys = tmp_path / "keys"
    status = cli.main(
        ["scrub", *L1, str(document), "-o", str(tmp_path / "out"), "--map", str(keys)]
    )
    assert status == cli.EXIT_OK
    assert (keys / "offerta.fdmap").is_file()


def test_no_passphrase_and_no_terminal_is_a_usage_error(document, tmp_path, monkeypatch):
    """A silent skip would mean a user who finds out at restore time that there is
    nothing to restore from."""
    monkeypatch.delenv(cli.PASSPHRASE_ENV, raising=False)
    monkeypatch.setattr("sys.stdin", _NotATerminal())
    with pytest.raises(SystemExit):
        cli.main(
            ["scrub", *L1, str(document), "-o", str(tmp_path / "out"), "--map", str(tmp_path / "k")]
        )


def test_a_weak_passphrase_from_the_environment_leaves_nothing_on_disk(
    document, tmp_path, monkeypatch
):
    """The rule has to hold for every source, not only for the prompt.

    `write_key_map` checks again, so nothing weak was ever written - but it
    raises from inside the per-file loop, so the run died on a traceback with the
    scrubbed copy already on disk. That is verbatim the failure `_cmd_scrub` says
    it prevents by resolving the passphrase before anything is read.
    """
    monkeypatch.setenv(cli.PASSPHRASE_ENV, "corto")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        cli.main(["scrub", *L1, str(document), "-o", str(out_dir), "--map", str(tmp_path / "keys")])
    assert list(tmp_path.rglob("*.fdmap")) == []
    assert list(out_dir.glob("*")) == [], "the scrubbed copy must not be written either"


def test_a_weak_passphrase_file_leaves_nothing_on_disk(document, tmp_path):
    weak = tmp_path / "pass.txt"
    weak.write_text("corto\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        cli.main(
            [
                "scrub",
                *L1,
                str(document),
                "-o",
                str(out_dir),
                "--map",
                str(tmp_path / "keys"),
                "--map-passphrase-file",
                str(weak),
            ]
        )
    assert list(tmp_path.rglob("*.fdmap")) == []
    assert list(out_dir.glob("*")) == []


def test_the_passphrase_variable_is_not_left_for_subprocesses(document, tmp_path, monkeypatch):
    """Read once and removed, because PyMuPDF shells out to Tesseract.

    Not a cross-user leak - `/proc/<pid>/environ` is owner-only - but an
    unnecessary copy of the key to every value in the document, in processes that
    have no business holding it.
    """
    import os

    monkeypatch.setenv(cli.PASSPHRASE_ENV, "correct horse battery staple")
    status = cli.main(
        ["scrub", *L1, str(document), "-o", str(tmp_path / "out"), "--map", str(tmp_path / "keys")]
    )
    assert status == cli.EXIT_OK
    assert cli.PASSPHRASE_ENV not in os.environ


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful here")
def test_a_passphrase_file_others_can_read_is_reported(document, tmp_path, capsys):
    """A warning, not a refusal. `ssh` refuses a world-readable private key; this
    file is the key to every value in the document, but refusing would break a
    working setup over a mode the user may not control, so it is said out loud and
    the run continues."""
    loose = tmp_path / "pass.txt"
    loose.write_text("correct horse battery staple\n", encoding="utf-8")
    loose.chmod(0o644)
    status = cli.main(
        [
            "scrub",
            *L1,
            str(document),
            "-o",
            str(tmp_path / "out"),
            "--map",
            str(tmp_path / "keys"),
            "--map-passphrase-file",
            str(loose),
        ]
    )
    assert status == cli.EXIT_OK
    assert "readable" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful here")
def test_the_restored_document_and_its_report_are_owner_only(document, tmp_path, passphrase_file):
    """The key file was meticulously 0600 and the document holding the same values
    in the clear was not. `core/outputs.py` is the one answer; this is the CLI
    half of asking it, and `test_rpc.py` is the other - the defect `15ee0e1` was
    about was the same thing missing on the untested side."""
    out_dir, keys, back = tmp_path / "out", tmp_path / "keys", tmp_path / "back"
    assert (
        cli.main(
            [
                "scrub",
                *L1,
                str(document),
                "-o",
                str(out_dir),
                "--map",
                str(keys),
                "--map-passphrase-file",
                str(passphrase_file),
            ]
        )
        == cli.EXIT_OK
    )
    report = tmp_path / "r.json"
    assert (
        cli.main(
            [
                "restore",
                str(out_dir / "offerta.txt"),
                "--map",
                str(keys / "offerta.fdmap"),
                "-o",
                str(back),
                "--map-passphrase-file",
                str(passphrase_file),
                "--report",
                str(report),
            ]
        )
        == cli.EXIT_OK
    )
    assert (back / "offerta.txt").stat().st_mode & 0o777 == 0o600
    assert report.stat().st_mode & 0o777 == 0o600
    assert back.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful here")
def test_the_scrubbed_document_is_left_to_the_umask(document, tmp_path):
    """The one artifact whose purpose is to be sent. Narrowing it to the owner
    would tighten the handoff the feature exists for, and stage 6 has already
    searched it for every value that was meant to be gone."""
    previous = os.umask(0o022)
    try:
        out_dir = tmp_path / "out"
        assert cli.main(["scrub", *L1, str(document), "-o", str(out_dir)]) == cli.EXIT_OK
        assert (out_dir / "offerta.txt").stat().st_mode & 0o777 == 0o644
    finally:
        os.umask(previous)


@pytest.mark.skipif(os.name == "nt", reason="O_NOFOLLOW does not exist here")
def test_a_symlink_where_the_output_belongs_is_refused(document, tmp_path, capsys):
    """`write_bytes` after `mkdir(exist_ok=True)` follows a link, so in a shared or
    predictable output directory a pre-planted one redirects the write."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    elsewhere = tmp_path / "config"
    elsewhere.write_text("do not touch", encoding="utf-8")
    (out_dir / "offerta.txt").symlink_to(elsewhere)

    assert cli.main(["scrub", *L1, str(document), "-o", str(out_dir)]) == cli.EXIT_USAGE
    assert elsewhere.read_text(encoding="utf-8") == "do not touch"
    assert "symbolic link" in capsys.readouterr().err


def test_scrub_then_restore_returns_the_document(document, tmp_path, passphrase_file):
    original = document.read_text(encoding="utf-8")
    out_dir, keys, back = tmp_path / "out", tmp_path / "keys", tmp_path / "back"

    assert (
        cli.main(
            [
                "scrub",
                *L1,
                str(document),
                "-o",
                str(out_dir),
                "--map",
                str(keys),
                "--map-passphrase-file",
                str(passphrase_file),
            ]
        )
        == cli.EXIT_OK
    )
    assert (
        cli.main(
            [
                "restore",
                str(out_dir / "offerta.txt"),
                "--map",
                str(keys / "offerta.fdmap"),
                "-o",
                str(back),
                "--map-passphrase-file",
                str(passphrase_file),
            ]
        )
        == cli.EXIT_OK
    )
    assert (back / "offerta.txt").read_text(encoding="utf-8") == original


def test_a_wrong_passphrase_stops_the_restore_before_any_file(tmp_path, passphrase_file):
    wrong = tmp_path / "wrong.txt"
    wrong.write_text("something else entirely\n", encoding="utf-8")
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "x.fdmap").write_text("{}", encoding="utf-8")
    target = tmp_path / "in.txt"
    target.write_text("[PERSON_1]\n", encoding="utf-8")

    status = cli.main(
        [
            "restore",
            str(target),
            "--map",
            str(keys / "x.fdmap"),
            "-o",
            str(tmp_path / "back"),
            "--map-passphrase-file",
            str(wrong),
        ]
    )
    assert status == cli.EXIT_USAGE
    assert not (tmp_path / "back" / "in.txt").exists()


def test_an_incomplete_restore_exits_five_and_still_writes(
    document, tmp_path, passphrase_file, monkeypatch
):
    """The character of this command in one assertion. Distinct from EXIT_LEAK
    because it is the opposite handling: a leak writes nothing, this writes the
    caller's best artifact and says what is wrong with it."""
    out_dir, keys, back = tmp_path / "out", tmp_path / "keys", tmp_path / "back"
    cli.main(
        [
            "scrub",
            *L1,
            str(document),
            "-o",
            str(out_dir),
            "--map",
            str(keys),
            "--map-passphrase-file",
            str(passphrase_file),
        ]
    )

    from freedocs.formats import plaintext

    monkeypatch.setattr(
        plaintext.PlainTextHandler,
        "write_back",
        lambda self, edits: self.data,
    )
    status = cli.main(
        [
            "restore",
            str(out_dir / "offerta.txt"),
            "--map",
            str(keys / "offerta.fdmap"),
            "-o",
            str(back),
            "--map-passphrase-file",
            str(passphrase_file),
        ]
    )
    assert status == cli.EXIT_INCOMPLETE
    assert status != cli.EXIT_LEAK
    assert (back / "offerta.txt").is_file()


def test_the_exit_code_and_the_rpc_code_are_the_same_number():
    """Two adapters, one failure, one number - as 3 already is. Drifting apart
    would mean a shell script and a window disagreeing about what happened.

    Only the pairs that are deliberate. ``EXIT_UNSUPPORTED`` is 4 and
    ``MISSING_DEPENDENCY`` is 4 by coincidence, not by design: the terminal
    collapses three refusals into one status where the pipe keeps them apart, so
    pinning that pair would assert an intent nobody had.
    """
    from freedocs import rpc

    assert cli.EXIT_INCOMPLETE == rpc.INCOMPLETE_RESTORE
    assert cli.EXIT_LEAK == rpc.LEAK_DETECTED


class _NotATerminal:
    """Just enough of a stream for the no-prompt branch."""

    def isatty(self) -> bool:
        return False


# -- --remove and the term list -----------------------------------------------------

TERMS_PASSPHRASE = "correct horse battery staple"


def test_remove_takes_out_a_value_no_detector_found(document: Path, tmp_path: Path):
    out = tmp_path / "out"
    status = cli.main(
        ["scrub", str(document), "-o", str(out), *L1, "--remove", "Realise Consulting SA"]
    )
    assert status == cli.EXIT_OK
    assert "Realise Consulting SA" not in (out / document.name).read_text(encoding="utf-8")


def test_a_term_list_is_used_by_scrub_and_counted_in_the_report(
    document: Path, tmp_path: Path, monkeypatch, capsys
):
    pytest.importorskip("cryptography", reason="the restore extra is required")
    terms = tmp_path / "firm.fdterms"
    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, TERMS_PASSPHRASE)
    assert cli.main(["terms", "create", str(terms)]) == cli.EXIT_OK
    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, TERMS_PASSPHRASE)
    assert (
        cli.main(["terms", "add", str(terms), "Realise Consulting SA", "Progetto Aurora"])
        == cli.EXIT_OK
    )

    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, TERMS_PASSPHRASE)
    out, report = tmp_path / "out", tmp_path / "report.json"
    status = cli.main(
        [
            "scrub",
            str(document),
            "-o",
            str(out),
            *L1,
            "--terms",
            str(terms),
            "--report",
            str(report),
        ]
    )
    assert status == cli.EXIT_OK
    assert "Realise Consulting SA" not in (out / document.name).read_text(encoding="utf-8")
    written = report.read_text(encoding="utf-8")
    assert '"loaded": 2' in written and '"matched": 1' in written
    assert "Progetto Aurora" not in written
    assert "Progetto Aurora" not in capsys.readouterr().out


def test_a_term_list_with_no_passphrase_and_no_terminal_is_a_usage_error(
    document: Path, tmp_path: Path, monkeypatch
):
    pytest.importorskip("cryptography", reason="the restore extra is required")
    monkeypatch.delenv(cli.TERMS_PASSPHRASE_ENV, raising=False)
    monkeypatch.setattr("sys.stdin", _NotATerminal())
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="no passphrase for the term list"):
        cli.main(["scrub", str(document), "-o", str(out), *L1, "--terms", str(tmp_path / "x")])
    assert not (out / document.name).exists()


def test_an_export_needs_a_yes_where_nobody_can_be_asked(tmp_path: Path, monkeypatch):
    pytest.importorskip("cryptography", reason="the restore extra is required")
    terms = tmp_path / "firm.fdterms"
    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, TERMS_PASSPHRASE)
    cli.main(["terms", "create", str(terms)])
    monkeypatch.setattr("sys.stdin", _NotATerminal())
    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, TERMS_PASSPHRASE)
    with pytest.raises(SystemExit, match="--yes"):
        cli.main(["terms", "export", str(terms), str(tmp_path / "plain.txt")])
    assert not (tmp_path / "plain.txt").exists()
    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, TERMS_PASSPHRASE)
    assert (
        cli.main(["terms", "export", str(terms), str(tmp_path / "plain.txt"), "--yes"])
        == cli.EXIT_OK
    )


def test_a_wrong_term_list_passphrase_is_a_usage_error_that_quotes_nothing(
    tmp_path: Path, monkeypatch, capsys
):
    pytest.importorskip("cryptography", reason="the restore extra is required")
    terms = tmp_path / "firm.fdterms"
    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, TERMS_PASSPHRASE)
    cli.main(["terms", "create", str(terms)])
    monkeypatch.setenv(cli.TERMS_PASSPHRASE_ENV, "wrong but long enough")
    with pytest.raises(SystemExit) as caught:
        cli.main(["terms", "list", str(terms)])
    assert "wrong but long enough" not in str(caught.value)

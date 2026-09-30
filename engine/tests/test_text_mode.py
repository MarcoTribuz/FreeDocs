"""Pasted text: scrub, hold the mapping, restore the reply, and let nothing stay.

Driven through the pipe, because that is what the window will see, and pinned to
the checksum layer: these tests are about the loop and what it keeps, not about
detection quality. The canaries are the verified ones from ``conftest``.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from freedocs import cli
from freedocs.core.limits import MAX_TEXT_CHARS
from freedocs.formats import plaintext
from freedocs.rpc import INPUT_TOO_LARGE, INVALID_REQUEST, LEAK_DETECTED, Session, handle
from freedocs.text_mode import MAX_TEXT_MAPS, PASTED_NAME, TextMaps, UnknownHandle

from .conftest import CANARIES

IBAN = CANARIES["IBAN"]
FISCALE = CANARIES["IT_CODICE_FISCALE"]
EMAIL = CANARIES["EMAIL"]

PASTE = (
    "Gentile ufficio,\n"
    f"il cliente con codice fiscale {FISCALE} chiede il bonifico su {IBAN}.\n"
    f"Rispondete a {EMAIL}, per favore.\n"
    "Una frase qualunque che nessun rilevatore reclama.\n"
)

#: Needs the cipher only for the key-file half; the handle half does not.
needs_cipher = pytest.mark.skipif(
    __import__("importlib.util").util.find_spec("cryptography") is None,
    reason="the restore extra is required for a key file",
)


@pytest.fixture
def session() -> Session:
    return Session(out=io.StringIO())


def call(session: Session, method: str, **params) -> dict:
    params.setdefault("detectors", "l1")
    response = handle(
        session, json.dumps({"jsonrpc": "2.0", "id": 3, "method": method, "params": params})
    )
    assert response is not None
    return response


def result_of(session: Session, method: str, **params) -> dict:
    response = call(session, method, **params)
    assert "error" not in response, response["error"]
    return response["result"]


def error_of(session: Session, method: str, **params) -> dict:
    response = call(session, method, **params)
    assert "result" not in response, response["result"]
    return response["error"]


def placeholders_in(text: str) -> list[str]:
    import re

    return re.findall(r"\[[A-Z][A-Z0-9_]*_\d+\]", text)


# -- the round trip -------------------------------------------------------------


def test_a_reply_is_restored_from_the_held_mapping(session: Session):
    """The loop the mode exists for. The reply reorders the sentences and uses
    one placeholder twice, which is what a model answering does."""
    scrubbed = result_of(session, "scrub_text", text=PASTE, keep_map=True)
    assert scrubbed["ok"] and scrubbed["handle"]
    for value in (IBAN, FISCALE, EMAIL):
        assert value not in scrubbed["text"]

    tokens = placeholders_in(scrubbed["text"])
    assert len(tokens) == 3
    iban = next(token for token in tokens if token.startswith("[IBAN"))
    reply = (
        f"Ho verificato {iban}. Il cliente {tokens[0]} va contattato.\n"
        f"Ripeto: il conto è {iban}, e l'indirizzo {tokens[-1]}.\n"
    )
    restored = result_of(session, "restore_text", text=reply, handle=scrubbed["handle"])
    assert restored["ok"]
    assert restored["text"].count(IBAN) == 2
    assert not placeholders_in(restored["text"])
    assert restored["path"] == PASTED_NAME


def test_an_unedited_round_trip_is_the_paste(session: Session):
    scrubbed = result_of(session, "scrub_text", text=PASTE, keep_map=True)
    restored = result_of(session, "restore_text", text=scrubbed["text"], handle=scrubbed["handle"])
    assert restored["text"] == PASTE


def test_a_handle_survives_a_second_reply(session: Session):
    """A restore does not consume the handle: asking the model twice is normal."""
    scrubbed = result_of(session, "scrub_text", text=PASTE, keep_map=True)
    for _ in range(2):
        restored = result_of(
            session, "restore_text", text=scrubbed["text"], handle=scrubbed["handle"]
        )
        assert IBAN in restored["text"]


# -- what is kept, and for how long -------------------------------------------------


def test_nothing_is_held_unless_asked(session: Session):
    scrubbed = result_of(session, "scrub_text", text=PASTE)
    assert scrubbed["handle"] is None
    assert len(session._text_maps) == 0


def test_an_unknown_handle_is_refused_without_naming_a_value(session: Session):
    error = error_of(session, "restore_text", text=f"{IBAN} [IBAN_1]", handle="not-a-handle")
    assert error["code"] == INVALID_REQUEST
    assert IBAN not in json.dumps(error)
    assert "scrub the original text again" in error["message"]


def test_forget_releases_a_held_mapping_and_leaves_the_file_cache(session: Session, tmp_path: Path):
    document = tmp_path / "scheda.txt"
    document.write_text(f"IBAN: {IBAN}\n", encoding="utf-8")
    result_of(session, "inspect", path=str(document))
    scrubbed = result_of(session, "scrub_text", text=PASTE, keep_map=True)

    forgot = result_of(session, "forget", text_maps=[scrubbed["handle"]])
    assert forgot["text_maps_released"] == 1
    # Dropping a paste is not dropping the documents on another screen.
    assert len(session._extractions) == 1
    assert error_of(session, "restore_text", text="x", handle=scrubbed["handle"])["code"] == (
        INVALID_REQUEST
    )


def test_forget_all_releases_every_mapping(session: Session):
    for _ in range(3):
        result_of(session, "scrub_text", text=PASTE, keep_map=True)
    assert result_of(session, "forget", text_maps="all")["text_maps_released"] == 3
    assert len(session._text_maps) == 0


def test_a_plain_forget_does_not_touch_held_mappings(session: Session):
    """The window forgets its documents after every batch; a paste in flight on
    another screen must not lose its way back because of it."""
    scrubbed = result_of(session, "scrub_text", text=PASTE, keep_map=True)
    result_of(session, "forget")
    result_of(session, "restore_text", text=scrubbed["text"], handle=scrubbed["handle"])


def test_the_ninth_mapping_evicts_the_first(session: Session):
    handles = [
        result_of(session, "scrub_text", text=PASTE, keep_map=True)["handle"]
        for _ in range(MAX_TEXT_MAPS + 1)
    ]
    assert len(session._text_maps) == MAX_TEXT_MAPS
    assert error_of(session, "restore_text", text="x", handle=handles[0])["code"] == INVALID_REQUEST
    result_of(session, "restore_text", text="x", handle=handles[-1])


def test_handles_are_random_and_not_derived_from_the_text():
    maps = TextMaps()
    from freedocs.core.mapping import KeyMap

    empty = KeyMap(
        document=PASTED_NAME,
        format_name="plaintext",
        output_sha256="0" * 64,
        placeholder_language="en",
        entries=(),
    )
    first, second = maps.hold(empty), maps.hold(empty)
    assert first != second
    assert len(first) >= 20
    with pytest.raises(UnknownHandle):
        maps.get("anything")
    with pytest.raises(TypeError):
        maps.release("some")


# -- what must never travel ----------------------------------------------------------


def test_a_leak_returns_no_text(session: Session, monkeypatch):
    """Stage 6 failing on a paste is a leak exactly as on a file, and the answer
    carries no scrubbed text: a nearly-clean paste gets sent."""
    monkeypatch.setattr(plaintext.PlainTextHandler, "write_back", lambda self, edits: self.data)
    outcome = result_of(session, "scrub_text", text=PASTE, keep_map=True)
    assert outcome["ok"] is False
    assert outcome["error"]["code"] == LEAK_DETECTED
    assert "text" not in outcome
    blob = json.dumps(outcome)
    for value in (IBAN, FISCALE, EMAIL):
        assert value not in blob
    # And nothing was held for a scrub that produced nothing.
    assert len(session._text_maps) == 0


def test_the_report_carries_no_value_and_no_pasted_phrase(session: Session):
    """The `include_text` rule: the report reaches places the pipe does not, and
    the paste is a superset of the findings - the phrase below is no finding."""
    scrubbed = result_of(session, "scrub_text", text=PASTE, keep_map=True)
    report = json.dumps(scrubbed["report"])
    for value in (IBAN, FISCALE, EMAIL):
        assert value not in report
    assert "nessun rilevatore reclama" not in report
    assert scrubbed["report"]["source"] == PASTED_NAME


def test_an_oversized_paste_is_refused_before_it_is_read(session: Session):
    error = error_of(session, "inspect_text", text="a" * (MAX_TEXT_CHARS + 1))
    assert error["code"] == INPUT_TOO_LARGE


def test_text_must_be_a_string(session: Session):
    assert error_of(session, "scrub_text", text=["no"])["code"] == INVALID_REQUEST


# -- the preview ---------------------------------------------------------------------


def test_inspect_text_returns_the_text_and_the_same_shape_as_inspect(session: Session):
    preview = result_of(session, "inspect_text", text=PASTE)
    assert preview["text"] == PASTE
    assert preview["path"] == PASTED_NAME
    assert {"findings", "characters", "warnings", "hidden", "suppressed", "parts"} <= set(preview)
    assert {finding["text"] for finding in preview["findings"]} >= {IBAN, FISCALE}


def test_an_emoji_before_a_value_keeps_the_span_the_engine_named(session: Session):
    """Python counts code points and JavaScript UTF-16 units. A kept span built
    from the engine's own offsets must be honoured past a surrogate pair."""
    text = f"😀 {IBAN}\n{IBAN}\n"
    preview = result_of(session, "inspect_text", text=text)
    first = min(preview["findings"], key=lambda finding: finding["start"])
    assert first["start"] == 2  # a code-point offset, not UTF-16's 3
    keep = [
        {"start": first["start"], "end": first["end"], "text": first["text"], "path": PASTED_NAME}
    ]
    scrubbed = result_of(session, "scrub_text", text=text, keep_spans=keep)
    assert scrubbed["text"].startswith(f"😀 {IBAN}\n")
    assert IBAN not in scrubbed["text"].splitlines()[1]


def test_no_router_stage_is_announced_for_a_paste(session: Session):
    result_of(session, "scrub_text", text=PASTE)
    stages = [
        json.loads(line)["params"]["stage"]
        for line in session.out.getvalue().splitlines()
        if json.loads(line).get("method") == "stage"
    ]
    assert stages and "router" not in stages


# -- the key file ------------------------------------------------------------------


@needs_cipher
def test_a_key_file_restores_a_reply_tomorrow(session: Session, tmp_path: Path):
    passphrase = "correct horse battery staple"
    scrubbed = result_of(
        session, "scrub_text", text=PASTE, map=str(tmp_path), map_passphrase=passphrase
    )
    assert scrubbed["handle"] is None
    assert Path(scrubbed["key_file"]).name == "pasted.fdmap"
    assert scrubbed["report"]["key_file_written"] is True

    fresh = Session(out=io.StringIO())
    restored = result_of(
        fresh,
        "restore_text",
        text=scrubbed["text"],
        map=scrubbed["key_file"],
        passphrase=passphrase,
    )
    assert restored["text"] == PASTE


def test_a_key_file_needs_its_passphrase(session: Session, tmp_path: Path):
    assert error_of(session, "scrub_text", text=PASTE, map=str(tmp_path))["code"] == INVALID_REQUEST


def test_restore_text_needs_a_handle_or_a_map(session: Session):
    assert error_of(session, "restore_text", text="x")["code"] == INVALID_REQUEST


# -- the command line ----------------------------------------------------------------


def _run(monkeypatch, capsys, argv: list[str], stdin: str) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def test_scrub_dash_writes_only_the_text_to_stdout(monkeypatch, capsys):
    code, out, err = _run(monkeypatch, capsys, ["scrub", "-", "--detectors", "l1"], PASTE)
    assert code == cli.EXIT_OK
    assert IBAN not in out
    assert out.count("\n") == PASTE.count("\n")
    assert "verify" in err


@needs_cipher
def test_restore_dash_reads_a_reply_from_stdin(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setenv("FREEDOCS_MAP_PASSPHRASE", "correct horse battery staple")
    _, scrubbed, _ = _run(
        monkeypatch, capsys, ["scrub", "-", "--detectors", "l1", "--map", str(tmp_path)], PASTE
    )
    # Set again: the CLI pops the variable once read, so a child process it
    # starts does not inherit the passphrase.
    monkeypatch.setenv("FREEDOCS_MAP_PASSPHRASE", "correct horse battery staple")
    code, out, _ = _run(
        monkeypatch, capsys, ["restore", "-", "--map", str(tmp_path / "pasted.fdmap")], scrubbed
    )
    assert code == cli.EXIT_OK
    assert out == PASTE


@pytest.mark.parametrize(
    "argv",
    [["scrub", "-", "other.txt"], ["scrub", "-", "-o", "out"], ["scrub", "file.txt"]],
)
def test_dash_and_the_output_directory_are_usage_errors_when_mixed(monkeypatch, capsys, argv):
    code, out, _ = _run(monkeypatch, capsys, argv, "")
    assert code == cli.EXIT_USAGE
    assert out == ""

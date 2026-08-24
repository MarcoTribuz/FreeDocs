"""The key file: does it protect what it holds, and can it be read back?

Every test here is about one of three failures, because those are the ones that
turn this feature from useful into dangerous: the file readable without the
passphrase, an error message carrying what the file was protecting, or a silent
mis-read that writes the wrong value into a document.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography", reason="the restore extra is required for a key file")
pytest.importorskip("stdnum", reason="python-stdnum is required for the L1 layer")

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.core.mapping import (
    MAP_SUFFIX,
    MAP_VERSION,
    MIN_PASSPHRASE,
    BadPassphrase,
    KeyMap,
    MalformedMap,
    MapEntry,
    check_passphrase,
    key_map_from,
    map_path_for,
    mapping_unavailable_reason,
    read_key_map,
    refuse_inside,
    write_key_map,
)
from freedocs.core.policy import Action
from freedocs.pipeline import Decision, ScrubResult
from freedocs.verify import VerifyResult

from .conftest import CANARIES, l1_scrubber

PASSPHRASE = "correct horse battery staple"


@pytest.fixture
def source(tmp_path: Path, document: str) -> Path:
    path = tmp_path / "scheda-cliente.txt"
    path.write_text(document, encoding="utf-8", newline="")
    return path


def _decision(text: str, placeholder: str, entity: EntityType = EntityType.PERSON) -> Decision:
    return Decision(
        finding=Finding(
            span=Span(start=0, end=len(text)),
            entity=entity,
            text=text,
            layer=Layer.NER,
            detector="test",
        ),
        action=Action.REDACT,
        replacement=placeholder,
    )


def _result(decisions: list[Decision], *, output: bytes = b"scrubbed") -> ScrubResult:
    return ScrubResult(
        source=Path("doc.txt"),
        format_name="plaintext",
        output=output,
        decisions=decisions,
        hidden_removed=[],
        verify=VerifyResult(leaks=(), checked_values=0, skipped_short=0, output_chars=0),
        source_chars=0,
    )


# -- what goes in the file -----------------------------------------------------


def test_the_map_is_built_from_a_finished_scrub(source: Path):
    """No accessor on the allocator, and none needed.

    The pairing survives in `ScrubResult.decisions` after `allocator.close()`,
    which is what lets this feature exist without reopening the thing whose whole
    job is to forget.
    """
    result = l1_scrubber().scrub_file(source)
    key_map = key_map_from(result, placeholder_language="en")

    values = {entry.value for entry in key_map.entries}
    assert CANARIES["IBAN"] in values
    assert CANARIES["EMAIL"] in values
    # Every entry names a placeholder that is actually in the scrubbed output.
    output = result.output.decode("utf-8")
    for entry in key_map.entries:
        assert entry.placeholder in output


def test_report_only_findings_get_no_entry():
    """A DATE is flagged and never replaced, so there is nothing to undo."""
    flagged = Decision(
        finding=Finding(
            span=Span(start=0, end=10),
            entity=EntityType.DATE,
            text="2024-03-01",
            layer=Layer.NER,
            detector="test",
        ),
        action=Action.REPORT,
        replacement=None,
    )
    key_map = key_map_from(_result([flagged]), placeholder_language="en")
    assert key_map.entries == ()


def test_the_first_spelling_in_document_order_is_what_comes_back():
    """`_normalise` collapses case, so only one spelling can be restored.

    Pinned rather than left to chance: the value written is the first occurrence
    in the document, because `_decide` walks findings in span order and this
    reads them in the same order. `variants` says the round trip is lossy here.
    """
    decisions = [
        _decision("Mario Rossi", "[PERSON_1]"),
        _decision("MARIO ROSSI", "[PERSON_1]"),
        _decision("Mario  Rossi", "[PERSON_1]"),
    ]
    key_map = key_map_from(_result(decisions), placeholder_language="en")

    (entry,) = key_map.entries
    assert entry.value == "Mario Rossi"
    assert entry.occurrences == 3
    assert entry.variants == 3
    assert "more than one" in key_map.warnings()[0]


def test_one_spelling_produces_no_warning():
    decisions = [_decision("Mario Rossi", "[PERSON_1]")] * 2
    key_map = key_map_from(_result(decisions), placeholder_language="en")
    assert key_map.entries[0].variants == 1
    assert key_map.warnings() == []


# -- the file on disk ----------------------------------------------------------


def test_the_file_on_disk_reveals_no_value(tmp_path: Path, source: Path):
    """The whole point. Every canary must be absent from the raw bytes."""
    result = l1_scrubber().scrub_file(source)
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, key_map_from(result, placeholder_language="en"), PASSPHRASE)

    raw = path.read_bytes()
    leaked = [name for name, value in CANARIES.items() if value.encode("utf-8") in raw]
    assert not leaked, f"key file exposes {leaked}"


def test_the_file_is_not_readable_by_other_accounts(tmp_path: Path):
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, _empty_map(), PASSPHRASE)
    assert path.stat().st_mode & 0o777 == 0o600


def test_overwriting_an_open_file_tightens_its_mode(tmp_path: Path):
    """O_CREAT keeps an existing file's mode, so yesterday's key file would keep
    yesterday's permissions without the explicit chmod."""
    path = tmp_path / ("doc" + MAP_SUFFIX)
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)
    write_key_map(path, _empty_map(), PASSPHRASE)
    assert path.stat().st_mode & 0o777 == 0o600


def test_round_trip(tmp_path: Path):
    key_map = KeyMap(
        document="offerta.docx",
        format_name="docx",
        output_sha256="abc123",
        placeholder_language="it",
        entries=(
            MapEntry(
                placeholder="[PERSONA_1]",
                value="Mario Rossi",
                entity=EntityType.PERSON,
                country=None,
                occurrences=3,
                variants=1,
            ),
            MapEntry(
                placeholder="[IBAN_1]",
                value=CANARIES["IBAN"],
                entity=EntityType.IBAN,
                country="ch",
                occurrences=1,
                variants=1,
            ),
        ),
    )
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, key_map, PASSPHRASE)
    assert read_key_map(path, PASSPHRASE) == key_map


def test_two_writes_of_the_same_map_differ(tmp_path: Path):
    """A fresh salt and nonce per file, so identical content is not identical
    bytes - otherwise two key files would betray that they hold the same values."""
    first, second = tmp_path / ("a" + MAP_SUFFIX), tmp_path / ("b" + MAP_SUFFIX)
    write_key_map(first, _empty_map(), PASSPHRASE)
    write_key_map(second, _empty_map(), PASSPHRASE)
    assert first.read_bytes() != second.read_bytes()


# -- refusing to open ----------------------------------------------------------


def test_the_wrong_passphrase_is_refused_without_quoting_it(tmp_path: Path):
    """The message travels: to stderr, and through `rpc.handle`, which renders an
    exception's own text straight into a response."""
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, _one_entry_map(), PASSPHRASE)

    with pytest.raises(BadPassphrase) as caught:
        read_key_map(path, "not the passphrase at all")

    message = str(caught.value)
    assert "not the passphrase at all" not in message
    assert CANARIES["IBAN"] not in message


def test_a_tampered_header_is_refused(tmp_path: Path):
    """The header is the AEAD associated data, so the ciphertext cannot be lifted
    onto a different one - a key file claiming to describe another document."""
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, _one_entry_map(), PASSPHRASE)

    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["document"]["name"] = "somebody-elses.docx"
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(BadPassphrase):
        read_key_map(path, PASSPHRASE)


def test_tampered_ciphertext_is_refused(tmp_path: Path):
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, _one_entry_map(), PASSPHRASE)

    envelope = json.loads(path.read_text(encoding="utf-8"))
    sealed = envelope["entries"]
    envelope["entries"] = ("B" if sealed[0] != "B" else "C") + sealed[1:]
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(BadPassphrase):
        read_key_map(path, PASSPHRASE)


def test_a_future_version_is_refused_rather_than_guessed(tmp_path: Path):
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, _one_entry_map(), PASSPHRASE)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["freedocs_map"] = MAP_VERSION + 1
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(MalformedMap, match="version"):
        read_key_map(path, PASSPHRASE)


def test_something_that_is_not_a_key_file_is_refused(tmp_path: Path):
    path = tmp_path / ("doc" + MAP_SUFFIX)
    path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(MalformedMap):
        read_key_map(path, PASSPHRASE)


def test_a_duplicate_placeholder_is_refused(tmp_path: Path):
    """One of the two values could never be restored, and guessing which would be
    writing the wrong value into a document while reporting success."""
    path = tmp_path / ("doc" + MAP_SUFFIX)
    write_key_map(path, _one_entry_map(), PASSPHRASE)

    # Re-encrypt a payload with a duplicate, using the file's own header so the
    # AAD still matches - the point is the parser, not the cipher.
    import base64

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from freedocs.core.mapping import _aad, _derive

    envelope = json.loads(path.read_text(encoding="utf-8"))
    header = {key: value for key, value in envelope.items() if key != "entries"}
    row = {
        "placeholder": "[IBAN_1]",
        "value": "x",
        "entity": "IBAN",
        "country": None,
        "occurrences": 1,
        "variants": 1,
    }
    payload = json.dumps({"entries": [row, row]}).encode("utf-8")
    salt = base64.b64decode(envelope["kdf"]["salt"])
    nonce = base64.b64decode(envelope["nonce"])
    envelope["entries"] = base64.b64encode(
        AESGCM(_derive(PASSPHRASE, salt)).encrypt(nonce, payload, _aad(header))
    ).decode("ascii")
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(MalformedMap, match="twice"):
        read_key_map(path, PASSPHRASE)


# -- the passphrase ------------------------------------------------------------


def test_a_short_passphrase_is_refused_and_not_quoted():
    with pytest.raises(ValueError) as caught:
        check_passphrase("short")
    assert "short" not in str(caught.value).replace("characters", "")
    assert str(MIN_PASSPHRASE) in str(caught.value)


def test_a_short_passphrase_writes_nothing(tmp_path: Path):
    path = tmp_path / ("doc" + MAP_SUFFIX)
    with pytest.raises(ValueError):
        write_key_map(path, _one_entry_map(), "abc")
    assert not path.exists()


# -- where the file goes -------------------------------------------------------


def test_a_directory_gets_one_file_per_document(tmp_path: Path):
    assert map_path_for(tmp_path / "keys", Path("/x/offerta.docx")) == (
        tmp_path / "keys" / ("offerta" + MAP_SUFFIX)
    )


def test_a_named_file_is_taken_as_given(tmp_path: Path):
    named = tmp_path / ("mine" + MAP_SUFFIX)
    assert map_path_for(named, Path("/x/offerta.docx")) == named


def test_the_output_directory_is_refused(tmp_path: Path):
    """The accident that actually happens: zip the output folder, send it, and the
    scrubbed document travels with the key to undo it."""
    output = tmp_path / "clean"
    assert refuse_inside(output, output) is not None
    assert refuse_inside(output / "keys", output) is not None
    assert refuse_inside(tmp_path / "keys", output) is None


def test_the_capability_and_the_refusal_have_one_source():
    """`mapping_unavailable_reason()` is the only authority, so the window cannot
    be told a key file is possible and then be refused one."""
    assert mapping_unavailable_reason() is None


def _empty_map() -> KeyMap:
    return KeyMap(
        document="doc.txt",
        format_name="plaintext",
        output_sha256="",
        placeholder_language="en",
        entries=(),
    )


def _one_entry_map() -> KeyMap:
    return KeyMap(
        document="doc.txt",
        format_name="plaintext",
        output_sha256="",
        placeholder_language="en",
        entries=(
            MapEntry(
                placeholder="[IBAN_1]",
                value=CANARIES["IBAN"],
                entity=EntityType.IBAN,
                country="ch",
                occurrences=1,
                variants=1,
            ),
        ),
    )

"""The envelope two files share, and the promise that moving it changed nothing.

`core/sealed.py` was extracted from `core/mapping.py` so the term list could be
sealed the same way. A key file somebody kept last month must still open, and
one written today must be the same bytes it would have been - so the first two
tests are about a fixture written by the code this replaced, with its randomness
pinned.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

pytest.importorskip("cryptography", reason="the restore extra is required for a sealed file")

from freedocs.core import sealed
from freedocs.core.findings import EntityType
from freedocs.core.mapping import (
    BadPassphrase,
    KeyMap,
    MalformedMap,
    MapEntry,
    read_key_map,
    write_key_map,
)
from freedocs.core.terms import Term, TermList, TermListError, open_terms, save_terms

FIXTURE = Path(__file__).parent / "fixtures" / "before-sealed.fdmap"
PASSPHRASE = "correct horse battery staple"

#: What the fixture holds. Invented values, not canaries: this file is checked
#: in, and a real identifier would be one more thing a scanner flags.
FIXTURE_MAP = KeyMap(
    document="scheda-cliente.txt",
    format_name="plaintext",
    output_sha256="0" * 64,
    placeholder_language="en",
    entries=(
        MapEntry("[PERSON_1]", "Mario Rossi", EntityType.PERSON, None, 2, 2),
        MapEntry("[IBAN_1]", "CH93 0076 2011 6238 5295 7", EntityType.IBAN, "ch", 1, 1),
    ),
)


def test_a_key_file_written_before_the_extraction_still_opens():
    assert read_key_map(FIXTURE, PASSPHRASE) == FIXTURE_MAP


def test_a_key_file_written_now_is_byte_identical(tmp_path: Path, monkeypatch):
    """The fixture was written with `secrets.token_bytes` returning 0, 1, 2, ...

    Pinning the same randomness and writing the same map must reproduce it
    exactly. Anything else - a key order, an indent, a field renamed on the way
    through - is a key-file format change made by a refactor that promised none.
    """
    monkeypatch.setattr(secrets, "token_bytes", lambda n: bytes(range(n)))
    path = tmp_path / "again.fdmap"
    write_key_map(path, FIXTURE_MAP, PASSPHRASE)
    assert path.read_bytes() == FIXTURE.read_bytes()


def test_a_key_file_is_refused_as_a_term_list():
    with pytest.raises(TermListError, match="is a key file, not a term list"):
        open_terms(FIXTURE, PASSPHRASE)


def test_a_term_list_is_refused_as_a_key_file(tmp_path: Path):
    path = tmp_path / "firm.fdterms"
    save_terms(path, TermList((Term("Nordwind Holding"),)), PASSPHRASE)
    with pytest.raises(MalformedMap, match="is a term list, not a key file"):
        read_key_map(path, PASSPHRASE)


def test_the_two_kinds_raise_their_own_errors():
    """A caller catching `MalformedMap` must not be handed a term-list problem."""
    assert issubclass(MalformedMap, sealed.MalformedSealed)
    assert issubclass(TermListError, sealed.MalformedSealed)
    assert not issubclass(MalformedMap, TermListError)
    assert not issubclass(TermListError, MalformedMap)


def _sealed_list(tmp_path: Path) -> Path:
    path = tmp_path / "firm.fdterms"
    save_terms(path, TermList((Term("Nordwind Holding"),)), PASSPHRASE)
    return path


def test_a_flipped_ciphertext_byte_does_not_open(tmp_path: Path):
    import base64

    path = _sealed_list(tmp_path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    raw = bytearray(base64.b64decode(envelope["terms"]))
    raw[0] ^= 1
    envelope["terms"] = base64.b64encode(bytes(raw)).decode("ascii")
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(BadPassphrase):
        open_terms(path, PASSPHRASE)


def test_a_header_lifted_onto_another_file_does_not_open(tmp_path: Path):
    """The header is the AAD: one list's ciphertext under another's salt fails."""
    first = _sealed_list(tmp_path)
    second = tmp_path / "other.fdterms"
    save_terms(second, TermList((Term("Progetto Aurora"),)), PASSPHRASE)
    a = json.loads(first.read_text(encoding="utf-8"))
    b = json.loads(second.read_text(encoding="utf-8"))
    a["terms"] = b["terms"]
    first.write_text(json.dumps(a), encoding="utf-8")
    with pytest.raises(BadPassphrase):
        open_terms(first, PASSPHRASE)


@pytest.mark.parametrize("field, value", [("p", 2**24), ("n", 2**30), ("r", True)])
def test_the_work_factor_band_holds_for_a_term_list(
    tmp_path: Path, monkeypatch, field: str, value: object
):
    """The band was written for the key file and lives in the envelope now.

    A term list is a thing a firm copies between machines, which is the same
    reason a key file needed it.
    """
    import hashlib

    path = _sealed_list(tmp_path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["kdf"][field] = value
    path.write_text(json.dumps(envelope), encoding="utf-8")

    def refuse(*args, **kwargs):  # pragma: no cover - reaching this is the failure
        raise AssertionError(f"the derivation ran with {field}={value!r}")

    monkeypatch.setattr(hashlib, "scrypt", refuse)
    with pytest.raises(TermListError):
        open_terms(path, PASSPHRASE)


def test_the_header_of_a_term_list_says_nothing_about_it(tmp_path: Path):
    """No count, no name, no date: how many clients a firm has is confidential."""
    path = _sealed_list(tmp_path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert set(envelope) == {"freedocs_terms", "kdf", "cipher", "nonce", "terms"}


def test_the_size_of_a_term_list_does_not_count_its_entries(tmp_path: Path):
    """AES-GCM is a stream mode, so without padding one more entry is one more
    entry's worth of bytes on disk."""
    one = tmp_path / "one.fdterms"
    many = tmp_path / "many.fdterms"
    save_terms(one, TermList((Term("Nordwind Holding"),)), PASSPHRASE)
    save_terms(many, TermList(tuple(Term(f"Client number {i}") for i in range(40))), PASSPHRASE)
    assert one.stat().st_size == many.stat().st_size

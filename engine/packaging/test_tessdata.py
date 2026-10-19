"""Tests for the language-data fetcher. No network: the downloads are faked."""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tessdata as T

from freedocs.formats.pdf import DEFAULT_OCR_LANGUAGE


def test_every_language_the_engine_asks_for_is_pinned():
    """A language added to OCR without a file here is a bundle that cannot read it."""
    assert set(DEFAULT_OCR_LANGUAGE.split("+")) <= set(T.PINNED)


def test_urls_name_the_commit_not_a_branch():
    """`main` is a content decision somebody else makes."""
    assert all(T.COMMIT in T.url_for(name) and "/main/" not in T.url_for(name) for name in T.PINNED)


def pin(monkeypatch, content: bytes) -> None:
    monkeypatch.setattr(T, "PINNED", {"ita": hashlib.sha256(content).hexdigest()})


def test_a_file_with_the_wrong_hash_is_stale_even_though_it_exists(monkeypatch, tmp_path):
    """A `tessdata_best` copy under the same name is not the pinned file."""
    pin(monkeypatch, b"pinned")
    (tmp_path / "ita.traineddata").write_bytes(b"something else")
    assert T.stale(tmp_path) == ["ita"]
    (tmp_path / "ita.traineddata").write_bytes(b"pinned")
    assert T.stale(tmp_path) == []


def test_check_touches_nothing_and_fails_on_a_gap(monkeypatch, tmp_path):
    pin(monkeypatch, b"pinned")
    monkeypatch.setattr(T.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    assert T.main(["--check", "--directory", str(tmp_path)]) == 1
    assert not list(tmp_path.iterdir())


def test_a_download_that_does_not_match_is_refused_and_leaves_nothing(monkeypatch, tmp_path):
    """No truncated or swapped file under the real name: `tessdata_path()` would count it."""
    pin(monkeypatch, b"pinned")
    monkeypatch.setattr(T.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"tampered"))
    with pytest.raises(SystemExit, match="refusing"):
        T.main(["--directory", str(tmp_path)])
    assert not list(tmp_path.iterdir())


def test_a_matching_download_is_moved_into_place(monkeypatch, tmp_path):
    pin(monkeypatch, b"pinned")
    monkeypatch.setattr(T.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"pinned"))
    assert T.main(["--directory", str(tmp_path)]) == 0
    assert (tmp_path / "ita.traineddata").read_bytes() == b"pinned"
    assert not list(tmp_path.glob("*.part"))

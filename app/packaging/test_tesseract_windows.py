"""Tests for staging the Windows Tesseract. No network; the installer is faked.

Running the staged ``tesseract.exe`` is Windows-only and happens in ``app.yml``;
what is pinned here is what decides which bytes reach every installer.
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tesseract_windows as W


def test_the_executable_its_dlls_and_the_licence_are_kept():
    assert W.wanted(Path("tesseract.exe"))
    assert W.wanted(Path("libtesseract-5.dll"))
    assert W.wanted(Path("zlib1.DLL"))
    assert W.wanted(Path("doc/LICENSE"))


def test_the_training_tools_and_the_installers_own_tessdata_are_left_out():
    """The language data is pinned in the sidecar; a second copy is a second answer."""
    for name in (
        "lstmtraining.exe",
        "winpath.exe",
        "tesseract.1.html",
        "tessdata/eng.traineddata",
        "tessdata/ScrollView.jar",
        "$PLUGINSDIR/System.dll",
        "doc/README.md",
    ):
        assert not W.wanted(Path(name)), name


def test_the_download_is_pinned_to_a_release_not_latest():
    assert W.VERSION in W.URL and "latest" not in W.URL


def test_a_download_that_does_not_match_is_refused_and_leaves_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(W.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"tampered"))
    with pytest.raises(SystemExit, match="refusing"):
        W.installer(tmp_path)
    assert not list(tmp_path.iterdir())


def test_a_cached_installer_with_the_right_hash_is_not_fetched_again(monkeypatch, tmp_path):
    content = b"the pinned installer"
    monkeypatch.setattr(W, "SHA256", hashlib.sha256(content).hexdigest())
    (tmp_path / Path(W.URL).name).write_bytes(content)
    monkeypatch.setattr(W.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    assert W.installer(tmp_path).read_bytes() == content


def test_a_stage_missing_the_executable_fails(monkeypatch, tmp_path):
    """A directory holding only a licence is not a Tesseract."""

    def extract(command, **_):
        out = Path(next(part[2:] for part in command if part.startswith("-o")))
        (out / "doc").mkdir()
        (out / "doc" / "LICENSE").write_text("Apache", encoding="utf-8")

    monkeypatch.setattr(W, "seven_zip", lambda: "7z")
    monkeypatch.setattr(W.subprocess, "run", extract)
    with pytest.raises(SystemExit, match=r"tesseract\.exe"):
        W.stage(tmp_path / "setup.exe", tmp_path / "out")


def test_a_stage_replaces_what_an_earlier_version_left(monkeypatch, tmp_path):
    """A stale DLL beside a new executable is a crash nobody can reproduce."""
    output = tmp_path / "out"
    output.mkdir()
    (output / "libold-1.dll").write_bytes(b"old")

    def extract(command, **_):
        out = Path(next(part[2:] for part in command if part.startswith("-o")))
        for name in W.REQUIRED:
            (out / name).write_bytes(b"x")

    monkeypatch.setattr(W, "seven_zip", lambda: "7z")
    monkeypatch.setattr(W.subprocess, "run", extract)
    W.stage(tmp_path / "setup.exe", output)
    assert not (output / "libold-1.dll").exists()
    assert (output / "NOTICE.txt").read_bytes().count(b"\r\n") == 0

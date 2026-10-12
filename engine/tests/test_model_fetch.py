"""The first-run download: what the engine says about the weights, and how it fetches them.

No test here touches the network. The hub's functions are replaced with fakes that
behave the way ``hf_hub_download`` was measured to behave - a bar built with
``tqdm_class``, advanced per chunk - because what matters is the contract with
the window: bytes as ``done``/``of``, a closed set of answers, and a failure that
says "try again" rather than a traceback.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from freedocs.core.errors import ModelDownloadFailed
from freedocs.core.model_manifest import REQUIRED_FILES
from freedocs.detect.backends import gliner_backend
from freedocs.rpc import INVALID_REQUEST, MODEL_DOWNLOAD_FAILED, Session, handle

#: CI installs no `ner` extra, and the hub client arrives only with it. The
#: functions under test import it lazily for the same reason.
huggingface_hub = pytest.importorskip("huggingface_hub")

SIZES = {name: 1000 * (index + 1) for index, name in enumerate(REQUIRED_FILES)}


class _Metadata:
    def __init__(self, size: int) -> None:
        self.size = size


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """A fake hub and cache: files appear in the cache when they are downloaded."""
    snapshot = tmp_path / "snapshot"
    cache: dict[str, Path] = {}

    def try_to_load_from_cache(repo: str, name: str, **_: object) -> object:
        hit = cache.get(name)
        return str(hit) if hit else None

    def get_hf_file_metadata(url: str, **_: object) -> _Metadata:
        return _Metadata(SIZES[url])

    def hf_hub_url(repo: str, name: str, **_: object) -> str:
        return name

    def hf_hub_download(repo: str, name: str, *, tqdm_class: type, **_: object) -> str:
        bar = tqdm_class(total=SIZES[name], initial=0)
        for _chunk in range(4):
            bar.update(SIZES[name] // 4)
        bar.close()
        cache[name] = snapshot / name
        return str(cache[name])

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", try_to_load_from_cache)
    monkeypatch.setattr(huggingface_hub, "get_hf_file_metadata", get_hf_file_metadata)
    monkeypatch.setattr(huggingface_hub, "hf_hub_url", hf_hub_url)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", hf_hub_download)
    # Every report, not one per quarter second: the throttle is for a real line.
    monkeypatch.setattr(gliner_backend, "_REPORT_INTERVAL", 0.0)
    monkeypatch.delenv(gliner_backend.MODEL_ENV, raising=False)
    return cache


def test_progress_is_in_bytes_over_the_whole_download(hub: dict[str, Path]):
    reports: list[tuple[int, int]] = []
    snapshot = gliner_backend.fetch_model(lambda done, of: reports.append((done, of)))

    total = sum(SIZES.values())
    assert {of for _, of in reports} == {total}, "the total is known from the first report"
    dones = [done for done, _ in reports]
    assert dones == sorted(dones), "progress never goes backwards across files"
    assert dones[-1] == total
    assert snapshot == hub["config.json"].parent


def test_a_file_already_cached_is_not_fetched_again(hub: dict[str, Path], tmp_path: Path):
    hub["model.safetensors"] = tmp_path / "snapshot" / "model.safetensors"
    reports: list[tuple[int, int]] = []
    gliner_backend.fetch_model(lambda done, of: reports.append((done, of)))
    assert reports[-1][1] == sum(SIZES.values()) - SIZES["model.safetensors"]


def test_a_failed_download_is_one_named_error(hub, monkeypatch: pytest.MonkeyPatch):
    def offline(*_: object, **__: object) -> str:
        raise OSError("Network is unreachable")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", offline)
    with pytest.raises(ModelDownloadFailed, match="next attempt"):
        gliner_backend.fetch_model(lambda done, of: None)


def test_a_partial_cache_is_not_a_snapshot(hub: dict[str, Path], tmp_path: Path):
    hub["config.json"] = tmp_path / "snapshot" / "config.json"
    assert gliner_backend.cached_snapshot() is None


# -- over the pipe -------------------------------------------------------------


def request(session: Session, method: str) -> dict:
    response = handle(session, json.dumps({"jsonrpc": "2.0", "id": 3, "method": method}))
    assert response is not None
    return response


def notifications(session: Session) -> list[dict]:
    assert isinstance(session.out, io.StringIO)
    lines = [json.loads(line) for line in session.out.getvalue().splitlines() if line]
    return [line for line in lines if "method" in line]


def test_status_says_missing_then_present(hub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("freedocs.rpc._module_present", lambda _module: True)
    session = Session(out=io.StringIO())
    before = request(session, "model_status")["result"]
    assert before == {"source": "hub", "ner_available": True, "present": False}

    for name in REQUIRED_FILES:
        hub[name] = tmp_path / "snapshot" / name
    assert request(session, "model_status")["result"]["present"] is True


def test_a_build_without_the_layer_never_asks_for_the_model(hub, monkeypatch):
    monkeypatch.setattr("freedocs.rpc._module_present", lambda _module: False)
    status = request(Session(out=io.StringIO()), "model_status")["result"]
    assert status["ner_available"] is False
    assert status["present"] is False


def test_fetch_reports_download_notifications_and_loads(hub, monkeypatch):
    loaded: list[str] = []

    class _Backend:
        @property
        def model(self) -> object:
            loaded.append("model")
            return object()

    monkeypatch.setattr("freedocs.detect.ner.load_backend", lambda _name: _Backend())
    session = Session(out=io.StringIO())
    assert request(session, "model_fetch")["result"] == {"present": True}
    assert loaded == ["model"], "the response means the layer works, not that files exist"

    downloads = [note["params"] for note in notifications(session)]
    assert downloads, "a download nobody hears about is the bug this replaces"
    for params in downloads:
        assert set(params) == {"id", "done", "of"}
        assert params["id"] == 3
    assert downloads[-1]["done"] == downloads[-1]["of"] == sum(SIZES.values())


def test_fetch_failure_has_its_own_code(hub, monkeypatch):
    def offline(*_: object, **__: object) -> str:
        raise OSError("Network is unreachable")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", offline)
    error = request(Session(out=io.StringIO()), "model_fetch")["error"]
    assert error["code"] == MODEL_DOWNLOAD_FAILED


def test_a_bundled_build_refuses_to_fetch(hub, monkeypatch, tmp_path: Path):
    """A portable copy that reached for the network once is one nobody trusts offline."""
    bundled = tmp_path / "ner-model"
    bundled.mkdir()
    (bundled / "config.json").write_text("{}")
    monkeypatch.setenv(gliner_backend.MODEL_ENV, str(bundled))
    session = Session(out=io.StringIO())
    assert request(session, "model_fetch")["error"]["code"] == INVALID_REQUEST
    assert request(session, "model_status")["result"]["source"] == "bundled"

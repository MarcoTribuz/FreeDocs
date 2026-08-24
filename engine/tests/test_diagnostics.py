"""The health check has to be right about being wrong."""

from __future__ import annotations

import json

import pytest

from freedocs import diagnostics
from freedocs.cli import main
from freedocs.core.mapping import mapping_unavailable_reason
from freedocs.diagnostics import MINIMUM_PYTHON, Check, run_checks


def test_every_check_that_fails_says_what_is_missing():
    for check in run_checks("http://127.0.0.1:11434"):
        assert check.detail
        if not check.ok:
            # A failure with no consequence stated is a failure nobody acts on.
            assert len(check.detail) > len(check.name)


def test_the_python_floor_matches_the_declared_one():
    """CI runs the floor; a doctor claiming a different one is a second answer."""
    assert MINIMUM_PYTHON == (3, 10)


def test_a_missing_optional_layer_is_a_warning_and_not_an_error(monkeypatch, capsys):
    """A machine without Tesseract is a normal machine."""
    monkeypatch.setattr(
        diagnostics, "_ocr_check", lambda: Check("OCR", False, "no tesseract", required=False)
    )
    assert main(["doctor"]) == 0
    assert "warn" in capsys.readouterr().out


def test_strict_turns_a_degradation_into_a_failure(monkeypatch):
    monkeypatch.setattr(
        diagnostics, "_ocr_check", lambda: Check("OCR", False, "no tesseract", required=False)
    )
    assert main(["doctor", "--strict"]) == 2


def test_a_broken_build_fails_without_strict(monkeypatch):
    """Degraded is a choice; broken is not."""
    monkeypatch.setattr(
        diagnostics,
        "_layers_check",
        lambda: Check("Detection layers", False, "nothing assembled", required=True),
    )
    assert main(["doctor"]) == 2


def test_the_ocr_check_names_which_half_is_missing(monkeypatch):
    """The binary and the language data install by different routes.

    Reporting only "OCR unavailable" sends the reader to pip for something pip
    cannot install.
    """
    from freedocs.formats import pdf

    monkeypatch.setattr(pdf, "tesseract_binary", lambda: None)
    monkeypatch.setattr(pdf, "tessdata_path", lambda: "/somewhere/tessdata")
    check = diagnostics._ocr_check()
    assert not check.ok
    assert "executable" in check.detail
    assert check.fix and "package manager" in check.fix

    monkeypatch.setattr(pdf, "tesseract_binary", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(pdf, "tessdata_path", lambda: None)
    check = diagnostics._ocr_check()
    assert not check.ok
    assert "traineddata" in check.detail
    assert check.fix and "FREEDOCS_TESSDATA" in check.fix


def test_the_json_report_is_parseable_and_states_the_verdict(capsys):
    assert main(["doctor", "--json"]) in (0, 2)
    report = json.loads(capsys.readouterr().out)
    assert isinstance(report["ok"], bool)
    assert {"name", "ok", "detail", "fix", "required"} <= set(report["checks"][0])


def test_the_check_does_not_load_the_model():
    """A diagnostic that triggers a 1.2 GB download is not a diagnostic.

    Asserted on the backend rather than on wall-clock, which would be flaky.
    """
    from freedocs.pipeline import default_registry

    registry = default_registry()
    ner = [d for d in registry.detectors if type(d).__name__ == "NerDetector"]
    if not ner:
        pytest.skip("the NER extra is not installed in this environment")
    assert ner[0]._backend is None


def test_a_packaged_build_does_not_advise_uv_sync(monkeypatch):
    """Advice a user cannot act on is worse than no advice.

    Inside a PyInstaller bundle there is no virtualenv to sync and no
    `pyproject.toml` to sync it from. The fix becomes absent rather than being
    rewritten, because what a packaged user should do depends on which build they
    have — a portable zip is replaced, an installer is reinstalled — and the
    engine does not know which one it is inside.
    """
    monkeypatch.setattr(diagnostics.sys, "frozen", True, raising=False)
    for check in run_checks("http://127.0.0.1:11434"):
        assert "uv sync" not in (check.fix or "")


def test_a_checkout_still_advises_uv_sync(monkeypatch):
    """The other direction, so the branch above cannot pass by saying nothing."""
    monkeypatch.delattr(diagnostics.sys, "frozen", raising=False)
    monkeypatch.setattr(diagnostics, "_module_present", lambda module: False)
    fixes = [check.fix for check in run_checks("http://127.0.0.1:11434")]
    assert any("uv sync" in (fix or "") for fix in fixes)


def test_the_ner_check_reports_a_bundled_model_as_bundled(monkeypatch, tmp_path):
    """Where the weights are is worth saying, and it is not "downloading"."""
    from tests.test_portable import write_payload

    if not diagnostics._module_present("gliner2"):
        pytest.skip("the NER extra is not installed in this environment")
    payload = write_payload(tmp_path / "ner-model")
    monkeypatch.setenv("FREEDOCS_NER_MODEL", str(payload))
    check = diagnostics._ner_check()
    assert check.ok
    assert "bundled" in check.detail


def test_an_incomplete_bundled_model_fails_the_check(monkeypatch, tmp_path):
    """`doctor` is where a truncated payload is meant to surface.

    The alternative is the first document failing deep inside `from_pretrained`,
    which reads as "this tool is broken" rather than "this copy is incomplete".
    """
    from tests.test_portable import write_payload

    if not diagnostics._module_present("gliner2"):
        pytest.skip("the NER extra is not installed in this environment")
    payload = write_payload(tmp_path / "ner-model")
    (payload / "model.safetensors").write_text("truncated", encoding="utf-8")
    monkeypatch.setenv("FREEDOCS_NER_MODEL", str(payload))
    check = diagnostics._ner_check()
    assert not check.ok
    assert check.fix


def test_the_key_file_check_reports_the_extra():
    """One authority. The check must not form its own opinion about the cipher's
    presence: a second answer here can disagree with the one `capabilities`
    published and the one `--map` will raise."""
    check = diagnostics._mapping_check()
    assert check.name == "Key file"
    assert check.ok == (mapping_unavailable_reason() is None)


def test_a_missing_key_file_extra_is_degraded_and_not_broken(monkeypatch):
    """A build without it scrubs exactly as well and stays irreversible, which is
    the engine's default anyway - so this is "does less", not "is broken"."""
    # Patched at the source module, not on `diagnostics`: `_mapping_check` imports
    # it inside the function - the same lazy-import discipline every optional layer
    # here follows - so a module-level attribute would never be read.
    monkeypatch.setattr(
        "freedocs.core.mapping.mapping_unavailable_reason",
        lambda: "cryptography is not installed",
    )
    check = diagnostics._mapping_check()
    assert not check.ok
    assert check.degraded
    assert not check.required
    # A fix a developer can act on, and none inside a bundle - the rule
    # `_sync_fix` exists for.
    assert check.fix == "uv sync --extra restore"


def test_a_packaged_build_gets_no_key_file_fix(monkeypatch):
    monkeypatch.setattr(
        "freedocs.core.mapping.mapping_unavailable_reason",
        lambda: "cryptography is not installed",
    )
    monkeypatch.setattr(diagnostics, "_frozen", lambda: True)
    assert diagnostics._mapping_check().fix is None

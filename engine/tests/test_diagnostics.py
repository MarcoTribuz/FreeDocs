"""The health check has to be right about being wrong."""

from __future__ import annotations

import json

import pytest

from freedocs import diagnostics
from freedocs.cli import main
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

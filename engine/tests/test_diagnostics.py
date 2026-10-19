"""The health check has to be right about being wrong."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

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
    # The binary half, whichever route this machine gets: the command for a
    # package manager that is actually installed, or the sentence naming both
    # routes when none is. Asserted on the *subject* rather than the wording,
    # because the wording is now machine-dependent - and it must never be the
    # tessdata advice, which is the other half.
    assert check.fix and "tesseract" in check.fix.casefold()
    assert "FREEDOCS_TESSDATA" not in check.fix

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


def test_a_frozen_build_advises_no_layer_fix_it_cannot_run(monkeypatch):
    """`_layers_check` was the one check that composed its own `uv sync`.

    It skipped `_sync_fix`, so it went on printing advice a packaged user cannot
    act on - there is no virtualenv in a bundle to sync - while the module around
    it was fixed. The empty registry has to be forced: on a machine with the
    `ner` extra installed this check has no fix at all, so an unforced assertion
    passes without exercising the branch.
    """
    monkeypatch.setattr(diagnostics, "_frozen", lambda: True)
    monkeypatch.setattr("freedocs.pipeline.default_registry", lambda: SimpleNamespace(detectors=[]))
    check = diagnostics._layers_check()
    assert not check.ok
    assert check.fix is None

    monkeypatch.setattr(diagnostics, "_frozen", lambda: False)
    check = diagnostics._layers_check()
    assert check.fix == "uv sync --extra ner"


def test_no_frozen_fix_names_a_virtualenv(monkeypatch):
    """The loop, so the next check that hardcodes one fails here too."""
    monkeypatch.setattr(diagnostics, "_frozen", lambda: True)
    for check in run_checks("http://127.0.0.1:1"):
        assert check.fix is None or "uv sync" not in check.fix, check.name


# -- the install command, which is as far towards an installer as this goes -----


def hide_the_binary(monkeypatch) -> None:
    """Pretend no package manager has installed Tesseract.

    `_SYSTEM_BINARIES` names real paths, so on any machine with Homebrew's
    Tesseract the fallback answers and a test about the absent case would be
    measuring this machine rather than the code.
    """
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", ())
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")


def test_the_ocr_fix_names_the_package_manager_this_machine_has(monkeypatch, tmp_path):
    """Detected, not guessed: naming apt on a Fedora box is advice that fails."""
    hide_the_binary(monkeypatch)
    manager = tmp_path / "opt" / "brew"
    manager.parent.mkdir(parents=True, exist_ok=True)
    manager.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        diagnostics, "_PACKAGE_MANAGERS", ((str(manager), "brew install tesseract tesseract-lang"),)
    )
    check = diagnostics._ocr_check()
    assert not check.ok
    assert check.fix == "brew install tesseract tesseract-lang"


def test_no_package_manager_leaves_the_advice_generic(monkeypatch, tmp_path):
    """A command naming a manager that is not installed is worse than a sentence."""
    hide_the_binary(monkeypatch)
    monkeypatch.setattr(diagnostics, "_PACKAGE_MANAGERS", ((str(tmp_path / "absent"), "nope"),))
    check = diagnostics._ocr_check()
    assert check.fix and "FREEDOCS_TESSERACT" in check.fix


def test_a_packaged_build_still_advises_a_system_package(monkeypatch, tmp_path):
    """The distinction `_sync_fix` draws, asserted in the opposite direction.

    A missing *extra* is suppressed when frozen because the engine cannot see
    which build shape it is in. A *platform* it can see, and a system package
    installs the same way whatever build asked - so this one must survive.
    """
    hide_the_binary(monkeypatch)
    monkeypatch.setattr(diagnostics, "_frozen", lambda: True)
    manager = tmp_path / "brew"
    manager.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        diagnostics, "_PACKAGE_MANAGERS", ((str(manager), "brew install tesseract tesseract-lang"),)
    )
    assert diagnostics._ocr_check().fix == "brew install tesseract tesseract-lang"


def test_every_install_command_names_the_language_data():
    """`brew install tesseract` ships English only, and that reads as working.

    `tessdata_path()` counts a directory holding *any* `.traineddata`, so an
    English-only install makes `ocr_available` true while an Italian scan reads
    badly - and a value OCR misreads fails its checksum, is never detected, and
    survives. Shortening one of these lines is a quiet leak.
    """
    for manager, command in diagnostics._PACKAGE_MANAGERS:
        assert "tesseract" in command.casefold(), manager
        if command in diagnostics._LANGUAGES_FROM_THE_BUNDLE:
            continue
        # Every one names at least one language beyond the base package: a
        # `-lang` metapackage, a `-langpack-xx`, a `-ocr-xxx`, or `tesseract-ita`.
        beyond_base = [
            word
            for word in command.split()
            if word.startswith("tesseract") and word not in {"tesseract", "tesseract-ocr"}
        ]
        assert beyond_base, manager


def test_only_winget_is_excused_from_naming_the_language_data():
    """The exemption is a closed list, so a shortened line cannot hide in it.

    winget's Tesseract package takes no language choice, and on Windows the
    language data is the bundle's job. Anything else joining that list has to say
    where its languages come from, here, in a test somebody will read.
    """
    assert {diagnostics._WINGET_COMMAND} == diagnostics._LANGUAGES_FROM_THE_BUNDLE


def test_winget_is_located_from_the_user_profile(tmp_path):
    """An App Installer alias lives under `LOCALAPPDATA`; there is no fixed path."""
    entries = diagnostics._winget({"LOCALAPPDATA": str(tmp_path)})
    assert entries == (
        (
            str(tmp_path / "Microsoft" / "WindowsApps" / "winget.exe"),
            diagnostics._WINGET_COMMAND,
        ),
    )
    assert diagnostics._winget({}) == ()


def test_a_windows_machine_with_winget_is_told_the_winget_line(monkeypatch, tmp_path):
    """The gap that left Windows with only a generic sentence to copy."""
    hide_the_binary(monkeypatch)
    alias = tmp_path / "Microsoft" / "WindowsApps" / "winget.exe"
    alias.parent.mkdir(parents=True)
    alias.write_bytes(b"")
    monkeypatch.setattr(
        diagnostics, "_PACKAGE_MANAGERS", diagnostics._winget({"LOCALAPPDATA": str(tmp_path)})
    )
    assert diagnostics._ocr_check().fix == diagnostics._WINGET_COMMAND


@pytest.mark.skipif(sys.platform == "win32", reason="the POSIX half of `_present`")
def test_a_dangling_package_manager_link_is_not_a_package_manager(tmp_path):
    """`lexists` is for winget's alias only; on POSIX a broken link is a leftover."""
    link = tmp_path / "brew"
    link.symlink_to(tmp_path / "uninstalled")
    assert not diagnostics._present(link)


# -- the one install the engine runs ------------------------------------------


def a_homebrew(monkeypatch, tmp_path, *, languages_missing: bool):
    """A fake `brew` the table treats as Homebrew, and a language-data answer."""
    brew = tmp_path / "brew"
    brew.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        diagnostics, "_PACKAGE_MANAGERS", ((str(brew), "brew install tesseract tesseract-lang"),)
    )
    monkeypatch.setattr(diagnostics, "_UNATTENDED", frozenset({str(brew)}))
    monkeypatch.setattr(
        "freedocs.formats.pdf.missing_languages", lambda: ["ita"] if languages_missing else []
    )
    return brew


def test_homebrew_is_run_and_asks_only_for_the_binary_when_the_languages_are_here(
    monkeypatch, tmp_path
):
    """`tesseract-lang` is over a gigabyte the installer's sidecar already carries."""
    brew = a_homebrew(monkeypatch, tmp_path, languages_missing=False)
    plan = diagnostics.install_plan()
    assert plan == diagnostics.InstallPlan(
        "brew install tesseract", (str(brew), "install", "tesseract")
    )


def test_homebrew_brings_the_languages_when_they_are_missing(monkeypatch, tmp_path):
    a_homebrew(monkeypatch, tmp_path, languages_missing=True)
    plan = diagnostics.install_plan()
    assert plan is not None and plan.argv is not None
    assert plan.argv[1:] == ("install", "tesseract", "tesseract-lang")


def test_what_is_shown_is_what_runs(monkeypatch, tmp_path):
    """Nobody presses a button that runs something other than the line they read."""
    a_homebrew(monkeypatch, tmp_path, languages_missing=False)
    plan = diagnostics.install_plan()
    assert plan is not None and plan.argv is not None
    assert plan.command.split()[1:] == list(plan.argv[1:])


def test_a_manager_that_needs_elevation_is_shown_and_never_run(monkeypatch, tmp_path):
    apt = tmp_path / "apt"
    apt.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(diagnostics, "_PACKAGE_MANAGERS", ((str(apt), "sudo apt install x"),))
    plan = diagnostics.install_plan()
    assert plan == diagnostics.InstallPlan("sudo apt install x", None)
    with pytest.raises(ValueError):
        diagnostics.run_install(plan)


def test_only_homebrew_is_unattended():
    """M17: elevation is not a subset of what a person asked for."""
    assert all(path.endswith("/brew") for path in diagnostics._UNATTENDED)
    run = {manager for manager, _ in diagnostics._PACKAGE_MANAGERS} & diagnostics._UNATTENDED
    assert run == diagnostics._UNATTENDED


def stand_in(code: str) -> diagnostics.InstallPlan:
    """A harmless process in place of the package manager."""
    return diagnostics.InstallPlan("brew install tesseract", (sys.executable, "-c", code))


def test_a_successful_install_reports_nothing():
    assert diagnostics.run_install(stand_in("pass")) is None


def test_a_failed_install_says_which_command_and_how_it_ended():
    failure = diagnostics.run_install(
        stand_in("import sys; print('Error: no bottle available', file=sys.stderr); sys.exit(1)")
    )
    assert failure is not None
    assert failure.startswith("brew install tesseract exited with status 1")
    assert "no bottle available" in failure


def test_the_installer_cannot_wait_on_a_prompt_nobody_sees():
    """stdin is closed and Homebrew is told it is not interactive."""
    code = (
        "import os, sys; "
        "sys.exit(0 if os.environ.get('NONINTERACTIVE') == '1' and sys.stdin.read() == '' else 3)"
    )
    assert diagnostics.run_install(stand_in(code)) is None


def test_an_install_that_hangs_is_ended_and_reported(monkeypatch):
    monkeypatch.setattr(diagnostics, "INSTALL_TIMEOUT_SECONDS", 0.5)
    failure = diagnostics.run_install(stand_in("import time; time.sleep(5)"))
    assert failure is not None and "did not finish" in failure


def test_no_passphrase_reaches_the_installer(monkeypatch):
    """M10, one process further out: Homebrew runs scripts nobody here wrote."""
    monkeypatch.setenv("FREEDOCS_MAP_PASSPHRASE", "correct horse battery staple")
    monkeypatch.setenv("FREEDOCS_TERMS_PASSPHRASE", "another one")
    code = (
        "import os, sys; sys.exit(3 if any(k.startswith('FREEDOCS_') for k in os.environ) else 0)"
    )
    assert diagnostics.run_install(stand_in(code)) is None

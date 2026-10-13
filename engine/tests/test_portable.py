"""The portable build's contract with the engine: paths in, no network out.

A portable copy is unzipped onto a machine that installed nothing, so everything
here is about being *told* where things are rather than finding them. None of it
needs the `ner` extra — the point is what happens before the model is loaded, and
by the time loading matters the questions below have already been answered.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from freedocs.core.errors import ModelNotFound
from freedocs.core.model_manifest import MANIFEST_NAME, REQUIRED_FILES, manifest_for, verify
from freedocs.detect.backends.gliner_backend import (
    DEFAULT_MODEL,
    MODEL_ENV,
    GlinerBackend,
    model_source,
)
from freedocs.formats.pdf import (
    TESSERACT_NOT_EXECUTABLE,
    TESSERACT_WRONG_NAME,
    _tessdata_candidates,
    _windows_roots,
    adopt_tesseract,
    ocr_unavailable_reason,
    tesseract_binary,
)


def write_payload(root: Path, *, repo: str = DEFAULT_MODEL) -> Path:
    """A model directory shaped like the real one, with tiny files.

    Contents rather than sizes are what makes this cheap: the checks under test
    compare a file against its own recorded size, so a four-byte stand-in
    exercises exactly the same path as 1.2 GB.
    """
    root.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"contents of {name}", encoding="utf-8")
    manifest = manifest_for(root, list(REQUIRED_FILES), repo=repo)
    (root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return root


def hide_system_binaries(monkeypatch) -> None:
    """Pretend no package manager has installed Tesseract.

    `_SYSTEM_BINARIES` names real paths, so on any developer machine with
    Homebrew's Tesseract the fallback answers and a test asserting the absent case
    would be measuring this machine rather than the code. Emptying it is also how
    the tests below separate the three tiers from each other.
    """
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", ())


def executable(path: Path) -> Path:
    """A file the platform running the tests agrees is runnable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def binary_name() -> str:
    return "tesseract.exe" if sys.platform == "win32" else "tesseract"


# -- where the model comes from ------------------------------------------------


def test_an_unset_variable_means_the_pinned_repository(monkeypatch):
    monkeypatch.delenv(MODEL_ENV, raising=False)
    assert model_source() == DEFAULT_MODEL


def test_a_real_directory_is_used_verbatim(monkeypatch, tmp_path):
    payload = write_payload(tmp_path / "ner-model")
    monkeypatch.setenv(MODEL_ENV, str(payload))
    assert model_source() == str(payload)


def test_a_path_that_is_not_a_model_is_refused_rather_than_downloaded(monkeypatch, tmp_path):
    """The one that matters.

    Falling back to `DEFAULT_MODEL` here would turn a typo in a portable build
    into a silent 1.2 GB download on a machine that has a network, and into a 404
    about a repository nobody named on a machine that does not.
    """
    empty = tmp_path / "not-a-model"
    empty.mkdir()
    monkeypatch.setenv(MODEL_ENV, str(empty))
    with pytest.raises(ModelNotFound) as caught:
        model_source()
    assert str(empty) in str(caught.value)


def test_the_backend_resolves_the_source_per_instance(monkeypatch, tmp_path):
    """Not at import, which is the trap `DEFAULT_LABELS` already carries.

    `load_backend` is `@cache`d, so a module-level `os.environ` read would be
    taken once by whichever caller happened to be first — and every test after
    that one would silently assert about the wrong value.
    """
    payload = write_payload(tmp_path / "ner-model")
    monkeypatch.setenv(MODEL_ENV, str(payload))
    assert GlinerBackend().model_id == str(payload)
    monkeypatch.delenv(MODEL_ENV)
    assert GlinerBackend().model_id == DEFAULT_MODEL


# -- is the payload actually all there ----------------------------------------


def test_a_complete_payload_has_nothing_to_report(tmp_path):
    payload = write_payload(tmp_path / "ner-model")
    assert verify(payload, repo=DEFAULT_MODEL) == []


def test_a_truncated_file_is_caught_by_size_alone(tmp_path):
    """The failure a portable build has and a downloaded one does not.

    An unzip that ran out of disk, or a stick pulled mid-write, leaves a file
    that opens and is the wrong length. Without this the first symptom is a
    document failing deep inside `from_pretrained`.
    """
    payload = write_payload(tmp_path / "ner-model")
    weights = payload / "model.safetensors"
    weights.write_text("t", encoding="utf-8")
    problems = verify(payload, repo=DEFAULT_MODEL)
    assert any("model.safetensors" in problem and "bytes" in problem for problem in problems)


def test_a_file_edited_without_changing_length_needs_the_hash_check(tmp_path):
    payload = write_payload(tmp_path / "ner-model")
    config = payload / "config.json"
    config.write_text("X" * len(config.read_text(encoding="utf-8")), encoding="utf-8")
    assert verify(payload, repo=DEFAULT_MODEL) == []
    assert verify(payload, repo=DEFAULT_MODEL, hashes=True) != []


def test_a_missing_file_is_named(tmp_path):
    payload = write_payload(tmp_path / "ner-model")
    (payload / "tokenizer.json").unlink()
    assert any("tokenizer.json" in problem for problem in verify(payload, repo=DEFAULT_MODEL))


def test_a_payload_of_the_wrong_model_is_refused(tmp_path):
    """A build and its weights have to agree on which model they are.

    Two versions of this tool with different pins would otherwise happily load
    each other's weights and report detection quality nobody has measured.
    """
    payload = write_payload(tmp_path / "ner-model", repo="someone/else")
    assert any(DEFAULT_MODEL in problem for problem in verify(payload, repo=DEFAULT_MODEL))


def test_a_missing_manifest_is_reported_and_not_assumed_fine(tmp_path):
    bare = tmp_path / "ner-model"
    bare.mkdir()
    assert verify(bare, repo=DEFAULT_MODEL) != []


# -- the halves of OCR a portable build cannot install ------------------------


def test_the_tesseract_override_is_validated_not_trusted(monkeypatch, tmp_path):
    """A path that does not resolve must leave the capability saying no.

    `ocr_unavailable_reason` is the single authority precisely so the capability
    the window shows and the refusal the engine raises cannot disagree. An
    override that bypassed it would report OCR available and then fail on the
    first scan.
    """
    hide_system_binaries(monkeypatch)
    monkeypatch.setenv("FREEDOCS_TESSERACT", str(tmp_path / "nowhere" / "tesseract"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() is None
    reason = ocr_unavailable_reason()
    assert reason is not None and "executable" in reason


def test_a_file_that_is_not_executable_does_not_count(monkeypatch, tmp_path):
    """What "not executable" means differs, so the case has to differ with it.

    On POSIX it is a cleared permission bit. On Windows there is no such bit —
    `os.access(X_OK)` is true for anything that exists — and the shell decides by
    extension, so the unrunnable file is one whose suffix is not in PATHEXT.
    Asserting the POSIX case on Windows is what made this pass locally and fail
    in CI.
    """
    hide_system_binaries(monkeypatch)
    if sys.platform == "win32":
        fake = tmp_path / "tesseract.txt"
        fake.write_text("not a program", encoding="utf-8")
    else:
        fake = tmp_path / "tesseract"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        fake.chmod(0o644)
    monkeypatch.setenv("FREEDOCS_TESSERACT", str(fake))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() is None


def test_an_executable_override_is_adopted_and_put_on_path(monkeypatch, tmp_path):
    """The `PATH` half is not decoration.

    Nothing in this engine runs Tesseract: PyMuPDF does, by shelling out, and it
    resolves the executable through `PATH` — it has an argument for the language
    data and none for the binary. So an override that only satisfied
    `tesseract_binary` would report OCR available and still fail.
    """
    binary = executable(tmp_path / "bin" / binary_name())
    monkeypatch.setenv("FREEDOCS_TESSERACT", str(binary))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() == str(binary)
    assert str(binary.parent) in os.environ["PATH"].split(os.pathsep)


# -- the launch context, which is what actually varies ------------------------


def test_a_package_manager_install_is_found_when_path_cannot_see_it(monkeypatch, tmp_path):
    """The reported regression, and it is about how the process was started.

    A macOS `.app` opened from Finder inherits launchd's environment, so `PATH` is
    `/usr/bin:/bin:/usr/sbin:/sbin` — `/opt/homebrew/bin` is not on it and cannot
    be. The bundle therefore reported no Tesseract on a machine where `brew
    install tesseract` had already succeeded, while the language-data half
    resolved fine because `_SYSTEM_TESSDATA` was already a list of locations.
    """
    binary = executable(tmp_path / "opt" / "homebrew" / "bin" / binary_name())
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", (str(binary),))
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() == str(binary)


def test_a_binary_found_off_path_is_put_on_path(monkeypatch, tmp_path):
    """Same requirement as the override, and the reason the two share `_adopt`.

    PyMuPDF resolves `tesseract` through `PATH` and takes no argument for it. A
    fallback that reported the path without the side effect would make
    `capabilities` promise OCR and the first scan fail inside Tesseract — the
    bug the fallback exists to fix, moved one step later.
    """
    binary = executable(tmp_path / "opt" / "homebrew" / "bin" / binary_name())
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", (str(binary),))
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() == str(binary)
    assert str(binary.parent) in os.environ["PATH"].split(os.pathsep)


def test_the_override_still_wins_over_an_installed_one(monkeypatch, tmp_path):
    """A caller who named a binary gets that binary, not whatever is installed."""
    chosen = executable(tmp_path / "chosen" / binary_name())
    installed = executable(tmp_path / "installed" / binary_name())
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", (str(installed),))
    monkeypatch.setenv("FREEDOCS_TESSERACT", str(chosen))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() == str(chosen)


def test_path_still_wins_over_an_installed_one(monkeypatch, tmp_path):
    """The list is a last resort.

    Someone who put a chosen build on `PATH` has said which one they want just as
    clearly as the override does, so the fallback must not overrule it.
    """
    on_path = executable(tmp_path / "on-path" / binary_name())
    installed = executable(tmp_path / "installed" / binary_name())
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", (str(installed),))
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setattr("freedocs.formats.pdf.shutil.which", lambda _: str(on_path))
    assert tesseract_binary() == str(on_path)


def test_the_installed_locations_are_tried_in_order(monkeypatch, tmp_path):
    """First hit wins, so Apple-silicon Homebrew beats a MacPorts leftover."""
    first = executable(tmp_path / "homebrew" / binary_name())
    second = executable(tmp_path / "macports" / binary_name())
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", (str(first), str(second)))
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() == str(first)


def test_a_per_user_windows_install_is_searched():
    """The reported regression on Windows: installed by hand, never found.

    The UB Mannheim installer's "just for me" puts Tesseract under
    `%LOCALAPPDATA%` and adds nothing to `PATH`, while the list used to name only
    the machine-wide directory on `C:`.
    """
    roots = _windows_roots({"LOCALAPPDATA": "/u/AppData/Local"})
    assert os.path.join("/u/AppData/Local", "Programs", "Tesseract-OCR") in roots


def test_program_files_is_read_not_assumed_to_be_on_c():
    roots = _windows_roots({"ProgramFiles": "D:/Programs"})
    assert roots == (os.path.join("D:/Programs", "Tesseract-OCR"),)


def test_a_machine_wide_install_is_tried_before_a_per_user_one():
    """A managed fleet installs for everybody, and that is the copy to use."""
    roots = _windows_roots(
        {"LOCALAPPDATA": "/u/local", "ProgramW6432": "/pf", "ProgramFiles": "/pf"}
    )
    assert roots[0] == os.path.join("/pf", "Tesseract-OCR")
    # The 64-bit process reports the same directory twice; it is listed once.
    assert len(roots) == len(set(roots))


def test_scoop_is_found_through_its_app_directory_not_its_shim():
    assert _windows_roots({"USERPROFILE": "/u"}) == (
        os.path.join("/u", "scoop", "apps", "tesseract", "current"),
    )
    # A relocated Scoop says so in its own variable, which wins.
    assert _windows_roots({"USERPROFILE": "/u", "SCOOP": "/s"}) == (
        os.path.join("/s", "apps", "tesseract", "current"),
    )


def test_no_windows_environment_adds_no_locations():
    """What macOS and Linux see: the list gains nothing and costs no `stat`."""
    assert _windows_roots({}) == ()


def test_an_unrunnable_file_in_an_installed_location_is_not_adopted(monkeypatch, tmp_path):
    """The list is checked, not trusted — same standard as the override.

    A directory left behind by an uninstall can hold a file of the right name.
    Adopting it would put the capability and the refusal back in disagreement,
    which is the one thing this module must not do.
    """
    fake = tmp_path / "leftover" / ("tesseract.txt" if sys.platform == "win32" else "tesseract")
    fake.parent.mkdir(parents=True)
    fake.write_text("not a program", encoding="utf-8")
    if sys.platform != "win32":
        fake.chmod(0o644)
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", (str(fake),))
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() is None
    reason = ocr_unavailable_reason()
    assert reason is not None and "executable" in reason


def test_the_pyinstaller_data_directory_is_a_tessdata_candidate(monkeypatch, tmp_path):
    """The spec and the lookup used to disagree about one directory level.

    `freedocs-engine.spec` adds the `.traineddata` with destination "tessdata",
    and with no `contents_directory` set PyInstaller 6 puts datas under
    `_internal/` — while the existing candidate looked beside the executable, one
    level up. No build had shipped tessdata yet, so nothing had noticed.
    """
    meipass = tmp_path / "_internal"
    monkeypatch.setattr("sys._MEIPASS", str(meipass), raising=False)
    # Built with `Path`, not spelled with forward slashes: the candidates are
    # native paths and `\` is the separator on the platform this has to pass on.
    assert str(meipass / "tessdata") in _tessdata_candidates()


def test_an_explicit_tessdata_choice_still_wins(monkeypatch):
    monkeypatch.setenv("FREEDOCS_TESSDATA", "/chosen")
    assert _tessdata_candidates()[0] == "/chosen"


def test_windows_executability_is_the_extension_not_a_permission_bit(monkeypatch, tmp_path):
    """The Windows branch, exercised on whatever platform runs this.

    Otherwise the only thing covering it is the CI job that caught the original
    mistake, and a rule about PATHEXT that is checked on one runner out of three
    is a rule that breaks quietly.
    """
    from freedocs.formats.pdf import _is_executable

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")

    runnable = tmp_path / "tesseract.exe"
    runnable.write_text("MZ", encoding="utf-8")
    assert _is_executable(runnable)

    # The mistake a user actually makes: naming the POSIX binary on Windows.
    bare = tmp_path / "tesseract"
    bare.write_text("MZ", encoding="utf-8")
    assert not _is_executable(bare)

    assert not _is_executable(tmp_path / "absent.exe")


def test_a_stripped_environment_still_has_a_pathext_answer(monkeypatch, tmp_path):
    """No PATHEXT is a stripped environment, not a licence to accept anything."""
    from freedocs.formats.pdf import _is_executable

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("PATHEXT", raising=False)
    runnable = tmp_path / "tesseract.exe"
    runnable.write_text("MZ", encoding="utf-8")
    assert _is_executable(runnable)
    odd = tmp_path / "tesseract.txt"
    odd.write_text("MZ", encoding="utf-8")
    assert not _is_executable(odd)


# --- the payload's integrity, checked where it is used ------------------------


def test_a_payload_altered_without_changing_its_length_is_refused(tmp_path: Path):
    """The one failure a size check cannot see, and the one that matters most.

    A truncated copy fails deep inside `from_pretrained` and looks broken. A
    payload whose *bytes* changed while its length did not loads perfectly and
    detects less — and silently detecting less is this tool's defining failure,
    the thing every other guard here exists to prevent. Sizes cannot see it;
    only a hash can.
    """
    from freedocs.detect.backends.gliner_backend import verify_bundled

    root = write_payload(tmp_path / "ner-model")
    weights = root / "model.safetensors"
    original = weights.read_bytes()
    weights.write_bytes(b"X" + original[1:])
    assert weights.stat().st_size == len(original), "the test must not change the length"

    with pytest.raises(ModelNotFound, match="SHA-256"):
        verify_bundled(str(root))


def test_an_intact_payload_is_accepted(tmp_path: Path):
    """The half a wrong check breaks: refusing a good bundle is an outage."""
    from freedocs.detect.backends.gliner_backend import verify_bundled

    verify_bundled(str(write_payload(tmp_path / "ner-model")))


def test_the_hub_route_is_not_hash_checked(tmp_path: Path):
    """A repository id is not a directory, and the hub already checks its own
    blobs. Refusing to load because there is no manifest beside a cache entry
    would break every installer build."""
    from freedocs.detect.backends.gliner_backend import DEFAULT_MODEL, verify_bundled

    verify_bundled(DEFAULT_MODEL)


def test_a_directory_with_no_manifest_is_left_alone(tmp_path: Path):
    """`FREEDOCS_NER_MODEL` is also the developer's hook for pointing at a
    checkout. A manifest is what a *built* payload carries, so its absence means
    "nobody claimed anything about this" rather than "this is damaged"."""
    from freedocs.detect.backends.gliner_backend import verify_bundled

    root = write_payload(tmp_path / "ner-model")
    (root / MANIFEST_NAME).unlink()
    verify_bundled(str(root))


# -- a Tesseract somebody chose, which is the only route that can be misnamed ---


def test_a_binary_pymupdf_cannot_resolve_by_name_is_refused(monkeypatch, tmp_path):
    """Runnable is not enough, and this is what makes a file picker safe.

    `_adopt` puts the candidate's *directory* on `PATH` and PyMuPDF resolves the
    bare name `tesseract` out of it. Every caller that existed before a person
    could choose supplied a path already named that, so the gap was unreachable;
    a picker reaches it, and in the worst direction - the capability would say
    OCR is available and the first scan would fail inside Tesseract.
    """
    hide_system_binaries(monkeypatch)
    # Runnable on both platforms, and still the wrong name: Windows decides
    # runnable by the extension, so without `.exe` this test would be asking
    # the other refusal.
    misnamed = "tesseract-5.3.4.exe" if sys.platform == "win32" else "tesseract-5.3.4"
    chosen = executable(tmp_path / "opt" / misnamed)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert adopt_tesseract(chosen) == TESSERACT_WRONG_NAME
    assert tesseract_binary() is None
    reason = ocr_unavailable_reason()
    assert reason is not None and "executable" in reason


def test_a_choice_that_is_not_runnable_is_refused_for_that_reason(monkeypatch, tmp_path):
    """The two refusals are kept apart because the next move differs."""
    hide_system_binaries(monkeypatch)
    # No `.exe` and no executable bit: not runnable on either platform.
    # `binary_name()` here was runnable on Windows, where the extension is
    # the whole test.
    plain = tmp_path / "bin" / "tesseract"
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text("not runnable\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert adopt_tesseract(plain) == TESSERACT_NOT_EXECUTABLE


def test_a_refused_choice_leaves_the_environment_as_it_was(monkeypatch, tmp_path):
    """A rejected path left in the variable is state nobody chose.

    It would also leave `doctor` naming an override that is not being used, which
    is the report disagreeing with the behaviour.
    """
    hide_system_binaries(monkeypatch)
    good = executable(tmp_path / "good" / binary_name())
    monkeypatch.setenv("FREEDOCS_TESSERACT", str(good))
    assert adopt_tesseract(tmp_path / "nowhere" / binary_name()) == TESSERACT_NOT_EXECUTABLE
    assert os.environ["FREEDOCS_TESSERACT"] == str(good)


def test_a_choice_that_takes_is_adopted_and_put_on_path(monkeypatch, tmp_path):
    hide_system_binaries(monkeypatch)
    chosen = executable(tmp_path / "elsewhere" / binary_name())
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert adopt_tesseract(chosen) is None
    assert tesseract_binary() == str(chosen)
    assert str(chosen.parent) in os.environ["PATH"].split(os.pathsep)


def test_the_most_recent_choice_is_the_one_that_runs(monkeypatch, tmp_path):
    """`PATH` order decides which binary PyMuPDF executes, so prepending matters.

    Two adoptions in one session is what a user correcting a wrong pick does, and
    appending instead of prepending would leave the first choice winning.
    """
    hide_system_binaries(monkeypatch)
    first = executable(tmp_path / "one" / binary_name())
    second = executable(tmp_path / "two" / binary_name())
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert adopt_tesseract(first) is None
    assert adopt_tesseract(second) is None
    entries = os.environ["PATH"].split(os.pathsep)
    assert entries.index(str(second.parent)) < entries.index(str(first.parent))
    assert tesseract_binary() == str(second)


def test_the_system_locations_are_still_scanned_past_a_wrongly_named_file(monkeypatch, tmp_path):
    """One unadoptable leftover in an early location must not hide a real install.

    `return _adopt(path)` inside the loop would have ended the scan on the first
    runnable file, adopted or not.
    """
    misnamed = executable(tmp_path / "early" / "tesseract-old")
    real = executable(tmp_path / "late" / binary_name())
    monkeypatch.setattr("freedocs.formats.pdf._SYSTEM_BINARIES", (str(misnamed), str(real)))
    monkeypatch.delenv("FREEDOCS_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert tesseract_binary() == str(real)

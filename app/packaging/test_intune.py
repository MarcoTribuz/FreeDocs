"""Tests for the Intune packaging script.

Only the parts that decide something run here. Reading the MSI and calling
IntuneWinAppUtil are Windows-only and Microsoft's; what is pinned is everything
that would let a wrong package through: a development version, a stale MSI, an
upgrade code that makes the next version install beside this one, and a staging
folder carrying a second file onto every machine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intune as I

V = I.V

PINNED = "9b739aa3-694f-5e3b-b9a3-fd637b39bbda"


def config(pinned: str | None = PINNED) -> dict:
    windows = {"wix": {"upgradeCode": pinned}} if pinned else {}
    return {
        "productName": "FreeDocs",
        "bundle": {"windows": windows, "longDescription": "x"},
    }


# --------------------------------------------------------------------------
# The upgrade code


def test_the_pinned_upgrade_code_is_the_one_tauri_derived_before_it():
    # An MSI built from v0.2.0, before the pin, must be the same product to
    # Windows as one built after it; otherwise the first upgrade duplicates.
    assert I.expected_upgrade_code(config()) == I.expected_upgrade_code(config(pinned=None))


def test_the_repository_config_pins_the_upgrade_code():
    assert I.conf()["bundle"]["windows"]["wix"]["upgradeCode"] == PINNED


def test_the_upgrade_code_is_compared_in_one_spelling():
    assert I.expected_upgrade_code(config(PINNED.upper())) == PINNED.upper()


# --------------------------------------------------------------------------
# The version


def test_a_development_version_is_refused(monkeypatch):
    monkeypatch.setattr(V, "current", lambda root: V.parse("0.3.0-dev.4"))
    with pytest.raises(SystemExit, match="development version"):
        I.release_version()


def test_a_release_version_is_accepted(monkeypatch):
    monkeypatch.setattr(V, "current", lambda root: V.parse("0.3.0"))
    assert I.release_version() == V.parse("0.3.0")


def test_the_msi_name_is_the_one_tauri_writes():
    assert I.msi_name(config(), V.parse("0.2.0")) == "FreeDocs_0.2.0_x64_en-US.msi"


# --------------------------------------------------------------------------
# Finding the MSI


def _put(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"msi")
    return path


def test_an_msi_of_another_version_is_not_picked_up(tmp_path):
    _put(tmp_path / "release" / "bundle" / "msi" / "FreeDocs_0.1.0_x64_en-US.msi")
    with pytest.raises(SystemExit, match=r"no FreeDocs_0\.2\.0"):
        I.find_msi("FreeDocs_0.2.0_x64_en-US.msi", tmp_path)


@pytest.mark.parametrize("prefix", [(), (I.TRIPLE,)])
def test_the_msi_is_found_with_and_without_a_target(tmp_path, prefix):
    name = "FreeDocs_0.2.0_x64_en-US.msi"
    built = _put(tmp_path.joinpath(*prefix, "release", "bundle", "msi", name))
    assert I.find_msi(name, tmp_path) == built


def test_two_builds_of_one_version_are_refused(tmp_path):
    name = "FreeDocs_0.2.0_x64_en-US.msi"
    _put(tmp_path / "release" / "bundle" / "msi" / name)
    _put(tmp_path / I.TRIPLE / "release" / "bundle" / "msi" / name)
    with pytest.raises(SystemExit, match="exists twice"):
        I.find_msi(name, tmp_path)


# --------------------------------------------------------------------------
# The MSI's own properties


PROPERTIES = {
    "ProductCode": "{11111111-2222-3333-4444-555555555555}",
    "ProductVersion": "0.2.0",
    "UpgradeCode": "{" + PINNED.upper() + "}",
    "Manufacturer": "FreeDocs",
}


def test_the_property_table_is_parsed_from_powershell_output():
    text = "ProductCode={A}\r\nProductVersion=0.2.0\r\nARPNOMODIFY=1\r\n\r\n"
    assert I.parse_properties(text) == {
        "ProductCode": "{A}",
        "ProductVersion": "0.2.0",
        "ARPNOMODIFY": "1",
    }


def test_matching_properties_pass():
    I.check_properties(
        PROPERTIES, version=V.parse("0.2.0"), upgrade_code=I.expected_upgrade_code(config())
    )


def test_a_stale_msi_is_refused():
    with pytest.raises(SystemExit, match=r"ProductVersion is 0\.2\.0, this tree is 0\.2\.1"):
        I.check_properties(
            PROPERTIES, version=V.parse("0.2.1"), upgrade_code=I.expected_upgrade_code(config())
        )


def test_a_different_upgrade_code_is_refused():
    other = {**PROPERTIES, "UpgradeCode": "{00000000-0000-0000-0000-000000000000}"}
    with pytest.raises(SystemExit, match="beside the previous version"):
        I.check_properties(
            other, version=V.parse("0.2.0"), upgrade_code=I.expected_upgrade_code(config())
        )


def test_a_missing_property_is_refused_by_name():
    partial = {k: v for k, v in PROPERTIES.items() if k != "ProductCode"}
    with pytest.raises(SystemExit, match="ProductCode is missing"):
        I.check_properties(partial, version=V.parse("0.2.0"), upgrade_code="x")


# --------------------------------------------------------------------------
# Packaging


def test_staging_holds_the_msi_and_nothing_else(tmp_path):
    msi = _put(tmp_path / "build" / "FreeDocs_0.2.0_x64_en-US.msi")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "left-over.txt").write_text("from a previous run")
    I.stage(msi, staging)
    assert [p.name for p in staging.iterdir()] == [msi.name]


def test_the_settings_sheet_installs_per_machine_and_silently(tmp_path):
    msi = _put(tmp_path / "FreeDocs_0.2.0_x64_en-US.msi")
    sheet = I.settings(config(), V.parse("0.2.0"), msi, PROPERTIES)
    assert sheet["install_behavior"] == "System"
    assert sheet["install_command"] == 'msiexec /i "FreeDocs_0.2.0_x64_en-US.msi" /qn /norestart'
    assert sheet["uninstall_command"] == f"msiexec /x {PROPERTIES['ProductCode']} /qn /norestart"
    assert sheet["detection"]["product_code"] == PROPERTIES["ProductCode"]
    json.dumps(sheet)


def test_the_msi_path_is_not_handed_to_powershell_as_script_text():
    # `powershell -Command <script> <path>` appends the path to the script, so
    # it must travel in the environment and the script must read it from there.
    assert "$args" not in I._READ_PROPERTIES
    assert f"$env:{I.MSI_ENV}" in I._READ_PROPERTIES


def test_the_tool_is_never_fetched(tmp_path, monkeypatch):
    monkeypatch.delenv(I.TOOL_ENV, raising=False)
    monkeypatch.setattr(I.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match=r"not\s+downloaded by this script"):
        I.find_tool(None)

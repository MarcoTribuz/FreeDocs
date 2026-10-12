"""Wrap the Windows installer as an Intune Win32 app, and say how to deploy it.

Additive by construction, like `portable.py`: this reads the `.msi` that
`tauri build` already produced and builds nothing. An installer is the same file
whether or not anyone runs this afterwards.

Why a Win32 app around the MSI and not the MSI itself as a line-of-business app:
a Win32 app gets dependencies (Tesseract), supersedence (the next version
replaces this one), a custom detection rule if the MSI one ever stops being
enough, and a size limit the installer is nowhere near. Why the MSI and not the
NSIS `-setup.exe`: NSIS installs per user by default, and Intune installs as
SYSTEM, so the app would land in the SYSTEM profile where nobody can launch it.

Three things are refused rather than worked around, because each produces a
package that uploads fine and fails somewhere less visible:

* **A development version.** WiX refuses one anyway, but an `.msi` left in
  `target/` by an earlier release build would be picked up and shipped under a
  number this tree no longer carries.
* **An MSI whose properties disagree with this tree.** `ProductVersion` must be
  the version `scripts/version.py` reads, and `UpgradeCode` must be the one the
  config pins. A different upgrade code makes Windows treat the next version as
  a different product, and every machine ends up with two FreeDocs.
* **A staging folder holding anything but the MSI.** `IntuneWinAppUtil` packs
  the whole folder, so a stray file would be deployed to every machine.

`IntuneWinAppUtil.exe` is Microsoft's and is never fetched here: this project's
scripts do not reach the network to package something. Point at it with
`--tool`, `INTUNEWINAPPUTIL`, or `PATH`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parent

sys.path.insert(0, str(ROOT / "scripts"))

import version as V  # noqa: E402

TAURI_CONF = APP / "src-tauri" / "tauri.conf.json"
TARGET = APP / "src-tauri" / "target"
OUTPUT = APP / "dist-intune"
TRIPLE = "x86_64-pc-windows-msvc"

TOOL_ENV = "INTUNEWINAPPUTIL"

#: Return codes Intune should treat as success. These are Intune's own defaults
#: for a Win32 app and are written out so the settings sheet is complete rather
#: than relying on someone knowing that.
RETURN_CODES = {
    0: "success",
    1707: "success",
    3010: "soft reboot",
    1641: "hard reboot",
    1618: "retry",
}


def conf() -> dict:
    return json.loads(TAURI_CONF.read_text(encoding="utf-8"))


def expected_upgrade_code(config: dict) -> str:
    """The upgrade code this tree's MSI must carry.

    Pinned in `bundle.windows.wix.upgradeCode` since this script landed. Before
    that Tauri derived it as a UUID v5 of `<productName>.exe.app.x64` in the DNS
    namespace, and the pinned value is exactly that derivation — so an MSI built
    from `v0.2.0`, which predates the pin, is the same product to Windows as one
    built today.
    """
    pinned = config.get("bundle", {}).get("windows", {}).get("wix", {}).get("upgradeCode")
    if pinned:
        return str(uuid.UUID(pinned)).upper()
    derived = uuid.uuid5(uuid.NAMESPACE_DNS, f"{config['productName']}.exe.app.x64")
    return str(derived).upper()


def release_version(root: Path = ROOT) -> V.Version:
    """The version of this tree, refused if it is a development one."""
    current = V.current(root)
    if current.dev is not None:
        raise SystemExit(
            f"this tree is {current}, a development version; an Intune package is "
            "built from a release (main, a release branch or a v* tag)"
        )
    return current


def msi_name(config: dict, version: V.Version) -> str:
    return f"{config['productName']}_{version.semver()}_x64_en-US.msi"


def find_msi(name: str, target: Path = TARGET) -> Path:
    """The MSI of exactly this version, wherever `tauri build` put it.

    `--target` puts the bundle under `target/<triple>/` and a plain build under
    `target/`; `docs/building.md` uses the second and CI the first. Matched by
    full name rather than globbed, because `bundle/msi/` keeps every version a
    machine ever built.
    """
    candidates = [
        target / "release" / "bundle" / "msi" / name,
        target / TRIPLE / "release" / "bundle" / "msi" / name,
    ]
    found = [path for path in candidates if path.is_file()]
    if not found:
        listed = "\n  ".join(str(path) for path in candidates)
        raise SystemExit(f"no {name} in either place `tauri build` writes one:\n  {listed}")
    if len(found) > 1:
        # Two builds of one version is the shape `provenance.refuse_duplicates`
        # already refuses: two files, one name, and no way to say which shipped.
        listed = "\n  ".join(str(path) for path in found)
        raise SystemExit(f"{name} exists twice; delete the one you did not mean:\n  {listed}")
    return found[0]


# The Windows Installer automation object is late-bound COM, and PowerShell
# cannot call its methods by name (`OpenDatabase` "does not exist"), so every
# call goes through InvokeMember. Read-only (mode 0) and in its own process,
# so the handle is released before IntuneWinAppUtil opens the same file.
#
# The path arrives in an environment variable, not as an argument: with
# `-Command`, PowerShell joins every argument after the script into the script
# text itself, so `$args[0]` would be empty and a path with a space in it
# would become code.
MSI_ENV = "FREEDOCS_INTUNE_MSI"

_READ_PROPERTIES = r"""
$ErrorActionPreference = 'Stop'
function Invoke-Method($target, $name, $arguments) {
  $target.GetType().InvokeMember($name, 'InvokeMethod', $null, $target, $arguments)
}
function Get-Field($record, $index) {
  $record.GetType().InvokeMember('StringData', 'GetProperty', $null, $record, $index)
}
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = Invoke-Method $installer 'OpenDatabase' @($env:FREEDOCS_INTUNE_MSI, 0)
$view = Invoke-Method $db 'OpenView' @('SELECT Property, Value FROM Property')
Invoke-Method $view 'Execute' $null | Out-Null
while ($true) {
  $record = Invoke-Method $view 'Fetch' $null
  if ($null -eq $record) { break }
  Write-Output ((Get-Field $record 1) + '=' + (Get-Field $record 2))
}
"""


def read_msi_properties(msi: Path) -> dict[str, str]:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _READ_PROPERTIES],
        capture_output=True,
        text=True,
        env={**os.environ, MSI_ENV: str(msi.resolve())},
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"could not read the MSI's Property table:\n{result.stderr.strip()}")
    return parse_properties(result.stdout)


def parse_properties(text: str) -> dict[str, str]:
    properties = {}
    for line in text.splitlines():
        name, sep, value = line.strip().partition("=")
        if sep:
            properties[name] = value
    return properties


def check_properties(properties: dict[str, str], *, version: V.Version, upgrade_code: str) -> None:
    """Refuse an MSI that is not the build this tree describes."""
    problems = []
    for key in ("ProductCode", "ProductVersion", "UpgradeCode"):
        if key not in properties:
            problems.append(f"{key} is missing from the Property table")
    if problems:
        raise SystemExit("not an MSI this script understands:\n  " + "\n  ".join(problems))

    if V.parse(properties["ProductVersion"]) != version:
        problems.append(f"ProductVersion is {properties['ProductVersion']}, this tree is {version}")
    found = properties["UpgradeCode"].strip("{}").upper()
    if found != upgrade_code:
        problems.append(
            f"UpgradeCode is {found}, the config pins {upgrade_code}; Windows would "
            "install it beside the previous version instead of over it"
        )
    if problems:
        raise SystemExit("the MSI does not match this tree:\n  " + "\n  ".join(problems))


def find_tool(explicit: str | None) -> Path:
    for candidate in (explicit, os.environ.get(TOOL_ENV), shutil.which("IntuneWinAppUtil")):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise SystemExit(
        "IntuneWinAppUtil.exe was not found. It is Microsoft's packaging tool "
        "(github.com/microsoft/Microsoft-Win32-Content-Prep-Tool) and is not "
        f"downloaded by this script: pass --tool, set {TOOL_ENV}, or put it on PATH"
    )


def stage(msi: Path, staging: Path) -> Path:
    """A folder holding the MSI and nothing else, because all of it gets packed."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    copied = staging / msi.name
    shutil.copy2(msi, copied)
    return copied


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def settings(config: dict, version: V.Version, msi: Path, properties: dict[str, str]) -> dict:
    """What to type into the Intune portal, in the order it asks.

    Intune reads the product code out of the `.intunewin` and pre-fills the
    uninstall command and the MSI detection rule; they are written here as well
    so the sheet can be checked against what the portal shows.
    """
    product_code = properties["ProductCode"]
    return {
        "name": config["productName"],
        "version": version.semver(),
        "publisher": properties.get("Manufacturer", config["productName"]),
        "description": config["bundle"]["longDescription"],
        "setup_file": msi.name,
        "msi_sha256": sha256(msi),
        "install_command": f'msiexec /i "{msi.name}" /qn /norestart',
        "uninstall_command": f"msiexec /x {product_code} /qn /norestart",
        "install_behavior": "System",
        "device_restart_behavior": "App install may force a device restart",
        "return_codes": {str(code): meaning for code, meaning in RETURN_CODES.items()},
        "requirements": {
            "architecture": "x64",
            # WebView2's own floor. Windows 11 ships the runtime; on Windows 10
            # the MSI installs it, which needs the network at install time.
            "minimum_os": "Windows 10 1809",
        },
        "detection": {
            "rule": "MSI",
            "product_code": product_code,
            "product_version_check": False,
        },
        "upgrade_code": properties["UpgradeCode"],
        "supersedence": "Replace the previous FreeDocs app with 'Uninstall previous version' off; "
        "the MSI's upgrade code already removes it",
        "dependencies": "Optional: Tesseract OCR (UB Mannheim) as its own Win32 app, "
        "only needed for scanned PDFs",
    }


def package(msi: Path, tool: Path, output: Path) -> Path:
    staging = output / "staging"
    staged = stage(msi, staging)
    command = [str(tool), "-c", str(staging), "-s", staged.name, "-o", str(output), "-q"]
    print("$", " ".join(command))
    subprocess.run(command, check=True)
    shutil.rmtree(staging)
    wrapped = output / f"{msi.stem}.intunewin"
    if not wrapped.is_file():
        raise SystemExit(f"IntuneWinAppUtil reported success and wrote no {wrapped.name}")
    return wrapped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--msi", type=Path, help="the .msi to wrap (default: this version's)")
    parser.add_argument("--tool", help="path to IntuneWinAppUtil.exe")
    parser.add_argument("--output", type=Path, default=OUTPUT, help=f"default: {OUTPUT}")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify the MSI against this tree and print the settings; package nothing",
    )
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        raise SystemExit("IntuneWinAppUtil and the MSI automation object are Windows only")

    config = conf()
    version = release_version()
    msi = args.msi or find_msi(msi_name(config, version))
    properties = read_msi_properties(msi)
    check_properties(properties, version=version, upgrade_code=expected_upgrade_code(config))
    sheet = settings(config, version, msi, properties)

    if not args.check_only:
        args.output.mkdir(parents=True, exist_ok=True)
        wrapped = package(msi, find_tool(args.tool), args.output)
        sheet_path = args.output / f"{msi.stem}.intune.json"
        sheet_path.write_text(json.dumps(sheet, indent=2) + "\n", encoding="utf-8")
        print(f"{wrapped} ({wrapped.stat().st_size / 1024 / 1024:.0f} MB)")
        print(f"{sheet_path}")

    print(json.dumps(sheet, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

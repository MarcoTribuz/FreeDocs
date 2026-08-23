"""Assemble the portable bundle: unzip, run, no installer and no network.

Additive by construction. This never edits `tauri.conf.json` and never touches
what the installers produce — it runs its own `tauri build` with
`tauri.portable.conf.json` merged in, which is the only place the 1.2 GB of model
weights are named. An installer built before or after this is byte-for-byte the
build it was.

Three shapes, because the platforms genuinely differ and Tauri 2.11 has no zip or
directory target to hide that behind (`tauri build --help` lists `app` and `dmg`
on macOS and nothing archive-shaped anywhere):

* **macOS** — a `.app` is already relocatable, so this bundles one and archives
  it with `ditto`. Not `zip`: a `.app` contains symlinked frameworks and `zip`
  flattens them into copies, which both doubles the archive and breaks signing
  later.
* **Linux** — an AppImage, which is the platform's portable format. It mounts
  read-only, which is fine: nothing in a portable FreeDocs writes. See the
  `APPIMAGE_EXTRACT_AND_RUN` note in `appimage_env`.
* **Windows** — no bundle at all, then a staging directory assembled by hand,
  because Windows has no equivalent of a relocatable app directory and the NSIS
  and MSI targets both install.

Tesseract language data is deliberately *not* a resource here. The PyInstaller
spec already puts it inside the sidecar, and `formats/pdf.py` now looks there —
so a second copy beside the app would be 143 MB of the same files. The
`FREEDOCS_TESSDATA` hook stays, for a user who drops a `tessdata/` directory in.

Everything is copied explicitly rather than read out of Tauri's release
directory. That layout happens to be right today; an explicit copy is the thing
that can be checked, and the thing that fails loudly when it is wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parent
ENGINE = ROOT / "engine"

TAURI_CONF = APP / "src-tauri" / "tauri.conf.json"
#: Absolute, because `--config` resolves a relative path against the working
#: directory and `tauri build` runs from `app/` while the file lives beside
#: `tauri.conf.json` in `app/src-tauri/`.
PORTABLE_CONF = APP / "src-tauri" / "tauri.portable.conf.json"

SIDECAR = ENGINE / "dist" / "freedocs-engine"
MODEL = ENGINE / "models" / "ner"

OUTPUT = APP / "dist-portable"


def conf() -> dict:
    return json.loads(TAURI_CONF.read_text(encoding="utf-8"))


def target_triple() -> str:
    """The triple this machine builds for.

    Named explicitly rather than left to cargo's default, because it is also half
    the artifact's name and a portable zip that does not say what it runs on is a
    portable zip nobody can file a bug about.
    """
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "aarch64-apple-darwin" if machine in {"arm64", "aarch64"} else "x86_64-apple-darwin"
    if sys.platform == "win32":
        return "x86_64-pc-windows-msvc"
    return "aarch64-unknown-linux-gnu" if machine == "aarch64" else "x86_64-unknown-linux-gnu"


def archive_name() -> str:
    return f"FreeDocs-{conf()['version']}-portable-{target_triple()}"


def require_inputs() -> None:
    """Fail before a ten-minute build rather than during it.

    Both of these are produced by scripts in `engine/packaging/`, and a `tauri
    build` that discovers a missing resource does so after compiling everything.
    """
    executable = "freedocs-engine.exe" if sys.platform == "win32" else "freedocs-engine"
    missing = []
    if not (SIDECAR / executable).is_file():
        missing.append(f"{SIDECAR / executable} (run engine/packaging/build.py)")
    if not (MODEL / "config.json").is_file():
        missing.append(f"{MODEL} (run engine/packaging/model.py)")
    if missing:
        raise SystemExit("missing inputs:\n  " + "\n  ".join(missing))


def appimage_env() -> dict[str, str]:
    """What the AppImage bundler needs on a runner with no FUSE 2.

    The existing failure this addresses is `failed to run linuxdeploy`, with no
    diagnostic of its own, after nine minutes. Tauri downloads `linuxdeploy`,
    which is itself an AppImage and has to mount itself to run — and Ubuntu 22.04
    ships FUSE 3 only, so it cannot.

    `APPIMAGE_EXTRACT_AND_RUN` is the fix that does not depend on the runner
    image: every nested AppImage tool extracts instead of mounting, needing no
    FUSE at all. Installing `libfuse2` also works and is done alongside in CI,
    but a package that has to be present is a thing that can stop being present.

    `NO_STRIP` is not caution. `freedocs-engine.spec` sets `strip=False` because
    "the engine speaks on stdout and must never be stripped of it", and a
    `linuxdeploy` strip pass would undo that decision silently.
    """
    return {
        "APPIMAGE_EXTRACT_AND_RUN": "1",
        "NO_STRIP": "true",
        "ARCH": "x86_64" if "x86_64" in target_triple() else "aarch64",
    }


def tauri_build(*args: str, env: dict[str, str] | None = None) -> None:
    command = [
        "npm",
        "run",
        "--silent",
        "tauri",
        "--",
        "build",
        "--config",
        str(PORTABLE_CONF),
        "--target",
        target_triple(),
        *args,
    ]
    print("$", " ".join(command))
    # CI=true is required on macOS and harmless elsewhere: the .dmg step drives
    # AppleScript to arrange a Finder window, and without Finder automation
    # permission it dies in `AppleEvent timed out (-1712)` after minutes of
    # bundling. Tauri passes --skip-jenkins when CI is set.
    merged = {**os.environ, "CI": "true", **(env or {})}
    subprocess.run(command, cwd=APP, env=merged, check=True)


def bundle_dir() -> Path:
    return APP / "src-tauri" / "target" / target_triple() / "release" / "bundle"


def release_dir() -> Path:
    return APP / "src-tauri" / "target" / target_triple() / "release"


def zip_directory(source: Path, archive: Path, *, arcroot: str) -> Path:
    """Deflate a tree into one archive, preserving the executable bit.

    `shutil.make_archive` would be shorter and loses the mode, which on macOS and
    Linux means an unzipped copy whose engine cannot be executed — a portable
    build that unpacks and does nothing.
    """
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            info = zipfile.ZipInfo(f"{arcroot}/{path.relative_to(source).as_posix()}")
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as handle:
                bundle.writestr(info, handle.read())
    return archive


def build_macos() -> Path:
    tauri_build("--bundles", "app")
    app_bundle = bundle_dir() / "macos" / f"{conf()['productName']}.app"
    if not app_bundle.is_dir():
        raise SystemExit(f"{app_bundle} was not produced")
    archive = OUTPUT / f"{archive_name()}.zip"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    # ditto rather than zipfile: a .app carries symlinked frameworks, and the
    # stdlib writer would either skip them or write the target twice.
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app_bundle), str(archive)],
        check=True,
    )
    return archive


def build_linux() -> Path:
    tauri_build("--bundles", "appimage", "--verbose", env=appimage_env())
    produced = sorted((bundle_dir() / "appimage").glob("*.AppImage"))
    if not produced:
        raise SystemExit(
            "no AppImage was produced; the bundler's own output above is the "
            "diagnostic the earlier attempt at this lacked"
        )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / f"{archive_name()}.AppImage"
    shutil.copy2(produced[0], destination)
    destination.chmod(0o755)
    return destination


def build_windows() -> Path:
    """A staging directory, then a zip. Windows has no relocatable app shape.

    `--no-bundle` because both Windows targets install: NSIS and MSI are
    installers by definition, and there is no third target that is a folder.
    """
    tauri_build("--no-bundle")
    executable = release_dir() / "app.exe"
    if not executable.is_file():
        raise SystemExit(f"{executable} was not produced")

    staging = OUTPUT / archive_name()
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Renamed here because the Cargo package is `app` and there is no [[bin]]
    # section, so only the bundler ever calls it FreeDocs — and `app.exe` on a
    # user's desktop names nothing.
    shutil.copy2(executable, staging / f"{conf()['productName']}.exe")
    shutil.copytree(SIDECAR, staging / "freedocs-engine")
    shutil.copytree(MODEL, staging / "ner-model")

    runtime = APP / "src-tauri" / "webview2"
    if (runtime / "msedgewebview2.exe").is_file():
        shutil.copytree(runtime, staging / "webview2")
    else:
        # Stated, not silent. Without it the window simply never opens on a
        # machine that has no WebView2 runtime, which is the least diagnosable
        # failure this app has.
        print(
            f"warning: no WebView2 runtime at {runtime}; this zip needs one "
            "already installed on the target machine",
            file=sys.stderr,
        )

    return zip_directory(staging, OUTPUT / f"{archive_name()}.zip", arcroot=archive_name())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check-inputs",
        action="store_true",
        help="verify the sidecar and the model are staged, and build nothing",
    )
    args = parser.parse_args(argv)

    require_inputs()
    if args.check_inputs:
        print("inputs are staged")
        return 0

    builders = {"darwin": build_macos, "linux": build_linux, "win32": build_windows}
    builder = builders.get(sys.platform)
    if builder is None:
        raise SystemExit(f"no portable build is defined for {sys.platform}")

    artifact = builder()
    size = artifact.stat().st_size / 1024 / 1024
    print(f"{artifact} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

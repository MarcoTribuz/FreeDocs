"""Stage the Tesseract executable the Windows installers carry.

    python app/packaging/tesseract_windows.py

Writes ``app/src-tauri/tesseract-bin/``, which ``tauri.windows.conf.json`` ships
as the resource directory ``bin/``. That is the path ``portable_env()`` in
``engine.rs`` already looks for, so the app hands the engine
``FREEDOCS_TESSERACT`` and nobody has to install anything for a scanned PDF.

**Why Windows, and only Windows.** On macOS and Linux Tesseract is a platform
package linked against a dozen system libraries; Debian's ``deb.depends`` already
makes apt the installer, and a macOS copy would need every dylib rewritten. The UB
Mannheim build for Windows is the opposite: one directory, ``tesseract.exe`` beside
every DLL it loads, which Windows resolves from the executable's own directory.
So it can be carried as it is, and the per-user install that the window then
failed to find - the bug this started from - stops being a step at all.

**Extracted, never run.** 7-Zip reads the NSIS installer as an archive, so staging
writes no registry key, no uninstaller and no Start-menu entry on the build
machine, and it works on a Mac as well as on the runner. The training tools, the
HTML manuals, the Java viewer and the installer's own ``tessdata`` are left out:
the language data comes from ``engine/packaging/tessdata.py``, pinned, inside the
sidecar.

**Pinned to a file and its hash.** The release asset carries no digest in GitHub's
API, so the hash below was taken from the file fetched on 2026-10-13. A changed
download is a failed build, not a different Tesseract.

Standard library only, plus a ``7z`` executable: ``windows-latest`` has one on
``PATH``, Homebrew's ``p7zip`` is enough on a Mac.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
OUTPUT = APP / "src-tauri" / "tesseract-bin"
CACHE = HERE / ".cache"

VERSION = "5.4.0.20240606"
URL = (
    "https://github.com/UB-Mannheim/tesseract/releases/download/"
    f"v{VERSION}/tesseract-ocr-w64-setup-{VERSION}.exe"
)
SHA256 = "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"

#: The two files whose absence means the staging produced nothing usable. Checked
#: by name because "the directory is not empty" passes for a directory holding
#: only the licence.
REQUIRED = ("tesseract.exe", "libtesseract-5.dll")

NOTICE = f"""\
Tesseract OCR {VERSION}, Windows x64 build by UB Mannheim, carried unmodified.

Source:   {URL}
SHA-256:  {SHA256}
Project:  https://github.com/tesseract-ocr/tesseract (Apache License 2.0, see LICENSE)
Build:    https://github.com/UB-Mannheim/tesseract/wiki

The DLLs beside tesseract.exe are the build's own runtime dependencies (Leptonica,
libarchive, libtiff, libpng, libjpeg, libwebp, ICU, the MinGW runtime and others),
each under its own licence as published by its project; they are redistributed
exactly as the UB Mannheim installer ships them. FreeDocs runs tesseract.exe only
through PyMuPDF, to read scanned pages on this machine.
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def seven_zip() -> str:
    """A 7-Zip that can read NSIS, found the way each platform installs one."""
    for name in ("7z", "7zz"):
        found = shutil.which(name)
        if found:
            return found
    default = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "7-Zip" / "7z.exe"
    if default.is_file():
        return str(default)
    raise SystemExit("no 7z executable found (Windows: 7-Zip; macOS: brew install p7zip)")


def installer(cache: Path = CACHE) -> Path:
    """The pinned installer, from the cache when it is already the right file."""
    target = cache / Path(URL).name
    if target.is_file() and sha256(target) == SHA256:
        return target
    cache.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    print(f"fetching {URL}", flush=True)
    with urllib.request.urlopen(URL, timeout=300) as response:
        partial.write_bytes(response.read())
    actual = sha256(partial)
    if actual != SHA256:
        partial.unlink()
        raise SystemExit(f"{target.name} hashed {actual}, expected {SHA256}; refusing to stage it")
    partial.replace(target)
    return target


def wanted(relative: Path) -> bool:
    """The executable, its DLLs, and the licence files. Nothing else."""
    if len(relative.parts) == 1:
        return relative.name == "tesseract.exe" or relative.suffix.lower() == ".dll"
    return relative.parts[0] == "doc" and relative.name in {"LICENSE", "AUTHORS"}


def stage(source: Path, output: Path = OUTPUT) -> list[str]:
    """Extract ``source`` and copy what :func:`wanted` keeps into ``output``.

    ``output`` is emptied first: a DLL left over from an earlier version would be
    loaded by the new executable, and that is a crash nobody could reproduce.
    """
    with tempfile.TemporaryDirectory() as scratch:
        subprocess.run(
            [seven_zip(), "x", "-y", f"-o{scratch}", str(source)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        root = Path(scratch)
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        kept = []
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if path.is_file() and wanted(relative):
                destination = output / relative.name
                shutil.copy2(path, destination)
                kept.append(relative.name)
    missing = [name for name in REQUIRED if not (output / name).is_file()]
    if missing:
        raise SystemExit(f"the installer did not contain {', '.join(missing)}")
    # Bytes, not text: `write_text` on Windows turns `\n` into CRLF.
    (output / "NOTICE.txt").write_bytes(NOTICE.encode("utf-8"))
    return kept


def smoke(output: Path = OUTPUT) -> None:
    """Run it, where it can run. Proves every DLL it loads made it across."""
    if os.name != "nt":
        print("not on Windows: tesseract.exe was staged and not run")
        return
    result = subprocess.run(
        [str(output / "tesseract.exe"), "--version"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"tesseract.exe --version failed:\n{result.stderr}")
    print(result.stdout.splitlines()[0] if result.stdout else "tesseract.exe ran")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    kept = stage(installer(), args.output)
    smoke(args.output)
    size = sum(path.stat().st_size for path in args.output.iterdir())
    print(f"tesseract {VERSION}: {len(kept)} files, {size / 1e6:.0f} MB in {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - packaging only
    sys.exit(main())

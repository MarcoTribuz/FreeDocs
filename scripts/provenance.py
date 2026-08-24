#!/usr/bin/env python3
"""What was built, and what it is made of.

The installers are unsigned, and that is a decision rather than an oversight: an
Apple Developer ID and a Windows code-signing certificate are both annual bills on
a two-person project. What it leaves is a user with a download and no way to tell
whether it is the file this repository produced. Checksums and an SBOM are what
can be offered instead, and this is where they come from.

The point of generating them *here* rather than in a workflow is that with GitHub
Actions switched off there is no runner to attach them to a release. The artifact
and its manifest are made by the same command on the same machine, so a set that
does not match is a set that never travelled together.

Two things this deliberately does not claim.

**Not reproducibility.** Nothing here says a second build would produce the same
bytes; PyInstaller, cargo and the CycloneDX writers all stamp a timestamp. It
says "this is the file I built and this is what went into it", which is a
different and much weaker promise, and the one that is actually true.

**Not a signature.** A checksum published beside a download proves integrity
against corruption, not against whoever could replace the download. It is worth
having anyway, because the realistic failure is a truncated transfer and a
mirror, not a targeted attacker.

    python3 scripts/provenance.py           # checksums, engine and frontend SBOMs
    python3 scripts/provenance.py --rust    # the shell's SBOM, which needs a tool
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
APP = ROOT / "app"
TAURI = APP / "src-tauri"
#: Gitignored, and shared with nothing: `engine/dist` is PyInstaller's.
OUT = ROOT / "dist"

#: What `tauri build` produces that a person downloads. The `.app` bundle and the
#: `share/` tree are left out because they are directories - a checksum over a
#: directory is a decision about traversal order that nobody wants to depend on.
INSTALLERS = (".dmg", ".deb", ".AppImage", ".msi", ".exe")


def artifacts() -> list[Path]:
    """Every file this repository produces for somebody else to run.

    Both bundle layouts, because `npm run tauri build` writes to
    `target/release/bundle` and the workflow's `--target` writes to
    `target/<triple>/release/bundle`. Missing one of those is how a local run
    would checksum nothing and say so, which is worse than useless on the day it
    matters. Looking in both is also what surfaces the duplicate below.
    """
    found: list[Path] = []
    for bundle in (TAURI / "target").glob("**/release/bundle"):
        found += [
            path
            for path in bundle.rglob("*")
            if path.is_file() and path.suffix in INSTALLERS and not _scratch(path)
        ]
    portable = APP / "dist-portable"
    if portable.is_dir():
        found += [
            path
            for path in portable.iterdir()
            if path.is_file() and path.suffix in (".zip", ".AppImage")
        ]
    return sorted(set(found))


def _scratch(path: Path) -> bool:
    """`hdiutil`'s shadow files, which look exactly like the artifact.

    Building a `.dmg` leaves `rw.<pid>.<name>.dmg` in `bundle/macos/` beside the
    `.app` when the run is interrupted - and the run *is* routinely interrupted
    here, because the `.dmg` step hangs on Finder automation without `CI=true`.
    They are a partially written copy of the thing being checksummed, so
    publishing one is publishing a hash nobody can reproduce.
    """
    return path.name.startswith("rw.")


def refuse_duplicates(paths: list[Path]) -> None:
    """Two files, one name, two hashes: refuse rather than write both lines.

    Found by running this for the first time on a working checkout. A plain
    `tauri build` and a `--target aarch64-apple-darwin` one produce
    `FreeDocs_0.1.0_aarch64.dmg` in two different trees, so a stale one sits
    beside the fresh one and the manifest gets two entries for one download.
    Checked rather than resolved by mtime: "the newer one is the real one" is a
    guess, and this file exists so nobody has to guess.
    """
    seen: dict[str, Path] = {}
    for path in paths:
        first = seen.get(path.name)
        if first is not None:
            raise SystemExit(
                f"two files would be published as {path.name}:\n"
                f"  {first.relative_to(ROOT)}\n  {path.relative_to(ROOT)}\n"
                "one of them is from an older build; delete the stale target tree "
                "and run the build again"
            )
        seen[path.name] = path


def checksums(paths: list[Path]) -> str:
    """`sha256sum -c` format, keyed on the file's own name.

    The basename rather than a path relative to this checkout, because the person
    checking has a download directory and not a checkout. Names are unique across
    platforms - the target triple is in every one of them - so flattening them
    loses nothing.
    """
    lines = []
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        lines.append(f"{digest.hexdigest()}  {path.name}")
    return "\n".join(lines) + "\n"


def _toolchain_path() -> dict[str, str]:
    """Put the Rust toolchain's directory on PATH, not just its binary in a command.

    `cargo cyclonedx` shells out to `rustc` **by bare name** to record the target
    platform, so handing this an absolute path to the tool satisfies the tool and
    not what the tool runs. It panics with `Failed to invoke rustc! Is it in your
    $PATH?` from a non-interactive shell, where `~/.cargo/bin` routinely is not.

    Third time this exact shape has come up here: `scripts/ci.py`'s
    `cargo_path_env` for `cargo metadata`, and `FREEDOCS_TESSERACT` in the engine
    for PyMuPDF shelling out to Tesseract.
    """
    binary = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo")
    directory = str(Path(binary).parent)
    current = os.environ.get("PATH", "")
    if directory in current.split(os.pathsep):
        return {}
    return {"PATH": directory + os.pathsep + current}


def _capture(cmd: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **_toolchain_path()}
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        raise SystemExit(f"{cmd[0]} failed: {' '.join(cmd)}")
    return completed.stdout


def engine_sbom() -> str:
    """The Python environment the sidecar was frozen from.

    The *environment*, not the lockfile, and the difference matters here in the
    opposite direction from the audit step: PyInstaller freezes what is installed,
    so the environment is what the bundle contains. `scripts/ci.py build` installs
    the `ner` extra first, which is what makes this the shipped set rather than a
    subset of it.
    """
    return _capture(
        ["uv", "run", "--with", "cyclonedx-bom", "cyclonedx-py", "environment"], ENGINE
    )


def frontend_sbom() -> str:
    """Every JavaScript dependency, dev ones included, and that is not a mistake.

    Nothing in `node_modules` ships as a file - `adapter-static` builds an SPA and
    the webview serves it - but Svelte's runtime and everything else the bundler
    inlined *is* in that SPA. A production-only SBOM of this app is an empty
    document that would read as "no JavaScript dependencies", which is the
    opposite of true. `npm audit --omit=dev` asks a different question and is
    right to.
    """
    return _capture(["npm", "sbom", "--sbom-format", "cyclonedx"], APP)


def rust_sbom() -> str:
    """The shell's crate tree. Needs `cargo cyclonedx`, which is a separate tool.

    Written to a file beside `Cargo.toml` by the tool rather than to stdout, so it
    is read back and removed here: there is no flag that makes it print. The name
    is `<override>.<format>`, which is `sbom.json` and not the `sbom.cdx.json`
    the extension elsewhere in this file would suggest - checked rather than
    assumed, because a wrong guess here is an SBOM silently left in the checkout.
    """
    binary = shutil.which("cargo-cyclonedx") or str(Path.home() / ".cargo/bin/cargo-cyclonedx")
    _capture([binary, "cyclonedx", "--format", "json", "--override-filename", "sbom"], TAURI)
    produced = TAURI / "sbom.json"
    if not produced.is_file():
        raise SystemExit(f"cargo cyclonedx reported success and wrote no {produced.name}")
    text = produced.read_text(encoding="utf-8")
    produced.unlink()
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provenance.py", description=__doc__)
    parser.add_argument(
        "--rust",
        action="store_true",
        help="write the shell's SBOM instead. Separate because it needs a tool "
        "that is not installed by default, which `scripts/ci.py` reports as a "
        "skip rather than swallowing.",
    )
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.rust:
        (OUT / "sbom-shell.cdx.json").write_text(rust_sbom(), encoding="utf-8")
        print(f"written: {(OUT / 'sbom-shell.cdx.json').relative_to(ROOT)}")
        return 0

    built = artifacts()
    if not built:
        # Loudly, rather than writing an empty SHA256SUMS. A manifest of nothing
        # is indistinguishable from a manifest of a build that produced nothing,
        # and it is the second one that gets published by accident.
        raise SystemExit(
            "no installers or portable bundles found; run `scripts/ci.py build` first"
        )

    refuse_duplicates(built)
    (OUT / "SHA256SUMS").write_text(checksums(built), encoding="utf-8")
    (OUT / "sbom-engine.cdx.json").write_text(engine_sbom(), encoding="utf-8")
    (OUT / "sbom-frontend.cdx.json").write_text(frontend_sbom(), encoding="utf-8")

    for path in built:
        print(f"  {path.relative_to(ROOT)}")
    print(f"written: {OUT.relative_to(ROOT)}/SHA256SUMS and two SBOMs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

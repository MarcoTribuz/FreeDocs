"""Build the engine sidecar for the platform this runs on.

PyInstaller does not cross-compile, so each platform builds its own. That is why
this is a script rather than a note in a README: the same command has to work on
a developer's Mac and on three CI runners.

    uv run --extra dev --extra pdf --extra ooxml --extra ner \
        python packaging/build.py

The result is ``engine/dist/freedocs-engine/``, which ``tauri.conf.json`` ships as
a resource directory. Building it is not required for ``tauri dev``: the Rust side
falls back to the virtualenv, so the app runs before the bundle exists.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
SPEC = HERE / "freedocs-engine.spec"
OUTPUT = ENGINE / "dist" / "freedocs-engine"

#: A sentence with a name in it. Detecting the name is the only thing that proves
#: the model stack made it into the bundle: `capabilities` reports the NER layer as
#: present without ever importing it, because the backend loads its model on first
#: use. A bundle that passes capabilities and fails this is exactly what shipped
#: the first time this script was written.
SMOKE_TEXT = "Il cliente Mario Rossi ha firmato il contratto.\n"


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("$", " ".join(command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def build() -> Path:
    if not SPEC.is_file():  # pragma: no cover - packaging only
        raise SystemExit(f"missing spec file: {SPEC}")
    # A stale build is worse than no build: PyInstaller happily reuses an old
    # collected directory and the result is a bundle nobody can reason about.
    for stale in (ENGINE / "build", ENGINE / "dist"):
        shutil.rmtree(stale, ignore_errors=True)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            # Stated explicitly rather than left to the working directory:
            # tauri.conf.json refers to engine/dist by path, and a build that
            # lands anywhere else fails much later with a confusing message.
            "--distpath",
            str(ENGINE / "dist"),
            "--workpath",
            str(ENGINE / "build"),
            str(SPEC),
        ],
        cwd=ENGINE,
    )
    if not OUTPUT.is_dir():  # pragma: no cover - packaging only
        raise SystemExit(f"PyInstaller produced no {OUTPUT}")
    return OUTPUT


def smoke_test(bundle: Path) -> None:
    """Run the built binary and ask it what it can do.

    Every format handler and detector backend in this engine is imported lazily,
    so a missing hidden import produces a binary that works right up until the
    user opens that format. Asking `capabilities` exercises the registry and the
    handler list, which is where such an omission shows up.
    """
    executable = bundle / ("freedocs-engine.exe" if sys.platform == "win32" else "freedocs-engine")
    if not executable.is_file():  # pragma: no cover - packaging only
        raise SystemExit(f"no executable at {executable}")

    import json
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        sample = Path(scratch) / "campione.txt"
        sample.write_text(SMOKE_TEXT, encoding="utf-8")
        requests = "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "capabilities"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "inspect",
                        "params": {"path": str(sample)},
                    }
                ),
            ]
        )
        completed = subprocess.run(
            [str(executable)],
            input=requests + "\n",
            capture_output=True,
            text=True,
            # Generous: the first model load in a fresh bundle is slow, and a
            # timeout here reads as a broken build rather than a slow one.
            timeout=900,
        )
    if completed.returncode != 0:  # pragma: no cover - packaging only
        raise SystemExit(
            f"the built engine exited {completed.returncode}\n{completed.stderr[-2000:]}"
        )

    formats: set[str] = set()
    entities: set[str] = set()
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get("error"):  # pragma: no cover - packaging only
            raise SystemExit(f"the built engine returned an error: {message['error']}")
        payload = message.get("params") or message.get("result") or {}
        formats.update(payload.get("formats") or [])
        entities.update(finding["entity"] for finding in payload.get("findings") or [])

    expected = {".pdf", ".docx", ".xlsx", ".pptx", ".txt"}
    missing = expected - formats
    if missing:  # pragma: no cover - packaging only
        raise SystemExit(
            f"the built engine does not support {sorted(missing)}; a hidden import "
            "is probably missing from freedocs-engine.spec"
        )
    if "PERSON" not in entities:  # pragma: no cover - packaging only
        raise SystemExit(
            "the built engine did not find the name in the smoke sample, so the NER "
            "model stack is missing from the bundle. Its imports happen at call time "
            "and PyInstaller cannot see them; check the collect_submodules block in "
            "freedocs-engine.spec."
        )
    print(f"smoke test passed: {len(formats)} formats, and the model found the name")


def report_size(bundle: Path) -> None:
    total = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
    print(f"bundle: {bundle} ({total / 1e6:.0f} MB)")
    print(
        "note: the NER model (~1.2 GB) and Tesseract language data are NOT in here. "
        "They are fetched or installed separately, and the engine reports their "
        "absence through `capabilities` so the app can say so."
    )


if __name__ == "__main__":  # pragma: no cover - packaging only
    built = build()
    smoke_test(built)
    report_size(built)

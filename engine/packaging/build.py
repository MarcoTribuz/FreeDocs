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

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
SPEC = HERE / "freedocs-engine.spec"
OUTPUT = ENGINE / "dist" / "freedocs-engine"

#: A sentence with a name and a foreign VAT number in it, and both halves have to
#: be found.
#:
#: The name proves the model stack made it into the bundle: `capabilities` reports
#: the NER layer as present without ever importing it, because the backend loads
#: its model on first use, and a bundle that passes capabilities and fails this is
#: exactly what shipped the first time this script was written.
#:
#: The VAT number proves the country rule set did too. `stdnum` keeps one module
#: per country and imports them by name at call time, so PyInstaller sees none of
#: them and a missing `collect_submodules` produces a bundle that finds Swiss
#: numbers and silently finds nothing from anywhere else. The French TVA is the
#: one to test with: it accepts 0.12% of random values of its shape, so this
#: cannot pass by luck.
SMOKE_NAME = "Mario Rossi"
#: A string no detector finds, so only the term list can remove it.
SMOKE_TERM = "Progetto Aurora"
SMOKE_TEXT = (
    f"Il cliente {SMOKE_NAME} ha firmato il contratto.\n"
    "Numero de TVA du fournisseur: FR40303265045.\n"
    f"Riferimento interno: {SMOKE_TERM}.\n"
)

#: Used once, inside a temporary directory, to prove the cipher is in the bundle.
#: A constant rather than a random string so a failing build is reproducible by
#: hand, and it protects nothing: the file it opens is deleted seconds later.
SMOKE_PASSPHRASE = "smoke test passphrase"


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

    The key file is exercised the same way and for the same reason. `capabilities`
    reports `mapping_available` from `find_spec`, which is true of a bundle whose
    cipher never made it in - so a scrub writes a key file, a restore reads it
    back, and the value has to arrive. Asking the capability alone is precisely
    the mistake this whole function was rewritten to stop making.

    The term list is sealed with the same cipher and gets the same treatment:
    created, saved through an update that re-opens it from disk, and then used
    by an inspect that has to come back with the list's own finding.
    """
    executable = bundle / ("freedocs-engine.exe" if sys.platform == "win32" else "freedocs-engine")
    if not executable.is_file():  # pragma: no cover - packaging only
        raise SystemExit(f"no executable at {executable}")

    import json
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        sample = Path(scratch) / "campione.txt"
        sample.write_text(SMOKE_TEXT, encoding="utf-8")
        clean = Path(scratch) / "clean"
        keys = Path(scratch) / "keys"
        back = Path(scratch) / "back"
        terms = Path(scratch) / "firm.fdterms"
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
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "scrub",
                        "params": {
                            "paths": [str(sample)],
                            "output_dir": str(clean),
                            "map": str(keys),
                            "map_passphrase": SMOKE_PASSPHRASE,
                        },
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "restore",
                        "params": {
                            "path": str(clean / sample.name),
                            "map": str(keys / (sample.stem + ".fdmap")),
                            "passphrase": SMOKE_PASSPHRASE,
                            "output_dir": str(back),
                        },
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "terms_create",
                        "params": {"path": str(terms), "passphrase": SMOKE_PASSPHRASE},
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "terms_update",
                        "params": {"add": [SMOKE_TERM], "passphrase": SMOKE_PASSPHRASE},
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "inspect",
                        "params": {"path": str(sample), "use_terms": True},
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
        # Read while the scratch directory still exists. The assertion is below
        # with the others, but the evidence only lives inside this block.
        restored_text = ""
        restored_file = back / sample.name
        if restored_file.is_file():
            restored_text = restored_file.read_text(encoding="utf-8")
    if completed.returncode != 0:  # pragma: no cover - packaging only
        raise SystemExit(
            f"the built engine exited {completed.returncode}\n{completed.stderr[-2000:]}"
        )

    formats: set[str] = set()
    entities: set[str] = set()
    term_findings: set[str] = set()
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get("error"):  # pragma: no cover - packaging only
            raise SystemExit(f"the built engine returned an error: {message['error']}")
        payload = message.get("params") or message.get("result") or {}
        formats.update(payload.get("formats") or [])
        entities.update(finding["entity"] for finding in payload.get("findings") or [])
        term_findings.update(
            finding["text"]
            for finding in payload.get("findings") or []
            if finding.get("detector") == "terms"
        )

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
    if "VAT_ID" not in entities:  # pragma: no cover - packaging only
        raise SystemExit(
            "the built engine did not find the French VAT number in the smoke "
            "sample, so the per-country stdnum modules are missing from the bundle. "
            "stdnum imports them by name at call time; check the collect_submodules "
            "block in freedocs-engine.spec."
        )
    if SMOKE_NAME not in restored_text:  # pragma: no cover - packaging only
        raise SystemExit(
            "the built engine wrote a key file it could not use: the restored "
            "document does not contain the name that was removed. The cipher is "
            "imported at call time and PyInstaller cannot see it; check the "
            'collect_submodules("cryptography") block in freedocs-engine.spec.'
        )
    if SMOKE_TERM not in term_findings:  # pragma: no cover - packaging only
        raise SystemExit(
            "the built engine did not remove the term list's entry: a term list was "
            "created and saved but could not be used. It is sealed with the key "
            "file's cipher; check freedocs-engine.spec."
        )
    print(
        f"smoke test passed: {len(formats)} formats, the model found the name, the "
        "checksum layer found the foreign VAT number, a key file round-tripped, and "
        "a term list was sealed, reopened and applied"
    )


def check_tessdata(bundle: Path) -> None:
    """Every OCR language the engine asks for is inside the bundle, or say so.

    The spec bundles whatever ``engine/models/tessdata`` holds and nothing when it
    is empty, which keeps a fresh clone buildable - and is also how every CI
    installer shipped with no language data while the documentation said nine.
    ``FREEDOCS_REQUIRE_TESSDATA`` turns the warning into a failure; ``app.yml``
    sets it, after ``packaging/tessdata.py`` has filled the directory.
    """
    from freedocs.formats.pdf import DEFAULT_OCR_LANGUAGE

    present = {path.stem for path in bundle.rglob("tessdata/*.traineddata")}
    missing = sorted(set(DEFAULT_OCR_LANGUAGE.split("+")) - present)
    if not missing:
        print(f"tessdata: all {len(present)} languages inside the bundle")
        return
    message = (
        f"the bundle carries no language data for {', '.join(missing)}; "
        "run `python packaging/tessdata.py` before building"
    )
    if os.environ.get("FREEDOCS_REQUIRE_TESSDATA"):
        raise SystemExit(message)
    print(f"warning: {message}")


def report_size(bundle: Path) -> None:
    total = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
    print(f"bundle: {bundle} ({total / 1e6:.0f} MB)")
    print(
        "note: the NER model (~1.2 GB) is NOT in here; it is fetched on first use, "
        "and the engine reports its absence through `capabilities`."
    )


if __name__ == "__main__":  # pragma: no cover - packaging only
    built = build()
    smoke_test(built)
    check_tessdata(built)
    report_size(built)

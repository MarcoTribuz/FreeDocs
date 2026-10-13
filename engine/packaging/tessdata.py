"""Put the OCR language data a bundle ships into ``engine/models/tessdata``, verified.

``freedocs-engine.spec`` bundles whatever ``.traineddata`` that directory holds and
bundles nothing when it is empty, which is right for a fresh clone and was wrong
for every installer CI ever produced: no workflow filled the directory, so each
one shipped no language data at all while ``docs/intune.md`` said it carried
nine. Tesseract then read scans with whatever its own installer had added -
English, on a default Windows install - and a value OCR misreads fails its
checksum and survives. This script is what fills the directory.

    python packaging/tessdata.py           # fetch what is missing or wrong
    python packaging/tessdata.py --check   # say so, touch nothing, no network

**Pinned to a commit and to a hash per file.** ``main`` of ``tesseract-ocr/tessdata``
has not moved since 2024, but a build reading ``main`` is a build whose content
someone else decides, and the hash is what makes a swapped file a failed build
rather than a shipped one. The hashes were taken from files fetched at that commit,
not copied from anywhere.

**A file already present with the wrong hash is replaced, not trusted.** A
developer's directory can hold a ``tessdata_best`` or a Homebrew copy under the
same name - this one did, for ``eng`` and ``osd`` - and a bundle built from it is
a bundle nobody else can reproduce.

Standard library only: it runs in CI before the engine is installed, like
``model.py`` and ``scripts/provenance.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
TESSDATA = ENGINE / "models" / "tessdata"

SOURCE = "https://github.com/tesseract-ocr/tessdata"
COMMIT = "ced78752cc61322fb554c280d13360b35b8684e4"

#: One file per language in ``pdf.DEFAULT_OCR_LANGUAGE``, plus ``osd``, which
#: Tesseract consults for orientation. ``test_tessdata.py`` holds the two lists
#: together, so a language added to the engine without a file here fails a test
#: instead of shipping a bundle that cannot read it. 169 MB in all.
PINNED: dict[str, str] = {
    "deu": "896b3b4956503ab9daa10285db330881b2d74b70d889b79262cc534b9ec699a4",
    "eng": "daa0c97d651c19fba3b25e81317cd697e9908c8208090c94c3905381c23fc047",
    "fra": "eac01c1d72540d6090facb7b2f42dd0a2ee8fc57c5be1b20548ae668e2761913",
    "ita": "4f7476c611312beb8f8e182888da08ea642d9824ae4402cc6235f61ab1406406",
    "nld": "b1f6767f50daf5903802fb970e7b9f64ee1f12be0b2b324dfdf8e8b05771572f",
    "osd": "e19f2ae860792fdf372cf48d8ce70ae5da3c4052962fe22e9de1f680c374bb0e",
    "pol": "179e91afb3232949288a4e186de44eb0beffb6a295283bebf4af35a36b380b3c",
    "por": "016c6a371bb1e4c48fe521908cf3ba3d751fade0ab846ad5d4086b563f5c528c",
    "spa": "0b0fcbb4665189e01ab8019e591f014dd7260460de072543edd4b2cb4ede7c96",
    "swe": "24e2dd15cc0088d211c5f1bd49971e600317f201502deadbc417f0ffd6c9a6f8",
}


def url_for(name: str) -> str:
    return f"{SOURCE}/raw/{COMMIT}/{name}.traineddata"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stale(directory: Path = TESSDATA) -> list[str]:
    """Every pinned language that is absent or does not hash to its pin."""
    return [
        name
        for name, expected in PINNED.items()
        if not (directory / f"{name}.traineddata").is_file()
        or sha256(directory / f"{name}.traineddata") != expected
    ]


def fetch(name: str, directory: Path = TESSDATA) -> None:
    """Download one file beside its destination, verify it, then move it in.

    Written to a ``.part`` first so an interrupted download never leaves a
    truncated ``.traineddata`` under the real name - which ``tessdata_path()``
    would count, because it counts any file with that suffix.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.traineddata"
    partial = target.with_suffix(".part")
    print(f"fetching {name}.traineddata", flush=True)
    with urllib.request.urlopen(url_for(name), timeout=120) as response:
        partial.write_bytes(response.read())
    actual = sha256(partial)
    if actual != PINNED[name]:
        partial.unlink()
        raise SystemExit(
            f"{name}.traineddata from {COMMIT[:12]} hashed {actual}, expected {PINNED[name]}; "
            "refusing to bundle it"
        )
    partial.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify only; no network")
    parser.add_argument("--directory", type=Path, default=TESSDATA)
    args = parser.parse_args(argv)

    wrong = stale(args.directory)
    if args.check:
        for name in wrong:
            print(f"missing or not the pinned file: {name}.traineddata")
        return 1 if wrong else 0
    for name in wrong:
        fetch(name, args.directory)
    print(f"tessdata: {len(PINNED)} languages at {COMMIT[:12]} in {args.directory}")
    return 0


if __name__ == "__main__":  # pragma: no cover - packaging only
    sys.exit(main())

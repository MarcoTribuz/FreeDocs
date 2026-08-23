"""What a bundled NER model directory must contain, and how to check it.

Written by ``packaging/model.py`` and read by :mod:`freedocs.diagnostics`, which
is why it lives here rather than in either: a manifest whose format is defined in
the script that writes it is a format the reader can only guess at, and the point
of the file is to catch a payload that is not what it claims to be.

The failure this guards is specific. A portable build carries the weights, so the
weights can be *incomplete* in a way a downloaded copy cannot — a stick pulled
mid-write, an unzip that ran out of disk, a partial network copy. Without a check
the first symptom is a document that fails deep inside ``from_pretrained``, and
the second is a user concluding the tool is broken rather than the copy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

#: Written beside the weights.
MANIFEST_NAME = "manifest.json"

#: The five files ``GLiNER2.from_pretrained`` actually opens — see its
#: ``download_or_local``. A copy missing any of them is not a model, and naming
#: them here is what turns "the first document failed" into "the payload is
#: incomplete".
#:
#: The repository also holds ``README.md`` and ``.gitattributes``. Those are
#: carried when present and are not required, because the cache route only ever
#: fetched what the loader asked for.
REQUIRED_FILES = (
    "config.json",
    "encoder_config/config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
)

#: 8 MiB blocks. ``model.safetensors`` is 1.2 GB and reading it whole to hash it
#: would allocate that much to no purpose.
_HASH_BLOCK = 8 * 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def verify(directory: Path, *, repo: str, hashes: bool = False) -> list[str]:
    """What is wrong with the payload, as sentences, or an empty list.

    Sizes by default and hashes only when asked. Hashing 1.2 GB catches exactly
    one thing a size check does not — bytes that changed without the length
    changing — and paying seconds of I/O for that on every call would make this
    too slow for ``doctor``, which is the caller that matters. The build checks
    hashes once, where seconds are free.

    Returns rather than raises. This is a diagnostic, and a health check that
    throws is a health check nobody can call twice.
    """
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"{manifest_path} is missing, so the payload cannot be checked"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{manifest_path} is unreadable: {exc}"]

    problems: list[str] = []
    recorded_repo = manifest.get("repo")
    if recorded_repo != repo:
        problems.append(f"the payload is {recorded_repo!r} but this build expects {repo!r}")

    recorded = manifest.get("files") or {}
    for name in REQUIRED_FILES:
        if name not in recorded:
            problems.append(f"{name} is not in the manifest")

    for name, expected in sorted(recorded.items()):
        path = directory / name
        if not path.is_file():
            problems.append(f"{name} is missing")
            continue
        actual = path.stat().st_size
        if actual != expected.get("size"):
            problems.append(f"{name} is {actual} bytes, expected {expected.get('size')}")
            continue
        if hashes and sha256_of(path) != expected.get("sha256"):
            problems.append(f"{name} does not match its recorded SHA-256")
    return problems


def manifest_for(directory: Path, names: list[str], *, repo: str) -> dict:
    return {
        "repo": repo,
        "files": {
            name: {
                "size": (directory / name).stat().st_size,
                "sha256": sha256_of(directory / name),
            }
            for name in sorted(names)
        },
    }

"""Materialise the NER model as a flat directory a portable build can carry.

The installers download the weights on first use and that stays true. This script
exists for the portable bundle, which must work with the network off, and it
produces something the Hugging Face cache is not: a directory of **real files**.

Two reasons it cannot simply be the cache. First, ``snapshots/<rev>/`` is entirely
symlinks into ``blobs/``, and neither ``actions/upload-artifact`` nor a Windows zip
preserves a symlink — one drops them, the other either fails or silently writes the
1.2 GB blob twice. Second, the cache is keyed by revision and shaped for
``hf_hub_download``; a bundle wants a path it can hand straight to
``GLiNER2.from_pretrained``, which accepts a local directory (see
``download_or_local`` in ``gliner2/model.py``).

Sources, in order:

1. The local Hugging Face cache, dereferenced. In CI the weights are already on
   the runner by the time this runs, because the sidecar smoke test in
   ``build.py`` loads the model — so this costs no second download and, more to
   the point, needs no change to that step.
2. ``snapshot_download``, for a machine that has never run the engine.

Attribution is written here rather than by hand because it applies to what this
script produces: the model is Apache 2.0, which obliges a copy of the licence and
a notice of what was taken, and a NOTICE maintained separately from the payload is
a NOTICE that stops describing it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent

# Importable without installing the engine: this script runs in CI before any
# `uv run` of the package itself, and the pin belongs to the backend either way.
sys.path.insert(0, str(ENGINE))

from freedocs.core.model_manifest import (  # noqa: E402
    MANIFEST_NAME,
    REQUIRED_FILES,
    manifest_for,
    verify,
)
from freedocs.detect.backends.gliner_backend import DEFAULT_MODEL  # noqa: E402

#: Where a portable build's `ner-model` resource is staged from. Gitignored via
#: the `engine/models/` rule, which exists because models are never committed.
OUTPUT = ENGINE / "models" / "ner"

_NOTICE = """\
This directory contains third-party model weights redistributed with FreeDocs.

    {repo}

Licensed under the Apache License, Version 2.0. The full licence text is in
LICENSE-Apache-2.0.txt beside this file, and at:

    https://www.apache.org/licenses/LICENSE-2.0

The weights are a fine-tune of GLiNER2 on an mdeberta-v3-base encoder, which is
what lets one model read Italian, German, French and English without being told
which. FreeDocs itself is AGPL-3.0; Apache-2.0 permits this redistribution, and
this file is the attribution it asks for in return.

Nothing here was modified. The files are byte-for-byte what the Hugging Face
repository above serves, and manifest.json records the size and SHA-256 of each
one so a truncated copy is caught before a document is.
"""


def _cached_snapshot() -> Path | None:
    """The newest local snapshot of the pinned model, or None.

    Uses ``huggingface_hub``'s own idea of where the cache is rather than
    hard-coding ``~/.cache/huggingface``: a machine with ``HF_HOME`` set has one
    somewhere else, and guessing would silently download 1.2 GB it already has.
    """
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return None
    root = Path(HF_HUB_CACHE) / f"models--{DEFAULT_MODEL.replace('/', '--')}" / "snapshots"
    if not root.is_dir():
        return None
    snapshots = sorted((entry for entry in root.iterdir() if entry.is_dir()), key=lambda p: p.name)
    for snapshot in reversed(snapshots):
        if all((snapshot / name).exists() for name in REQUIRED_FILES):
            return snapshot
    return None


def _copy_dereferenced(source: Path, destination: Path) -> list[str]:
    """Copy a tree, following every symlink, and report what landed.

    ``shutil.copytree(symlinks=False)`` would do it, but it also refuses a
    destination that exists and gives no list back — and the list is what the
    manifest is built from.
    """
    copied: list[str] = []
    for entry in sorted(source.rglob("*")):
        if entry.is_dir():
            continue
        relative = entry.relative_to(source).as_posix()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # copyfile, not copy2: the cache's mtimes are download times and carrying
        # them over makes a fresh payload look stale to anything comparing dates.
        shutil.copyfile(entry, target, follow_symlinks=True)
        copied.append(relative)
    return copied


def _download(destination: Path) -> list[str]:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "huggingface_hub is required to fetch the model; install the 'ner' extra"
        ) from exc
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(DEFAULT_MODEL, local_dir=str(destination))
    # `local_dir` materialises real files, but it also leaves a `.cache/`
    # bookkeeping directory behind that has no business in a shipped payload.
    bookkeeping = destination / ".cache"
    if bookkeeping.is_dir():
        shutil.rmtree(bookkeeping)
    return [
        entry.relative_to(destination).as_posix()
        for entry in sorted(destination.rglob("*"))
        if entry.is_file() and entry.name != MANIFEST_NAME
    ]


def check(destination: Path = OUTPUT, *, hashes: bool = False) -> list[str]:
    """Thin wrapper so the script and ``doctor`` ask the same question."""
    return verify(destination, repo=DEFAULT_MODEL, hashes=hashes)


def _write_attribution(destination: Path) -> None:
    shutil.copyfile(HERE / "licences" / "Apache-2.0.txt", destination / "LICENSE-Apache-2.0.txt")
    (destination / "NOTICE.txt").write_text(_NOTICE.format(repo=DEFAULT_MODEL), encoding="utf-8")


def materialise(destination: Path = OUTPUT, *, force: bool = False) -> Path:
    if not force and not check(destination):
        print(f"{destination} is already complete")
        return destination

    snapshot = _cached_snapshot()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    if snapshot is not None:
        print(f"copying {DEFAULT_MODEL} from {snapshot}")
        names = _copy_dereferenced(snapshot, destination)
    else:
        print(f"downloading {DEFAULT_MODEL} (about 1.25 GB)")
        names = _download(destination)

    _write_attribution(destination)
    names = [name for name in names if name not in {"LICENSE-Apache-2.0.txt", "NOTICE.txt"}]
    manifest = manifest_for(destination, names, repo=DEFAULT_MODEL)
    (destination / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    remaining = check(destination)
    if remaining:
        raise SystemExit("the payload is incomplete:\n  " + "\n  ".join(remaining))

    total = sum(entry["size"] for entry in manifest["files"].values())
    print(f"{len(manifest['files'])} files, {total / 1024 / 1024:.0f} MB, in {destination}")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report on the existing payload and write nothing",
    )
    parser.add_argument(
        "--hashes",
        action="store_true",
        help="with --check, also verify SHA-256 rather than sizes alone",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even when the payload already verifies",
    )
    args = parser.parse_args(argv)

    if args.check:
        problems = check(hashes=args.hashes)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0

    materialise(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

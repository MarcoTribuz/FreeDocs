#!/usr/bin/env python3
"""Attach `SHA256SUMS` and the SBOMs to a GitHub release.

`provenance.py` runs once per platform job, so each job has a third of the
picture: its own installers' hashes and its own SBOMs. Those went up as workflow
artifacts and nowhere else, so from v1.4.1 the release page carried installers
and nothing a person could check them against. v1.0.2 to v1.2.0 had both only
because they were attached by hand. This is the step that was missing, run by
`app.yml` once every platform has uploaded, and by hand to repair a release.

The published `SHA256SUMS` is built from the digests GitHub computed on the
release's own assets, and every hash a build job recorded must agree with one of
them. Two sources, compared, for two reasons:

- the release holds files no build manifest names - `tauri-action` uploads the
  `.app.tar.gz` it makes for the updater, which `provenance.py` never sees - so
  the build manifests alone would leave a download without a line;
- a server digest alone would hash whatever was uploaded, which is the thing
  being vouched for. Agreement with the build side is what says the asset on the
  page is the file the runner produced.

A disagreement or a missing digest is a refusal, never a partial manifest: a
`SHA256SUMS` that silently omits a download reads as covering it.

    python3 scripts/publish_provenance.py --tag v1.4.1 --artifacts DIR [--dry-run]

``DIR`` holds one `freedocs-provenance-<target>/` per platform, as
`gh run download <run> -p 'freedocs-provenance-*'` lays them out.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "MarcoTribuz/FreeDocs"
PREFIX = "freedocs-provenance-"

# The asset names v1.0.2 to v1.2.0 were published under. A reader's link to
# `sbom-engine-windows-x64.cdx.json` keeps meaning the same thing.
PLATFORMS = {
    "aarch64-apple-darwin": "macos-arm64",
    "x86_64-unknown-linux-gnu": "linux-x64",
    "x86_64-pc-windows-msvc": "windows-x64",
}

# What this script publishes, so a re-run does not checksum its own output.
OWN = ("SHA256SUMS",)
OWN_PREFIX = "sbom-"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def find_release(repo: str, tag: str) -> dict:
    """By listing, because `releases/tags/<tag>` does not answer for a draft,
    and `tauri-action` creates the release as one."""
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases"))
    for release in (r for page in pages for r in page):
        if release["tag_name"] == tag:
            return release
    raise SystemExit(f"no release (draft or published) for tag {tag} in {repo}")


def read_manifest(text: str, source: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        if len(digest) != 64 or not name:
            raise SystemExit(f"{source}: not a sha256sum line: {line!r}")
        hashes[name] = digest
    return hashes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--dry-run", action="store_true", help="write the files, upload nothing")
    args = parser.parse_args(argv)

    # Every platform, or nothing: one missing directory is a release whose
    # SHA256SUMS would cover two thirds of its downloads.
    built: dict[str, str] = {}
    sboms: list[tuple[Path, str]] = []
    for target, label in PLATFORMS.items():
        folder = args.artifacts / f"{PREFIX}{target}"
        manifest = folder / "SHA256SUMS"
        if not manifest.is_file():
            raise SystemExit(f"missing {manifest}")
        recorded = read_manifest(manifest.read_text(encoding="utf-8"), str(manifest))
        for name, digest in recorded.items():
            if built.get(name, digest) != digest:
                raise SystemExit(f"{name}: two build jobs recorded different hashes")
            built[name] = digest
        found = sorted(folder.glob("sbom-*.cdx.json"))
        if not found:
            raise SystemExit(f"no SBOM in {folder}")
        for sbom in found:
            stem = sbom.name.removesuffix(".cdx.json")
            sboms.append((sbom, f"{stem}-{label}.cdx.json"))

    release = find_release(args.repo, args.tag)
    published: dict[str, str] = {}
    for asset in release["assets"]:
        name = asset["name"]
        if name in OWN or name.startswith(OWN_PREFIX):
            continue
        digest = asset.get("digest") or ""
        if not digest.startswith("sha256:"):
            raise SystemExit(f"{name}: GitHub reports no sha256 digest for this asset")
        published[name] = digest.removeprefix("sha256:")

    problems = []
    for name, digest in sorted(built.items()):
        if name not in published:
            # A portable zip is built but never attached to the release; only an
            # installer that should be on the page and is not is a problem.
            if not name.endswith(".zip"):
                problems.append(f"{name}: built but not on the release")
        elif published[name] != digest:
            problems.append(f"{name}: the release asset is not the file the build hashed")
    if problems:
        raise SystemExit("refusing to publish a manifest:\n  " + "\n  ".join(problems))

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        lines = [f"{published[name]}  {name}" for name in sorted(published)]
        # LF on every platform, for the same reason provenance.py insists on it.
        (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        for source, name in sboms:
            shutil.copyfile(source, out / name)
        files = sorted(out.iterdir())
        print(f"{release['tag_name']} ({'draft' if release['draft'] else 'published'}):")
        print((out / "SHA256SUMS").read_text(encoding="utf-8"), end="")
        for path in files:
            print(f"  {path.name}")
        if args.dry_run:
            print("dry run: nothing uploaded")
            return 0
        subprocess.run(
            ["gh", "release", "upload", args.tag, "--repo", args.repo, "--clobber"]
            + [str(path) for path in files],
            check=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

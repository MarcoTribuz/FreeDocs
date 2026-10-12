#!/usr/bin/env python3
"""The one place that knows what this project's version is.

Nine lines in eight files carry it, in two spellings, across three package
ecosystems, and until this module existed nothing compared them: every artifact
the project had ever produced said `0.1.0`, and `scripts/provenance.py` was
already refusing builds because two trees held the same filename.

The rule is `core/limits.py`'s: four callers asking one question get one answer.
Here it is nine writers and one arithmetic.

Two things about this file are load-bearing and are argued for where they are
implemented: the two spellings (`_Site.render`), and the surgical lockfile edit
(`_LOCKS`).
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ".githooks"

BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
DIM = "\033[2m"
OFF = "\033[0m"


class VersionError(RuntimeError):
    """A version could not be read, parsed or written.

    Its own type so a hook can tell "this tree is inconsistent" from "python
    itself fell over", and report the first without a traceback.
    """


# --------------------------------------------------------------------------
# The value


@dataclasses.dataclass(frozen=True, order=False)
class Version:
    """One logical version. `dev` is `None` on a release, an integer on develop.

    Not a string, because the string is ambiguous: PEP 440 spells a development
    release `0.2.0.dev1` and SemVer spells the same thing `0.2.0-dev.1`, and
    comparing the two as text reports drift that does not exist.
    """

    major: int
    minor: int
    patch: int
    dev: int | None = None

    # `dev` sorts *below* the release it leads to, and a release below the next
    # patch: 0.3.0-dev.7 < 0.3.0 < 0.3.1. That ordering is the whole reason
    # develop may run ahead of main without ever colliding with a hotfix.
    @property
    def key(self) -> tuple[int, int, int, int, int]:
        return (self.major, self.minor, self.patch, 0 if self.dev is not None else 1, self.dev or 0)

    def __lt__(self, other: Version) -> bool:
        return self.key < other.key

    def pep440(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}" + (
            f".dev{self.dev}" if self.dev is not None else ""
        )

    def semver(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}" + (
            f"-dev.{self.dev}" if self.dev is not None else ""
        )

    def __str__(self) -> str:
        return self.semver()


# Tolerant on the way in, exact on the way out. Both separators before `dev`
# and both after it, because PEP 440 permits all four and the point of reading
# is to recognise whatever the previous writer produced.
_PARSE = re.compile(
    r"""^
    (?P<major>0|[1-9][0-9]*)\.
    (?P<minor>0|[1-9][0-9]*)\.
    (?P<patch>0|[1-9][0-9]*)
    (?:[-_.]?dev[-_.]?(?P<dev>[0-9]+))?
    $""",
    re.VERBOSE,
)


def parse(text: str) -> Version:
    match = _PARSE.match(text.strip())
    if match is None:
        raise VersionError(f"not a version this project can write: {text!r}")
    dev = match.group("dev")
    return Version(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        None if dev is None else int(dev),
    )


def bump(current: Version, part: str) -> Version:
    """Apply one increment.

    `major`, `minor` and `patch` open a new development line rather than naming
    a release: the release version is set on the release branch, by `release`.
    A version reached by bumping is therefore never a version anything ships.
    """
    if part == "dev":
        if current.dev is None:
            raise VersionError(
                f"{current} is a release version, so there is no development "
                "counter to advance. Open the next line with `bump minor` first."
            )
        return dataclasses.replace(current, dev=current.dev + 1)
    if part == "patch":
        return Version(current.major, current.minor, current.patch + 1, 0)
    if part == "minor":
        return Version(current.major, current.minor + 1, 0, 0)
    if part == "major":
        return Version(current.major + 1, 0, 0, 0)
    raise VersionError(f"unknown part: {part!r}")


def release(current: Version) -> Version:
    """Drop the development counter. A no-op on a version that has none."""
    return dataclasses.replace(current, dev=None)


# --------------------------------------------------------------------------
# The nine places


@dataclasses.dataclass(frozen=True)
class Site:
    """One line in one file that carries the version.

    `pattern` must have exactly one group and must match exactly once. Not
    "at least once": a pattern that matched twice would rewrite one occurrence
    and leave the other, and the two files where that is a real risk
    (`package-lock.json` says `"version"` 149 times, `uv.lock` and `Cargo.lock`
    once per dependency) are the two where a miss is invisible until
    `npm ci` or `uv sync --locked` fails in someone else's checkout.
    """

    path: str
    pattern: re.Pattern[str]
    spelling: str  # "pep440" or "semver"
    what: str

    def render(self, version: Version) -> str:
        # Python and the JavaScript/Rust side spell a development version
        # differently, and this is not cosmetic. `diagnostics.engine_version()`
        # prefers `importlib.metadata.version("freedocs")`, which returns the
        # PEP 440 *normalised* form, and falls back to `__init__.__version__`
        # when frozen. Write `0.2.0-dev.1` into the Python files and a checkout
        # reports `0.2.0.dev1` while a bundle reports `0.2.0-dev.1` — which is
        # verbatim the split that function was written to unify.
        return version.pep440() if self.spelling == "pep440" else version.semver()

    def read(self, text: str) -> str:
        matches = list(self.pattern.finditer(text))
        if len(matches) != 1:
            raise VersionError(
                f"{self.path}: expected exactly one {self.what}, found {len(matches)}"
            )
        return matches[0].group(1)

    def write(self, text: str, version: Version) -> str:
        matches = list(self.pattern.finditer(text))
        if len(matches) != 1:
            raise VersionError(
                f"{self.path}: expected exactly one {self.what}, found {len(matches)}"
            )
        match = matches[0]
        start, end = match.span(1)
        return text[:start] + self.render(version) + text[end:]


def _block(name: str) -> re.Pattern[str]:
    """The `version =` line of the one `[[package]]` block naming this project.

    Lockfiles are edited in place rather than regenerated. `uv lock` and
    `npm install --package-lock-only` can reach the network, and a project whose
    premise is that it works offline must not need a registry to change its own
    version number.
    """
    return re.compile(r'\[\[package\]\]\nname = "' + re.escape(name) + r'"\nversion = "([^"]+)"')


_SITES: tuple[Site, ...] = (
    Site(
        "engine/pyproject.toml",
        re.compile(r'^version = "([^"]+)"$', re.MULTILINE),
        "pep440",
        "[project] version",
    ),
    Site(
        "engine/freedocs/__init__.py",
        re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE),
        "pep440",
        "__version__",
    ),
    Site("engine/uv.lock", _block("freedocs"), "pep440", "freedocs package entry"),
    Site(
        "app/package.json",
        re.compile(r'^  "version": "([^"]+)",$', re.MULTILINE),
        "semver",
        "top-level version",
    ),
    Site(
        "app/package-lock.json",
        re.compile(r'\A\{\n  "name": "[^"]+",\n  "version": "([^"]+)",'),
        "semver",
        "top-level version",
    ),
    Site(
        "app/package-lock.json",
        re.compile(
            r'"packages": \{\n    "": \{\n      "name": "[^"]+",\n      "version": "([^"]+)",'
        ),
        "semver",
        'packages[""] version',
    ),
    Site(
        "app/src-tauri/Cargo.toml",
        re.compile(r'^version = "([^"]+)"$', re.MULTILINE),
        "semver",
        "[package] version",
    ),
    Site("app/src-tauri/Cargo.lock", _block("app"), "semver", "app package entry"),
    Site(
        "app/src-tauri/tauri.conf.json",
        re.compile(r'^  "version": "([^"]+)",$', re.MULTILINE),
        "semver",
        "top-level version",
    ),
)

PATHS: tuple[str, ...] = tuple(dict.fromkeys(site.path for site in _SITES))


# --------------------------------------------------------------------------
# Reading and writing the tree


def _read_file(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # a missing file is a broken checkout, not a crash
        raise VersionError(f"{relative}: {exc}") from exc


def readings(root: Path = ROOT) -> list[tuple[Site, str]]:
    """Every site's raw string, in declaration order."""
    return [(site, site.read(_read_file(root, site.path))) for site in _SITES]


def current(root: Path = ROOT) -> Version:
    """The project's version, refusing to answer while the sites disagree.

    There is no "majority wins" and no "the first one is right": a tree where
    `tauri.conf.json` and `package-lock.json` differ produces installers that
    `npm ci` will not even build, and guessing which half is correct is how a
    bump gets applied twice.
    """
    parsed = [(site, parse(raw)) for site, raw in readings(root)]
    distinct = {version for _, version in parsed}
    if len(distinct) != 1:
        lines = "\n".join(f"  {site.path:34} {site.what:24} {version}" for site, version in parsed)
        raise VersionError("the version sites disagree:\n" + lines)
    return distinct.pop()


def write(version: Version, root: Path = ROOT) -> list[str]:
    """Write `version` everywhere, then read it all back.

    The read-back is not paranoia about the filesystem — it is the only thing
    that catches a pattern which matched the wrong line, since a regex that
    finds *something* writes *somewhere* and says nothing.
    """
    by_path: dict[str, str] = {}
    for site in _SITES:
        text = by_path.get(site.path) or _read_file(root, site.path)
        by_path[site.path] = site.write(text, version)

    changed = []
    for path, text in by_path.items():
        target = root / path
        if target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")
            changed.append(path)

    written = current(root)
    if written != version:
        raise VersionError(f"wrote {version} but the tree reads {written}")
    return changed


# --------------------------------------------------------------------------
# Git


def _git(*args: str, root: Path = ROOT) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise VersionError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def version_at(commit: str, root: Path = ROOT) -> Version | None:
    """The version recorded in `commit`, or None if that commit predates this.

    `pre-push` judges the commit being pushed, not the working tree: pushing an
    old branch while develop is checked out must not be refused for develop's
    version, and a tag must be checked against what the tag actually points at.
    """
    site = _SITES[-1]  # tauri.conf.json — the file that names the installers
    result = subprocess.run(
        ["git", "show", f"{commit}:{site.path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return parse(site.read(result.stdout))
    except VersionError:
        return None


CHANGELOG = "CHANGELOG.md"


def changelog_names(text: str, version: Version) -> bool:
    """Whether `text` has a `## X.Y.Z` section for `version`.

    A release whose notes were never written is the gap this closes: the tag
    build makes a draft, the draft's notes are written from this file, and a
    version missing here is one whose changes nobody can look up next year.
    The heading must start the line and the version must end at a space or the
    line's end, so `## 1.1.0` does not also answer for `1.1`, or `1.1.0` for
    `1.1.0-dev.3`.
    """
    heading = re.compile(rf"^## {re.escape(version.semver())}(?:\s|$)", re.MULTILINE)
    return heading.search(text) is not None


def changelog_at(commit: str, root: Path = ROOT) -> str | None:
    """`CHANGELOG.md` as recorded in `commit`, or None if it has none."""
    result = subprocess.run(
        ["git", "show", f"{commit}:{CHANGELOG}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


# --------------------------------------------------------------------------
# Commands


def _print_sites(root: Path) -> None:
    for site, raw in readings(root):
        print(f"  {DIM}{site.path:34}{OFF} {site.what:24} {raw}")


def cmd_show(args: argparse.Namespace) -> int:
    version = current(args.root)
    print(f"{BOLD}{version.semver()}{OFF}  {DIM}(PEP 440: {version.pep440()}){OFF}")
    if args.verbose:
        _print_sites(args.root)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    version = current(args.root)
    print(f"{GREEN}ok{OFF} {len(_SITES)} sites agree on {version.semver()}")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    before = current(args.root)
    after = bump(before, args.part)
    changed = write(after, args.root)
    print(f"{before} -> {BOLD}{after}{OFF}  {DIM}({len(changed)} files){OFF}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    before = current(args.root)
    after = parse(args.value)
    changed = write(after, args.root)
    print(f"{before} -> {BOLD}{after}{OFF}  {DIM}({len(changed)} files){OFF}")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    before = current(args.root)
    after = release(before)
    if after == before:
        print(f"{before} is already a release version")
        return 0
    changed = write(after, args.root)
    print(f"{before} -> {BOLD}{after}{OFF}  {DIM}({len(changed)} files){OFF}")
    # A reminder, not a refusal: the notes are usually written on the release
    # branch after this runs. `pre-push` refuses the tag until they exist.
    log = args.root / CHANGELOG
    if not (log.is_file() and changelog_names(log.read_text(encoding="utf-8"), after)):
        print(f"{DIM}next: add a `## {after.semver()} — <date>` section to {CHANGELOG}{OFF}")
    return 0


def cmd_install_hooks(args: argparse.Namespace) -> int:
    _git("config", "core.hooksPath", HOOKS_DIR, root=args.root)
    print(f"{GREEN}ok{OFF} core.hooksPath = {HOOKS_DIR}")
    for hook in sorted((args.root / HOOKS_DIR).glob("*")):
        if hook.is_file():
            print(f"  {DIM}{hook.name}{OFF}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="version.py",
        description="Read, check and advance the one version this project has.",
    )
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command")

    show = sub.add_parser("show", help="print the current version")
    show.add_argument("--verbose", "-v", action="store_true", help="list every site")
    show.set_defaults(func=cmd_show)

    check = sub.add_parser("check", help="fail unless every site agrees")
    check.set_defaults(func=cmd_check, verbose=False)

    bump_parser = sub.add_parser("bump", help="advance one component")
    bump_parser.add_argument("part", choices=["dev", "patch", "minor", "major"])
    bump_parser.set_defaults(func=cmd_bump)

    set_parser = sub.add_parser("set", help="write an exact version")
    set_parser.add_argument("value")
    set_parser.set_defaults(func=cmd_set)

    sub.add_parser("release", help="drop the development counter").set_defaults(func=cmd_release)

    sub.add_parser("install-hooks", help=f"point git at {HOOKS_DIR}/").set_defaults(
        func=cmd_install_hooks
    )

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    try:
        return args.func(args)
    except VersionError as exc:
        # No traceback: every one of these is a statement about the tree, and a
        # hook prints it to somebody who is mid-merge.
        print(f"{RED}version:{OFF} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

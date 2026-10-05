#!/usr/bin/env python3
"""The git hooks, as one testable module rather than two shell scripts.

Branch protection is not available on this repository — `/branches/main/protection`
answers HTTP 403, *"Upgrade to GitHub Pro or make this repository public"* — and
GitHub Actions is switched off. So these two hooks are the only enforcement the
branching model has, and the honest reading of that is: they are a seatbelt for
the person wearing them, not a gate on the repository. `--no-verify` skips
`pre-push`, and a merge performed in the GitHub web interface runs neither.

Nothing here makes a network call. `core/egress.py` argues the case for the
engine and it applies with more force to a hook: asking the GitHub API for a
pull request's milestone would make a merge fail on a train.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from version import (
    BOLD,
    DIM,
    GREEN,
    OFF,
    PATHS,
    RED,
    VersionError,
    bump,
    current,
    version_at,
    write,
)

ROOT = Path(__file__).resolve().parent.parent
ZERO = "0" * 40

# `Merge branch 'feature/x'`, `Merge branch 'feature/x' into develop`, and the
# subject `git merge` writes for a pull request finished locally
# (`Merge pull request #12 from owner/feature/x`). A plain `git pull` produces
# `Merge branch 'develop' of https://github.com/...`, which must *not* match:
# every fetch would otherwise advance the counter.
_FEATURE_MERGE = re.compile(r"^Merge (?:branch|pull request) .*\bfeature/", re.IGNORECASE)


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise VersionError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


# --------------------------------------------------------------------------


def post_merge(_argv: list[str]) -> int:
    """Advance the development counter when a feature lands on develop.

    Git ignores this hook's exit status, so it cannot fail a merge and must not
    try to. When something is wrong it says so and tells the reader what to run;
    the merge itself has already happened either way.
    """
    try:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        if branch != "develop":
            return 0

        # A fast-forward brought no feature in — there is nothing to count.
        parents = _git("rev-list", "--parents", "-n", "1", "HEAD").split()
        if len(parents) < 3:
            return 0

        subject = _git("log", "-1", "--pretty=%s")
        if subject.startswith("Version "):  # re-running the hook is inert
            return 0
        if not _FEATURE_MERGE.match(subject):
            return 0

        before = current(ROOT)
        after = bump(before, "dev")
        write(after, ROOT)
        try:
            _commit_the_bump(after)
        except VersionError:
            # Put the files back. A hook that cannot commit must not leave the
            # bump sitting in the working tree, because the next `git status`
            # then shows eight modified files nobody edited.
            write(before, ROOT)
            raise
        print(f"{GREEN}version{OFF} {before} -> {BOLD}{after}{OFF}")
    except VersionError as exc:
        print(f"{RED}version:{OFF} {exc}", file=sys.stderr)
        print(
            f"{DIM}the merge stands; run `python3 scripts/version.py bump dev` "
            f"once the tree is consistent{OFF}",
            file=sys.stderr,
        )
    return 0


def _commit_the_bump(version: object) -> None:
    """Add one ordinary commit on top of the merge, using plumbing.

    `git commit` cannot be used here, and the reason is not obvious: git runs
    `post-merge` *before* it clears the merge state, so `MERGE_HEAD` still
    exists. A partial commit (`git commit -- <paths>`) is refused outright —
    `fatal: cannot do a partial commit during a merge` — and a full `git commit`
    would read `MERGE_HEAD` and give the bump a second parent, quietly turning
    it into another merge commit.

    Staging the bump earlier, from `prepare-commit-msg`, was tried and does not
    work either: git has already written the merge tree by then and ignores the
    index change, so the merge commit lands without the version in it.

    `write-tree` + `commit-tree` + `update-ref` consults none of that state.
    """
    _git("add", "--", *PATHS)
    tree = _git("write-tree")
    commit = _git("commit-tree", tree, "-p", "HEAD", "-m", f"Version {version}")
    _git("update-ref", "-m", f"commit: Version {version}", "HEAD", commit)


# --------------------------------------------------------------------------


def pre_push(_argv: list[str]) -> int:
    """Refuse a push that would publish a version nobody could reproduce.

    Three refusals, and each one has already been possible in this repository:
    a tree whose nine sites drifted, a `main` carrying a development version,
    and a `v*` tag that does not match the `tauri.conf.json` the installers are
    named from — `app.yml` passes `tagName` to `tauri-action` verbatim and
    checks it against nothing.
    """
    try:
        current(ROOT)
    except VersionError as exc:
        print(f"{RED}refusing to push:{OFF} {exc}", file=sys.stderr)
        return 1

    refusals: list[str] = []
    for line in sys.stdin.read().splitlines():
        fields = line.split()
        if len(fields) != 4:
            continue
        _local_ref, local_sha, remote_ref, _remote_sha = fields
        if local_sha == ZERO:  # a deletion carries no commit to judge
            continue

        # The commit being pushed, not the working tree: pushing an old branch
        # while develop is checked out must not be judged by develop's version.
        version = version_at(local_sha, ROOT)
        if version is None:  # predates this mechanism; nothing to check against
            continue

        if remote_ref == "refs/heads/main" and version.dev is not None:
            refusals.append(
                f"main would carry {version}, a development version. "
                "Finish the release branch first: `python3 scripts/version.py release`."
            )
        if remote_ref.startswith("refs/tags/v"):
            tag = remote_ref[len("refs/tags/") :]
            if version.dev is not None:
                refusals.append(f"{tag} points at {version}, a development version.")
            elif tag != f"v{version.semver()}":
                refusals.append(
                    f"{tag} points at a tree whose version is {version.semver()}. "
                    f"The installers would be named {version.semver()} and the "
                    f"release {tag}."
                )

    for refusal in refusals:
        print(f"{RED}refusing to push:{OFF} {refusal}", file=sys.stderr)
    if refusals:
        print(f"{DIM}`git push --no-verify` overrides this{OFF}", file=sys.stderr)
        return 1
    return 0


HOOKS = {"post-merge": post_merge, "pre-push": pre_push}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in HOOKS:
        print(f"usage: hooks.py {{{'|'.join(HOOKS)}}} [args...]", file=sys.stderr)
        return 2
    return HOOKS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

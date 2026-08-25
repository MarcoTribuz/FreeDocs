# Branching and releases

```bash
python3 scripts/version.py install-hooks   # once per clone; git does not ship hooks
python3 scripts/version.py show            # what this tree calls itself
```

Until this landed, every artifact the project had ever produced said `0.1.0`.
Not a stale bump — there was no mechanism: no tags, no releases, and the version
written by hand in nine places that nothing compared.

## The branches

| Branch | Cut from | Merges into | Version it carries |
|---|---|---|---|
| `main` | — | — | a release, `X.Y.Z` |
| `develop` | `main` | `release/*` | `X.Y.Z-dev.N` |
| `feature/*` | `develop` | `develop` | whatever develop had |
| `release/X.Y.Z` | `develop` | `main` **and** `develop` | `X.Y.Z` |
| `hotfix/X.Y.Z` | `main` | `main` **and** `develop` | `X.Y.Z` |

`main` never carries a development version and the pre-push hook refuses one.

## The version

One value, `major.minor.patch` with an optional development counter, and two
spellings of it because Python and the rest of the tree disagree about how to
write a prerelease:

| Spelling | Files | Example |
|---|---|---|
| PEP 440 | `engine/pyproject.toml`, `engine/freedocs/__init__.py`, `engine/uv.lock` | `0.2.0.dev1` |
| SemVer | `app/package.json`, `app/package-lock.json`, `Cargo.toml`, `Cargo.lock`, `tauri.conf.json` | `0.2.0-dev.1` |

`scripts/version.py` is the only thing that writes either, and `check` compares
the parsed value rather than the string, so the two spellings are not read as
drift. It is wired into `scripts/ci.py check` as the first step.

The ordering is what makes the model work: `0.3.0-dev.7` < `0.3.0` < `0.3.1`. A
development counter always sorts below the release it leads to, so `develop` can
run a whole cycle ahead of `main` without ever reaching a number a hotfix wants.

```bash
python3 scripts/version.py show            # current value, both spellings
python3 scripts/version.py show -v         # ... and every site it was read from
python3 scripts/version.py check           # non-zero if the nine disagree
python3 scripts/version.py bump dev        # 0.2.0-dev.1 -> 0.2.0-dev.2
python3 scripts/version.py bump minor      # 0.2.0       -> 0.3.0-dev.0
python3 scripts/version.py release         # 0.3.0-dev.9 -> 0.3.0
python3 scripts/version.py set 0.2.1       # exact, for a hotfix
```

`bump major|minor|patch` opens a *development* line — it always ends in
`-dev.0`. A version reached by bumping is never a version anything ships; the
release number is settled by `release`, on the release branch.

## A feature

```bash
git switch develop && git pull
git switch -c feature/short-name
# ... work, one subject, and `python3 scripts/ci.py check` green ...
git switch develop
git merge --no-ff feature/short-name
git push origin develop
git branch -d feature/short-name
```

The `--no-ff` is not style. `post-merge` bumps the development counter when it
sees a merge commit whose subject names a `feature/` branch, and a fast-forward
produces no merge commit and no bump.

The bump lands as its own `Version 0.2.0-dev.N` commit directly on top of the
merge, not inside it. That is forced rather than chosen: git has already written
the merge tree before any hook could add to it.

## A release

```bash
git switch -c release/0.2.0 develop
python3 scripts/version.py release          # 0.2.0-dev.N -> 0.2.0
git commit -am "Version 0.2.0"
# ... only fixes on this branch; no new features ...
python3 scripts/ci.py check

git switch main && git merge --no-ff release/0.2.0
git tag -a v0.2.0 -m "0.2.0"
git push origin main v0.2.0                 # the tag is what builds the release

git switch develop && git merge --no-ff release/0.2.0
python3 scripts/version.py bump minor       # opens 0.3.0-dev.0
git commit -am "Version 0.3.0-dev.0"
git push origin develop
git branch -d release/0.2.0
```

Pushing `v0.2.0` is what would make the installers, through the `v*` trigger in
`.github/workflows/app.yml`. **Actions is switched off on this repository**, so
today that tag records the release and builds nothing; see `docs/packaging.md`.

## A hotfix

```bash
git switch -c hotfix/0.2.1 main
python3 scripts/version.py set 0.2.1
# ... the fix, and its test ...
git commit -am "Version 0.2.1"

git switch main && git merge --no-ff hotfix/0.2.1
git tag -a v0.2.1 -m "0.2.1" && git push origin main v0.2.1
git switch develop && git merge --no-ff hotfix/0.2.1   # take the fix, keep develop's version
git push origin develop
```

The back-merge will conflict on the nine version lines, because `develop` is
already ahead. Resolve in `develop`'s favour — `python3 scripts/version.py show`
afterwards, and it should still read `0.3.0-dev.N`.

## Milestones

A milestone named `v0.2.0` documents what a release contains. It is deliberately
**not** wired to anything: a hook that asked the GitHub API which milestone a
pull request carried would make a merge fail on a train, and this is a project
whose whole premise is that it works with the network off. The trigger is the
merge, not the milestone.

## What the hooks do, and what they cannot

`scripts/version.py install-hooks` sets `core.hooksPath` to `.githooks/`. Git
does not distribute hooks with a clone, so every checkout runs it once. The
bodies live in `scripts/hooks.py`.

**`post-merge`** advances the development counter. It acts only when the current
branch is `develop`, `HEAD` is a merge commit, and the subject names a
`feature/` branch — that last guard is why an ordinary `git pull`, whose subject
is `Merge branch 'develop' of https://github.com/...`, does not inflate the
number on every fetch. Git ignores this hook's exit status, so it cannot fail a
merge and does not try to: when the tree is inconsistent it says so and names
the command to run.

**`pre-push`** refuses three things: a push from a tree whose nine sites have
drifted, a `main` carrying a development version, and a `v*` tag whose name does
not match the version of the commit it points at. That last one closes a real
hole — `app.yml` hands `tagName` to `tauri-action` verbatim and checks it
against nothing, so a tag and the installers it names could disagree.

Both are a seatbelt, not a gate, and the reason is worth stating plainly:

- **Branch protection is not available here.** `/branches/main/protection`
  answers HTTP 403, *"Upgrade to GitHub Pro or make this repository public"*.
  Every branch reports `protected: false`. Nothing server-side can require a
  base branch, a review or a status check.
- **A merge in the GitHub web interface runs no local hook**, so a pull request
  merged in the browser lands on `develop` without a bump. Finish features
  locally, as above. If one does slip through, the next `push` still runs
  `check`, and `python3 scripts/version.py bump dev` puts it right.
- **`git push --no-verify` skips `pre-push`.**

## Known limitation: prerelease versions and Windows installers

WiX and MSI require a numeric `X.Y.Z`, so a Windows bundle cannot be built from
a tree carrying `-dev.N`. This does not affect CI — `app.yml` bundles only on
`main`, a `v*` tag, or a manual dispatch, never on `develop` — but a local
`python3 scripts/ci.py build` on Windows from a `develop` checkout will fail in
the bundler. Build from a release branch, or from `main`.

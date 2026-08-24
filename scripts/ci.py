#!/usr/bin/env python3
"""What CI used to run, run here instead.

GitHub Actions is switched off on this repository: a private repo's included
minutes were exhausted twice, and the second time every job on every workflow
began failing in two seconds with no runner assigned and no steps executed —
which reads exactly like a broken commit and is not one. Rather than leave the
workflows firing against an empty allowance, they are disabled at the repository
setting and this script is the gate.

The workflow files are deliberately untouched, so re-enabling costs one command
and nothing has to be reconstructed:

    gh api -X PUT /repos/<owner>/<repo>/actions/permissions -F enabled=true

Three things here are not transcriptions of the YAML, because a laptop is not a
runner:

**The Python floor gets its own virtualenv.** CI gives each matrix entry a fresh
machine; here there is one checkout, and `uv sync --python 3.10` would *delete*
the 3.12 environment it does not recognise and rebuild it on the next command.
`UV_PROJECT_ENVIRONMENT` puts the floor in `.venv-310` beside it, so both stay
usable and neither run pays for the other. This is the local shape of the bug
`engine.yml` documents: passing `--python` to `uv sync` alone was silently not
enough there either.

**`cargo` is often missing from a non-interactive shell's PATH** even when it is
installed, so it is resolved rather than assumed.

**`tauri build` needs `CI=true` on macOS.** The `.dmg` step drives Finder over
AppleScript to arrange icons, and without automation permission it fails with
`AppleEvent timed out (-1712)` after minutes of bundling. Tauri skips that step
when `CI` is set.

What this cannot do is the matrix. CI ran Linux and Windows; this runs whatever
machine you are on. The Windows gap is the one that has actually bitten this
project — `write_text` translating "\n" to CRLF broke three leak tests, and
`npm` being `npm.cmd` broke the portable build — so a green run here is weaker
evidence than a green run there was, and is worth saying out loud rather than
forgetting.

    python3 scripts/ci.py check        # the pull-request gate
    python3 scripts/ci.py build        # the sidecar and the desktop bundle
    python3 scripts/ci.py all
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
APP = ROOT / "app"
TAURI = APP / "src-tauri"

#: The declared floor in `engine/pyproject.toml`. CI checked it on Linux only,
#: because it is a language-version question rather than a platform one.
FLOOR = "3.10"
#: Kept out of `.venv` so running the floor does not cost a rebuild of the
#: environment every other command uses. See the module docstring.
FLOOR_VENV = ".venv-310"

#: What CI installs for the checks. The `ner` extra is deliberately absent: it
#: pulls torch and ~1.2 GB of weights, the model-backed tests skip themselves
#: without it, and detection quality is measured by `freedocs benchmark` rather
#: than asserted here. The build adds it, because a bundle whose smoke test
#: cannot load the model fails on its first real document.
#:
#: `restore` is present for the opposite reason. It is one small wheel, and the
#: checks it enables are not quality measurements that skip harmlessly: the key
#: file is the only artifact this tool writes that could hand back every value it
#: removed, and a gate that skipped "no value is readable in the key file" would
#: be skipping the one assertion that makes the feature safe.
EXTRAS = [
    "uv",
    "sync",
    "--extra",
    "dev",
    "--extra",
    "pdf",
    "--extra",
    "ooxml",
    "--extra",
    "restore",
]

GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
#: Move up one line and erase it, so a running step is replaced by its result
#: rather than leaving two lines behind. Gated on the same condition as the
#: colours, for a stronger reason: a colour code in a pipe is ugly, a cursor
#: movement in a pipe corrupts the transcript somebody is trying to read.
CLEAR = "\033[1A\033[2K"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = RED = YELLOW = DIM = OFF = CLEAR = ""


@dataclass
class Step:
    name: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    #: Why this step cannot run, when it cannot. A skip is reported, never
    #: silent: a gate that quietly drops a check is worse than one that fails.
    skip: str | None = None


@dataclass
class Outcome:
    step: Step
    status: str  # "ok" | "failed" | "skipped"
    seconds: float


def cargo() -> str | None:
    """Where cargo actually is.

    A login shell has it on PATH and a non-interactive one frequently does not,
    which makes "cargo: command not found" the most common false failure when
    driving this from an editor or an agent.
    """
    found = shutil.which("cargo")
    if found:
        return found
    fallback = Path.home() / ".cargo" / "bin" / "cargo"
    return str(fallback) if fallback.is_file() else None


def cargo_audit() -> str | None:
    """Where `cargo audit` is, when it is anywhere.

    A separate binary from `cargo`, installed by `cargo install cargo-audit` and
    absent by default, so it is looked for rather than assumed. Same two places
    as :func:`cargo`, for the same reason.
    """
    found = shutil.which("cargo-audit")
    if found:
        return found
    fallback = Path.home() / ".cargo" / "bin" / "cargo-audit"
    return str(fallback) if fallback.is_file() else None


def cargo_path_env() -> dict[str, str]:
    """Put cargo's directory on PATH, not just its absolute path in a command.

    `tauri build` does not take a path to cargo — it shells out to
    `cargo metadata` by bare name and resolves it through PATH, so handing the
    Step an absolute binary satisfies the step that runs cargo directly and does
    nothing for the one that runs it indirectly. That is what the first run of
    this script hit: the sidecar built for 143 seconds and then the bundle died
    instantly on `failed to run command cargo metadata ... (os error 2)`.

    Same shape as `FREEDOCS_TESSERACT` in the engine, which has to extend PATH
    for exactly this reason: nothing in FreeDocs runs Tesseract, PyMuPDF does,
    and it looks the binary up by name.
    """
    binary = cargo()
    if not binary:
        return {}
    directory = str(Path(binary).parent)
    current = os.environ.get("PATH", "")
    if directory in current.split(os.pathsep):
        return {}
    return {"PATH": directory + os.pathsep + current}


def engine_steps(python: str, *, sync: bool, venv: str | None) -> list[Step]:
    """One matrix entry of `engine.yml`, for one interpreter.

    The `ner` extra is omitted on purpose, as in CI: it pulls torch and ~1.2 GB
    of weights, the model-backed tests skip themselves without it, and detection
    quality is measured by `freedocs benchmark` rather than asserted here.
    """
    env = {"UV_PYTHON": python}
    if venv:
        env["UV_PROJECT_ENVIRONMENT"] = venv

    label = f"engine {python}"
    steps = []
    if sync:
        steps.append(
            Step(
                f"{label}: install",
                EXTRAS,
                ENGINE,
                env,
            )
        )
    steps += [
        Step(f"{label}: lint", ["uv", "run", "ruff", "check", "."], ENGINE, env),
        Step(f"{label}: format", ["uv", "run", "ruff", "format", "--check", "."], ENGINE, env),
        Step(f"{label}: test", ["uv", "run", "pytest", "-q", "-m", "not slow"], ENGINE, env),
        # Separate from the suite so a failure here is unmistakable: this is the
        # one that decides whether the tool is usable at all.
        Step(
            f"{label}: leak checks",
            ["uv", "run", "pytest", "-q", "-m", "leak and not slow"],
            ENGINE,
            env,
        ),
        # Gold data. Bad offsets would make every future benchmark number
        # meaningless, and nothing else would notice.
        Step(
            f"{label}: corpus integrity",
            ["uv", "run", "pytest", "-q", "tests/test_corpus.py"],
            ENGINE,
            env,
        ),
    ]
    return steps


#: Written by the export step and read by the audit step. Gitignored: it is a
#: derived view of `uv.lock`, and a second checked-in copy of a dependency set is
#: a second thing that can be out of date.
AUDIT_REQUIREMENTS = ".audit-requirements.txt"


def audit_steps() -> list[Step]:
    """Is anything this depends on known to be vulnerable?

    The check CI never had, and the one whose absence is least visible: lint and
    tests fail loudly when they regress, while an advisory published against a
    pinned dependency changes nothing at all about a green run. It fails rather
    than warning, because an advisory printed on every run is an advisory nobody
    reads - the reasoning `.github/dependabot.yml` opens with.

    **The Python half audits the lockfile, not the installed environment.** The
    checks deliberately omit the `ner` extra, so an environment audit would skip
    torch - by a distance the largest dependency here and the one most likely to
    be named. `--all-extras` on the export covers what `build` installs as well
    as what `check` does, which is the set a release actually ships.

    No ignore list, and that was measured rather than assumed. `cargo audit`
    separates vulnerabilities from *warnings* and fails only on the first: this
    tree reports zero vulnerabilities and seventeen warnings, which are the
    unmaintained GTK3 bindings and the `glib` unsoundness `dependabot.yml`
    explains cannot be fixed from this repository. So the default behaviour is
    already the right one, and `-D warnings` would turn a standing, unfixable
    fact into a red gate. The `cookie` advisory is dev-only, which is what
    `--omit=dev` is for. If a real vulnerability ever does surface here it
    belongs in an ignore list with its sentence, not silenced.
    """
    audit = cargo_audit()
    return [
        Step(
            "audit: export the locked dependency set",
            [
                "uv",
                "export",
                "--format",
                "requirements-txt",
                "--no-hashes",
                "--all-extras",
                # The project itself is not on PyPI, so leaving it in makes
                # `--strict` fail on a package that could never be audited.
                "--no-emit-project",
                "-o",
                AUDIT_REQUIREMENTS,
            ],
            ENGINE,
        ),
        Step(
            "audit: python dependencies",
            # `--strict`: a dependency the database has nothing to say about and
            # one it could not look up at all are different answers, and only the
            # first is reassuring.
            ["uv", "run", "--with", "pip-audit", "pip-audit", "--strict", "-r", AUDIT_REQUIREMENTS],
            ENGINE,
        ),
        Step(
            # Every JavaScript dependency here is a devDependency: the app is
            # built by `adapter-static` into an SPA served from the webview, so
            # nothing in `node_modules` ships. This reports zero today and is the
            # guard for the day a runtime dependency is added.
            "audit: frontend dependencies",
            ["npm", "audit", "--omit=dev"],
            APP,
        ),
        Step(
            "audit: rust dependencies",
            [audit or "cargo-audit", "audit"],
            TAURI,
            skip=None if audit else "cargo-audit is not installed (cargo install cargo-audit)",
        ),
    ]


def frontend_steps(*, sync: bool) -> list[Step]:
    steps = []
    if sync:
        steps.append(Step("frontend: install", ["npm", "ci"], APP))
    steps += [
        # Also the completeness check for the four message catalogues: each is
        # `satisfies Messages`, so a missing key and a misspelled extra one are
        # both type errors rather than a hole somebody notices in the window.
        Step("frontend: type-check", ["npm", "run", "check"], APP),
        Step("frontend: test", ["npm", "test"], APP),
    ]
    return steps


def rust_steps() -> list[Step]:
    binary = cargo()
    return [
        Step(
            "rust: test",
            [binary or "cargo", "test"],
            TAURI,
            skip=None if binary else "cargo is not installed or not on PATH",
        )
    ]


def build_steps() -> list[Step]:
    """The bundle workflow, minus its gates.

    `app.yml` runs the engine suite and the Rust tests before it bundles, on the
    grounds that shipping an app around a broken engine wastes everyone's time
    downloading it. Those live under `check` here instead, so `build` is the
    packaging step alone and `all` is the faithful equivalent of that workflow.
    Reach for `build` when you have already run the checks and want the artifact.
    """
    binary = cargo()
    return [
        # The `ner` extra is required here and not in the checks: a bundle whose
        # smoke test cannot load the model is a bundle that fails on its first
        # real document, which is what `packaging/build.py` exists to catch.
        Step(
            "build: install engine with ner",
            [*EXTRAS, "--extra", "ner"],
            ENGINE,
        ),
        Step(
            "build: engine sidecar",
            ["uv", "run", "--with", "pyinstaller", "python", "packaging/build.py"],
            ENGINE,
        ),
        Step(
            "build: desktop bundle",
            ["npm", "run", "tauri", "build"],
            APP,
            # CI=true: without it the .dmg step hangs on Finder automation and
            # dies after minutes of bundling. PATH: tauri resolves cargo by name.
            {"CI": "true", **cargo_path_env()},
            skip=None if binary else "cargo is not installed or not on PATH",
        ),
    ]


def run(step: Step, *, quiet: bool) -> Outcome:
    if step.skip:
        print(f"{YELLOW}skip{OFF}  {step.name}  {DIM}({step.skip}){OFF}")
        return Outcome(step, "skipped", 0.0)

    print(f"{DIM}····{OFF}  {step.name}", flush=True)
    started = time.monotonic()
    completed = subprocess.run(
        step.cmd,
        cwd=step.cwd,
        env={**os.environ, **step.env},
        capture_output=quiet,
        text=True,
    )
    seconds = time.monotonic() - started

    if completed.returncode == 0:
        print(f"{CLEAR}{GREEN}ok{OFF}    {step.name}  {DIM}{seconds:.0f}s{OFF}", flush=True)
        return Outcome(step, "ok", seconds)

    print(f"{CLEAR}{RED}FAIL{OFF}  {step.name}  {DIM}{seconds:.0f}s{OFF}", flush=True)
    if quiet:
        # Held back until it matters, then printed whole: a failure the reader
        # has to go looking for is a failure they will skip.
        sys.stdout.write(completed.stdout or "")
        sys.stderr.write(completed.stderr or "")
    print(f"{DIM}      {' '.join(step.cmd)}  (in {step.cwd.relative_to(ROOT)}){OFF}")
    return Outcome(step, "failed", seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci.py", description="Run the checks and builds GitHub Actions used to run."
    )
    parser.add_argument("target", choices=["check", "build", "all"], nargs="?", default="check")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="reinstall dependencies first, as a fresh runner would. Off by "
        "default: locally they are usually already there and it is the slowest "
        "part of the run.",
    )
    parser.add_argument(
        "--no-floor",
        action="store_true",
        help=f"skip the Python {FLOOR} pass. It is the declared floor in "
        "pyproject.toml, so skipping it is how 3.11+ syntax reaches main.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="run every step instead of stopping at the first failure",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="stream each step's output instead of holding it back",
    )
    args = parser.parse_args(argv)

    steps: list[Step] = []
    if args.target in ("check", "all"):
        steps += engine_steps("3.12", sync=args.sync, venv=None)
        if not args.no_floor:
            # Always synced: the floor environment is not the one day-to-day work
            # keeps current, so assuming it exists is how this pass starts
            # testing a stale dependency set.
            steps += engine_steps(FLOOR, sync=True, venv=FLOOR_VENV)
        steps += frontend_steps(sync=args.sync)
        steps += rust_steps()
        # Last in `check`, because it is the step most likely to fail for a
        # reason nobody in this repository can fix, and a lint error found after
        # a five-minute audit is a lint error found late.
        steps += audit_steps()
    if args.target in ("build", "all"):
        steps += build_steps()

    print(f"{DIM}{len(steps)} steps{OFF}\n")
    outcomes: list[Outcome] = []
    for step in steps:
        outcome = run(step, quiet=not args.verbose)
        outcomes.append(outcome)
        if outcome.status == "failed" and not args.keep_going:
            break

    failed = [o for o in outcomes if o.status == "failed"]
    skipped = [o for o in outcomes if o.status == "skipped"]
    total = sum(o.seconds for o in outcomes)
    print()
    if failed:
        print(f"{RED}{len(failed)} failed{OFF}: {', '.join(o.step.name for o in failed)}")
    else:
        print(f"{GREEN}all {len(outcomes) - len(skipped)} passed{OFF} in {total:.0f}s")
    if skipped:
        print(f"{YELLOW}{len(skipped)} skipped{OFF}: {', '.join(o.step.name for o in skipped)}")
    if len(outcomes) < len(steps):
        print(f"{DIM}{len(steps) - len(outcomes)} not reached{OFF}")

    # Said every time rather than only on success: the thing most likely to go
    # wrong after this is trusting a green local run the way a green CI run
    # could be trusted, and those are not the same claim.
    print(
        f"\n{DIM}This machine only. CI also ran Linux and Windows, which is "
        f"where this project's cross-platform failures have actually been.{OFF}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

# Contributing to FreeDocs

Thanks for looking. This is a small codebase where the reasoning is the valuable
part, so the bar is less "does it work" and more "does the next person understand
why".

**One rule before anything else: never attach a real document.** Not to an issue,
not to a pull request, not to a test fixture. Build a synthetic file that
reproduces the problem — `engine/tests/conftest.py` shows how, and the identifiers
in it are real-shaped values with correct check digits rather than anybody's data.

## Setup

```bash
cd engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner
```

Python 3.12 is what this is developed on. **3.10 is the declared floor** in
`pyproject.toml` and CI runs it, so avoid 3.11+ syntax — no `match` on things that
need 3.11 semantics, no `except*`, no `Self` from `typing`.

`--extra ner` fetches roughly 1.2 GB of model weights to the Hugging Face cache on
first use. You can work without it: the model-backed tests skip themselves.

```bash
uv run pytest -q                       # full suite (~675 tests, ~30s with model+OCR)
uv run pytest -q -m "not slow"         # skip the model-backed tests (~1s)
uv run pytest -q -m leak               # only the end-to-end leak checks
uv run pytest -q -k plan_edits         # one test by name
uv run ruff check . && uv run ruff format --check .
```

The desktop app:

```bash
cd app && npm install
npm run check    # svelte-check, and it proves all four message catalogues are complete
npm test         # vitest
```

CI runs lint, format, the suite, the leak checks and the corpus check on Python
3.10 and 3.12 on Linux and 3.12 on Windows, in about thirty seconds. Windows is
there because that is where the cross-platform failures have actually been.

## What a good change looks like

**Comments explain *why*, especially where a simpler approach was tried and
failed.** The codebase is small; the reasoning is the part worth preserving. A
docstring that restates the signature is noise — say what failure the code
prevents.

**A measurement beats an opinion.** Several things in here look arbitrary and are
not: the confidence of each validator comes from running it against 20 000 random
format-plausible values, `MAX_CHUNK_CHARS` and the NER threshold come from sweeps,
and the propagation floor came from a four-point sweep that also disproved half the
reasoning behind the old value. If you want to change one of those numbers, re-run
the measurement and put the result in the pull request.

**A detector change needs a benchmark number, before and after.**

```bash
uv run freedocs benchmark
```

Coverage and over-redaction are the two figures that matter; F1 is third. And read
[docs/benchmark.md](docs/benchmark.md) first — three entities is the noise floor on
this corpus, so a delta smaller than that is not a result, and adding corpus text
moves NER chunk boundaries in a way that looks exactly like a rule improving.

## Four rules that are not obvious from the code

**1. Gold offsets are derived, never hand-written.** `engine/corpus/*.txt` uses
inline `[LABEL:text]` markup and the offsets are computed from it. Hand-maintained
offsets rot silently — insert a word and every number after it is wrong — and then
the benchmark measures the annotation instead of the model. An unknown label is an
error, not a skip.

**2. A canary must pass its real checksum.** A test value with a bad check digit is
rejected by the validator, so nothing is detected, nothing leaks, and the leak test
passes while proving nothing. Compute the check digit; do not invent it. Two of the
four codice fiscale values tried during early development were invalid. And at
twelve countries a value broken for one checksum is often valid for another, so a
new trap has to be checked against *every* rule — a test enforces that.

**3. A suppression rule needs a corpus case, and the burden of proof runs the other
way.** Every other rule can be wrong and merely noisy; a rule in
`detect/suppress.py` can be wrong and turn a working scrub into a leak. The country
list came from six measured false positives, the jurisdiction patterns from nine. A
currency rule that seemed obviously right was dropped because the model never
produced the finding it was meant to suppress.

**4. The app holds no rules.** Every judgement about what is confidential, what
gets removed and what the user is warned about lives in Python. Two places deciding
what an IBAN looks like is two answers that can disagree, so
`app/src/lib/engine.ts` carries messages and nothing else. If a frontend change
needs to know something about the engine, the engine should publish it.

## Adding things

**A format**: implement `extract`, `write_back` and `scrub_hidden` in
`formats/base.FormatHandler` and nothing else. Stages 3, 4 and 6 are shared and
format-agnostic — do not let format knowledge leak into `detect/`,
`core/policy.py` or `verify.py`. Write the leak test so it searches *inside* the
container: a Flate-compressed PDF stream or a zip part, not the raw bytes.

**An identifier**: add a `Rule` to `detect/validators.py` with its `country`, and
always pair the pattern with a real validator from `python-stdnum` rather than
tightening the regex. If the validator accepts most of what it sees, it is not a
validator — leave the identifier to the model and say so.

**An entity type**: `core/findings.EntityType` plus a label in every locale of
`core/policy.PLACEHOLDER_LABELS` that needs one. Quasi-identifiers belong in
`REPORT_ONLY`: removing a date silently hides residual risk instead of surfacing
it.

**A user-visible string in the app**: it goes in all four catalogues under
`app/src/lib/i18n/`, and `npm run check` fails if one is missing. But engine prose
is not translated — the rule is **if it came from an enum, translate it; if it came
from an f-string, quote it**, and the reasoning is in
[docs/desktop-app.md](docs/desktop-app.md).

## Two invariants that a pull request must not weaken

**The mapping never reaches disk.** Scrubbing is anonymisation, not
pseudonymisation. Reports carry counts and positions, never values, and a test
enforces it.

**Verification fails loudly.** Stage 6 re-opens the output, re-extracts it and
searches for every value that should be gone. If your change makes a handler read
less than everything for speed, override `harden_for_verification()` — that hook
exists because a redacted scan carries enough placeholder text to look ordinary,
and verification was inspecting the placeholders instead of the pixels.

## Branching

Gitflow, and the full runbook is [docs/gitflow.md](docs/gitflow.md). The short
version: cut `feature/*` from `develop`, merge it back with `--no-ff`, and open
a pull request against `develop` — `main` receives only a `release/*` or a
`hotfix/*`.

**Run this once per clone**, because git does not distribute hooks:

```bash
python3 scripts/version.py install-hooks
```

That points `core.hooksPath` at `.githooks/`. `post-merge` advances the
development counter when a feature lands on `develop`; `pre-push` refuses a tree
whose nine version sites have drifted, a `main` carrying a development version,
and a `v*` tag that does not match the tree it points at.

They are a seatbelt rather than a gate, and for a reason worth knowing before
you rely on them: branch protection is not available on this repository —
`/branches/main/protection` answers HTTP 403, *"Upgrade to GitHub Pro or make
this repository public"* — so nothing server-side can require a base branch or a
review. A pull request merged in the browser also runs no local hook and so
lands without a bump; finish features locally, and if one slips through,
`python3 scripts/version.py bump dev` puts it right.

Never edit a version by hand. Nine lines in eight files carry it, three of them
lockfile entries, and a bump that misses one breaks `uv sync --locked` or
`npm ci` for everybody else:

```bash
python3 scripts/version.py show -v     # the nine sites and what each says
python3 scripts/version.py check       # also the first step of `ci.py check`
```

## Pull requests

Small, one subject, and green:

```bash
python3 scripts/ci.py check
```

The PR template asks for the benchmark delta when a detector changed — that
field is not decoration.

**GitHub Actions is switched off, so nothing checks a pull request but you.**
This is a private repository and its included minutes were exhausted twice; the
second time, every job on every workflow started failing in two seconds with no
runner assigned and no steps executed, which looks exactly like a broken commit
and is not one. Rather than keep firing at an empty allowance, Actions is
disabled at the repository setting and `scripts/ci.py` runs the same gate here.
The workflow files are untouched, so turning it back on is one command:

```bash
gh api -X PUT /repos/MarcoTribuz/FreeDocs/actions/permissions -F enabled=true
```

`scripts/ci.py check` runs the two workflows a pull request used to run: lint,
format, the suite, the leak checks and the corpus check on Python 3.12 *and* on
3.10, plus the frontend type-check and tests and the Rust bridge's tests. About
seventy seconds. `scripts/ci.py build` does what the bundle workflow did — the
PyInstaller sidecar and the desktop bundle.

What it cannot do is the matrix. CI ran Linux and Windows too, and that is
where this project's cross-platform failures have actually been: `write_text`
translating `\n` to CRLF broke three leak tests, and `npm` being `npm.cmd`
broke the portable build. A green run on your machine is weaker evidence than a
green run there was, and a change that touches paths, file writing or
subprocesses deserves to be said out loud in the pull request rather than
assumed.

Discussion about direction is welcome in an issue before the code exists. Several
things in this repository were measured and deliberately *not* built, and
[docs/benchmark.md](docs/benchmark.md) lists them, so an idea that looks missing may
already have an answer.

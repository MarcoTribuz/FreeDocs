# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FreeDocs removes confidential data from documents so they can be handed to an
LLM. Local, offline, AGPL-3.0. See `README.md` for the positioning and the
competitive gap it targets; the full design and milestone plan live in
`~/.claude/plans/allora-questo-una-recursive-twilight.md`.

**`README.md` is a landing page; the deep documentation lives in `docs/`.** The
README is the 30-second decision — hero, one reproducible demo, the honest "what
it does not do" list — and every long explanation moved to `docs/architecture.md`,
`benchmark.md`, `cli.md`, `hidden-content.md`, `scanned-pdfs.md`,
`desktop-app.md`, `packaging.md` and `llm-review.md`. **It exists in four
languages** (`README.md` canonical English, plus `README.it.md`, `README.de.md`,
`README.fr.md`) and `docs/` is **not** translated: a measurement duplicated four
times is a measurement that disagrees with itself after the next benchmark run.
Inside the translated READMEs the window's own rule applies — enum-shaped things
get real words, engine output is quoted in English verbatim. Every published
figure comes from a `freedocs benchmark` run, and the same figures appear in all
four files; a test of that is a `grep`, not a suite.

**Current state: M8 complete, plus international coverage.** The engine handles
plain text, PDF (born-digital and scanned), `docx`, `xlsx` and `pptx`, with
checksum, NER and value-propagation detection. Identifiers are checksum-confirmed
for twelve countries (ch, it, de, at, fr, be, es, pt, nl, pl, se, gb) and the NER
layer reads it/de/fr/en without being told which. Three passes then correct the
free-text layer: `detect/addresses.py` assembles a street address around its
postal code, `detect/organisations.py` finds a company name from its legal form
where the model found nothing, and `detect/suppress.py` drops the places that
identify nobody. Every table that matches prose folds diacritics through
`core/text.py`, because the tables are written unaccented and real French and
German documents are not. A Tauri app in `app/` drives it
over a JSON pipe, and an opt-in local-LLM pass reviews the output. After reading
the preview a caller can excuse one occurrence or name a value the detectors
missed, through `core/overrides.py`, and stage 6 verifies the result either way.
There is also an opt-in reverse path: `scrub --map` writes an encrypted key file
and `freedocs restore` puts the values back into whatever came back from the
model. Off by default, because it is the one thing that makes a scrub reversible —
see *The reverse path*.
Anything further is new work, not a remaining milestone.

**The window was rebuilt.** Three steps, a design system of its own, the
extracted document shown with every finding marked and walkable from the
keyboard, and an interface in it/de/fr/en. The engine grew the answers that made
that possible and no rules: `inspect` can return the text its offsets point into,
a `stage` notification says where inside a file a run is, and `doctor` and
`countries` publish what this machine can do and what each country actually gets.
See *The desktop app*.

## Commands

All Python work happens in `engine/`.

```bash
cd engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner --extra restore   # Python 3.12, pinned

uv run pytest -q                       # full suite (~675 tests, ~30s with model+OCR)
uv run pytest -q -m "not slow"         # skip the model-backed tests (~1s)
uv run pytest -q -m leak               # only the end-to-end leak checks
uv run pytest tests/test_stream.py -q  # one file
uv run pytest -q -k plan_edits         # one test by name
uv run ruff check . && uv run ruff format --check .

uv run freedocs inspect FILE           # report findings, write nothing
uv run freedocs scrub FILE -o out/     # write a scrubbed copy
uv run freedocs scrub FILE -o out/ --map keys/   # ... plus an encrypted key file
uv run freedocs restore FILE --map keys/FILE.fdmap -o back/   # put the values back
uv run freedocs entities               # list supported entity types
uv run freedocs countries              # list countries and what each one gets
uv run freedocs doctor                 # what this machine can actually do
uv run freedocs doctor --strict        # non-zero when any optional layer is missing
uv run freedocs benchmark              # score detectors against corpus/
uv run freedocs benchmark --detectors "l1,all:gliner2,all:presidio"
uv run freedocs benchmark --countries ch,it              # price a country selection
uv run freedocs benchmark --apply-min-confidence 0.5     # what a scrub would do
```

`--extra ner` fetches ~1.2 GB of model weights to the Hugging Face cache on first
use. CI deliberately omits it: the `slow`-marked tests skip themselves, and
detection quality is measured by `benchmark`, not asserted in CI.

**GitHub Actions is disabled at the repository setting, and `scripts/ci.py` is
the gate.** The included minutes on this private repository were exhausted
twice; the second time every job on every workflow began failing in two seconds
with no runner assigned and no steps executed — which reads exactly like a
broken commit and is not one, and cost an afternoon to diagnose the first time.
The workflow files are deliberately untouched, so re-enabling is one command and
nothing has to be reconstructed:

```bash
python3 scripts/ci.py check       # the pull-request gate, ~70s
python3 scripts/ci.py build       # sidecar + desktop bundle
gh api -X PUT /repos/MarcoTribuz/FreeDocs/actions/permissions -F enabled=true
```

Do not diagnose a two-second all-red run as a code problem. Check
`gh api /repos/MarcoTribuz/FreeDocs/actions/permissions` first: `enabled: false`
is this decision, and an empty `steps: []` on a job that did run is the billing
signature.

Three things in `scripts/ci.py` are not transcriptions of the YAML, because a
laptop is not a runner. The Python floor gets **its own virtualenv**
(`UV_PROJECT_ENVIRONMENT=.venv-310`): CI gives each matrix entry a fresh machine,
but here `uv sync --python 3.10` would *delete* the 3.12 environment it does not
recognise — the local shape of the bug `engine.yml` already documents. **`cargo`
is resolved *and put on PATH***, which are two fixes and not one: it is routinely
absent from a non-interactive shell's PATH, and handing a step the absolute
binary satisfies `cargo test` while doing nothing for `tauri build`, which shells
out to `cargo metadata` by bare name. The first run of the script proved it —
the sidecar built for 143 seconds and the bundle then died instantly on
`os error 2`. Same shape as `FREEDOCS_TESSERACT`, which extends PATH because
PyMuPDF, not FreeDocs, is what runs Tesseract. And `tauri build` is given
`CI=true`, without which the `.dmg` step hangs on Finder automation.

What CI ran and this cannot is **the matrix**: Linux and Windows. That is where
this project's cross-platform failures have actually been — `write_text`
translating `\n` to CRLF, `npm` being `npm.cmd` — so a green local run is a
weaker claim than a green CI run was. Say so rather than forget it. 3.10 is the
declared floor in `pyproject.toml`, so avoid 3.11+ syntax; the floor pass covers
the language question, nothing covers the platform one right now.

**It had never passed once before 22 August 2026, and two of the reasons are
worth not reinventing.** The 3.10 job was never running 3.10: `--python` was
passed to `uv sync` and to nothing else, so the next plain `uv run` chose the
runner's default interpreter, *deleted* the virtualenv it did not recognise, made
a three-package one and died on `Failed to spawn: ruff` before linting a line.
`UV_PYTHON` is job-level for that reason; do not go back to flagging one command.
And one RPC test asked for `detectors="ner"`, which no build without the extra can
answer, so it failed on every run — a model-backed test has to skip itself or ask
something the model is not needed for.

`.github/workflows/app.yml` is the expensive one and it does **not** run on pull
requests. Bundling is 8 minutes on macOS, 13 on Linux and 26 on Windows, three
times over, and it was running on every push to every open branch. It now runs on
a push to `main`, on a `v*` tag, and on `workflow_dispatch`. The trade is
deliberate: a change that breaks packaging is found just after it lands rather
than just before, and the engine workflow — which is what a pull request runs —
covers Windows so the class of bug that motivated the bundle on PRs is still
caught early. Do not add a `paths` filter to it: the same filter would apply to
the tag trigger, and a release tag whose commit touches nothing under `app/`
would silently skip the build that makes the release.

## The desktop app

```bash
cd app && npm install
npm run check          # svelte-check; also proves the four message catalogues complete
npm test               # vitest: offset arithmetic, plural rules, display names
npm run tauri dev      # see the note below before trusting which engine it used
CI=true npm run tauri build   # needs engine/dist/freedocs-engine to exist first

cd engine && uv run --with pyinstaller python packaging/build.py
```

**`tauri dev` does not necessarily run the engine you just edited.** `locate()` in
`src-tauri/src/engine.rs` prefers a bundled resource over the repository venv, and
a bundle left in `target/debug/freedocs-engine/` from an earlier
`packaging/build.py` wins. Symptom: the window is missing a feature the Python
gained after that bundle was built, which looks like a frontend bug and is not one.
Either delete that directory or set `FREEDOCS_ENGINE` to
`engine/.venv/bin/freedocs-rpc`, which beats both.

Two smaller things that cost time: `cargo` is often absent from a non-interactive
shell's PATH, and `tauri dev` dies with the shell that started it, so it needs
detaching to survive. And the engine is one long-lived process — after editing
`rpc.py` the running sidecar still has the old code, so restart the app rather than
reloading the webview.

The app holds **no rules**. Every judgement about what is confidential, what gets
removed and what the user is warned about lives in Python. Two places deciding
what an IBAN looks like is two answers that can disagree, so `app/src/lib/engine.ts`
carries messages and nothing else.

### How the window is put together

Three steps — File, Review, Result — on one route, with a rail. One route
because the wizard state is not addressable and a route change would drop the
in-memory `Inspection`, which cost a PDF extraction to obtain. Reachability is
**derived, never stored**: a step the user cannot be on cannot be the current
one, and two sources for that fact is a window showing Review with nothing to
review.

```
app.css                 the only global stylesheet: tokens, reset, focus ring
routes/+layout.svelte   chrome (theme, language), skip link, the two live regions
routes/+page.svelte     orchestrator: which step, what is reachable, the terminal failure
lib/app.svelte.ts       the session: caps, files, inspections, results, options, actions
lib/review.svelte.ts    per-file review state: selection, filter, block and segment caches
lib/highlight.ts        PURE: blocks(), segment(), rebucket(), codePointOffsets()
lib/i18n/               a typed message contract plus en, it, de, fr
lib/components/         the primitives; lib/screens/ the three steps and their panes
```

**Tokens carry their measured contrast ratio as a comment.** There is no contrast
checker in this pipeline, so a number beside the token is the cheapest thing that
an edit can violate. Three tokens were rejected by that measurement rather than by
taste: white on the chosen accent `#2f9e79` is 3.34:1, below what a button label
needs, so the fill is the same hue at `#22785c`; `--text-3` was 4.26:1 and moved;
the `place` underline was 2.77:1 against its own tint. In dark mode a white label
on the accent measured 2.40:1, so that label is dark.

**Secondary text is a colour, not an `opacity`.** The old window built its whole
hierarchy from twelve opacity values. Opacity cannot be measured for contrast and
dims a border along with the text inside it.

**Dark mode is one attribute and two blocks.** `ssr = false` means nothing paints
before JavaScript, so `lib/theme.svelte.ts` resolves the preference and stamps
`data-theme` while it is being imported — before any markup exists. That is also
what lets a manual choice beat the OS in *both* directions, which a
`prefers-color-scheme` block cannot do without a second copy of the palette.
`system` stays a real third state: the media query is listened to.

**Python counts code points; JavaScript counts UTF-16 code units.** Inside the
BMP they agree, which is almost every document. With an emoji or a rare CJK
character they diverge by the number of surrogate pairs before the offset — and
then every highlight after it is misplaced *and* every `keep_spans` sent back
describes text the user never saw, so `core/overrides.py` either refuses the
decision as stale or keeps whatever moved into that range. `codePointOffsets`
converts for rendering only: `View.marks` holds UTF-16 offsets for slicing the
string, the engine's own offsets stay in `inspection.findings` at the same index,
and **a kept span is always built from the latter**. Sending a rendering offset
back to Python is the one mistake in this window that would look like nothing at
all. The old window never met this because it displayed `finding.text` and never
sliced by offset.

**A finding grows its block rather than being cut by it.** Half a mark is two
clickable things where the user sees one value, and neither half's offsets
describe it. Overlapping findings are a contract violation — the registry resolves
overlaps before anything reaches the wire — so the later one is dropped rather
than merged, and a test asserts every character is emitted exactly once.

**Roving tabindex, and the first mark is the tab stop when nothing is selected.**
Hundreds of buttons in the tab order makes Tab useless, so the marked text is one
stop and the arrows move inside it. The first version made every mark
`tabindex="-1"` in the empty-selection state, which left the document
unreachable from the keyboard; svelte-check's warning about the group handler is
what led to finding it.

**A mark's state is announced by a hidden prefix, not `aria-label`.** A label on a
button that contains text *replaces* that text, so the value itself would stop
being announced.

**Engine prose stays English, and the window says so.** Warnings, limitations,
caveats, review summaries and error messages are quoted inside an element
carrying `lang="en"`, with one line in the reader's language explaining that.
Translating them in Python was rejected: the test suite asserts on their content
and `Leak.describe()` is safety-critical prose; a locale is a property of a UI
session, not of a pipe that also answers the CLI and a report on disk; four
chances to soften a "not installed" into something that reads as "not required"
is four chances to ship a build that quietly finds less. The rule is **if it came
from an enum, translate it; if it came from an f-string, quote it** — entity
names, actions, stage names and country codes get real words, sentences do not.

**Plurals go through `Intl.PluralRules`.** French puts zero in the singular and
the other three do not, which is measured in `plural.test.ts` — that single fact
is why the `(s)` suffix the old window used was wrong rather than merely ugly.

**The frontend tests are Node-only, and that is a scope decision.** Vitest covers
`highlight.ts`, the plural rules, the display names and the catalogues; there are
no component tests, because rendering a `Chip` to assert `aria-pressed="true"`
tests that Svelte writes an attribute we wrote. The discipline that replaces them
is to push logic out of components until they are too dumb to be worth testing —
the review screen's keyboard map is `nextFinding` in `highlight.ts` for exactly
that reason. No browser automation either: `tauri-driver` supports only Linux and
Windows, so a WebDriver suite would run only on the two platforms this app has
been built for and never launched on, and synthetic clicks are refused on this
machine anyway (`-25208`).

What is verified by hand and stated as such: dark-mode appearance, the entity
palette's distinguishability, that the highlight layer is actually smooth in the
webview (Node can only prove `blocks()` is linear), `prefers-reduced-motion`, and
every screen-reader announcement.

`freedocs/rpc.py` is the contract: newline-delimited JSON on stdin/stdout, one
object per line, requests carrying an `id` and progress arriving as notifications
without one. It is tested by `tests/test_rpc.py` because the protocol is all the
app can see, and it is far cheaper to test than the app. Those tests pin
`detectors="l1"` — they are about response shape, and letting them load the model
tripled the suite's runtime.

**The engine is a pipe, never a socket.** It reads and writes files named by
whoever is on the other end, so its only safe caller is a parent process that
already has the user's permission. One process serves the whole session: loading
GLiNER2 takes seconds and running it takes milliseconds.

**The channel carries values; the disk must not.** `inspect` returns the matched
text, because a preview that cannot show what is about to be removed is not a
preview, and that is fine down a local pipe. The JSON report, which does reach
disk, carries counts and positions only. `Leak.describe()` is value-free for the
same reason: that message travels to stderr and through the RPC layer, and an
error about confidential values surviving must not carry them.

**The preview text is opt-in, one blob, and capped.** `include_text` makes
`inspect` return the whole extracted document, which is a *superset* of the
matched values: it contains the confidential text no layer detected. So a caller
that renders no preview never receives a document, and the text must never reach
a report, a warning or an error's `data` block —
`test_the_scrub_report_never_carries_the_preview_text` checks that with a phrase
that is not a finding, which the value-free assertion beside it cannot catch. It
is one blob rather than a window around each finding because `keep_spans` sends
the same offsets back, and a window would mean a second coordinate system and a
second place doing the arithmetic. `MAX_PREVIEW_CHARS` truncates and the response
says so; **the finding list is never truncated with it**, because a finding
hidden to make the numbers agree is the failure this feature must not introduce.

**One read-and-detect path, used by the preview and the scrub.**
`Scrubber.read` and `Scrubber.detect_in` replaced a second copy of those stages
that lived in `rpc.py`. Two copies is how a preview comes to show findings the
scrub that follows it does not agree with. Both take a *path* as well as a
handler, so routing happens inside the stage that reports it.

**A handler's warnings are read twice, and the two readings differ.**
`Extraction.warnings` is a snapshot taken at extraction time — complete for a
preview. A handler goes on warning during write-back (a placeholder shrunk to
fit, a renamed sheet, an embedded workbook), so `ScrubResult.warnings` is built
from the *live* handler. Merging them into one list dropped three of those, and
the tests said so; `Inspection.notes` keeps the configuration's warnings apart
for that reason.

**Extractions are cached per `(path, mtime, size)`, four at a time.** Every kept
occurrence re-inspects, because propagation means one decision can change other
findings and the window is not allowed to guess the new answer — and without the
cache that re-OCRs every page of a scan for a file that has not changed. A file
whose size or modification time moved is read again: serving old text would show
a preview of a document that no longer exists.

**`TextStream.part_at` is a bisect, not a scan.** The `rpc._part_of` it replaced
walked every anchor once per finding, which on a 200-page PDF is tens of
thousands of anchors times hundreds of findings — exactly the document the
preview is for.

**Progress is two notifications, and neither claims a percentage.** `progress`
counts files and is unchanged, byte for byte, which is what
`test_scrub_emits_progress_per_file` is now the proof of. `stage` says where
inside one file the run is. There is no `percent` and there must not be one: how
long detection takes next to extraction on an unseen document is not a fact the
engine has, so `index`/`count` counts *stages* and `done`/`of` appear only where
a stage has a real unit (pages, so far).
`test_no_stage_notification_claims_a_percentage` guards it. `count` comes from
the plan the run is executing — six stages, seven with a reviewer, three for an
inspection — which is also why `capabilities` publishes no stage list: a stepper
drawn from one would be wrong for both of those cases. Stage names are a closed
vocabulary pinned by a test, because the window translates them by key.

NER chunk progress is deliberately absent. The loop is countable, but it sits
inside a swappable backend and CI installs no `ner` extra, so the plumbing would
ship untested; `done`/`of` are optional on any stage, so adding it later is one
line in `ner.py` and no protocol change.

**A cancel button needs a reader thread, and is out of scope.** `serve()` is
`for line in source:`, so while a request runs nobody reads stdin and a `cancel`
sits in the pipe buffer until the request it named has finished — the
notification alone changes nothing. Doing it properly means a daemon reader
thread, a cancel that names the request id (without it, a cancel racing the end
of request 7 kills request 8), writes staying on the main thread, and
`test_stdin_closing_still_ends_the_session` written *first*. Until then the way
out is killing the sidecar, which costs a GLiNER2 reload — and the extraction
cache above removes most of the wait that made the button feel necessary.

### Packaging

One-dir, not one-file: a one-file bundle unpacks half a gigabyte of torch to a
temp directory on every launch. `tauri.conf.json` ships it as a resource and
`src-tauri/src/engine.rs` spawns the executable inside it, falling back to the
repository virtualenv so `tauri dev` works before any bundle exists.

**`packaging/build.py` must exercise the model, not just `capabilities`.** Every
format handler and detector backend imports lazily, and `NerDetector` is
constructed without touching gliner2 — so `capabilities` cheerfully reported the
NER layer present in a bundle that had no model stack in it at all, and the first
real document failed. The smoke test now inspects a sentence with a name in it and
demands a `PERSON` finding. Anything imported inside a function needs
`collect_submodules` in the spec; PyInstaller cannot see call-time imports.

**`CI=true` is required for `tauri build`.** The `.dmg` step runs AppleScript to
arrange icons in a Finder window; without Finder automation permission it fails
with `AppleEvent timed out (-1712)` after minutes of bundling. Tauri passes
`--skip-jenkins` when `CI` is set. The `.app` is unaffected.

**Multi-platform is built, not run.** `.github/workflows/app.yml` bundles macOS
arm64 (`macos-15`), Linux (`.deb`) and Windows on their own runners, because
neither PyInstaller nor Tauri cross-compiles, and all three are green. That means
the sidecar builds, the smoke test loads the model and the installer is produced
— it does not mean anyone has launched the result anywhere but macOS. Say "builds"
and not "works" for Linux and Windows.

Two platforms are absent and the reasons differ. **Linux ships a `.deb` and no
AppImage**: the `.deb` bundles fine and the run then dies in `failed to run
linuxdeploy` with no diagnostic of its own. **Intel macOS is not built at all**:
`macos-13` was retired and the job simply queued forever with no runner assigned
— which looks exactly like a slow build — while the replacement `macos-15-intel`
is a billed larger runner. Cross-compiling from arm64 would cover the Rust half
and not the sidecar, so an Intel bundle needs an Intel machine. Both are gaps
rather than decisions about who to support.

`macos-14` was working when it was replaced by `macos-15`. It is *deprecated*,
which is the state `macos-13` was in shortly before it stopped being assigned
anything, so a deprecated runner label is worth moving off before it becomes a
job that hangs instead of failing.

## Architecture

Six stages, and only `pipeline.py` knows the order:

```
router -> extract -> detect -> policy -> write-back -> verify
```

`core/stream.py` is the load-bearing piece and worth reading before anything
else. The problem it solves: the text a detector reads and the bytes a writer
edits are not the same object. Word can store `Mario Rossi` across three runs, so
a detector needs it joined while a writer needs it split — flatten it naively and
the formatting is gone, which is why competing tools emit plain text.

The mechanism is an offset map. Extraction appends anchored chunks to a flat
string; each `Anchor` records where its characters came from (`part` plus an
opaque `locator` the handler alone interprets). Detection runs on the flat text.
`TextStream.plan_edits()` translates spans back into `AnchorEdit`s, placing the
replacement in the first anchor an edit touches and clearing the rest, so
surviving runs keep their own properties.

Consequences worth keeping in mind:

- Stages 3, 4 and 6 are format-agnostic and shared. Adding a format means
  implementing `extract`, `write_back` and `scrub_hidden` in
  `formats/base.FormatHandler` and nothing else. Do not let format knowledge
  leak into `detect/`, `core/policy.py` or `verify.py`.
- Separator text goes in via `add_filler()`, not `add()`. Filler has no source
  location, so an edit that lands only on filler raises rather than silently
  writing nowhere.
- Detectors must produce character offsets. This is why a generative LLM cannot
  be the primary detector: no reliable offsets, nothing to anchor.

### Detection layers

`detect/registry.py` merges layers and resolves overlaps by precedence
(L1 > L2 > L3), then span length, then confidence. Two edits may never touch the
same characters.

- **L1** (`detect/validators.py`, shipped): regex nominates, checksum decides.
  Forty rules over twelve countries, every validator from `python-stdnum`, which
  ships 201 number modules across 87 countries. Add identifiers here as a `Rule`
  with its `country`, and always pair the pattern with a real validator rather
  than tightening the regex.

  `SUPPORTED_COUNTRIES` is the list the CLI validates against, `capabilities`
  publishes and the window's chips are built from. A country in it with no rules
  needs a reason: the United States is the only one, present for its numbering
  plan and the model because neither of its numbers has a check digit. A test
  pins that so a third case cannot appear silently.
- **L2** (`detect/ner.py` + `detect/backends/`, shipped): GLiNER2 for names,
  organisations, locations, addresses, job titles. One `mdeberta-v3-base` model
  covers it/de/fr/en with no language hint. Backends are swappable so the choice
  rests on `benchmark` output; `presidio_backend.py` is the measured alternative,
  kept installable so the comparison stays reproducible.
- **L2.5** (`detect/propagate.py`, shipped): copies each confirmed value to its
  other occurrences. Runs after overlap resolution, then resolves again. Values
  of fewer than `MIN_PROPAGATION_LENGTH` (3) characters do not spread, and a
  legal form never spreads at any length — see the invariant below for why those
  are two separate rules.
- **L2.55** (`detect/addresses.py`, shipped): assembles `<street> <number>,
  <code> <city>` and the British inversion, anchored on the postal code. Fills
  gaps and absorbs a LOCATION it fully contains — the city the model returned
  instead of the whole address. Runs before the other two, because its span is
  the largest of the three.
- **L2.6** (`detect/organisations.py`, shipped): nominates a company name from
  the legal form that follows it, and **only where no layer claimed those
  characters**. It is a gap fill, not a detector — see the invariant below.
- **L2.7** (`detect/suppress.py`, shipped): removes findings that name something
  real and identify nobody. Country names and lowercase common nouns go on both
  sides of propagation; jurisdictions go only after it. Also the invariant
  below, because the two halves are not interchangeable.
- **L3** (`detect/llm_review.py`, shipped, off by default): an Ollama pass over the
  *already anonymised* text, flagging leftovers and quasi-identifiers. Advisory
  only, and not part of the registry — it produces no spans and drives no edits.

Do not add a language-detection step to make Presidio viable. It was measured:
running all four languages and merging is what pushes its PERSON precision to
0.28 and its over-redaction to 21%, and a detector guessing the language is one
more thing that fails silently on short or mixed text.

`NerDetector.min_score` defaults to 0.5 because a threshold sweep on the corpus
was flat from 0.2 to 0.6 and degraded above it — not because 0.5 looked sensible.
Re-run the sweep before changing it.

**Confidence per rule is a measurement, not a judgement.** `STRONG_CHECK`,
`MEDIUM_CHECK` and `WEAK_CHECK` in `validators.py` come from running each
validator against 20 000 randomly generated format-plausible values and counting
how many it accepts, anchored on the Italian partita IVA at 1.05% and 0.55 since
M0. Re-measure before changing one. Effective strength is pattern specificity
times checksum strength and only the second half is in that table, which is why
`ch-uid` is safe at full confidence while accepting 9.09%: the literal `CHE`
discards almost every candidate first.

**A validator that accepts most of what it sees is not a validator.**
`stdnum.us.ssn` accepts 89% of random values of its shape, `us.ein` 83%,
`at.businessid` 100% and `de.handelsregisternummer` 90% — they check format, or
need a court's city. Those identifiers are not in the rule table and must not be
added by tightening a regex to compensate. The model answers for them, and
`report.CAVEATS` says so.

**A rule below `min_confidence` is inert, and that is the design.** The weak
country rules do nothing at default settings unless a word naming them is nearby,
so they are keyword-gated rather than a second opinion. This also means the
benchmark charges for work the pipeline never does: `evaluate` calls `detect`
directly, so `freedocs benchmark --apply-min-confidence 0.5` is what reports the
pipeline's number and the bare command reports the detector's.

**Context keywords come in two kinds and they need opposite matching.**
`detect/keywords.py` splits every family into `*_STEMS`, matched as substrings,
and `*_CODES`, matched as whole words. Whole-word matching for everything was
tried and lost four cases the corpus already carried: `karte` is the tail of
`Firmenkarte` and `Zahlungskarten`, `card` the head of `cards`, `carte` of
`Cartes`. Substring matching for everything fires `iva` inside `arriva`, `vat`
inside `salvataggio`, `nif` inside `definisce`. Both tables are the union across
the languages covered, for the same reason Presidio runs every language: the
engine does not know which one it is reading.

Two mechanisms in `Rule` exist because of specific bugs, not as decoration:

- `shrink_to_fit` — the IBAN pattern is deliberately greedy and absorbs trailing
  digits; mod-97 then decides where the IBAN really ends. Without it,
  `CH93 0076 2011 6238 5295 7` was truncated to 20 characters and rejected.
- `confidence_without_context` — eleven digits passing an 11-digit Luhn is weak
  evidence, so partita IVA and card numbers drop to sub-1.0 confidence when no
  keyword is nearby, and `Policy.min_confidence` makes the call.

Phone detection uses `phonenumbers` with `Leniency.STRICT_GROUPING`. Do not
loosen it: under `VALID` the Italian numbering plan reads `03.03.2024` as a phone
number, and business documents are full of dates.

**One region-less pass, then one per country, and the split is not arbitrary.** A
number carrying its own country code is unambiguous, so *any* region argument
parses it and the `None` pass finds every international-format number in a single
sweep. It finds not one locally-written number: `044 668 18 00` is matched only by
`CH`. Measured on the corpus — the region-less pass alone gives 82.9% PHONE
coverage at precision 1.00, all thirteen plans 97.1% at 0.67 — and all of them are
on because a number a scrub leaves behind gets sent. Dedup is on **overlap**, not
an identical span: three plans read `044 910 55 66` and disagree about where it
ends, and the near-misses used to reach the registry as an intra-L1 contest at
equal precedence and equal confidence.

**`confirms()` needs to know which country, and usually does not.** One global
algorithm settles an IBAN or a card number wherever it was issued, so a failed
check digit is a rejection. A country-issued type is different: `TAX_ID` is
claimed by twelve countries and by none of the other hundred and eighty, so a
Brazilian CPF the model correctly spotted passes nothing here, and "no covered
country accepts it" is not evidence. Without a country there is no opinion.
Gating on the *pattern* instead was tried and reopens the bug the mechanism exists
for: the model's card claim is the text `1500\t2300`, which no card pattern
matches, so it would have been kept.

### The review layer

It is **not a detector** and must not become one. It has no offsets, and the
anchors are the only route from a finding to a run or a rectangle. It runs after
`verify`, on the text `verify` already re-extracted from the output — re-extracting
a scanned PDF would mean OCRing every page a third time, and `VerifyResult.extracted`
exists for exactly that reason.

Three properties to preserve:

- **`ReviewOutcome.ran` is separate from an empty `concerns` list.** "Ollama was
  not running" and "the reviewer had no objection" are different facts, and the
  second is reassuring. Collapsing them lets a silently skipped review read as a
  clean bill of health.
- **A non-loopback host is refused** without an explicit `allow_remote`. This is a
  tool whose premise is that documents do not leave the machine; a review host on
  the network is a decision, not a default. `_is_local` deliberately does not
  resolve hostnames — whether one still points at loopback tomorrow is not this
  code's call. `available_models` applies the same guard and shares the message
  through `_refuse_remote`: listing a host the scrub would then refuse reads as a
  bug, and two wordings for one rule is two rules to reason about. Unreachable
  still returns `[]` rather than raising — refused is loud, absent is quiet.
- **Where Ollama lives is configuration, not a rule.** `capabilities` reports the
  default host so the app can prefill it instead of holding a second copy, and the
  `review_models` method answers for one named host. Without it an Ollama on a
  non-default port left the window showing an empty list with no way to correct it.
  `allow_remote` stays reachable over the pipe with no control in the window: the
  opt-in belongs to a caller that states it, not to a checkbox.
- **An unreachable Ollama is reported, never raised.** `review_outcome` converts
  `OllamaUnavailable` into a stated fact, because a missing advisory layer must not
  fail a scrub that otherwise worked.

The response schema is passed to Ollama and enforced server-side, so "the model
ignored the format" cannot happen; `_parse_concerns` is defence, not parsing. Its
quotes come from the *scrubbed* text, which is why they are safe to print and to
put in the report.

## Invariants

Break these and the tool stops being trustworthy rather than merely buggy.

**The mapping never reaches disk.** Scrubbing is anonymisation, not
pseudonymisation. `SurrogateAllocator` keeps placeholder-to-original in memory
for one run and `pipeline.py` closes it in a `finally`, so a crash cannot leave a
re-identification key in a live process. Reports carry counts and positions,
never values — `test_report_contains_no_confidential_values` enforces this.

**Verification fails loudly.** Stage 6 re-opens the output, re-extracts it
(hidden parts included) and searches for every value that was supposed to be
gone. In strict mode a survivor raises `LeakDetected` and the CLI writes nothing.
A nearly-clean file is more dangerous than an obviously dirty one, because it
gets sent.

**Canaries must pass their real checksums.** A test value with a bad check digit
is rejected by the validator, so nothing is detected, nothing leaks, and the leak
test passes while proving nothing. `tests/conftest.py` holds verified values;
when adding one, compute the checksum rather than inventing it. Two of the four
codice fiscale values tried during M0 were invalid. The same applies to the
corpus: `test_corpus.py` asserts that every annotated identifier is actually
accepted by L1, so a bad value cannot make a detector look worse than it is.

**But "L1 rejects it" and "the value is fake" are different failures.** That test
used to cover PHONE, and it forbade a case worth having: `+39 0444 512 337` is a
valid Italian number that `STRICT_GROUPING` declines, because the numbering plan
groups the subscriber part as `512337`. Asserting it away would hide a real gap in
L1 — one GLiNER2 in fact closes, which is the layering working and is now visible.
So phone canaries are checked with `phonenumbers.is_valid_number` (is the value
real?) and the detection assertion is kept for the types L1 owns from pattern to
checksum, where a miss really is a corpus defect.

**Coverage is scored over the entities the policy removes.** `REPORT_ONLY` types
are flagged and never deleted, so "share fully removed" is meaningless for them in
both directions: finding every job title makes no document safer, and missing one
leaks nothing. They were 36 of 378 annotations and were inflating the headline.
`metrics.py` counts them apart (`report_only_recall`) and marks them in the
not-covered list so nobody reads one as a leak. `coverage_all` is kept for
comparison with figures published before the split.

**Quality is measured, not asserted.** Format tests pin the registry to L1 via
`tests/conftest.l1_scrubber()`, because they are about write-back and a model in
the loop makes them slow and threshold-sensitive. Detection quality lives in
`freedocs benchmark` against `corpus/`. Do not encode one model version's spans
in a unit test: the next model would "fail" while being better.

**Gold offsets are derived, never hand-written.** `corpus/*.txt` uses inline
`[LABEL:text]` markup. Hand-maintained offsets rot silently — insert a word and
every number after it is wrong — and then the benchmark measures the annotation
instead of the model. An unknown label is an error, not a skip: a dropped
annotation gets scored as a detector hallucination.

**The corpus has to be able to make something fail.** It is 537 annotated
entities across the four language files `corpus/{de,en,fr,it}.txt`, up from 103,
and growing it is what moved the headline down from 99.0% — the instrument
getting sharper, not a regression. `freedocs benchmark` prints the counts it
actually loaded, so trust that line over any figure written down here.

The French, German and Italian files are also written **with their accents**, and
that is load-bearing rather than cosmetic. They were ASCII until the day the
tables that match prose were found to be comparing unaccented entries against
text that has accents in it, and an ASCII corpus cannot show that failure at all.
The accents were added by substituting one codepoint for one codepoint
(`numero` → `numéro`, `ungultig` → `ungültig`), which is what let it happen with
no gold offset moving and no chunk boundary shifting — see the boundary note
below for why that mattered.

What the small corpus could not report: LOCATION is the only category still
leaking, at 94.3% coverage and 0.85 precision against PERSON's 100% and 1.00. Both
remaining leaks are a place name that also appears as somebody's surname in the
same document (`Lyon`, `Firenze`), which is a disambiguation no pattern can make —
and note *which* half fails: the model finds `Nathalie Lyon` and `Roberto Firenze`
and never the bare place, so there is no confirmed occurrence for propagation to
copy either. `Zug` and `Sion` looked like the same case and were not; see the
propagation floor below. Keep these collisions when editing the corpus; they are
the finding, and at 99.6% coverage they are most of what is left to find.

**Adding corpus text moves NER chunk boundaries, and that alone changes
coverage.** Appending six lines to `corpus/fr.txt` cost the annotated
`Meir 78, 2000 Antwerpen` two lines above it: the text is near the end of the
file, the final `iter_chunks` window moved, and GLiNER2 stopped returning an
address it had returned before. Verified by re-running with the new rules
disabled — the leak is there either way. So when the corpus grows, attribute the
delta before believing it: a rule and a boundary shift look identical in the
headline. It is also what forced `MAX_CHUNK_CHARS` to be measured rather than
guessed, which it now has been — see below.

**`MAX_CHUNK_CHARS` is 1200 because a sweep says so, and the sweep also refused
the obvious improvement.** Removable coverage is flat from 800 to 1500 (474 to 477
of 480) and falls above it; over-redaction improves monotonically with size (752
characters at 800, 493 at 3600) and flag-only recall collapses (96.2% at 1500,
76.9% at 3600). 1200 sits in the plateau and takes most of the over-redaction win
before either cost begins.

Two things the sweep settled that the old comment had wrong. The stated reason for
staying low — that an encoder silently truncates past 512 tokens, hiding a whole
document after the first page — **does not hold for this backend**: a name placed
at increasing depth in a single call still comes back at 9815 characters, with the
score decaying only 0.997 to 0.954. The ceiling is a quality trade, not a token
limit. And `CHUNK_OVERLAP` of 400 appears to dominate 200 on every column of the
corpus as it stands — one more entity, eleven fewer over-redacted characters, the
best exact F1 in the sweep — and none of it survives a control. Prepending 137,
411 and 700 characters of unannotated text to shift every boundary makes the
coverage win a wash and the over-redaction win a consistent loss, 620 characters
against 595 averaged over the four alignments.

That control is the transferable part. The same shift moves 1200/200 itself
between 473 and 477 of 480, so **three entities is the noise floor** on this
corpus and no delta smaller than that can be read off it. Any future tuning of a
chunking parameter needs the shift control, not just a better headline.

The four files also each end with a governing-law and payment block, added
unannotated. Those clauses are the cases `detect/suppress.py` is paid to pass,
and they are the reason `Basel`, `Geneve`, `Lugano` and `Milano` each appear both
as somebody's location and as a jurisdiction. Do not annotate them, and do not
delete them: without a document where the same string is confidential in one
sentence and not in the next, nothing here can be measured at all.

**At twelve countries a value broken for one checksum is often valid for
another.** `192598180` was written into the corpus as a rejected Polish REGON and
is a valid Portuguese NIF; `4360730410` was a rejected Polish NIP and is a valid
British UTR. At two countries "change the last digit" produced a value nothing
accepts; it no longer does, so a trap has to be checked against every rule.
`test_no_unexpected_identifier_is_found_outside_the_annotations` keeps that list
closed, scoped to the checksum-backed types — a numbering plan is not a checksum
and several plans read the same digits, so pinning those would pin one version of
the phonenumbers metadata.

**The corpus had no locally-written phone number until it was measured.** Thirty
annotated numbers, every one in international format, so it could not show what
the national plans buy and the honest comparison needed the gap filled first.
`test_annotated_phone_numbers_are_real_numbers` had to learn the same lesson: it
parsed with region `None`, which cannot read a national number at all, so adding
real ones made a correct annotation look invented.

Unannotated text is scored as over-redaction, so **an adversarial case must be a
realistic string a checksum rejects, never a valid identifier relabelled as
ordinary text.** Three of the traps first written here reused the same digits as an
annotated identifier elsewhere, which made one string both confidential and not.
The good ones: identifiers with a broken check digit (all correctly refused), a
four-part firmware version indistinguishable from an IPv4 address, and an
eight-digit customer number that is a valid Italian landline. The last two are why
IP and PHONE precision sit at 0.83, and no regex can settle either.

`evaluate()` calls `detect()` directly, so `Policy.min_confidence` is **not**
applied. The benchmark measures the detector, not the pipeline. Do not tune a
corpus trap against a threshold that is not in the loop.

**The postal code is the part of an address that needs no model.** GLiNER2 found
thirty-six of forty-one annotated addresses and all five misses failed the same
way — it returned the city as a LOCATION and dropped the street, so the house
number, street and postcode stayed in the document. `detect/addresses.py` finds
the code first and reads outwards, which took ADDRESS coverage from 87.8% to 100%
and LOCATION precision from 0.73 to 0.82, the second because the partial city
findings are absorbed rather than left beside the address.

A comma is not enough to find the left edge. `residence Meir 78, 2000 Antwerpen`
has no comma before the street, so a regex scanning back to the previous
punctuation yields `residence Meir 78`. The scan is a token walk with an explicit
vocabulary — capitalised words, house numbers, the connectors inside a street
name, and the lowercase words that *are* street types in the languages covered —
and anything else ends the address. Three details are each there for one corpus
case: a city word may not carry a full stop (`Napoli. Codice` was one address), a
short abbreviation may lead one (`St. Gallen`), and an elided article glued to a
capitalised name is a name token (`Rue de l'Industrie 9` was the last miss).

**A labelled-field extractor was measured and not built.** The source layer this
would have come from anchors on `Registered address:`, `Authorised signatory:`
and the like, and it is the largest thing in that codebase this engine does not
have. It was tested before being written: `corpus/en.txt` and `corpus/de.txt` now
end with a tab-separated onboarding form and a signature block — the first
tabular text in the corpus, since the engine handles docx and xlsx tables and the
corpus held only prose. GLiNER2 found all sixteen annotated entities in them, with
no false positive on any label. A harder probe put a spreadsheet header 1900
characters and one chunk away from its name column: all four names came back at
0.91 to 1.00.

The reason is structural and worth keeping. That codebase needs the layer because
it extracts plain text and *then* chunks it, and its own comment records an
800-character chunk starving the model of `Registered address:` until the score
fell to 0.345. `core/stream.py` keeps a label and its value adjacent in the flat
text, so the label is in the window anyway — and GLiNER2 does not need it, because
it reads the name. Do not add the layer without a corpus case; the form block is
there so the absence of one stays a measurement rather than an assumption.

The one thing the form block does show is a mislabel: `Urs Frei` after
`Zeichnungsberechtigt:` comes back ORGANISATION rather than PERSON. The characters
are still removed, so it is not a leak, and it is kept in the corpus as the
standing case for anyone who wants to argue for the layer on label quality.

**A gap fill must not compete with the layer it backs up.**
`detect/organisations.py` nominates a company name from the legal form after it,
and skips any candidate overlapping an existing finding *of any type*. Run as a
peer detector it was strictly worse: German capitalises common nouns, so the
backward scan produced `Kunde Nordwind Logistik GmbH` and
`Die Tochtergesellschaft Nordwind Logistik Deutschland GmbH`, each beating the
model's correct span because `_sort_key` prefers the longer span at equal
precedence. That cost eight points of ORGANISATION precision to gain one name.
Restricted to gaps it gains the same name and changes nothing else. Short legal
forms are matched **case-sensitively** for the same class of reason: `sa` is a
French possessive, `ab` a Swedish preposition, and lowercasing a two-letter form
turns every sentence into a company.

**Suppression is split across propagation, and the halves are not
interchangeable.** `detect/suppress.py` answers two different questions.
`drop_non_identifying` judges a *value* — a bare country name identifies nobody
anywhere, so it runs on both sides and cannot spread.
`drop_jurisdiction_mentions` judges an *occurrence* — the same city is
confidential in the party's address and not in "the courts of Zurich" — so it
runs **after** propagation only. Filtering jurisdictions first was measured and
cost three covered entities to save seventy-two over-redacted characters:
`Basel`, `Geneve` and `Milano` are each found by the model *only* in the clause,
and that sighting is the template propagation needs to reach the same city in the
address twenty lines up. Kill the clause mention early and the address survives.

**A suppression rule needs a corpus case, and the burden of proof runs the other
way here.** Every other rule can be wrong and merely noisy; this one can be wrong
and turn a working scrub into a leak. The country list came from six measured
false positives, the lowercase-organisation rule from two, the jurisdiction
patterns from nine. The currency rule that the same source suggested was
**dropped**: GLiNER2 never tagged "Swiss francs", "francs suisses" or
"United States dollars" at all, because FreeDocs has no nationality entity type
for "Indian" in "Indian Rupees" to land on. Do not add it back without a case.

Giving it one was tried and rejected — see the special-categories note below. The
short version is that the nationality type would not have made the currency rule
necessary either, because it lands on the adjective and the adjective is
`REPORT_ONLY`.

**City-states stay in.** Luxembourg, Monaco, Singapore, San Marino and Andorra
name a city as often as a country, and the country list drops findings outright,
so an ambiguous name in it is a leak. When the name could be either, the finding
stays.

**The propagation floor is 3, and half of the reason it used to be 5 was wrong.**
`MIN_PROPAGATION_LENGTH` was the only thing keeping `Zug` and `Sion` in their
documents: both were already confirmed findings elsewhere, so nothing but a length
test stood between them and the occurrence that survived. A sweep over 5, 4, 3 and
2 recovers `Sion` at 4 and `Zug` at 3, moves over-redaction not one character at
any floor, and gains nothing further at 2.

The old comment justified 5 on two grounds and only one of them was true. Short
strings do **not** match "inside unrelated words" — the pattern is bounded by
`(?<!\w)`/`(?!\w)` and never matched `Zug` inside `Zugang`, which is now pinned by
a test. What is true is the legal forms, so those are excluded **by name** rather
than by length, from the table `suppress.py` exports: a document where a detector
claims a bare `Ltd` would otherwise spread it to every other `Ltd` on the page,
which is not a second sighting of anything. It does not happen on the corpus — no
detector claims a bare legal form there — so that guard is against a case built to
break it, and it is the one part of the old floor's reasoning that survived.

This is also why `Lyon` and `Firenze` still leak while `Zug` and `Sion` do not.
Those two never appear as a standalone finding at all, only inside `Nathalie Lyon`
and `Roberto Firenze`, so there is no template to copy — propagating a substring of
a person's name to every place it occurs is exactly the inference `propagate.py`
refuses in its own docstring, and lowering a floor cannot reach them.

**A digit-free identifier claim is refused before any checksum runs.** `confirms()`
cannot refuse it: a country-issued type arriving from the model without a country
gets no opinion by design, which is the mechanism that keeps a Brazilian CPF. So
`cittadinanza italiana` came back NATIONAL_ID at 0.79 and `Turkish` at 0.52, both
above `Policy.min_confidence`, and each was removed and replaced with
`[NATIONAL_ID_1]`. That is worse than an ordinary false positive — it destroys the
sentence's meaning *and* files a nationality as an identifier. No identifier this
tool covers is written without a digit, and every annotated identifier in the
corpus contains one, so `registry._STRUCTURED` gates on that. The corpus cannot
show this one: in a full document the model returns nothing for that phrase, so the
evidence is the unit case and `corpus/it.txt` carries the sentence only as a
standing trap.

**Special categories were measured and are not detected.** Nationality, religion
and political affiliation are GDPR Article 9 data and FreeDocs has no entity type
for them, which is a decision and not an oversight. Asking GLiNER2 for
`nationality`, `religious affiliation` and `political affiliation` works on a
sentence that discloses one — `deutscher Staatsangehöriger` at 0.96, `Turkish
national` at 0.99, `nationalité algérienne` at 0.81, `SPD` as a political
affiliation at 0.97. On the corpus it returns eleven findings and **none of them is
that**: every one is an adjective modifying a thing, not a person — `deutsche
Konto`, `Dutch account`, `Swiss identification number` four times, `Swiss francs`.
Business documents use nationality words that way almost exclusively.

The cost of asking was two covered entities. Three more labels shift the model's
output distribution enough that `Preston` and `Neuchatel` stop being returned as
LOCATION: removable coverage 483 to 481, over-redaction 595 to 696 characters,
flag-only recall 92.3% to 86.5%, exact F1 0.929 to 0.912. Measured by injecting a
narrowed backend, which needs `load_backend.cache_clear()` — it is `@cache`d, and
patching `DEFAULT_LABELS` or the dataclass field after import silently does
nothing, so two runs agree and both are the unpatched one.

If this is revisited, the shape that avoids the interference is a second `predict`
call with only the special-category labels, merged as a strict gap fill that never
competes — a `REPORT_ONLY` finding winning an overlap against a LOCATION would stop
that LOCATION being removed, which is a leak. It costs a second model pass per
chunk, and it still needs a corpus document that actually discloses somebody's
nationality, which none of the four currently does.

**Chunk-artifact rejection was measured away.** A finding whose span starts or ends
mid-word is the signature of a chunk-boundary hit, and `iter_chunks` has a
guaranteed-progress fallback that can cut mid-word, so the defence looked free.
There are **zero** such findings across the corpus. The test was written first, as
the plan required, and it said not to build the rule.

**The human override is a layer, not a setting, and `keep` is the dangerous
half.** `core/overrides.py` carries what a person decided after reading the
preview: occurrences to leave alone, and values to remove that no detector
nominated. Every other control in the engine can only cause a value to be
*removed*; this is the one that can cause a value to stay, so it is built with the
burden of proof on that side.

Four decisions, each of which has a failure it prevents:

- **`Layer.HUMAN` outranks `VALIDATOR`.** An override a checksum could overrule is
  a suggestion, not a control. It is a layer purely so that `LAYER_PRECEDENCE`
  settles an overlap; it is not a detector and produces nothing without a caller
  supplying the decision.
- **A keep is a span, a removal is a value.** The window lists one row per
  occurrence, so "keep this one" is a range the caller already has — and it *must*
  be a range, because the same city is confidential in a party's address and not
  in a jurisdiction clause, which is the distinction `detect/suppress.py` exists
  for. A removal has no row to point at and no coordinate the caller could have
  got, since the preview sends findings and not the document text, so it names a
  string and every occurrence goes.
- **A kept span carries the text it covered, and a mismatch raises.** Offsets come
  from a previous extraction; nothing guarantees the file is unchanged. Honouring
  a stale span keeps whatever moved into that range while the caller believes they
  excused something harmless — so `StaleOverride` refuses it and names the
  decision. A removal that matches nothing is the opposite case and is reported as
  a warning: "removed" and "was not there" look identical in the output.
- **Decisions are scoped per document.** A batch is one request, and a span is an
  offset into one extraction, so `Override.for_path` splits them and `rpc.scrub`
  re-binds the `Scrubber` per file. Without it the second file of a batch is
  checked against the first file's spans and fails as stale — the check working on
  a question nobody asked.

**Stage 6 needed an allowance, and it is a count rather than an exemption.**
Verification is value-based and an override is occurrence-based, so keeping one
`Zurigo` and removing the next leaves the string in the document and the search
for it finds a survivor. This was found by the leak check failing on the first
end-to-end run of the feature, which is the check earning its keep. `verify_output`
now takes `kept` and permits each value exactly as many times as were kept — so a
write-back that quietly failed on the *other* occurrence is still a hard failure,
and `Leak.describe()` says the failure is the excess so it cannot be read as "the
override did not work". Nothing infers an allowance; it is granted only by a
caller naming the occurrence.

**`EntityType.OTHER` is reachable only through an override.** A caller who has not
said what a value *is* has still said it must go, and inventing a category for
them would put a guess in the output where a placeholder belongs. No detector
produces it — a detector that cannot name what it found has not found anything.
An unknown entity name on the wire is an error rather than a quiet downgrade to
`OTHER`, because a caller working from a different contract would otherwise get an
unexpected placeholder in their document.

**The window gained controls, not rules.** `lib/app.svelte.ts` collects spans and
strings and sends them; every judgement about what happens to them is in Python,
the same reason `app/src/lib/engine.ts` carries messages and nothing else. The two
`keep` controls are deliberately separate in the UI and on the wire: `keep` names
entity *types* to leave alone everywhere, `keep_spans` names single occurrences,
and one control for both would make "this Zurich is fine" mean "no location is
confidential". They are two visibly different controls in the detail panel for the
same reason.

That rule is also why two things in the window are read from the engine rather
than worked out locally. Which layer found a value comes from `Finding.layer`, not
from the shape of the detector string — the window used to read a colon as "the
model", which was the app holding a rule about the engine's naming and would have
started lying the moment a backend was renamed. And the example placeholder in the
advanced panel is composed by the engine's own `SurrogateAllocator`, so a preview
cannot promise `[PERSONA_1]` and produce `[PERSON_1]`.

Verified through `tests/test_rpc.py` rather than by driving the window, for the
reason at the top of that file — and note what could *not* be verified that way:
synthetic clicks are refused on this machine without accessibility permission
(`-25208`), so the in-window click-through has been seen to render but not seen to
be clicked.

**A kept span is built from the engine's offsets, never from the rendering
copy.** This is the frontend half of the same invariant and it has its own trap:
see "Python counts code points" under *The desktop app*. The offsets the
highlighter slices with are UTF-16 and the ones the engine indexes with are code
points, and they differ the moment a document contains an emoji.

**Placeholder families were considered and declined.** `[ORGANISATION_1]` /
`[_1a]` / `[_1b]` for `Acme`, `Acme Corp.` and `Acme Corporation` would tell the
model reading the output that those are one company — and would equally tell any
reader that those three strings were related, which is a re-identification thread
this tool cannot take back. PII-Shield can afford it because it restores the
values afterwards; FreeDocs never does. Flat numbering stays. This is a threat-model
decision, not a measurement, so do not reopen it as a patch.

**Everything that matches prose against a table folds diacritics, through the one
function in `core/text.py`.** Two copies of that function are two answers to the
same question, which is how the bug got in: `suppress.py` folded and
`Rule.confidence_at` merely casefolded, so five entries in `detect/keywords.py`
(`securite sociale`, `numero de tva`, `numero national`, `numero fiscal`,
`gultig bis`) never met the `sécurité sociale` or `numéro de TVA` a real document
contains. Seven weak rules across six countries were inert as a result — `at-vnr`,
`pt-nif`, `pt-cc`, `nl-bsn`, `pl-nip`, `gb-nhs`, `gb-utr`, all at 0.45 and so all
below `Policy.min_confidence` without a keyword.

Fixing it cost nothing and moved labels, not coverage: 0 characters of
over-redaction and 0 entities either way, exact F1 0.921 to 0.928, and seven spans
relabelled. Six of the seven were corrections, and they are the point — the
digits of a Portuguese NIF and a Dutch BSN were being reported as **Polish phone
numbers**, and a French `numéro fiscal` as a German one, because a `phonenumbers`
plan claim at 1.00 beats a correct rule sitting at 0.45. That is what a per-country
precision line of 0.62 was made of.

Two things not to undo. The country list in `suppress.py` is folded on **both**
sides, because it too was written unaccented (`osterreich`, `suede`, `grece`,
`turkiye`) and was therefore not suppressing the `Österreich` or `Suède` a
document actually carries — the bare country name was being redacted after all,
which is the exact over-redaction that list exists to prevent. And the legal-form
tables are **not** folded: they gained `sàrl`, `s.à r.l.` and `s.à.r.l.` as listed
spellings instead, because `organisations.py` matches its short forms
case-sensitively on purpose and folding a candidate to compare it would throw that
distinction away. `Sàrl` is what a Romandy or Luxembourg company registers under
and both passes were blind to it.

One collision is pinned rather than fixed, in `tests/test_diacritics.py`.
`228722377` in `corpus/fr.txt` is an annotated SIREN with the word `SIREN` six
characters in front of it, and also a valid Austrian TIN; once the window folds,
the `numéro fiscal` labelling the *next* number in the same list gives `at-tin` its
context too. Both then stand at precedence VALIDATOR, the same span and confidence
1.0, so the winner is whichever the rule table lists first — a decision nobody
made. The characters are removed either way, so it is a report attribution defect
and not a leak. Fixing it properly means letting the tie-break see *how far* away
each rule's own keyword is, which needs a new field on `Finding` and a measurement
of its own.

**Redaction removes, it does not cover.** `formats/pdf_text.py` uses PyMuPDF
`apply_redactions()` and always a full rewrite (`garbage=4, clean=True,
deflate=True`). Never overlay rectangles — the text stays selectable underneath,
which is the bug in `anonymize-documents-with-presidio`. Never save
incrementally: that appends the new version and leaves the redacted originals
earlier in the same file.

**Degradations get reported, never swallowed.** `FormatHandler.warn()` feeds
`ScrubResult.warnings`, the JSON report and the CLI. It exists because PyMuPDF
*silently drops* replacement text that does not fit its rectangle: removal still
happens, but the placeholder vanishes without a word. The handler shrinks the
font to `MIN_FONT_SIZE` and warns if even that fails. Any future handler facing a
compromise it cannot avoid must use the same channel.

**PyMuPDF's `scrub()` does not remove annotations.** It has flags for links and
annotation responses but none for annotations themselves, so `scrub_hidden()`
deletes them explicitly via `page.first_annot` / `delete_annot`. This regressed
once: a sticky note reading "cliente moroso" was still in the output while the
report claimed the annotation had been removed. `test_annotation_text_does_not_survive`
guards it. Metadata also survives `garbage=4, clean=True` unless cleared.

**A PDF leak test must decompress.** Content streams are Flate-compressed, so
searching the raw file bytes for a canary proves nothing. `tests/test_pdf.py`
walks every xref and searches the decompressed streams. Apply the same standard
to OOXML: search inside the zip parts, not the zip.

**Never return a scan as if it were processed.** `extract()` raises
`ScannedPdfNotSupported` when a page has no usable text layer *and OCR is
unavailable*, naming the pages and what to install, rather than producing an
untouched file the user believes was scrubbed. `hidden_text=False` is passed to
`scrub()` deliberately: an OCR layer over a scan *is* invisible text, and
deleting it blind would throw away content this pipeline can redact properly.

**On a scan the redaction is to the pixels.** There are no glyphs to delete: the
text is the image. `apply_redactions()` blanks the image pixels inside the rect
(`images` defaults to `PDF_REDACT_IMAGE_PIXELS`), editing the image stream rather
than covering it. The test that proves it re-runs OCR on the output; checking
`get_text()` proves nothing about a scan.

**The OCR decision is per page.** Real files mix born-digital and scanned pages.
`page.get_images()` is what distinguishes a scan from a genuinely blank page — OCR
the first, ignore the second — and PyMuPDF returns OCR results in the page's
coordinate system with the same `rawdict` shape as the text layer, so `_add_page`
handles both. Do not rasterise and map pixel coordinates by hand; it is the same
result with an extra transform to get wrong.

**`harden_for_verification()` exists because verification was checking the wrong
thing.** A scanned page is only machine-read when its text layer looks empty, and
a *redacted* scan carries the placeholders that replaced its content — enough text
to look ordinary. So verification inspected the placeholders and never the pixels,
and a failed pixel redaction would have passed. Any handler that reads less than
everything for speed must override this hook. `test_verification_re_reads_the_pixels`
pins it.

**"OCR is available" means the binary *and* the language data.** PyMuPDF does not
link Tesseract, it shells out to it, and the two halves install separately: the
`.traineddata` files are bundled beside the executable, the binary is a platform
package and cannot be. `capabilities.ocr_available` used to check the data alone,
so bundling it would have made the capability true everywhere — the window
promising an OCR the first scan could not deliver. One `ocr_unavailable_reason()`
decides, so the capability and the refusal cannot disagree, and the refusal names
which half is missing. Nine languages are requested at once, one per language of
the twelve supported countries; asking for all of them costs about 24 ms a page
and 86 MB on disk.

**OCR is a reading, not the text.** A value OCR misreads fails its checksum, is
never detected, and survives. Every machine-read page is named in a warning for
that reason. Do not remove the warning to tidy the output.

**Office write-back goes through `lxml` on the zip parts.** `openpyxl`,
`python-docx` and `python-pptx` have no management API for charts, images or pivot
tables and can drop them on save, so the engine never uses them —
`formats/ooxml/zip_part.py` reads the container once and rewrites only the parts
that were both parsed *and* marked dirty. Everything else is copied through as
the bytes it arrived as, which cannot lose what it never parsed.
`test_docx_real.py` asserts `styles.xml` and `theme1.xml` come back byte-identical.

`python-docx` and `openpyxl` *are* dev dependencies, used only in tests: they
produce realistic packages to validate against, so the suite is not just checking
our own hand-built XML back at us, and they read the output to confirm the file
still opens. Several of the findings below were surfaced that way and by nothing
else. They also disagree with Excel — openpyxl writes inline strings where Excel
writes a shared string table — which is why both paths are handled and both are
covered by a fixture.

**Excel keeps copies of its own data.** `xlsx.py` anchors the pivot cache, chart
caches and external-link caches so they are *redacted in place*: dropping a pivot
cache leaves the pivot blank until refreshed, and editing the values keeps the
workbook working. Sheet names live in `xl/workbook.xml` *and* `docProps/app.xml`
`TitlesOfParts`; redacting one is a leak.

**Redacting an Excel name renames the thing.** Formulas refer to sheets and
tables by name, so this breaks references. It is done anyway — leaving
identifying names would fail the leak check — and `XlsxHandler.write_back()`
warns with the list of what was renamed. `AttributeLocator.sanitise` exists
because `[` and `]` are illegal in a sheet name and `[PERSON_1]` contains both:
without it the output was a workbook Excel refused to open.

**Numeric cells are anchored only at `MIN_NUMERIC_LENGTH` digits or more.** A
sheet is mostly numbers and the 11-digit partita IVA checksum passes on about one
in ten arbitrary numbers of that length. Do not lower this without measuring the
over-redaction cost. A `t="s"` cell's `<v>` is an index into the string table, not
text — editing it repoints the cell at an unrelated string.

**A PowerPoint chart embeds a whole workbook, and it is scrubbed recursively.**
`PptxHandler` nests an `XlsxHandler` per `ppt/embeddings/*.xlsx` and folds its
anchors into the parent stream, routing write-back by `id(locator)` rather than by
part name. The nested part names are deliberately *not* prefixed for readability:
doing that handed the nested package a `mark_dirty` name it had never heard of, so
edits were applied to the elements and then discarded in favour of the original
bytes. The leak check caught it; `test_names_inside_the_embedded_workbook_do_not_survive`
keeps it caught. A pptx-in-pptx is excluded from nesting to bound the recursion.

**A leak test for a nested format must open the inner zip.** A chart's workbook is
a zip inside a zip, so a single-level search reports a clean file that is not.
`tests/test_pptx.py::survives_anywhere` descends one level and returns the part
name, so a failure says where.

**L1 gets the last word on L2's structured claims.**
`registry.drop_unconfirmed_structured` discards a NER finding labelled IBAN, card,
codice fiscale, partita IVA, AHV, UID or CH VAT when the matching checksum
rejects the text. GLiNER2 labelled two adjacent chart amounts a credit card at
0.87 — no threshold separates that from a real finding. `validators.confirms`
checks the checksum only, not the regex, so a model can still contribute a real
identifier written in a format the L1 pattern would not nominate.

**Separator choice is not cosmetic.** Cache values get `\n`, spreadsheet cells
within a row get `\t`. Joining two independent cached amounts with a tab is what
produced the credit-card false positive in the first place.

**Dropping a part means dropping what points at it.** `OoxmlPackage.drop()`
removes the part, any relationship resolving to it, and its
`[Content_Types].xml` override. Doing only the first leaves a dangling reference:
Word offers to repair the file and a strict consumer rejects it. Relationship
targets are relative to the *owning part's* directory, which is why
`_resolve()` strips two path components.

**The thumbnail is a picture of the unredacted page.** `docProps/thumbnail.*`
must go. Scrubbing every character and shipping a screenshot of the original
achieves nothing, and no amount of reading `document.xml` reveals it.

**Text lives in places reading the document does not reveal.** `<w:instrText>`
holds a HYPERLINK field's target, external relationship targets hold hyperlink
addresses, `customXml/` holds the data behind content controls, and headers,
footers and footnotes are separate parts. Relationship targets are exposed to the
pipeline as ordinary anchors via `AttributeLocator` rather than being pattern-
matched in the handler — the detectors already know what an email looks like.

**`xml:space="preserve"` is not optional.** When a replacement gains leading or
trailing whitespace it must be set, or Word eats the space and the words fuse.
Only ever added, never removed.

## The reverse path

`scrub --map` writes an encrypted key file and `freedocs restore` puts the values
back into whatever came back from the model. `core/mapping.py` owns the file,
`restore.py` owns five stages of its own — `router -> extract -> match ->
write-back -> verify`. Off by default, an optional `restore` extra for the cipher,
and `docs/restore.md` is the long version.

**The default did not change and neither did the allocator.**
`SurrogateAllocator` gains no accessor and `pipeline.py` does not import
`core/mapping.py`. The key file is built from a finished `ScrubResult`, whose
`Decision` rows still carry the original in `finding.text` and the placeholder in
`replacement` after `allocator.close()` has run in the `finally`. So the reverse
direction is a front-end decision about a finished result, not a branch inside the
pipeline — and if this ever needs a method on the allocator, the design has gone
wrong.

**Restore's verification asks two questions, and the second is the load-bearing
one.** Placeholder gone *and* value present. `PdfTextHandler.write_back` stamps a
redaction annotation rather than splicing, and PyMuPDF silently drops a
replacement that does not fit — and a real value is almost always longer than the
token it replaces. So on a PDF the common failure is the token removed and the
value never written, which a one-directional check reads as success. Same class as
`harden_for_verification()`, and the reason PDF is the weak format here while
plaintext and the three OOXML formats round-trip cleanly.

**An incomplete restore writes its file, which is the opposite of stage 6.** A
scrub that leaks must write nothing, because a nearly-clean document gets sent. A
restore that left one `[IBAN_1]` behind has produced the caller's best artifact and
its defect is visible in it. `EXIT_INCOMPLETE`/`INCOMPLETE_RESTORE` are both `5` by
intent — as `3` already matches — and a test pins the pair. Do not "fix" this into
consistency.

**Matching is literal, and the unknown list is the honest half.** A translated stem
(`[PERSONA_1]` out of an English scrub), an invented number, a reformatted token:
each is reported through `PLACEHOLDER_SHAPE` and left alone. Guessing which entry a
damaged token meant would write somebody else's value into a position nobody chose,
which is worse than a visible placeholder. No tolerant mode, not even behind a
flag. `[PERSON_1]` cannot prefix-match `[PERSON_11]` because the closing bracket
ends the token, which is the one place the brackets earn their keep and is pinned
by a test.

**The round trip is lossy on spelling, and it says so.** `policy._normalise`
casefolds and collapses whitespace, so `Mario Rossi`, `MARIO ROSSI` and
`Mario  Rossi` share one placeholder. `key_map_from` keeps the **first in document
order** — `_decide` walks findings in span order — and `MapEntry.variants` counts
the collapse so both the write and the restore warn about it.

**The matcher is not a detector and must not move into `detect/`.** It produces no
`Finding`, enters no registry, resolves no overlaps by precedence. It is closer to
`core/overrides.py`: a mechanism acting on what a caller already decided. Under
`detect/` it would eventually be given a confidence and a precedence, and then it
is a detector nobody measured.

**Restore does not call `scrub_hidden()` and must not use the RPC extraction
cache.** There is nothing to strip, and the returned document's metadata belongs to
whoever produced it — so restore cannot reuse `Scrubber.read`, which calls it, and
must not be routed through `rpc.Session.extraction`, whose cache holds extractions
taken *with* hidden content already deleted. Both are stated in the code so nobody
unifies them.

**No exception in `core/mapping.py` may quote the passphrase or a value.**
`rpc.handle` renders an unexpected exception as `f"{type(exc).__name__}: {exc}"`
straight into a response, so a message that carried either would be the leak this
tool exists to prevent. Same discipline as `Leak.describe()`, and
`test_rpc.py::test_a_wrong_passphrase_leaks_neither_it_nor_a_value` is the proof.

**There is no plaintext form of the key file and no `--map-passphrase` argument.**
A `--map` that degraded when the extra was missing would write the key in the clear
at the moment nobody was watching; a passphrase on a command line is in the shell
history and visible through `ps`. Three sources — a file, `FREEDOCS_MAP_PASSPHRASE`,
an interactive prompt — and no terminal with neither of the first two set is a
usage error rather than a silent skip.

**The key file is refused inside `--output-dir`** without `--map-in-output-dir`.
The realistic accident is not theft: it is zipping the output folder and sending
the scrubbed document with the key to undo it. `refuse_inside` lives in
`core/mapping.py` so the CLI and the pipe cannot disagree, and the check runs
before the first file is read.

**`mapping_unavailable_reason()` is the single authority**, exactly as
`ocr_unavailable_reason()` is: `capabilities` publishes it, `doctor` renders it,
and both write and read raise from it. And **`packaging/build.py`'s smoke test must
round-trip a real key file** — `find_spec` is true of a bundle whose cipher never
made it in, which is verbatim the bug the NER half of that smoke test was written
after.

**A handler's warning quotes a value in this direction, so the restore report
carries a count instead.** PyMuPDF's "does not fit the space its original occupied"
names a *placeholder* during a scrub and the *original value* during a restore,
because in the second case the value is what is being written. So
`build_restore_report` emits `handler_warnings: N` rather than the prose, and the
warnings themselves stay on the console and the local pipe — the channel
`inspect` already sends matched text over. `verification.problems` carries the
actionable half value-free. Found by writing the PDF test: a plaintext round trip
cannot show it, because plaintext never warns, and
`test_the_restore_report_carries_no_values` passed over the hole.

**The report says a key file exists and never where it is.** `build_report` takes
`key_file: bool`; the *path* goes only in the RPC response, which travels down a
local pipe to the process that chose the location. A report may be attached to a
ticket.

**The window gained a mode, not a fourth step, and still holds no rules.** A
returned document arrives days after the scrub, so there is nothing to continue
from; each mode owns its own step order in `ORDER` and reachability stays derived.
The key-file controls sit with the *scrub* options because the engine writes the
file inside the `scrub` request — which is what keeps the mapping from ever
crossing the pipe into the window. Neither passphrase touches `localStorage`: they
live in `session` for one call and are cleared in a `finally`, mode changes
included. `MIN_PASSPHRASE` in the window exists only so the engine's refusal is not
the first the user hears of it; the engine wins.

**Restore returns no offsets, deliberately.** `RestoreResult` carries placeholders,
entity names and counts. That is what keeps the UTF-16-versus-code-point trap out
of this feature entirely — read the note under *The desktop app* before adding a
"show me where" affordance.

**The `restore` extra is in the CI extras and `ner` still is not.** It is one small
wheel, and the checks it enables are not quality measurements that skip harmlessly:
a gate that skipped "no value is readable in the key file" would be skipping the
one assertion that makes the feature safe.

## Conventions

- Comments explain *why*, especially where a simpler approach was tried and
  failed. The codebase is small; the reasoning is the part worth preserving.
- Docstrings state the failure mode a piece of code prevents, not what the
  signature already says.
- New entity types go in `core/findings.EntityType` plus a label in every locale
  of `core/policy.PLACEHOLDER_LABELS` that needs one — a locale falls back to
  English for anything it omits. Quasi-identifiers belong in `REPORT_ONLY`:
  removing a date silently hides residual risk instead of surfacing it.
- **The type says what a number is for; the country lives on the finding.**
  `NATIONAL_ID`, `TAX_ID`, `VAT_ID`, `COMPANY_ID` rather than one member per
  country per number, which would be an enum of several hundred with every entry
  spelled again in the placeholder table, the report, the corpus labels and the
  tests. The country reaches the report and never the placeholder: `[TAX_ID_DE_1]`
  would hand the reader of the scrubbed text one more thing to re-identify with.
- **Placeholders are English by default and the stems are per locale.** The reader
  of a scrubbed document is usually a language model. The country-issued types are
  not translated in any locale: one stem stands for twelve countries and every
  national name for it would be wrong on eleven.
- Never claim the output is guaranteed clean. `report.CAVEATS` states the limits
  and should be updated as milestones change what is actually true.

## The portable bundle

A fourth artifact per platform: unzip and run, no installer, no network. Built by
`app/packaging/portable.py` with `src-tauri/tauri.portable.conf.json` merged in,
run locally — **the CI steps are gated on a `BUILD_PORTABLE` repository variable
and off by default**, because a second bundling pass over a 2.3 GB tree on three
runners (macOS billed at 10x) emptied this private repository's Actions allowance
the first time it ran. Gated rather than deleted, so a portable release is one
variable away. The feature is **additive by construction** — `tauri.conf.json` is untouched, `env.BUNDLES`
is untouched, and the portable CI steps are appended after the installer upload so
a failure here cannot cost installers that already succeeded. Verify that claim by
checking the `.dmg` is still a few hundred MB and not 1.5 GB, and that its
`Contents/Resources` holds no `ner-model`; if it grew, the model resource leaked
into the shared config. Verified after this landed: 366 MB, no `ner-model`. See `docs/portable.md`.

**The whole design follows from one fact: `GLiNER2.from_pretrained` accepts a local
directory.** Its `download_or_local` branches on `os.path.isdir`, so a portable
copy ships the weights as five plain files and points at them — no HF cache, no
redirected `HF_HOME`, no symlink farm (`snapshots/` is entirely symlinks into
`blobs/`, which `upload-artifact` drops and Windows zip either fails on or
duplicates). Because nothing is fetched, **the portable build needs no writable
state at all**, which is what makes a read-only AppImage mount and a macOS `.app`
non-problems. "Portable" reduces to resources resolved relative to the executable,
which `resource_dir()` already does in all three shapes.

**The engine is told, never asked.** `portable_env()` in `engine.rs` sets
`FREEDOCS_NER_MODEL`, `FREEDOCS_TESSDATA`, `FREEDOCS_TESSERACT` and — only
alongside a bundled model — `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`. Only paths
that exist are passed and an already-set variable is never overwritten, matching
`FREEDOCS_ENGINE`. So an installer build's sidecar environment is unchanged. The
offline pair is not belt-and-braces: without it an air-gapped machine spends a DNS
timeout inside `from_pretrained` before reading weights it already has.

**`model_source()` raises on a path it cannot load.** Falling back to the pinned
repo id would be a silent 1.2 GB download on a networked machine and a 404 about a
repository nobody named on an offline one. It is resolved per call, not at import:
`load_backend` is `@cache`d, so a module-level `os.environ` read is taken once by
whichever caller was first — the same trap `DEFAULT_LABELS` carries.

**`FREEDOCS_TESSERACT` must also put its directory on `PATH`.** Nothing in the
engine runs Tesseract; PyMuPDF does, by shelling out, and it resolves the binary
through `PATH` with no argument for it — only for the language data. An override
that merely satisfied `tesseract_binary()` would make `capabilities` promise OCR
and then fail on the first scan, which is the bug that made
`ocr_unavailable_reason()` the single authority. The binary is never bundled and
cannot be; the `.traineddata` are.

**A bundled payload can be incomplete in a way a downloaded one cannot** — a full
disk, a stick pulled mid-write. `core/model_manifest.py` owns the format because
`packaging/model.py` writes it and `diagnostics._weights()` reads it; sizes on
every `doctor`, hashes only on request, because hashing 1.2 GB catches only bytes
that changed without the length changing.

**`doctor`'s fixes are `sys.frozen`-aware and become absent, not rewritten.** What
a packaged user should do about a missing extra depends on which build they have —
a portable zip is replaced, an installer reinstalled — and the engine does not know
which it is inside. This closes the defect `rpc.doctor` used to admit in its own
docstring.

**The AppImage failure was probably FUSE, and that is still unverified.**
`linuxdeploy` is itself an AppImage and must mount itself; `ubuntu-22.04` ships
FUSE 3 only. But the first CI run with these fixes never reached `linuxdeploy` —
it died in `No space left on device` while copying resources, because the
artifact fits in the runner's 14 GB and the peak working set does not (a torch
venv, the sidecar, a cargo release tree, the `.deb`, and the model copied twice).
The cleanup step addresses the disk; whether FUSE was ever the problem remains
untested. `APPIMAGE_EXTRACT_AND_RUN=1` is the
fix that needs no FUSE and survives a runner image change, so it comes before
installing `libfuse2`. `NO_STRIP=true` is not caution: the spec sets `strip=False`
because the engine speaks on stdout, and a `linuxdeploy` strip would undo that
silently. The `.deb` step is left exactly as it was.

**Windows WebView2 has no stable download URL.** The fixed-version package is
published only under a per-version unguessable GUID and de-listed outside the two
newest releases, so CI reads `WEBVIEW2_FIXED_RUNTIME_URL` (a repository variable)
and skips when unset, with the build script saying so out loud. Hardcoding a URL is
a 404 waiting to happen; the evergreen installer is no use because it installs.
`adopt_bundled_webview()` runs at the top of `run()` and resolves `current_exe()`
rather than `resource_dir()`, because the loader reads the variable when the
builder creates the webview and `resource_dir()` needs a built `App`.

**Theme and locale are deliberately not portable.** They live in `localStorage`,
so in the webview profile under OS app-data. Redirecting that on macOS and Linux
would mean replacing `localStorage` with a file, reintroducing the async read at
boot that `theme.svelte.ts` exists to avoid — and with it the flash of the wrong
theme. Two enum values are not worth that.

**Licence: the model is Apache 2.0 and ungated**, so redistribution is permitted
and one-way compatible with AGPL-3.0. `packaging/model.py` writes the licence text
and a `NOTICE` beside the weights, generated by the script that produces the
payload so the two cannot drift.

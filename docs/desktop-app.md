# The desktop app

```bash
cd app && npm install
npm run check          # svelte-check; also proves the four message catalogues complete
npm test               # vitest: offset arithmetic, plural rules, display names
npm run tauri dev
CI=true npm run tauri build   # needs engine/dist/freedocs-engine to exist first
```

Three steps — File, Review, Result — with the extracted document shown and every
finding marked in place. That is what makes the per-occurrence decision usable:
the sentence *around* a value is what says whether a city is a party's address or
a jurisdiction clause, which is the distinction the engine keeps `keep` and
`keep_spans` apart for. The marks are walkable from the keyboard, `x` excuses one,
and every decision goes back to Python to be judged there.

## The app holds no rules

Every judgement about what is confidential, what gets removed and what the user is
warned about lives in Python. Two places deciding what an IBAN looks like is two
answers that can disagree, so `app/src/lib/engine.ts` carries messages and nothing
else.

That rule is why two things in the window are read from the engine rather than
worked out locally. Which layer found a value comes from `Finding.layer`, not from
the shape of the detector string — the window used to read a colon as "the model",
which was the app holding a rule about the engine's naming and would have started
lying the moment a backend was renamed. And the example placeholder in the
advanced panel is composed by the engine's own `SurrogateAllocator`, so a preview
cannot promise `[PERSONA_1]` and produce `[PERSON_1]`.

The two `keep` controls are deliberately separate in the UI and on the wire:
`keep` names entity *types* to leave alone everywhere, `keep_spans` names single
occurrences. One control for both would make "this Zurich is fine" mean "no
location is confidential".

## What the window shows, deliberately

The detection layers actually loaded; whether OCR is available *and which half of
Tesseract is missing when it is not*; what each country actually gets (the United
States has no check digit behind its numbers, and its chip says so); which rules a
raised threshold has silenced; every warning the engine raised; the hidden content
that was removed; and whether stage 6 re-opened the output and found nothing. A
build that quietly finds less has to say so.

Two things it deliberately does not do. **It never invents a percentage:**
progress counts files, stages and pages, because how long detection takes next to
extraction on an unseen document is not a fact the engine has. And **it does not
translate the engine's own sentences** — warnings, caveats, review summaries and
errors are quoted in English inside a window that is otherwise Italian, German,
French or English, with one line saying so. Translating them in Python was
rejected: the test suite asserts on their content, `Leak.describe()` is
safety-critical prose, a locale is a property of a UI session rather than of a
pipe that also answers the CLI, and four chances to soften a "not installed" into
something that reads as "not required" is four chances to ship a build that
quietly finds less. The rule is **if it came from an enum, translate it; if it
came from an f-string, quote it.**

## How it is put together

One route, with a rail — because the wizard state is not addressable and a route
change would drop the in-memory `Inspection`, which cost a PDF extraction to
obtain. Reachability is **derived, never stored**: a step the user cannot be on
cannot be the current one, and two sources for that fact is a window showing
Review with nothing to review.

```
app.css                 the only global stylesheet: tokens, reset, focus ring
routes/+layout.svelte   chrome (theme, language), skip link, the two live regions
routes/+page.svelte     orchestrator: which step, what is reachable, terminal failure
lib/app.svelte.ts       the session: caps, files, inspections, results, options, actions
lib/review.svelte.ts    per-file review state: selection, filter, block and segment caches
lib/highlight.ts        PURE: blocks(), segment(), rebucket(), codePointOffsets()
lib/i18n/               a typed message contract plus en, it, de, fr
lib/components/         the primitives; lib/screens/ the three steps and their panes
```

**Tokens carry their measured contrast ratio as a comment.** There is no contrast
checker in this pipeline, so a number beside the token is the cheapest thing an
edit can violate. Three tokens were rejected by that measurement rather than by
taste: white on the brand accent `#2f9e79` is 3.34:1, below what a button label
needs, so the fill is the same hue at `#22785c`; `--text-3` was 4.26:1 and moved;
the `place` underline was 2.77:1 against its own tint. In dark mode a white label
on the accent measured 2.40:1, so that label is dark.

**Secondary text is a colour, not an `opacity`.** Opacity cannot be measured for
contrast and dims a border along with the text inside it.

**Dark mode is one attribute and two blocks.** `ssr = false` means nothing paints
before JavaScript, so `lib/theme.svelte.ts` resolves the preference and stamps
`data-theme` while it is being imported. That is also what lets a manual choice
beat the OS in *both* directions, which a `prefers-color-scheme` block cannot do
without a second copy of the palette. `system` stays a real third state.

**Plurals go through `Intl.PluralRules`.** French puts zero in the singular and
the other three do not, which is measured in `plural.test.ts` — that single fact
is why the `(s)` suffix the old window used was wrong rather than merely ugly.

## The one silent trap: two coordinate systems

**Python counts code points; JavaScript counts UTF-16 code units.** Inside the BMP
they agree, which is almost every document. With an emoji or a rare CJK character
they diverge by the number of surrogate pairs before the offset — and then every
highlight after it is misplaced *and* every `keep_spans` sent back describes text
the user never saw, so `core/overrides.py` either refuses the decision as stale or
keeps whatever moved into that range.

`codePointOffsets` converts for rendering only: `View.marks` holds UTF-16 offsets
for slicing the string, the engine's own offsets stay in `inspection.findings` at
the same index, and **a kept span is always built from the latter**. Sending a
rendering offset back to Python is the one mistake in this window that would look
like nothing at all.

## Two smaller decisions in the marked text

**A finding grows its block rather than being cut by it.** Half a mark is two
clickable things where the user sees one value, and neither half's offsets
describe it. Overlapping findings are a contract violation — the registry resolves
overlaps before anything reaches the wire — so the later one is dropped rather
than merged, and a test asserts every character is emitted exactly once.

**Roving tabindex, and the first mark is the tab stop when nothing is selected.**
Hundreds of buttons in the tab order makes Tab useless. The first version made
every mark `tabindex="-1"` in the empty-selection state, which left the document
unreachable from the keyboard. And a mark's state is announced by a hidden prefix,
not `aria-label`: a label on a button that contains text *replaces* that text, so
the value itself would stop being announced.

## The protocol

`freedocs/rpc.py` is the contract: newline-delimited JSON on stdin/stdout, one
object per line, requests carrying an `id` and progress arriving as notifications
without one. It is tested by `tests/test_rpc.py` because the protocol is all the
app can see, and it is far cheaper to test than the app.

**The engine is a pipe, never a socket.** It reads and writes files named by
whoever is on the other end, so its only safe caller is a parent process that
already has the user's permission. One process serves the whole session: loading
GLiNER2 takes seconds and running it takes milliseconds.

**The channel carries values; the disk must not.** `inspect` returns the matched
text, because a preview that cannot show what is about to be removed is not a
preview, and that is fine down a local pipe. The JSON report, which does reach
disk, carries counts and positions only.

**The preview text is opt-in, one blob, and capped.** `include_text` makes
`inspect` return the whole extracted document, which is a *superset* of the
matched values: it contains the confidential text no layer detected. So a caller
that renders no preview never receives a document, and the text must never reach a
report, a warning or an error's `data` block. `MAX_PREVIEW_CHARS` truncates and the
response says so; **the finding list is never truncated with it**, because a
finding hidden to make the numbers agree is the failure this feature must not
introduce.

**Extractions are cached per `(path, mtime, size)`, four at a time.** Every kept
occurrence re-inspects, because propagation means one decision can change other
findings and the window is not allowed to guess the new answer — and without the
cache that re-OCRs every page of a scan for a file that has not changed. A file
whose size or modification time moved is read again: serving old text would show a
preview of a document that no longer exists.

**Progress is two notifications, and neither claims a percentage.** `progress`
counts files; `stage` says where inside one file the run is. `index`/`count`
counts *stages*, and `done`/`of` appear only where a stage has a real unit (pages,
so far). `count` comes from the plan the run is executing — six stages, seven with
a reviewer, three for an inspection — which is also why `capabilities` publishes no
stage list: a stepper drawn from one would be wrong for two of those cases. Stage
names are a closed vocabulary pinned by a test, because the window translates them
by key.

**A cancel button needs a reader thread, and is out of scope.** `serve()` is
`for line in source:`, so while a request runs nobody reads stdin and a `cancel`
sits in the pipe buffer until the request it named has finished. Doing it properly
means a daemon reader thread, a cancel that names the request id, writes staying on
the main thread, and `test_stdin_closing_still_ends_the_session` written *first*.
Until then the way out is killing the sidecar — and the extraction cache removes
most of the wait that made the button feel necessary.

## Tests: Node-only, and that is a scope decision

Vitest covers `highlight.ts`, the plural rules, the display names and the
catalogues. There are no component tests, because rendering a `Chip` to assert
`aria-pressed="true"` tests that Svelte writes an attribute we wrote. The
discipline that replaces them is to push logic out of components until they are
too dumb to be worth testing — the review screen's keyboard map is `nextFinding` in
`highlight.ts` for exactly that reason.

No browser automation either: `tauri-driver` supports only Linux and Windows, so a
WebDriver suite would run only on the two platforms this app has been built for and
never launched on, and synthetic clicks are refused on this machine anyway
(`-25208`).

What is verified by hand and stated as such: dark-mode appearance, the entity
palette's distinguishability, that the highlight layer is smooth in the webview
(Node can only prove `blocks()` is linear), `prefers-reduced-motion`, and every
screen-reader announcement.

## Two things that cost time during development

**`tauri dev` does not necessarily run the engine you just edited.** `locate()` in
`src-tauri/src/engine.rs` prefers a bundled resource over the repository venv, and
a bundle left in `target/debug/freedocs-engine/` from an earlier
`packaging/build.py` wins. Symptom: the window is missing a feature the Python
gained after that bundle was built, which looks like a frontend bug and is not
one. Either delete that directory or set `FREEDOCS_ENGINE`:

```bash
cd app && FREEDOCS_ENGINE=../engine/.venv/bin/freedocs-rpc npm run tauri dev
```

**The engine is one long-lived process.** After editing `rpc.py` the running
sidecar still has the old code, so restart the app rather than reloading the
webview. And `cargo` is often absent from a non-interactive shell's PATH.

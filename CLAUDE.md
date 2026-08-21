# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FreeDocs removes confidential data from documents so they can be handed to an
LLM. Local, offline, AGPL-3.0. See `README.md` for the positioning and the
competitive gap it targets; the full design and milestone plan live in
`~/.claude/plans/allora-questo-una-recursive-twilight.md`.

**Current state: M8 complete — the plan in the plan file is finished.** The engine
handles plain text, PDF (born-digital and scanned), `docx`, `xlsx` and `pptx`, with
checksum, NER and value-propagation detection over it/de/fr/en. A Tauri app in
`app/` drives it over a JSON pipe, and an opt-in local-LLM pass reviews the output.
Anything further is new work, not a remaining milestone.

## Commands

All Python work happens in `engine/`.

```bash
cd engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner   # Python 3.12, pinned

uv run pytest -q                       # full suite (429 tests, ~75s with model+OCR)
uv run pytest -q -m "not slow"         # skip the model-backed tests (~1s)
uv run pytest -q -m leak               # only the end-to-end leak checks
uv run pytest tests/test_stream.py -q  # one file
uv run pytest -q -k plan_edits         # one test by name
uv run ruff check . && uv run ruff format --check .

uv run freedocs inspect FILE           # report findings, write nothing
uv run freedocs scrub FILE -o out/     # write a scrubbed copy
uv run freedocs entities               # list supported entity types
uv run freedocs benchmark              # score detectors against corpus/
uv run freedocs benchmark --detectors "l1,all:gliner2,all:presidio"
```

`--extra ner` fetches ~1.2 GB of model weights to the Hugging Face cache on first
use. CI deliberately omits it: the `slow`-marked tests skip themselves, and
detection quality is measured by `benchmark`, not asserted in CI.

CI (`.github/workflows/engine.yml`) runs lint, format, the suite and the leak
checks on Python 3.10 and 3.12. Keep both green: 3.10 is the declared floor in
`pyproject.toml`, so avoid 3.11+ syntax.

## The desktop app

```bash
cd app && npm install
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

**Multi-platform is configured, not verified.** `.github/workflows/app.yml` builds
macOS arm64/x86_64, Linux and Windows on their own runners, because neither
PyInstaller nor Tauri cross-compiles. Only macOS has been built and run here. Do
not describe the other three as working.

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

- **L1** (`detect/validators.py`, shipped): regex nominates, checksum decides —
  codice fiscale CIN, partita IVA, AHV EAN-13, Swiss UID, IBAN mod-97, Luhn, all
  via `python-stdnum`. Add identifiers here as a `Rule`, and always pair the
  pattern with a real validator rather than tightening the regex.
- **L2** (`detect/ner.py` + `detect/backends/`, shipped): GLiNER2 for names,
  organisations, locations, addresses, job titles. One `mdeberta-v3-base` model
  covers it/de/fr/en with no language hint. Backends are swappable so the choice
  rests on `benchmark` output; `presidio_backend.py` is the measured alternative,
  kept installable so the comparison stays reproducible.
- **L2.5** (`detect/propagate.py`, shipped): copies each confirmed value to its
  other occurrences. Runs after overlap resolution, then resolves again.
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

**The corpus has to be able to make something fail.** It is 378 entities over
twenty documents, up from 103 over four, and growing it moved the headline from
99.0% to 97.4% — the instrument getting sharper, not a regression. What the small
one could not report: LOCATION coverage is 75.8% against PERSON's 100%, because
every remaining leak but one is a place name that also appears as somebody's
surname in the same document (`Basel`, `Preston`, `Lyon`, `Firenze`). Keep those
collisions when editing the corpus; they are the finding.

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
because `[` and `]` are illegal in a sheet name and `[PERSONA_1]` contains both:
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

## Conventions

- Comments explain *why*, especially where a simpler approach was tried and
  failed. The codebase is small; the reasoning is the part worth preserving.
- Docstrings state the failure mode a piece of code prevents, not what the
  signature already says.
- New entity types go in `core/findings.EntityType` plus a label in
  `core/policy.PLACEHOLDER_LABELS`. Quasi-identifiers belong in `REPORT_ONLY`:
  removing a date silently hides residual risk instead of surfacing it.
- Never claim the output is guaranteed clean. `report.CAVEATS` states the limits
  and should be updated as milestones change what is actually true.

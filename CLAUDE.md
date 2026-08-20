# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FreeDocs removes confidential data from documents so they can be handed to an
LLM. Local, offline, AGPL-3.0. See `README.md` for the positioning and the
competitive gap it targets; the full design and milestone plan live in
`~/.claude/plans/allora-questo-una-recursive-twilight.md`.

**Current state: M5 complete.** Plain text, text-layer PDF, `docx`, `xlsx` and
`pptx` end to end, with checksum, NER and value-propagation detection over
it/de/fr/en. No OCR — that is M6, and the code says so where it matters.

## Commands

All Python work happens in `engine/`.

```bash
cd engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner   # Python 3.12, pinned

uv run pytest -q                       # full suite (321 tests, ~42s with the model)
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
- **L3** (M8): opt-in Ollama pass over the *already anonymised* text, flagging
  leftovers and quasi-identifiers. Advisory only.

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
`ScannedPdfNotSupported` when a PDF has no usable text layer, rather than
producing an untouched file the user believes was scrubbed. `hidden_text=False`
is passed to `scrub()` deliberately: an OCR layer over a scan *is* invisible
text, and deleting it blind would throw away content this pipeline can redact
properly.

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

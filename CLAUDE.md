# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FreeDocs removes confidential data from documents so they can be handed to an
LLM. Local, offline, AGPL-3.0. See `README.md` for the positioning and the
competitive gap it targets; the full design and milestone plan live in
`~/.claude/plans/allora-questo-una-recursive-twilight.md`.

**Current state: M1 complete.** Plain text and text-layer PDF end to end with
checksum-backed detection. No Office formats, no OCR, no NER — those are M2
onwards, and the code says so where it matters.

## Commands

All Python work happens in `engine/`.

```bash
cd engine
uv sync --extra dev --extra pdf        # Python 3.12 (pinned in .python-version)

uv run pytest -q                       # full suite (110 tests)
uv run pytest -q -m leak               # only the end-to-end leak checks
uv run pytest tests/test_stream.py -q  # one file
uv run pytest -q -k plan_edits         # one test by name
uv run ruff check . && uv run ruff format --check .

uv run freedocs inspect FILE           # report findings, write nothing
uv run freedocs scrub FILE -o out/     # write a scrubbed copy
uv run freedocs entities               # list supported entity types
```

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
- **L2** (M2): NER encoder for names, addresses, organisations.
- **L3** (M8): opt-in Ollama pass over the *already anonymised* text, flagging
  leftovers and quasi-identifiers. Advisory only.

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
codice fiscale values tried during M0 were invalid.

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
`python-docx` and `python-pptx` are for *reading* structure only: they have no
management API for charts, images or pivot tables and can drop them on save.
Hidden content is where the real leak lives — pivot caches hold a raw copy of the
source data, and `pptx` charts embed their whole backing spreadsheet.

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

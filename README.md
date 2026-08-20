# FreeDocs

Remove confidential data from a document before it reaches an LLM. Local, offline,
open source.

Give it a file — plain text today, PDF and Office formats as the milestones land —
and it returns the same format with direct identifiers removed, plus a report of
what went and a verification pass proving none of it survived.

**Status: M5.** The pipeline works end to end on plain text, text-layer PDF and
all three Office formats, with checksum-backed and model-backed detection across
Italian, German, French and English. Scanned documents are still to come. See
[Roadmap](#roadmap).

## Why another one of these

Several tools already do part of this. None of them do all of it:

| Project | Formats | Detection | Gap |
|---|---|---|---|
| [rizzo-pii](https://github.com/Rizzo-AI-Academy/rizzo-pii) | txt, md, PDF | mmBERT + checksums, 22 Italian entities | no Office formats |
| [A5-PII-Anonymizer](https://github.com/AgenticA5/A5-PII-Anonymizer) | txt, docx, xlsx, csv, pdf | Piiranha ONNX | weak detector, no OCR, no pptx |
| [phileas](https://github.com/philterd/phileas) | pdf, docx, xlsx, csv, scans | regex + ML | no pptx |
| [desktop-redactor](https://github.com/williape/desktop-redactor) | csv, json, txt | Presidio | no documents |

What FreeDocs is aiming at, and what makes it different:

- **`xlsx` and `pptx`**, which almost nothing covers.
- **In-place redaction that preserves formatting**, by editing OOXML runs rather
  than flattening the document to text.
- **Hidden content**, which is where the real leak lives: pivot caches, tracked
  changes, speaker notes, shapes parked off-slide, document metadata.
- **A verification stage** that re-opens the output, re-extracts it and fails the
  run if any removed value is still findable.

## How it works

Six stages. Only `pipeline.py` knows the order:

```
router -> extract -> detect -> policy -> write-back -> verify
```

The interesting problem is that the text a model reads and the bytes a writer
edits are not the same thing. Word can store `Mario Rossi` as three separate
runs; a detector needs it joined, a writer needs it split. Flatten it naively and
you lose the formatting, which is why so many tools output plain text.

`core/stream.py` solves this with an offset map. Extraction appends anchored
chunks to a flat string, each `Anchor` remembering where its characters came
from. Detection runs on the flat text. `plan_edits()` translates the resulting
spans back into per-anchor edits, putting a replacement in the first run it
touches and clearing the rest — so surviving runs keep their own properties and
no new run has to be invented.

Detection is layered:

- **L1 — validators.** Regex nominates, checksum decides: codice fiscale CIN,
  partita IVA, AHV (EAN-13), Swiss UID, IBAN mod-97, Luhn. Precision near 1.0.
- **L2 — NER encoder.** For names, addresses, organisations, job titles. GLiNER2
  on an `mdeberta-v3-base` encoder, so one model handles four languages with no
  language hint. Must return character offsets, since those are what the anchors
  need.
- **L2.5 — value propagation.** A value identified once is identified: every
  other occurrence of it in the document is redacted too. Cheap, and it closed
  most of the residual gap (see below).
- **L1 verifies L2's structured claims.** When the model labels something a
  credit card, IBAN or codice fiscale, the matching checksum gets the final say.
  GLiNER2 called two chart amounts — `1500` and `2300` — a card number at 0.87
  confidence; no threshold separates that from a real finding, and Luhn settles
  it in one call.
- **L3 — LLM review via Ollama, opt-in.** A second pass over the *already
  anonymised* text, flagging leftovers and quasi-identifiers. Not the primary
  detector: a generative model does not return reliable offsets, so it cannot
  drive edits into a binary file.

## Measured, not estimated

`uv run freedocs benchmark` scores the layers against `corpus/`: 103 labelled
entities over Italian, German, French and English business documents.

The headline is not F1. For redaction the numbers that matter are **coverage**
(gold entities *fully* removed — a partial span is a leak, because "Rossi" left
behind still identifies someone) and **over-redaction** (characters removed that
were not confidential — a detector that redacts the page leaks nothing and is
useless).

| Layers | Coverage | Over-redaction | Exact micro-F1 |
|---|---|---|---|
| L1 only | 36.9% | 0.0% | 0.539 |
| GLiNER2 only | 80.6% | 0.3% | 0.854 |
| Presidio + spaCy only | 55.3% | 21.5% | 0.211 |
| L1 + GLiNER2 | 94.2% | 0.3% | 0.935 |
| **L1 + GLiNER2 + propagation** | **99.0%** | **0.3%** | **0.961** |

Three things came out of this that were not obvious beforehand:

- **Checksums alone leave about two thirds of the confidential entities in a
  business document.** That is why the NER layer is on by default despite its
  download size, and why a build without it says so loudly instead of quietly
  finding less.
- **Presidio lost on over-redaction, not on recall.** It has no way to know the
  document's language, so every configured language is run and merged, and PERSON
  precision falls to 0.28 — 65 predictions for 24 real names. 21% of the document
  removed for nothing destroys the document. The 1.2 GB model earns its size.
- **Every residual miss was a repeat mention.** The model found "Anna Bianchi" in
  the attendee list and scored the same name below threshold eight lines later.
  Propagation, a literal case-insensitive search with word boundaries, took
  coverage from 94.2% to 99.0% at no over-redaction cost.

The corpus is small and synthetic. These numbers rank configurations against each
other; they are not a published benchmark result, and the tool says so every time
it prints them.

## What a Word file hides

The visible text is the easy part. Everything below was found by building a
realistic `.docx` and looking inside the container, and every item is removed and
named in the report:

- **Deleted text is still in the file.** With track changes on, `<w:del>` keeps
  the removed words in `<w:delText>`. The paragraph someone cut because it named
  the wrong client is there verbatim, and Word shows it to anyone who turns
  markup on.
- **A rendered thumbnail of the first page.** `docProps/thumbnail.jpeg` is a
  picture of the unredacted document, shipped inside the redacted one. Scrubbing
  every character of text and leaving this behind achieves nothing.
- **Hyperlink targets live outside the body.** The visible link text is in
  `document.xml`; `mailto:mario.rossi@example.com` is in
  `document.xml.rels`. Redacting what you can read leaves the address behind.
- **Comments are separate parts**, and `people.xml` maps each commenter to a
  name and usually an email.
- **`customXml/`** is the data store behind content controls, so it holds a
  structured copy of the fields shown in the document.
- **Revision save IDs** (`w:rsid*`) are stable per editing session and link two
  documents to the same author.
- **Metadata** names the author, the last editor, the company, the manager, and
  the local template path — which contains a username.

Removing a part means also removing what points at it. A dangling relationship or
an orphaned `[Content_Types].xml` override makes Word offer to repair the file, so
`OoxmlPackage.drop()` does all three together.

## What an Excel file duplicates

A workbook keeps more copies of its own content than any other format, and each
one survives redacting every cell on every sheet:

- **The pivot cache** stores its own copy of the source rows. A pivot over a
  staff table contains the staff table. It is *redacted in place* rather than
  deleted, so the pivot keeps working.
- **Chart caches** hold the category labels, which are usually the names.
- **External links** cache the last-seen values of the workbook they point at,
  and their relationship target is a UNC path containing a username.
- **Sheet names appear twice**, in `xl/workbook.xml` and again in
  `docProps/app.xml` as `TitlesOfParts`. Redacting one leaves the other.
- **`veryHidden` sheets** are not in the sheet-tab menu at all — unhiding one
  needs the VBA editor — so they are where the raw extract behind a report ends
  up and gets forgotten.
- **Connection strings and Power Query scripts** carry server names, file paths
  and occasionally credentials.
- **The macro project** is opaque binary that cannot be redacted, only removed.

Hidden sheets, rows and columns are reported but kept: their text is redacted
like everything else, and deleting a sheet breaks every formula referencing it.

Two consequences worth knowing before using it on a workbook full of formulas:

- **Redacting a name renames things.** Excel refers to sheets and tables *by
  name* in formulas, so a redacted sheet name breaks the references to it. The
  alternative was leaving identifying names in the file, which the leak check
  would reject. The rename is reported as a warning, naming what changed.
- **Numbers are only anchored at nine digits or more.** A sheet is mostly
  numbers, and an eleven-digit partita IVA checksum passes on roughly one in ten
  arbitrary numbers of that length, so anchoring every amount would turn the
  ledger into placeholders.

## What a PowerPoint deck hides

- **A chart carries its whole source workbook.** `ppt/embeddings/*.xlsx` is a
  complete OOXML package inside the presentation — sheets, string table,
  metadata. A chart of three bars can hold five hundred rows. FreeDocs nests a
  real `XlsxHandler` inside the deck and folds its anchors into the same stream,
  so the workbook inside the chart gets the same treatment as a workbook on its
  own. The leak tests search the zip inside the zip.
- **Speaker notes** are a separate part per slide, invisible while presenting,
  and where the blunt version of the sentence tends to live.
- **Hidden slides** (`<p:sld show="0">`) are skipped when presenting and fully
  intact in the file.
- **Shapes dragged off the canvas** are the same habit without the menu: a text
  box at `x="-4000000"` on a slide 9144000 EMU wide is invisible and complete.
- **Alt text** on a shape is a description someone typed, so it can say anything.
- **SmartArt keeps its own data model** in `ppt/diagrams/`, duplicating the text
  it renders.

Hidden slides and off-canvas shapes are reported but kept: extraction walks the
whole slide part rather than what would be rendered, so their text is redacted
either way, and deleting a slide renumbers the deck.

## Anonymisation, not pseudonymisation

Values are replaced with typed placeholders — `[PERSONA_1]`, `[IBAN_2]` — that
are stable within a document, so the text still reads coherently. The mapping
lives in memory for one run and is destroyed in a `finally` block, including when
a stage raises. Nothing is written to disk, so there is no key to leak.

This does not eliminate re-identification risk. A document stripped of names can
still say "the CFO of the Lugano branch hired in March 2024". Quasi-identifiers
are reported rather than silently rewritten, and every report states the caveat.

## Usage

```bash
cd engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner   # ner adds ~1.2GB of model

uv run freedocs inspect documento.pdf          # what would go, without writing
uv run freedocs scrub documento.pdf -o out/    # write the scrubbed copy
uv run freedocs entities                       # supported entity types
uv run freedocs benchmark                      # score the layers on the corpus
```

Without `--extra ner` everything still works on checksums alone, and every report
states that names, organisations, locations and addresses are not being detected.

Useful flags: `--report r.json` for a machine-readable summary, `--keep URL` to
leave an entity type alone, `--min-confidence 0.8` to raise the threshold.

A failed verification exits non-zero and writes nothing. That is deliberate: a
file that is nearly clean is more dangerous than one that obviously is not,
because it gets sent.

## Roadmap

| M | Content | Status |
|---|---|---|
| M0 | Core, L1 validators, plain text, CLI, verify, tests | done |
| M1 | PDF text: true content-stream redaction, hidden-content scrub | done |
| M2 | L2 NER integrated, labelled corpus, measured coverage | done |
| M3 | `docx` with run-aware write-back and hidden-content scrub | done |
| M4 | `xlsx`, including pivot caches and `veryHidden` sheets | done |
| M5 | `pptx`: notes, hidden slides, off-canvas shapes, chart data | done |
| M6 | Scanned PDF: OCR plus redaction on word bounding boxes | next |
| M7 | Tauri desktop app | |
| M8 | L3 Ollama review, opt-in | |

## Licence

AGPL-3.0-or-later. The PDF milestone uses PyMuPDF, which is AGPL; staying AGPL is
what makes that free to use. Derivative works must stay open.

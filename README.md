# FreeDocs

Remove confidential data from a document before it reaches an LLM. Local, offline,
open source.

Give it a file — plain text today, PDF and Office formats as the milestones land —
and it returns the same format with direct identifiers removed, plus a report of
what went and a verification pass proving none of it survived.

**Status: M1.** The pipeline works end to end on plain text and on PDFs with a
text layer, using a checksum-backed detection layer. It does not yet handle
Office formats, scans, or names. See [Roadmap](#roadmap).

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
- **L2 — NER encoder.** For names, addresses, organisations. Must return
  character offsets, since those are what the anchors need.
- **L3 — LLM review via Ollama, opt-in.** A second pass over the *already
  anonymised* text, flagging leftovers and quasi-identifiers. Not the primary
  detector: a generative model does not return reliable offsets, so it cannot
  drive edits into a binary file.

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
uv sync --extra dev --extra pdf

uv run freedocs inspect documento.pdf          # what would go, without writing
uv run freedocs scrub documento.pdf -o out/    # write the scrubbed copy
uv run freedocs entities                       # supported entity types
```

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
| M2 | L2 NER integrated, precision/recall measured on a corpus | next |
| M3 | `docx` with run-aware write-back and hidden-content scrub | |
| M4 | `xlsx`, including pivot caches and `veryHidden` sheets | |
| M5 | `pptx`: notes, hidden slides, off-canvas shapes, chart data | |
| M6 | Scanned PDF: OCR plus redaction on word bounding boxes | |
| M7 | Tauri desktop app | |
| M8 | L3 Ollama review, opt-in | |

## Licence

AGPL-3.0-or-later. The PDF milestone uses PyMuPDF, which is AGPL; staying AGPL is
what makes that free to use. Derivative works must stay open.

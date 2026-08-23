# FreeDocs

Remove confidential data from a document before it reaches an LLM. Local, offline,
open source.

Give it a file — plain text today, PDF and Office formats as the milestones land —
and it returns the same format with direct identifiers removed, plus a report of
what went and a verification pass proving none of it survived.

**Status: M8 — the plan is complete, plus international coverage.** The engine
handles plain text, PDF (born-digital and scanned) and all three Office formats.
Identifiers are confirmed by checksum for **twelve countries** — Switzerland,
Italy, Germany, Austria, France, Belgium, Spain, Portugal, the Netherlands,
Poland, Sweden and the United Kingdom — and names, addresses and organisations
come from one multilingual model with no language hint. A Tauri desktop app
drives it, and an optional local-LLM pass reviews the result. See
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

- **L1 — validators.** Regex nominates, checksum decides. Forty rules over twelve
  countries: national identity and social-security numbers, tax numbers, VAT
  numbers, company-register numbers, plus IBAN mod-97 and Luhn, which are the
  same everywhere. Every validator comes from `python-stdnum`, which ships 201
  number modules across 87 countries and was already a dependency — extending
  the coverage was populating a table, not training anything.

  Confidence per rule is set from a measurement, not a judgement: each validator
  was run against 20 000 randomly generated format-plausible values to see how
  many it accepts. A rule whose pattern demands a literal prefix (`CHE`, `756`,
  `DE`, `ATU`) stays at full confidence even on a one-in-ten check digit, because
  the prefix discards almost every candidate before the checksum runs. A rule
  that is only digits gets a confidence tied to what its check digit actually
  does, and the weakest ones sit below the default threshold — found and
  reported, never removed, unless a word naming them is nearby.

  Some numbers cannot be done this way and are not pretended into the table. US
  social security and employer numbers have no check digit at all: `stdnum`
  accepts 89% and 83% of random values of their shape. They come from the model
  instead, which is the honest layer for an identifier only its context
  distinguishes. `freedocs countries` prints what each country actually gets.
- **L2 — NER encoder.** For names, addresses, organisations, job titles. GLiNER2
  on an `mdeberta-v3-base` encoder, so one model handles four languages with no
  language hint. Must return character offsets, since those are what the anchors
  need.
- **L2.5 — value propagation.** A value identified once is identified: every
  other occurrence of it in the document is redacted too. Cheap, and it closed
  most of the residual gap (see below).
- **L1 verifies L2's structured claims.** When the model labels something a
  credit card or an IBAN, the matching checksum gets the final say. GLiNER2
  called two chart amounts — `1500` and `2300` — a card number at 0.87
  confidence; no threshold separates that from a real finding, and Luhn settles
  it in one call.

  For a country-issued number the verifier needs to know *whose* it is, and
  usually does not. A tax number is claimed by the twelve countries here and by
  none of the other hundred and eighty, so a Brazilian CPF the model correctly
  spotted passes no check digit this build knows — and "nobody we cover accepts
  it" is not evidence against a number from a country nobody taught us. Without a
  country there is no opinion, and the finding survives.
- **L3 — LLM review via Ollama, opt-in.** A second pass over the *already
  anonymised* text, flagging leftovers and quasi-identifiers. Not the primary
  detector: a generative model does not return reliable offsets, so it cannot
  drive edits into a binary file. See [The second opinion](#the-second-opinion).

## Measured, not estimated

`uv run freedocs benchmark` scores the layers against `corpus/`: 514 labelled
entities over Italian, German, French and English business documents, of which 464
are entities the policy actually removes. The documents cover the twelve
countries, so a rule for one of them is measured rather than asserted.

The headline is not F1. For redaction the numbers that matter are **coverage**
(gold entities *fully* removed — a partial span is a leak, because "Rossi" left
behind still identifies someone) and **over-redaction** (characters removed that
were not confidential — a detector that redacts the page leaks nothing and is
useless).

Coverage is reported over the **removable** entities. The rest are `REPORT_ONLY`
types like job titles, which the policy flags and never deletes, so "share fully
removed" says nothing true about them in either direction. They were a tenth of
the corpus and had been quietly inflating the headline; they are now counted
apart, at 92.0% found.

| Layers | Coverage | Over-redaction | Exact micro-F1 |
|---|---|---|---|
| L1 only | 53.7% | 1.0% | 0.627 |
| GLiNER2 only | 84.1% | 2.2% | 0.773 |
| L1 + GLiNER2 | 94.0% | 2.9% | 0.894 |
| **L1 + GLiNER2 + propagation** | **97.6%** | **2.9%** | **0.912** |

Over-redaction is higher than the 1.2% published before, and most of that is the
corpus rather than the rules. On this corpus, restricted to Switzerland and Italy
so the rule set matches what was measured then, it is already 2.4%: the new
documents are denser in identifier-shaped strings and carry more adversarial
traps. Enabling the other ten countries takes it from 2.4% to 2.9% and buys 2.1
points of coverage. `--countries` reproduces either number, and
`--apply-min-confidence 0.5` reports what a scrub would actually do rather than
what the detector nominated, which is 2.7%.

Presidio is absent from this table on purpose: it was measured on the earlier
103-entity corpus at 55.3% coverage and **21.5%** over-redaction, and quoting that
figure beside numbers from a different corpus would compare two annotations rather
than two detectors. Re-running it needs the `ner-presidio` extra. The finding that
mattered has not changed and is why the option still exists to be re-measured:
Presidio lost on *over-redaction*, not on recall. It has no way to know the
document's language, so every configured language is run and merged, and PERSON
precision fell to 0.28. Removing a fifth of a document for nothing destroys it.

What this corpus shows that the previous one could not:

- **Checksums alone leave about half the confidential entities in a business
  document.** That is why the NER layer is on by default despite its download
  size, and why a build without it says so loudly instead of quietly finding less.
- **Propagation is worth more than any threshold change.** Most residual misses
  are repeat mentions: the model finds "Anna Bianchi" in the attendee list and
  scores the same name below threshold eight lines later. A literal
  case-insensitive search with word boundaries takes coverage from 94.0% to 97.6%
  at no over-redaction cost.
- **Place names that double as surnames are the weak spot.** Every remaining leak
  but one is a `LOCATION`: `Basel`, `Zug`, `Preston`, `Leeds`, `Geneve`, `Lyon`,
  `Sion`, `Firenze` — each of which also appears in the same document as somebody's
  surname. LOCATION coverage is 75.8% against 100% for PERSON. The earlier corpus
  had no such collisions and so reported nothing about them.
- **The over-redaction cost is nearly all ambiguity with no checksum behind it.**
  A four-part firmware version is indistinguishable from an IPv4 address, and an
  eight-digit customer number is a valid Italian landline. Nothing in a regex can
  settle either.

- **A phone number written the way a local writes it is only findable by that
  country's plan, and that is what those plans cost.** A number carrying its own
  country code is unambiguous, so one region-less pass finds every `+41 44 …` in
  the document. It finds not one `044 668 18 00`. Measured: the region-less pass
  alone reaches 82.9% PHONE coverage at precision 1.00, all thirteen national
  plans reach 97.1% at 0.67. All of them are on, because a number a scrub leaves
  behind gets sent while an over-redacted order number is read and shrugged at.

- **At twelve countries, a broken identifier is often a valid one somewhere
  else.** Three corpus traps written as rejected values had to be replaced: a
  rejected Polish REGON is a valid Portuguese NIF, a rejected Polish NIP is a
  valid British UTR. Changing the last digit no longer produces a value nothing
  accepts, and a trap now has to be checked against every rule — which a test
  enforces, because the benchmark otherwise charges the detector for being right.

- **Per-country precision is where a weak check digit shows.** `freedocs
  benchmark` prints it: Switzerland, Germany, France, Belgium, the Netherlands,
  Portugal and Sweden sit at 1.00, while Spain (0.40), the United Kingdom (0.55),
  Austria (0.58) and Poland (0.62) carry the rules whose validators accept 8-10%
  of random values of the right shape. Those are the rules that stay below the
  default threshold without a keyword beside them.

The corpus is still small and synthetic. These numbers rank configurations against
each other; they are not a published benchmark result, and the tool says so every
time it prints them.

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

## The desktop app

```bash
cd app
npm install
npm run check            # types, and proof that all four message catalogues are complete
npm test                 # the offset arithmetic behind the marked text
npm run tauri dev        # uses the engine from engine/.venv, no bundle needed
CI=true npm run tauri build   # needs the sidecar built first, see below
```

The app is a window around the engine and holds no rules of its own. Every
judgement about what is confidential, what gets removed and what the user is
warned about stays in Python: two places deciding what an IBAN looks like is two
answers that can disagree.

They talk newline-delimited JSON over a pipe — `engine/freedocs/rpc.py`, exercised
by 82 tests that need no GUI. One engine process serves the whole session, because
loading the NER model takes seconds and running it takes milliseconds. The engine
is **never** a socket: it reads and writes files named by whoever is on the other
end, so its only safe caller is a parent process that already has the user's
permission.

Three steps — pick the files, read what was found, see what was written — with the
extracted document shown and every finding marked in place. That is what makes the
per-occurrence decision usable: the sentence *around* a value is what says whether
a city is a party's address or a jurisdiction clause, which is the distinction the
engine keeps `keep` and `keep_spans` apart for. The marks are walkable from the
keyboard, `x` excuses one, and every decision goes back to Python to be judged
there.

What the window shows, deliberately: the detection layers actually loaded, whether
OCR is available *and which half of Tesseract is missing when it is not*, what
each country actually gets (the United States has no check digit behind its
numbers, and its chip says so), which rules a raised threshold has silenced, every
warning the engine raised, the hidden content that was removed, and whether stage
6 re-opened the output and found nothing. A build that quietly finds less has to
say so.

Two things it deliberately does not do. It never invents a percentage: progress
counts files and stages and pages, because how long detection takes next to
extraction on an unseen document is not a fact the engine has. And it does not
translate the engine's own sentences — warnings, caveats, review summaries and
errors are quoted in English inside a window that is otherwise Italian, German,
French or English, with one line saying so. A mistranslated "not installed" that
reads as "not required" is the failure this project refuses, and the test suite
asserts on those strings.

The frontend has no UI framework and one test dependency. What Vitest covers is
the offset arithmetic behind the marked text, and it covers it because that is
where being wrong is silent: Python counts code points and JavaScript counts
UTF-16 code units, so one emoji in a document moves every highlight after it —
and, worse, moves every span the window sends back.

### Building for distribution

```bash
cd engine
uv run --with pyinstaller python packaging/build.py   # -> engine/dist/freedocs-engine/
cd ../app && CI=true npm run tauri build              # -> .app and .dmg
```

`CI=true` matters: without it the `.dmg` step runs AppleScript to arrange icons in
a Finder window, which needs Finder automation permission and times out in any
non-interactive shell. The `.app` builds either way; only the disk image fails, and
only after several minutes. Result here: a 1.0 GB `.app` and a 325 MB `.dmg`.

One directory, not one file: a one-file bundle unpacks half a gigabyte of torch to
a temporary directory on every launch. It ships as a Tauri resource and the Rust
side spawns the executable inside it — and falls back to the repository
virtualenv, which is what makes `tauri dev` usable before any bundle exists.

`packaging/build.py` runs the built binary and asks it for `capabilities` before
declaring success. Every format handler and detector backend is imported lazily,
so a missing hidden import produces a binary that works until the user opens that
format; asking what it supports is what catches that.

Not in the bundle, on purpose: the NER model (~1.2 GB, fetched to the user's cache
on first use) and Tesseract. Both absences are reported through `capabilities`, so
the app says so rather than failing mysteriously.

**Multi-platform status, honestly.** `.github/workflows/app.yml` builds macOS
(arm64 and x86_64), Linux and Windows on their own runners, because neither
PyInstaller nor Tauri cross-compiles. macOS is the only one built and run here;
the Linux and Windows halves are configured and wired into CI but have not been
executed on this machine. Apple signing is opt-in through repository secrets — an
unsigned build still works for testing.

The obvious size win is not taken yet: torch is 501 MB of the bundle, and the NER
model would run under `onnxruntime` at roughly 15 MB. Exporting GLiNER2 to ONNX
needs re-benchmarking to prove the numbers above still hold, so it is a measured
optimisation rather than a refactor to do blind.

## The second opinion

```bash
uv run freedocs review-models                          # what Ollama has pulled
uv run freedocs scrub doc.docx -o out/ --review qwen3-coder:latest
```

Off by default. It takes tens of seconds, it needs a local model nobody is obliged
to have, and it changes nothing in the output.

What it is for is the one thing nothing else in this project can do. The checksum
and NER layers cover 99% of the corpus at 0.3% over-redaction, and what they cannot
fix is not a missed span — it is a document with every name removed that still says
"the only female partner in the Lugano office, hired in March 2019". No single
redaction repairs that. A reader can notice it; a span-based detector cannot.

Asked of a real local model, on a document whose every direct identifier was
already a placeholder, it returned exactly that:

```
[quasi_identifier] "l'unica donna partner dell'ufficio di Lugano"
    -> role plus location identifies one person
[quasi_identifier] '84 anni, residente a Bedigliora (312 abitanti)'
    -> age plus a town of 312 people
```

Three properties it holds to:

- **It never edits.** The output is already written when the review runs. Its
  findings are for a human, and the report says so.
- **A skipped review does not look like a clean one.** `ReviewOutcome.ran` is
  separate from an empty list of concerns, because "Ollama was not running" and
  "the reviewer had no objection" are different facts and the second is reassuring.
- **A non-loopback host is refused** unless the caller passes `--review-remote`.
  Ollama is local by default and nothing leaves the machine, which is the only
  basis on which this layer belongs in this tool. Pointing `OLLAMA_HOST` at a GPU
  box has to be a decision, not an accident — and the refusal says why: scrubbed is
  not the same as harmless, since the review exists precisely because
  quasi-identifiers survive a scrub.

  Listing a host's models is refused on the same terms, from the same message.
  Offering a choice that the scrub then rejects reads as a bug rather than as the
  rule it is, and asking a machine which models it has is still talking to it.

It reads the first 12 000 characters. A model handed forty pages returns
generalities, and the report says when only part was covered.

The window exposes the host and the model, not the guard. Where Ollama listens is
a runtime question — an instance on another port used to leave the app showing an
empty list with no way to correct it, which reads as "this build cannot review"
when the truth is "look somewhere else". The `review_models` RPC method answers
for one specific host, and the app prefills the default from `capabilities`
rather than keeping a second copy of the address. Allowing an off-machine host
stays a pipe-level parameter with no control in the window: it is reachable
deliberately, from the CLI or from a caller that says so.

## Scans: redacting pixels, not glyphs

On a scanned page there are no glyphs to delete — the text *is* the image. The
same `apply_redactions()` call blanks the image pixels inside the rectangle,
editing the image stream rather than covering it, so re-running OCR on the output
no longer reads the value. The tests check exactly that: they machine-read the
scrubbed file and assert the canary is unreadable, while the rest of the page
still is.

Three things this milestone settled:

- **The decision is per page, not per document.** Real files mix them — a
  contract exported from Word with the signed page scanned back in. PyMuPDF
  returns OCR results in the page's own coordinate system with the same structure
  as the text layer, so extraction, anchoring and redaction stay one code path.
- **Verification had to be made adversarial.** A scanned page is only
  machine-read when its text layer looks empty; after redaction it carries the
  placeholders, which is enough text to look ordinary. Verification was therefore
  inspecting the placeholders and never the pixels — a failed pixel redaction
  would have passed. `harden_for_verification()` now makes the check re-read every
  imaged page.
- **OCR is a reading, not the text.** A codice fiscale with one character misread
  fails its checksum, is never detected, and survives. That is inherent to
  redacting a scan, so every machine-read page is named in a warning telling the
  user to check it by eye.

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

Values are replaced with typed placeholders — `[PERSON_1]`, `[IBAN_2]` — that
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

### Scanned documents

OCR needs the Tesseract binary and its language data, neither of which pip can
install. PyMuPDF drives Tesseract directly, so there is no Python package:

```bash
brew install tesseract                     # or your platform's package
mkdir -p engine/models/tessdata
for lang in ita deu fra eng spa nld por pol swe; do
  curl -sSL -o "engine/models/tessdata/$lang.traineddata" \
    "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata"
done
```

Nine languages, one per language spoken in the twelve countries whose
identifiers this build confirms. Asking for all of them at once costs almost
nothing in time — 223 ms for one page with four languages, 247 ms with nine —
because the document's language is not known and a scrubber that has to guess it
before it can read the page has an extra way to fail silently. The cost is on
disk: 143 MB of language data, against 57 MB for four.

`engine/models/tessdata` is searched by default, after `FREEDOCS_TESSDATA` and
`TESSDATA_PREFIX`, and a packaged build carries the same files beside its
executable. Homebrew's `tesseract-lang` works too, at 1.2 GB for every language.

The binary and the language data are installed separately and only one of them
can be bundled, so `capabilities.ocr_available` checks for both.

Without it, a PDF whose pages have no text layer is **refused** — naming the
pages and what to install — rather than returned untouched.

Useful flags: `--report r.json` for a machine-readable summary, `--keep URL` to
leave an entity type alone, `--min-confidence 0.8` to raise the threshold,
`--countries ch,it` to look for identifiers from those countries only, and
`--placeholder-language it` to write the placeholders in Italian rather than
English.

`--countries` raises precision and can hide an identifier from a country you did
not expect in the file, so it is never required: leave it off and every supported
country is looked for. A narrowed run says so in the report and in the window,
because the output otherwise looks exactly like a full one.

Placeholders are English by default — `[PERSON_1]`, `[TAX_ID_1]` — because the
reader of a scrubbed document is usually a language model and the stem is the only
thing telling it what used to be there. Italian, German and French are available
for a human audience.

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
| M6 | Scanned PDF: OCR plus redaction on word bounding boxes | done |
| M7 | Tauri desktop app | done |
| M8 | L3 Ollama review, opt-in | done |

## Licence

AGPL-3.0-or-later. The PDF milestone uses PyMuPDF, which is AGPL; staying AGPL is
what makes that free to use. Derivative works must stay open.

# Command line reference

```bash
cd engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner
```

Python 3.12 is what this is developed on; 3.10 is the declared floor and CI runs
both. `--extra ner` fetches ~1.2 GB of model weights to the Hugging Face cache on
first use. Without it everything still works on checksums alone, and **every
report states that names, organisations, locations and addresses are not being
detected** — a build that finds less has to say so.

## `inspect` — report, write nothing

```bash
uv run freedocs inspect FILE [FILE ...] [--min-confidence F] [--detectors SPEC] [--countries CODES] [--remove VALUE] [--terms FILE]
```

```console
$ freedocs inspect examples/offerta-esempio.txt
offerta-esempio.txt  [plaintext]  645 chars
       31-52      ORGANISATION           redact    conf=0.94  via gliner2:organization
       53-83      ADDRESS                redact    conf=0.61  via gliner2:address
       89-104     COMPANY_ID             redact    conf=1.00  via ch-uid
      115-135     ORGANISATION           redact    conf=1.00  via gliner2:organization
      147-161     PERSON                 redact    conf=1.00  via gliner2:person
      163-184     JOB_TITLE              report    conf=0.96  via gliner2:job title
      192-225     EMAIL                  redact    conf=1.00  via email
      236-252     PHONE                  redact    conf=1.00  via phonenumbers-international
      299-310     VAT_ID                 redact    conf=1.00  via it-partita-iva-luhn11
      340-356     TAX_ID                 redact    conf=1.00  via it-codice-fiscale-cin
      379-405     IBAN                   redact    conf=1.00  via iban-mod97
      435-446     PERSON                 redact    conf=1.00  via gliner2:person
      448-469     JOB_TITLE              report    conf=0.97  via gliner2:job title
      490-502     PERSON                 redact    conf=1.00  via gliner2:person
```

`redact` and `report` are the two policy actions: a `REPORT_ONLY` type is flagged
and never deleted. `via` names the rule or the model label that nominated the
span, which is how a surprising finding gets traced to one place.

## `scrub` — write a scrubbed copy

```bash
uv run freedocs scrub FILE [FILE ...] -o DIR
pbpaste | uv run freedocs scrub - | pbcopy      # text on stdin, scrubbed text on stdout
```

| Flag | What it does |
|---|---|
| `-o, --output-dir DIR` | required for files, refused with `-`; scrubbed copies keep their filename |
| `--report PATH` | machine-readable JSON summary — counts and positions, never values |
| `--min-confidence F` | ignore findings below this confidence (default 0.5) |
| `--keep ENTITY` | leave an entity type untouched everywhere; repeatable |
| `--placeholder-language {de,en,fr,it}` | language of the placeholder stems written into the output |
| `--countries CODES` | e.g. `ch,it,de`; defaults to every supported country |
| `--detectors SPEC` | `l1`, `ner`, `all`, `all:presidio` |
| `--remove VALUE` | also remove every occurrence of this exact text; repeatable. Also on `inspect` |
| `--terms FILE` | also remove every entry of an encrypted term list — see [terms.md](terms.md). Also on `inspect` |
| `--terms-passphrase-file PATH` | the term list's passphrase; otherwise `FREEDOCS_TERMS_PASSPHRASE`, otherwise a prompt |
| `--allow-leaks` | write the output even when verification finds a survivor |
| `--review MODEL` | ask a local Ollama model to read the result — see [llm-review.md](llm-review.md) |
| `--review-host URL` | which Ollama (default `http://127.0.0.1:11434`) |
| `--review-remote` | permit a host that is not on this machine |
| `--map PATH` | also write an encrypted key file, so the scrub can be undone — see [restore.md](restore.md) |
| `--map-passphrase-file PATH` | read the key file's passphrase from the first line of this file |
| `--map-in-output-dir` | permit the key file inside `--output-dir`; refused by default |

Console output on a `.docx`:

```console
$ freedocs scrub examples/offerta-esempio.docx -o clean/
offerta-esempio.docx  [docx]
  removed:
    ADDRESS                1
    COMPANY_ID             1
    EMAIL                  1
    IBAN                   1
    ORGANISATION           2
    PERSON                 3
    PHONE                  1
    TAX_ID                 1
    VAT_ID                 1
  flagged for review: 2
  hidden content removed:
    docProps/thumbnail.jpeg page-thumbnail             rendered preview of the unredacted file
    customXml/_rels/item1.xml.rels custom-xml-store           data store behind content controls
    customXml/item1.xml custom-xml-store           data store behind content controls
    customXml/itemProps1.xml custom-xml-store           data store behind content controls
    docProps/core.xml metadata                   author, description, last editor, revision count
    docProps/app.xml extended-metadata          template path, total editing time
    word/document.xml revision-save-ids          3 rsid attribute(s) fingerprinting the editing session
    word/settings.xml revision-save-id-table     10 recorded editing session(s)
  verify: no leak: 12 distinct values checked against 564 characters of output
  written: clean/offerta-esempio.docx
```

### Notes on three flags

**`--countries` raises precision and can hide an identifier from a country you did
not expect in the file**, so it is never required: leave it off and every
supported country is looked for. A narrowed run says so in the report and in the
window, because the output otherwise looks exactly like a full one.

**`--placeholder-language` defaults to English** — `[PERSON_1]`, `[TAX_ID_1]` —
because the reader of a scrubbed document is usually a language model and the stem
is the only thing telling it what used to be there. Italian, German and French
exist for a human audience. The country-issued types are not translated in any
locale: one stem stands for twelve countries, and every national name for it would
be wrong on eleven.

**`--allow-leaks` is the one flag that turns off the safety net.** Without it a
failed verification exits non-zero and writes nothing, which is deliberate: a file
that is nearly clean is more dangerous than one that obviously is not, because it
gets sent.

**`--map` is the one flag that makes a scrub reversible**, and the only one that
creates something as confidential as the input. Without it the mapping is destroyed
at the end of the run and the scrub cannot be undone by anyone, including you. With
it, one encrypted `<stem>.fdmap` per document is written — and it must not travel
with the scrubbed copy. There is no `--map-passphrase`: a passphrase on a command
line is in the shell history and visible through `ps`. Read
[restore.md](restore.md) before using it.

## `restore` — put the values back

```bash
uv run freedocs restore FILE [FILE ...] --map KEYFILE -o DIR
pbpaste | uv run freedocs restore - --map keys/pasted.fdmap   # a pasted reply
```

| Flag | What it does |
|---|---|
| `--map PATH` | required; the key file written by `scrub --map` |
| `-o, --output-dir DIR` | required for files, refused with `-`; restored copies keep their filename |
| `--map-passphrase-file PATH` | read the passphrase from the first line of this file |
| `--report PATH` | machine-readable JSON summary — placeholders and counts, never values |

The file you pass is **whatever came back from the model**, not the document you
sent: a rewritten paragraph, a summary, an answer pasted into a `.md`. Any
supported format is read, and the placeholders are found in it.

```console
$ freedocs restore risposta.md --map keys/offerta.fdmap -o back/
risposta.md  [plaintext]
  restored:
    IBAN                   1
    PERSON                 5
  not in this document: [EMAIL_1]
  placeholder-shaped and unknown to this key file: [PERSONA_1]
  verify: restored: 6 occurrence(s) of 4 value(s) against 1841 characters of output
  written: back/risposta.md
```

Both extra lines matter. `not in this document` is a placeholder the key file knows
and the returned text does not have — usually text the model dropped, and not a
failure. `unknown to this key file` is a token that *looks* like ours and is not in
the map: a stem the model translated, a number it invented. Those are left exactly
where they are, because guessing which value a damaged token meant would put
somebody else's data in the document.

Runs no detector and loads no model, so it works the same on a build without the
`ner` extra. Needs the `restore` extra for the cipher; `freedocs doctor` says
whether this build has it.

### `-`: text on stdin

`scrub -` and `restore -` read text from stdin and write the result to stdout.
Stdout carries **only** the text, so a pipe into a model gets nothing else; the
summary, the key file's path and every warning go to stderr. `-` stands alone:
it cannot be mixed with files, and `-o` is refused beside it. A scrub that fails
verification writes nothing to stdout. With `--map DIR` the key file is
`DIR/pasted.fdmap`; a CLI process ends, so there is no held mapping here — that
is the window's text mode, over the pipe. The text is capped at 2 000 000
characters.

## `terms` — the encrypted term list

```bash
uv run freedocs terms create|list|add|remove|import|export|rekey FILE ...
```

Values removed on every scrub that passes `--terms FILE`. Every change is saved
before the command returns. `import` tells you to delete its source and does not
do it itself; `export` writes the list **unencrypted** and asks first. The full
reference, and what the encryption does and does not protect, is in
[terms.md](terms.md).

A value that `--remove` or the list names and the document does not contain is
counted in the report, never quoted. `--remove` values are also named on the
console, which already shows what was found; term-list entries are not, because
most of a list is absent from any one document.

## `entities`, `countries`, `doctor`

```bash
uv run freedocs entities     # the entity types this build detects
uv run freedocs countries    # what each country actually gets
uv run freedocs doctor       # what this machine can actually do
uv run freedocs doctor --json --strict
```

```
at  NATIONAL_ID, TAX_ID, VAT_ID          gb  NATIONAL_ID, TAX_ID, VAT_ID
be  NATIONAL_ID, VAT_ID                  it  TAX_ID, VAT_ID
ch  COMPANY_ID, NATIONAL_ID              nl  NATIONAL_ID, VAT_ID
de  TAX_ID, VAT_ID                       pl  COMPANY_ID, NATIONAL_ID, VAT_ID
es  COMPANY_ID, NATIONAL_ID              pt  NATIONAL_ID, TAX_ID
fr  COMPANY_ID, NATIONAL_ID, TAX_ID, VAT_ID
se  COMPANY_ID, NATIONAL_ID, VAT_ID
us  phone numbers and the NER layer only
```

The United States is in the list with no checksum rules because neither of its
numbers has a check digit — see [architecture.md](architecture.md#l1--validators-regex-nominates-checksum-decides).
A test pins that so a second such case cannot appear silently.

`doctor --strict` is off by default because a machine without Tesseract is a
normal machine, and a health check that calls that an error teaches people to
ignore it.

Its first line is `Engine build`, which is identity rather than health — always
`ok`, because a build is not a fault. It reports the version and whether this is a
packaged build, and the second half is the useful one: inside a bundle every fix
that would name a virtualenv is *withheld* rather than rewritten, and until this
line existed that absence looked exactly like a check with nothing to suggest. It
names no path and no build date on purpose — in a checkout the app spawns
`freedocs-rpc` while `sys.executable` is the interpreter, so a date from here
would be the modification time of Python. The desktop app reports that half,
because only the process that launched the engine knows which file it launched.

When Tesseract is missing, the OCR fix is the install command for the package
manager **this machine actually has**, language data included — see
[scanned-pdfs.md](scanned-pdfs.md). Nothing runs it for you, and that is a
decision rather than an omission.

## `benchmark`

```bash
uv run freedocs benchmark
uv run freedocs benchmark --detectors "l1,all:gliner2,all:presidio"
uv run freedocs benchmark --countries ch,it
uv run freedocs benchmark --apply-min-confidence 0.5
uv run freedocs benchmark --language it --language de
uv run freedocs benchmark --corpus path/to/corpus
```

See [benchmark.md](benchmark.md) for what each figure means and what the corpus
can and cannot show.

## `review-models`

```bash
uv run freedocs review-models [--review-host URL] [--review-remote]
```

Lists what the local Ollama has pulled. Unreachable returns an empty list rather
than raising — refused is loud, absent is quiet.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | done |
| 2 | usage error, including an unknown detector spec or country code |
| 3 | **verification found a surviving value; nothing was written for that file** |
| 4 | the input cannot be processed correctly and the honest answer is to refuse: unsupported format, a scanned PDF with no OCR available, a missing optional dependency |
| 5 | **`restore` only: the file was written and something did not make it back** |

Code 3 is the one to wire into a script. It means the tool did the work, checked
its own output, and refused to hand back a file it could not vouch for.

Code 5 is its mirror and the handling is deliberately opposite: the restored file
**is** on disk. A scrub that leaks must write nothing, because a nearly-clean
document gets sent; a half-restored one is your best available artifact and its
defect is visible in it. Treat 5 as "look at the output", not as "nothing
happened".

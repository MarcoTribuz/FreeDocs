# The reverse path

FreeDocs removes values and, by default, forgets what they were. That is
anonymisation, it is still the default, and it is what makes the tool safe to
point at a document you have not read.

It also stops one step short of a common task. The real sequence is *scrub → hand
to the model → get something back → put the real values back in*. Without the last
step FreeDocs can only be used to **ask** a model something; it cannot be used to
have a document **worked on**.

So there is a second, opt-in direction:

```console
$ freedocs scrub offerta.docx -o clean/ --map keys/
offerta.docx  [docx]
  removed:
    IBAN                   1
    PERSON                 3
  verify: no leak: 4 distinct values checked against 612 characters of output
  written: clean/offerta.docx
  key file: keys/offerta.fdmap

$ freedocs restore risposta.md --map keys/offerta.fdmap -o back/
risposta.md  [plaintext]
  restored:
    IBAN                   1
    PERSON                 5
  placeholder-shaped and unknown to this key file: [PERSONA_1]
  verify: restored: 6 occurrence(s) of 4 value(s) against 1841 characters of output
  written: back/risposta.md
```

Note what the second run was given: not the document that was sent, but **whatever
came back**. Usually that is not the same file at all — a rewritten paragraph, a
summary, an answer pasted into a `.md`. Restore reads any supported format and
looks for the placeholders in it.

## What changes when you use it

Everything below is what the tool does *not* do unless you pass `--map`.

**One thing is created that otherwise never exists.** The key file is the
placeholder-to-original mapping for one document. It is as confidential as the
original: anyone holding it and its passphrase holds every value the scrub
removed. It is not a report and must not be handled like one.

**The threat model shifts.** Without a key file there is nothing to steal and no
way to reverse the scrub, by anyone, including you. With one, the guarantee becomes
"the file cannot be read without its passphrase" — which is a real guarantee, and a
different one.

Because of that, everything about the file is built with the burden of proof on the
dangerous side.

## The key file

**It is always encrypted.** There is no plaintext form and no flag to ask for one.
The passphrase goes through scrypt (n=32768, r=8, p=1, fresh 16-byte salt) and the
payload through AES-256-GCM with a fresh 12-byte nonce. The cleartext header — the
version, the KDF parameters, the document name, the format, the SHA-256 of the
scrubbed output — is bound as associated data, so the ciphertext cannot be lifted
onto a different header and made to describe another document.

**There is no `--map-passphrase` argument**, deliberately: a passphrase on a
command line is in the shell history and visible to every other account through
`ps`. Three sources, in order:

1. `--map-passphrase-file PATH` — the first line, trailing newline stripped
2. the `FREEDOCS_MAP_PASSPHRASE` environment variable
3. an interactive prompt, asked twice when writing

No terminal and neither of the first two set is a usage error, never a silent
skip: a scrub that quietly wrote no key file is a scrub you find out about when you
try to restore. Minimum eight characters, refused hard.

**One file per document**, named `<stem>.fdmap`. A directory gets one per input. A
combined file would be one file that leaks three documents, and everything else in
this engine is already scoped per document for the same reason — see
`Override.for_path`.

**It is refused inside the output directory** unless you pass
`--map-in-output-dir`. The accident this prevents is not theft: it is zipping the
output folder and sending it, or having it inside a synced `Documents`. The
scrubbed document and the key to undo it, travelling together.

**Mode `0600`**, and set with `os.open` rather than a `chmod` afterwards — between
those two calls the key sits on disk world-readable.

**What is in it:** one row per placeholder, carrying the value, the entity type,
the country, how many times the scrub replaced it, and how many distinct spellings
collapsed into it. No offsets: they describe an extraction of a file that no longer
exists, restore searches the returned text anyway, and they would be extra
confidential detail in the one file that must carry as little as possible.

`REPORT_ONLY` types are absent. A date or a job title is flagged and never
replaced, so there is no placeholder to invert.

## The three things restore cannot do

**It cannot bring back what was removed rather than replaced.** `scrub_hidden()`
*deletes* thumbnails, metadata, custom XML stores, hidden slides and macro
projects. Those were never placeholdered. This is the expectation most likely to be
wrong.

**It cannot recover every spelling.** `policy._normalise` casefolds and collapses
whitespace, so `Mario Rossi`, `MARIO ROSSI` and `Mario  Rossi` share one
placeholder. What comes back is the first spelling in document order, and the key
file says so:

```
warning: 2 placeholder(s) stood for a value written more than one way (differing
case or spacing); a restore writes the first spelling seen in the source document,
not each original form
```

**It cannot repair a damaged placeholder.** Matching is literal. A stem the model
translated (`[PERSONA_1]` out of an English scrub), a number it invented
(`[PERSON_9]`), a token it reformatted (`[ PERSON_1 ]`) — each is reported and left
in place:

```
  placeholder-shaped and unknown to this key file: [PERSON_9], [PERSONA_1]
```

That is the deliberate trade. Guessing which entry a damaged token meant would put
somebody else's value in the document while reporting success; a visible
placeholder is the better failure. Markdown around an intact token is fine —
`**[PERSON_1]**` still contains `[PERSON_1]`.

One thing that needs no tolerance: `[PERSON_1]` cannot be confused with
`[PERSON_11]`, because the closing bracket ends the token. That is the one place
the brackets earn their keep.

## Verification runs both directions

Stage five re-opens what was written, re-extracts it as hard as a scrub verifies
its own output, and asks two questions per restored value: **is the placeholder
gone, and did the value arrive?**

The second half is not symmetry. `PdfTextHandler` replaces text by stamping a
redaction annotation, and PyMuPDF silently drops a replacement that does not fit
its rectangle — and a real value is almost always longer than the token it
replaces. So on a PDF the common failure is the token removed and the value never
written, which a one-directional check reads as a success.

Failures are named without their values, for the reason `Leak.describe()` names
none: the message travels to stderr, into a JSON report and through the RPC layer.

```
  [IBAN_1] was removed from the output but its IBAN value did not arrive - the
  replacement was dropped rather than written
```

**A handler's own warning is the exception, and the report drops it for that
reason.** In the scrub direction PyMuPDF's "does not fit the space its original
occupied" quotes a *placeholder*, which is harmless. Here it quotes the text being
written — the real value. So those warnings go to the console and down the local
pipe, the same channel `inspect` sends matched text over, and
`build_restore_report` carries `handler_warnings` as a **count** instead: a report
may be attached to a ticket. `verification.problems` names which value failed,
value-free, which is the part a reader can act on.

A plaintext round trip cannot show that, because it never warns. The test that
does is a PDF.

## An incomplete restore still writes its file

This is the opposite of a scrub, on purpose. A scrub that fails verification writes
nothing, because a nearly-clean document is more dangerous than an obviously dirty
one: it gets sent. A restore that left one `[IBAN_1]` behind has produced your best
available artifact, and its defect is visible in it.

So the file is written, every problem is printed, and the exit code is `5` —
distinct from the leak code `3` because the handling is distinct.

| Format | Round trip |
|---|---|
| `.txt`, `.md`, `.csv` and the rest of plaintext | Clean. True splice. |
| `docx`, `xlsx`, `pptx` | Clean. True splice through `lxml` on the zip parts, so a value longer than its placeholder lands in the first run and the others keep their formatting. |
| `pdf` | The weak case. Write-back is a redaction annotation, not a splice, so a longer value is shrunk to `MIN_FONT_SIZE` and warned about — and dropped if even that does not fit, which verification then catches. |

In practice a model rarely returns a PDF, and the plaintext and Office paths are
the ones this feature is for.

## This build, and the window

The cipher is an optional extra:

```bash
uv sync --extra dev --extra pdf --extra ooxml --extra restore
freedocs doctor          # "Key file" says whether this build can write one
```

A build without it refuses `--map` and `restore` with a `MissingDependency` and
exit code `4`, and never quietly writes an unencrypted file.
`mapping_unavailable_reason()` is the single authority — `capabilities` publishes
it, `doctor` renders it and both halves of the feature raise from it, so the
capability and the refusal cannot disagree.

In the desktop app the two directions are a mode switch in the rail, not a fourth
step: a document comes back from the model days after the scrub that produced it,
so there is no session to continue from. The key-file controls live with the scrub
options, before the run, because the engine writes the file inside the `scrub`
request — which is what keeps the mapping from ever crossing the pipe into the
window. The passphrase is held for the length of one call and cleared in a
`finally`; unlike the theme and the locale it never touches `localStorage`. The
control is disabled, with the engine's own sentence beside it, when
`mapping_available` is false.

## The RPC surface

```
scrub    { paths, output_dir, map, map_passphrase, map_in_output_dir?, ... }
         -> results[].key_file, results[].report.key_file_written

restore  { path, map, passphrase, output_dir }
         -> { ok, output, restored[], not_present[], unknown_placeholders[],
              problems[], warnings[], report }
```

`restore` takes one `path`, not a list: a key file describes one document.

### Pasted text

```
inspect_text  { text, ...inspect's options }        -> inspect's shape, text included
scrub_text    { text, keep_map?, map?, map_passphrase?, ...scrub's options }
              -> { ok, text, removed, flagged, warnings, suppressed, review,
                   handle, key_file, report }
restore_text  { text, handle }  or  { text, map, passphrase }
              -> restore's shape without output and format, plus text
forget        { text_maps: [handle, ...] | "all" }  -> text_maps_released
```

A paste has no file, so it goes by `pasted.txt` in the report and in a key file
(`pasted.fdmap`). Nothing is written to disk and nothing is cached. The mapping
goes one of three ways, chosen per text: **thrown away** (the default, the same
as every scrub), **held** in the engine under a handle with `keep_map: true`, or
**sealed** into a key file with `map` and `map_passphrase`.

A held mapping is the one re-identification key this engine keeps past the
request that made it, so it is bounded:

- only when `keep_map` asked for it, never by default;
- the handle is random (`secrets.token_urlsafe(16)`), never derived from the text;
- at most eight, the oldest dropped first;
- released by `forget` with `text_maps`, and by the process ending. A plain
  `forget` does not release them, and `forget {text_maps}` does not touch the
  cached file extractions.

`restore_text` does not consume the handle: asking the model a second time is
normal. A handle that is not held (forgotten, evicted, or from before a restart)
is `INVALID_REQUEST` with a message that names no value; scrub the text again.

A leak in `scrub_text` returns `scrub`'s value-free failure shape and **no
`text`**, and holds nothing. The pasted text is capped at
`capabilities.text_max_characters` (2 000 000).

The passphrase travels over the pipe — the same channel that already carries the
extracted document text, to a child process the caller started. What matters is
that no failure puts it into a response, which is why every error comes from
`core/mapping.py` rather than being composed near the value, and why
`test_rpc.py` asserts that a wrong-passphrase response contains neither the
passphrase nor a value.

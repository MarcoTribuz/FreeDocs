# Closing the gaps against Cedreon

Status: proposed, 30 September 2026. Nothing here is implemented. Decisions taken
the same day are marked **Decided** in their section.

The comparison that produced this list is the Cedreon gap analysis (Claude Docs,
Italian). In short: Cedreon is a hosted AI workspace whose masking is one feature;
FreeDocs is an offline scrubber whose output is a verified document. The gaps that
matter are the ones a user feels **between** FreeDocs and the model they paste
into: getting text in, getting the answer's values back, and not retyping the
same client names every time.

## What is in and what is out

| # | Work | Closes gap | Decision |
|---|---|---|---|
| G0 | Stop the report quoting requested values | (pre-existing bug) | **In, first.** Blocks G3. |
| G1 | Positioning: README ×4 leads with "no processor, verified output" | local-only is no longer a differentiator | **In.** |
| G2 | Text mode: paste in, scrubbed text out, paste the reply back, values restored | 1, 2, 3 | **In.** The largest item. |
| G3 | Firm term list, encrypted: values removed on every scrub | 4 | **In.** Medium, mostly the window editor. |
| G4 | Local run ledger, hash-chained | 5 | **Deferred** until someone asks for it. The design is kept below. |
| G5 | Launch the Windows, Linux and Intel macOS builds by hand | 6 | **In**, as a process item. |
| — | Built-in LLM gateway / chat | 1 | **Out.** It adds the network path `core/egress.py` exists to refuse, and makes FreeDocs a weaker Cedreon. |
| — | Browser version | 8 | **Out.** It contradicts the offline premise. |
| — | Teams, shared guardrails, knowledge base | 7 | **Out.** These are SaaS features, and G3 covers the single-user part. |

Order: G0 → G1 → G3 → G2, with G5 running in parallel and G4 on hold. G3 goes
before G2 because it touches only the file path and it produces
`core/sealed.py`. G2's "save a key file" and its term-list support then reuse
both.

## Rules this work must obey

These all come from `CLAUDE.md` and the code. A change that breaks one is wrong,
even if its tests are green.

1. **The app holds no rules.** Every judgement stays in Python. The window sends
   text, spans and paths, and renders what comes back.
2. **The report carries no values.** `build_report` output reaches disk and
   tickets. `detail` and `warn()` are descriptions, never values
   (`formats/base.py`).
3. **The mapping never reaches disk without `--map`**, and without it a scrub is
   irreversible. G2 keeps a mapping in engine memory, and that is a deliberate,
   opt-in widening that must be written down (see G2).
4. **`keep` is the dangerous half.** New controls may add removals. None may add
   an allowance (`TestWhatGrantsAnAllowance` stays closed).
5. **Stage 6 is not bypassed.** Text mode goes through `Scrubber.scrub` and
   `verify_output` like a file does. A leak writes and returns nothing.
6. **Python counts code points and JavaScript counts UTF-16.** Pasted text is
   where emoji are most likely, and `keep_spans` stay built from the engine's
   offsets (`codePointOffsets` is for rendering only).
7. **Every ceiling lives in `core/limits.py`**, and a breach is `InputTooLarge`.
8. **Outputs go through `core/outputs.py`.** What re-identifies is owner-only,
   and every write uses `O_NOFOLLOW`.
9. **Matching on restore is literal.** There is no tolerant mode for a mangled
   placeholder, not even behind a flag.
10. **Figures in the README are from `freedocs benchmark`** and identical in all
    four languages.
11. **Engine prose stays English.** Enum values are translated in the window.

---

## G0: stop the report quoting requested values

**Status: implemented** on `feature/report-requested-values`. The field names
below are the ones that landed: `Inspection.unmatched`, `ScrubResult.unmatched`,
`ScrubResult.caller_warnings`, and `requested_values_not_found` in the report.

**The bug.** `Scrubber.detect_in` adds
`f"the value {value!r} was asked to be removed but does not appear in this document"`
to `Inspection.notes`. `pipeline.scrub` then folds `inspection.notes` into
`ScrubResult.warnings` (`pipeline.py`, `warnings=[*handler.warnings, *inspection.notes]`),
and `build_report` writes `warnings` verbatim. So a value the caller asked to
remove, which is by definition confidential in the caller's opinion, lands in the
JSON report **exactly when it is absent from the document**. A batch scrubbed with
one list of names writes that list into the report of every document the names do
not appear in. `test_report_contains_no_confidential_values` cannot see it,
because its canaries are in the body.

G3 turns this from an edge case into the normal path: a term list of 300 client
names would copy most of them into every report.

**Fix.**

- Keep the quoting sentence on the preview and the pipe. The window and the CLI
  console need to say *which* value was not found; that channel already carries
  matched text.
- Stop it reaching `build_report`. Split `Inspection.notes` into `notes`
  (value-free: registry notes) and `unmatched: list[str]`, following the pattern
  `Extraction.warnings` / `ScrubResult.warnings` already uses. `ScrubResult`
  gains `unmatched_removals: int`, and the report carries only
  `"requested_values_not_found": N`.
- The RPC `scrub` response keeps the quoted sentences in `warnings`, because
  that is the local pipe and the window renders them. The `report` key inside the
  same response is `build_report`'s, so it becomes value-free automatically.

**Tests** (`tests/test_report.py`, `tests/test_rpc.py`):

- `test_the_report_does_not_quote_a_value_that_was_not_found`: remove
  `"Nordwind Holding"` from a document that does not contain it, and assert the
  string is nowhere in `json.dumps(build_report(...))` while the count is 1. The
  canary is structural, following `test_the_report_names_no_sheet_it_renamed`,
  and asserts both halves.
- The RPC `inspect` response still quotes it, so the preview keeps working.

**Docs.** Add one paragraph to *Invariants* in `CLAUDE.md` beside the sheet-name
note ("a value does not have to be in the text to be a value").

---

## G1: positioning

**Status: implemented** on `feature/readme-positioning`: the hero line, a
"nobody in between" paragraph after the opening one (with the egress limit
stated, linking `SECURITY.md`), the reverse-path bullet led by "irreversible by
default", and "it does not talk to the model for you" in the honest list. No
figures changed.

Cedreon's desktop app screens locally and offline, with its own OCR, so "runs
locally" no longer separates the two products. What does:

- **No data processor.** No DPA, no sub-processor register, no art. 321 CP
  agreement to countersign, because nobody else receives the document. Enforced
  by `core/egress.py`.
- **Verification that refuses.** Stage 6 re-extracts the output, and a survivor
  means nothing is written.
- **The document comes back as a document**: formatting preserved, hidden
  content, metadata and thumbnails removed.
- **Anonymisation by default.** Reversibility is opt-in (`--map`).
- **Measured.** Published figures from `freedocs benchmark`. AGPL.

**Where.** Change the hero and the "what it does not do" list in
`README.md`, `README.it.md`, `README.de.md` and `README.fr.md`. Name no
competitor: the README is a landing page, and a named comparison goes stale on
the competitor's next release. No new figures, so no benchmark run is needed.
If one is added, it comes from a fresh run and goes into all four files.

**Check.** `grep` that the same figures appear in all four files, which is the
existing rule.

---

## G3: firm term list, encrypted

**Status: implemented.** Engine and CLI on `feature/term-list`, the window on
`feature/term-list-window`. What changed from the design below, each for a reason
found while building it:

- `forget` locks the list only with `terms: true`. The window calls `forget` after
  every batch, and locking there would ask for the passphrase after every batch.
- `terms_import` takes the passphrase too, and `terms_update` and `terms_import`
  re-open the file with it before saving: a save under a mistyped passphrase
  would have re-keyed the list and succeeded.
- `matched` counts entries that removed something, read from the findings rather
  than by a second search, which halved the cost at `MAX_TERMS`.
- Nested requested values now go longest first, in the list and in the existing
  override alike; in caller order `Acme` left ` Corp` behind `Acme Corp`.
- The payload is padded to 4 KiB so the ciphertext length does not count the
  entries, which the header was already careful not to.
- Entries are 2 to 500 characters (`MIN_TERM_CHARS`, `MAX_TERM_CHARS`) with no
  control characters, so every entry survives its own export.
- Measured: 10 000 entries against 600 000 characters is 1.3 s of
  `Override.apply`, linear in both.
- Window: its own card on the file and review steps, not a section of
  `AdvancedPanel.svelte`. Everything in that disclosure only narrows the search,
  and a collapsed disclosure would hide that a list is unlocked and in use.
- Window: the passphrase is held until the list is locked, since every save
  re-opens the file with it; `lockTerms()` is the one place it is cleared.
- Window: Change passphrase… (not in the design) asks for the current one again
  rather than using the held one.
- Window: a restarted sidecar leaves the window showing an unlocked list the
  engine no longer holds. Stated in `docs/desktop-app.md`.

**What.** An encrypted file of values that are removed on every scrub: client
names, matter numbers, internal project code names. It is the persistent form of
the window's "add a value" control, and it can only ever **remove**.

**Why remove-only.** A persistent "never redact X" list would be a standing
allowance applied to documents nobody has read yet. That is the dangerous half of
`core/overrides.py` with the preview taken away. If someone asks for it, the
answer is no, and the reason is rule 4.

**Decided (30 September 2026): encrypted, with no plaintext form of the working
file.** The list is the firm's client register. Plaintext with owner-only
permissions was the first proposal. It was rejected because the realistic
exposure is not another account on the machine. It is **the folder being
synchronised**: firms keep everything in OneDrive, SharePoint, iCloud or Dropbox,
and a synced plaintext list sits on somebody else's servers where FileVault
protects nothing. The same applies to a backup on an unencrypted disk, and to
Windows machines with BitLocker off. It is also the existing precedent: the key
file has no plaintext form either, by decision.

### What it protects, and what it does not

This goes into `docs/terms.md` in these words, and nothing on the README may
claim more.

| Protects against | Does not protect against |
|---|---|
| The file reaching a cloud sync folder, a backup or a shared drive | Malware running as the user: it can read the passphrase as it is typed, or read the unlocked list from the engine's memory |
| Another account on the same machine | Someone with the passphrase |
| A stolen or discarded disk, with or without full-disk encryption | A plaintext export the user made and kept (see Export) |
| The file being attached to an e-mail by mistake | A weak passphrase: `MIN_PASSPHRASE` and scrypt raise the cost of guessing, but they cannot make "12345678" strong |

It is marketed as "encrypted at rest, unlocked once per session", **not** as
extreme security. A reviewer who finds the second claim contradicted by the table
above stops trusting the rest of the page.

### Four conditions that make encryption usable

Without these conditions, users route around the encryption, and a workaround
copy in plaintext is worse than no encryption.

1. **Unlocked once per session, not per scrub.** The engine holds the decrypted
   list until the session ends, the user locks it, or `forget` is called, as it
   already holds the GLiNER2 weights. A passphrase asked on every document
   produces weak passphrases.
2. **Edited from the window**: add, remove, search. Without an editor an
   encrypted list is unmanageable, and someone keeps a plaintext copy "for
   convenience".
3. **Import is one-way.** Import a plaintext or CSV list once. FreeDocs then
   says, plainly, that the source file should be deleted, and **never deletes it
   itself**, because deleting a user's file is not this tool's decision.
4. **Export is possible, explicit and warned.** There is no hidden way out, and
   no way out without the user asking for one.

### File format

Same envelope as a key file, and deliberately **not** readable as one.

- Suffix `.fdterms`. Like `.fdmap`, it is recognisable in a listing and easy to
  `.gitignore`.
- Cleartext header, which is also the AEAD associated data:
  `{"freedocs_terms": 1, "kdf": {...scrypt, salt}, "cipher": "AES-256-GCM", "nonce": ...}`.
  The version key differs from the key file's `freedocs_map`. A key file offered
  as a term list is refused as `MalformedMap`-shaped, and so is the reverse. The
  header carries **no count, no name, no dates**: the number of clients a firm
  has is itself confidential.
- Payload: `{"terms": [{"value": "...", "entity": "ORGANISATION"}, ...]}`.
  `entity` defaults to `OTHER`, and an unknown entity is an error, exactly as in
  `parse_override`.

### Engine

- **Extract the envelope from `core/mapping.py` into `core/sealed.py`**:
  `_derive`, `_aad`, the scrypt band checks (`MAX_SCRYPT_*`), `_b64`/`_unb64`,
  and `seal(kind, header_extra, payload, passphrase)` / `open_sealed(kind, raw, passphrase)`.
  `core/mapping.py` becomes a caller.
  **The key-file format must not change by one byte**: a `.fdmap` written before
  the refactor still opens (checked-in fixture), and one written after is
  identical in shape. Do not "improve" the key file while moving its code.
- **New `core/terms.py`**, about 150 lines.
  - `TermList` (frozen dataclass of `RemovedValue`), `create_terms`,
    `open_terms(path, passphrase)`, `save_terms(path, terms, passphrase)`, and
    `TermListError(ValueError)`.
  - `mapping_unavailable_reason()` is the single authority for "can this build
    encrypt". Do not add a second check. `capabilities` publishes
    `terms_available` from it.
  - **Atomic save.** The list is edited in place, so a crash mid-write must not
    lose the client register. Write to a sibling temporary file through
    `write_private`, with `O_NOFOLLOW`, then `os.replace`. That needs a
    `replace_private` in `core/outputs.py`, the first atomic writer there, and
    its docstring says why only this file needs it: a scrubbed output can be
    regenerated, and this cannot.
  - Every error carries line numbers or counts, **never a term or the
    passphrase**. This is the `core/mapping.py` rule, and
    `test_a_wrong_passphrase_leaks_neither_it_nor_a_value` gets a sibling.
- **Limits** in `core/limits.py`: `MAX_TERMS` (10 000) and `MAX_TERMS_BYTES`,
  with a measurement beside each. `Override._added` is O(terms × occurrences), so
  time a 10 000-term list against a 200-page extraction and write the number
  down. The sealed-file ceiling sits beside `MAX_MAP_BYTES`.
- **Matching** is the existing `Override._added` substring search: literal and
  case-sensitive. The terms are merged as `Override(remove=(*terms, *caller_removals))`,
  term list first, with `path=None`. **Case-insensitive matching is deferred**:
  it is the obvious next ask, but it needs a decision about which spelling the
  placeholder stands for, and a measurement of what it over-redacts.
- **Findings from the list** carry layer `H` and detector `terms`, so a person
  can tell "I added this now" from "the firm list added this". That is a new
  value of `Finding.detector`, with no new `Layer`.

### RPC

The session holds at most one unlocked list: `Session._terms: TermList | None`
and its path.

| Method | Does | Notes |
|---|---|---|
| `terms_create {path, passphrase}` | New empty list, unlocked | Refused when `path` exists: creating over an existing list would destroy it |
| `terms_unlock {path, passphrase}` | Decrypt into the session | Returns `{count}` only |
| `terms_lock {}` | Drop it from memory | Also done by `forget` with `all`, and at session end |
| `terms_list {query?}` | The terms, filtered | Values go down the local pipe, the channel that already carries matched text |
| `terms_update {add: [...], remove: [...], passphrase}` | Edit and save at once | There is no unsaved state in the window, so nothing to lose on a crash |
| `terms_import {source}` | Read plaintext or CSV into the unlocked list | The response says to delete the source; it never deletes it |
| `terms_export {output}` | Write plaintext through `write_private` | The window confirms first, and the response repeats the warning |
| `terms_rekey {old, new}` | Change the passphrase | Atomic, like every save |

- `inspect`, `scrub` and `scrub_text` take `use_terms: true`. They use the
  session's unlocked list, or fail with `INVALID_REQUEST` ("the term list is
  locked") and scrub nothing. A request that silently ignores a locked list
  produces a document the user believes had the firm's names removed.
- `terms_update` needs the passphrase to re-seal. The window collects it at
  unlock and holds it in `session` for the life of the unlock, cleared on lock,
  mode change and close, in a `finally`, never in `localStorage`. This is the one
  place the window keeps a passphrase longer than one call. Say so in
  `CLAUDE.md`. The alternative is asking for it on every edit, which is condition
  1 again.

### CLI

`freedocs terms create|list|add|remove|import|export|rekey FILE`, and
`scrub --terms FILE` / `inspect --terms FILE`. Passphrase sources are the key
file's three (a file, `FREEDOCS_TERMS_PASSPHRASE`, an interactive prompt), and a
terminal with none of them set is a usage error. A CLI run unlocks for one
process, so there is nothing to lock.

Also add `scrub --remove VALUE` (repeatable), which the pipe has had since
overrides landed and the CLI never gained. It is parsed through `parse_override`
so the two agree.

### Report

`"terms": {"loaded": N, "matched": M}`, counts only. This depends on G0: without
it, every term absent from a document is quoted in that document's report. The
console prints the same two numbers.

### Window

- A **Term list** panel in `AdvancedPanel.svelte`, with Create…, Open… and Lock.
  The *path* is remembered in `localStorage` beside the theme and re-validated on
  launch, as the Tesseract path is. The passphrase and the terms are never stored
  there.
- **Unlock prompt once per session**, the first time a scrub or the panel needs
  it. The minimum length is read from `capabilities.passphrase_min_characters`,
  as the key-file controls already do.
- **Editor**: a searchable list, add a value with an optional entity type,
  remove, Import… (then the "delete the original" notice), and Export… behind a
  confirmation that names the risk.
- A "Use the firm term list" toggle on each scrub. **Decided (30 September
  2026): on by default once a list is unlocked.** The two failures are not the
  same size. Off by default, a forgotten toggle sends a client's name to the
  model while verification says "no leak", because verification checks only what
  was meant to go: a silent leak. On by default, an unwanted removal is shown in
  the preview with detector `terms`, can be excused with the existing
  keep-this-occurrence control, and at worst costs one placeholder too many: a
  visible nuisance. That is the project's standing rule (over-redact when
  unsure), the same one that keeps city-states in the country list. The real
  risk behind the counter-argument is a list entry that is an ordinary word
  ("Alpina", "Nova"). The answer to that is visibility, not a default: the
  preview and the result both show how many terms matched and where. A
  "this term matches in most documents" hint in the editor is a possible later
  addition, not part of this item.
- Catalogue strings in en/it/de/fr. `npm run check` proves the four are complete.

### Packaging

The `packaging/build.py` smoke test already round-trips a key file, because
`find_spec` is true of a bundle whose cipher never made it in. Add a term-list
round trip beside it. The same class of bug, prevented the same way.

### Tests

- `tests/test_sealed.py`: an old `.fdmap` fixture opens after the refactor, a
  key file is refused as a term list and the reverse, a flipped ciphertext byte
  or a swapped header fails, and the scrypt band is enforced for both kinds.
- `tests/test_terms.py`:
  - create, open, a wrong passphrase, and a term readable nowhere in the raw file
    bytes;
  - an interrupted save (patch `os.replace` to raise) leaves the previous file
    intact;
  - error messages containing neither a term nor the passphrase;
  - a `MAX_TERMS` breach raising `InputTooLarge`;
  - import parsing: comments, the `ENTITY<TAB>value` prefix, an unknown entity,
    an empty term.
- The leak check: scrub with a list naming a string no detector finds, and
  assert that stage 6 passed and the string is absent from the decompressed
  output. Run it on plaintext, docx, xlsx and pdf, because the removal is only as
  good as write-back.
- The report: 50 terms with 3 matching, none of the 50 in the report, and
  `matched == 3` (needs G0).
- `tests/test_rpc.py`: the unlock/lock lifecycle, `forget` releasing it,
  `use_terms` with a locked list refusing, `terms_create` over an existing file
  refusing, and a wrong passphrase leaking nothing. All with `detectors="l1"`.

**Later, not now:** passphrase in the macOS Keychain or the Windows Credential
Manager, so it is never typed. The code is per platform, and Windows has never
been launched (G5).

**Docs.** New `docs/terms.md`, including the protection table above.
`docs/cli.md`. In `CLAUDE.md`, a paragraph under *The human override* ("the
term list is the persistent half of `remove`, and there is deliberately no
persistent half of `keep`") and one under *The reverse path* on `core/sealed.py`
and the passphrase the window holds.

---

## G2: text mode

This is the loop Cedreon closes and FreeDocs leaves to the user, and it can be
closed without a network call:

```
paste text ──► inspect_text ──► review (same screen) ──► scrub_text ──► copy
                                                            │
                                                  mapping held in engine
                                                  under an opaque handle
                                                            │
paste the model's reply ──► restore_text(handle) ──► copy restored text
```

### Where the mapping lives between scrub and restore

**Decided (30 September 2026): the user chooses, per text, and the default is
neither.** The result step offers three choices before scrubbing:

- **Don't keep** (default). This is irreversible, exactly like every scrub today.
- **Keep until I close FreeDocs** (option A below).
- **Save a key file** (option B below), with a passphrase and a folder.

The default stays irreversible because that is what the whole engine defaults to
(`--map` is off), and a text mode that remembered by default would be the first
feature to invert it. The choice is enforced by the engine through `keep_map`, so
the window only relays it and still holds no rule. It is **not** remembered in
`localStorage`: a remembered "keep" becomes a default nobody chose.

The three options that were considered:

| Option | Where the mapping is | Cost |
|---|---|---|
| A. **Engine memory, opaque handle** (recommended) | `Session._text_maps[handle]`, a `KeyMap` | Weakens "a crash cannot leave a re-identification key in a live process" for the lifetime of the handle. Core dumps are already off (`core/sandbox.py`). |
| B. Encrypted key file, as `--map` today | disk, passphrase | Asking for a passphrase and a folder for a paragraph of text is the friction this item exists to remove. |
| C. Window memory | the webview | **Rejected.** It crosses the pipe into the window, which the restore design refuses outright ("keeps the mapping from ever crossing the pipe into the window"). |

Option A's rules:

- **Opt-in per request.** `scrub_text` holds a map only when the request carries
  `keep_map: true`. Without it the handle is absent and the scrub is
  irreversible, as every scrub is today. The window sets it only when the user
  picked "keep until I close FreeDocs". The CLI never sets it.
- **The handle is random** (`secrets.token_urlsafe(16)`), never derived from the
  text or a hash of it.
- **Bounded and released.** At most 8 handles, dropping the oldest first. They go
  on `forget` (a new `text_maps` field, or `all`), on a mode change and "New
  text" in the window, and when the session ends. Idle expiry is **not** added:
  a timer is a second thread in a process that deliberately has one (see the
  cancel note in `CLAUDE.md`).
- **`restore_text` does not consume the handle.** A second reply from the same
  model is normal use. "New text" and `forget` release it.
- **Written into `CLAUDE.md` under *Invariants*** as a stated widening, with its
  bound, in the same shape as the paragraph on the extraction cache ("what the
  engine keeps resident, and how to make it stop").
- The optional **"save a key file"** control writes the held `KeyMap` through the
  existing `write_key_map`, with its passphrase rules, for a user who wants to
  restore tomorrow. This is option B, reached from A.

### Engine

- **No new format handler.** Text mode is `PlainTextHandler(Path("pasted.txt"), text.encode("utf-8"))`
  handed straight to `Scrubber.scrub`, which already accepts a `FormatHandler`.
  That keeps routing out of the path, and the per-line anchoring makes an
  unedited round trip byte-identical. `verify_output` re-opens with
  `type(handler)(handler.path, output)`, which works unchanged.
  - The virtual name is a constant, not the caller's choice. It appears in the
    report's `source` and in `KeyMap.document`.
  - `scrub_hidden()` on plaintext is a no-op, so `Scrubber.read` needs no
    branch.
- **`Restorer.restore(source: Path | FormatHandler)`**, the same signature change
  `Scrubber.read` made, and for the same reason. The only edit to `restore.py` is
  at the top of `restore()`. Restore still must not use `Session.extraction`
  (the note in `restore.py` stands).
- **New RPC methods**, each a thin shell over the above in `rpc.py`:
  - `inspect_text {text, …same options as inspect}` returns `inspect`'s shape.
    `include_text` is implied, since the caller sent the text. `path` in each
    finding is the virtual name. This is **not cached** in `_extractions`:
    re-extracting a paste costs nothing, and a cache entry is text held resident.
  - `scrub_text {text, keep_spans, remove, use_terms, keep_map, …}` returns
    `{ok, text, removed, flagged, warnings, suppressed, handle?, report}`. On
    `LeakDetected` it returns the same value-free failure shape as `_scrub_one`,
    and **no text**. Nothing is written to disk. The `report` object is returned
    but not saved; the window can offer "save report" through `write_private_json`.
  - `restore_text {handle, text}` returns `restore`'s shape minus
    `output`/`format`, plus `text`. An unknown handle is `INVALID_REQUEST` with a
    message that names no value. That covers a handle that was forgotten, evicted
    or belongs to a restarted sidecar.
  - `forget` gains `text_maps: [handle…] | "all"`.
- **Limits.** `MAX_TEXT_CHARS` in `core/limits.py`. The pipe is newline-delimited
  JSON and one request is one line, so a 50 MB paste is a 50 MB line. Measure
  what `json.loads` of a large line costs in RSS and set the ceiling from that
  (start the measurement at 5 MB). `InputTooLarge` has its own `RpcError` code
  already.
- **Stage notifications** reuse the existing vocabulary. `router` is not
  announced for text, because no routing happens. `test_no_stage_notification_claims_a_percentage`
  must still pass, and the closed-vocabulary test needs no new name.
- **The sidecar restarting loses every handle.** `restore_text` then fails with
  the unknown-handle error, and the window says the text must be scrubbed again.
  That is honest and needs no protocol change. `MAX_RESTARTS` is unchanged.

### CLI (small, optional)

`freedocs scrub -` reads stdin and writes the scrubbed text to stdout, and
`freedocs restore - --map KEY` reads stdin and writes the restored text to
stdout. Stdout is the output here, so status and warnings go to stderr. This is
a pipe-friendly equivalent, not a clipboard feature. Mapping on the CLI stays
`--map` only, because a CLI process ends, so there is nothing to hold a handle.

### Window

- A **third mode**, `'text'`, in `Mode` and `ORDER`. Its steps are
  `['file', 'review', 'result']` with a paste area in place of the file picker,
  so the rail, the reachability derivation and the review screen are reused.
  Adding a mode rather than a step follows `setMode`'s documented reasoning.
- **Paste step.** A `<textarea>` plus Inspect. The character count comes from
  the engine's `characters`, not `text.length`, because rule 6 says the two
  differ.
- **Review step.** Reuse `ReviewStep.svelte` and `DocumentText.svelte` unchanged.
  `inspect_text` returns the same payload shape, `review.svelte.ts` keys state by
  the virtual path, and "keep this one" builds `keep_spans` from
  `inspection.findings`, never from `View.marks`.
- **Result step.** The scrubbed text (read-only, selectable), Copy via
  `clipboard.ts` (no new permission), the verification line, and suppressed
  counts, as `ResultStep` shows them. Below it sits a second textarea, **"Paste
  the reply"**, and a Restore button. The restored text is shown with its
  problems (`unknown_placeholders`, `not_present`) in the reader's language
  (enum), while the engine's sentences are quoted under `lang="en"`.
- **Clearing.** Mode change, "New text" and window close call `forget` with the
  handle, fire-and-forget, as for files. The pasted text and the restored text
  are held in `session` and cleared the same way. **Neither ever touches
  `localStorage`.**
- **Placeholders a model mangled** (`[PERSONA_1]`, `**[PERSON_1]**`) are listed,
  never repaired. That is rule 9, and `restore.py`'s `PLACEHOLDER_SHAPE` already
  reports them.

### Tests

Engine (`tests/test_text_mode.py`, `tests/test_rpc.py`):

- The round trip: scrub text containing the `conftest` canaries with `keep_map`,
  simulate a model reply that reorders sentences and repeats one placeholder
  twice, restore it, and assert that every value is back and no placeholder is
  left.
- `scrub_text` without `keep_map` returns no handle, and `restore_text` refuses.
- A leak in `scrub_text` (force a write-back failure, as the existing leak tests
  do) returns no `text` field at all.
- Handles are released by `forget`, and the ninth scrub evicts the first.
- The unknown-handle error names no value.
- **Emoji before a finding:** `"😀 Mario Rossi"`. Keep that span using the
  engine's offsets and assert that it is honoured. This is the test rule 6 exists
  for.
- `MAX_TEXT_CHARS` breach returns `InputTooLarge`.
- `json.dumps` of the `report` in a `scrub_text` response contains no canary, and
  no pasted phrase that was not a finding either (the `include_text` rule).
- Every RPC test pins `detectors="l1"`.

Window (`vitest`, Node-only):

- The `ORDER.text` reachability derivation.
- A pure helper that builds `keep_spans` from findings (moved out of the
  component to follow the `nextFinding` precedent).

By hand, stated as such: the paste → copy → paste → restore click-through on
macOS, and a screen reader on the result step.

**Docs.** `docs/desktop-app.md` (text mode), `docs/restore.md` (the handle and
its lifetime), `docs/cli.md` (`-`), and `CLAUDE.md`: a new paragraph under *The
reverse path* plus the invariant widening.

---

## G4: local run ledger

**Decided (30 September 2026): deferred until a customer, auditor or professional
body asks for it.** Three reasons. Nobody is asking today, and the report already
holds most of what a line needs, so it is 2–3 days of work when someone does.
Cedreon's record sits on *their* servers, so a third party keeps it, and that is
what makes it credible; a ledger on the writer's own machine can be rewritten
from scratch by the writer, so selling it as an equivalent would overclaim. It
becomes strong only with an external anchor, such as the head hash sent monthly
to a compliance contact, and that needs designing rather than hurrying. And text
mode is what a user feels every day, while a ledger is felt only in an audit.

The design below is kept so the work starts from it.

Cedreon sells a "tamper-evident, append-only" record. The local equivalent is a
hash-chained log of what each run did, and it has to be designed so that it is
not a second report leak.

- **Opt-in.** `--ledger FILE` on the CLI, and a `ledger` path on RPC `scrub`,
  `scrub_text` and `restore`. The window stores the path, not contents, in
  `localStorage`.
- **Format.** JSON Lines, written owner-only through `core/outputs.py` and
  opened in append mode with `O_NOFOLLOW`. Each line is:
  `{seq, time, engine_version, operation, format, input_sha256, output_sha256, entities: {TYPE: {removed, reported}}, verification_passed, key_file, terms_matched, prev}`,
  where `prev` is the SHA-256 of the previous line's bytes and the first line's
  `prev` is 64 zeros.
- **What it must not carry:** values, filenames (use `input_sha256`: the report
  carries `source`, but a ledger accumulates across every document ever
  processed, so it is a list of every client file name), paths, and per-value
  hashes. A SHA-256 of a short value is reversible by enumeration. A hash of a
  whole document is not.
- **`freedocs ledger verify FILE`** re-walks the chain and reports the first
  broken link by `seq`. `freedocs ledger head FILE` prints the last line's hash
  for someone to note elsewhere, which is the only thing that makes truncation
  detectable.
- **The honest limit**, written in `docs/ledger.md` and in `report.CAVEATS`
  style: this is tamper-*evident* against edits, not tamper-*proof*. Anyone who
  can write the file can rewrite the whole chain, unless the head hash was
  recorded somewhere they cannot reach. No signature, because there is no key the
  attacker would not also hold on a single-user machine.
- **Concurrency.** One engine process appends, and a CLI run may do so at the
  same time. Use `fcntl.flock` on POSIX around read-last-line-then-append, and on
  Windows say "not locked" rather than pretend (the `core/outputs.py`
  precedent).
- **Tests.** Chain verification, a single edited byte detected at the right
  `seq`, a truncated file, and a canary-free check covering both value canaries
  and a structural one (the filename).

---

## G5: launch what is built

This is not code. Cedreon ships Intel macOS and Windows. FreeDocs builds Windows
and Linux, has launched neither, and does not build Intel macOS.

- [ ] Launch the Windows installer on a real Windows 11 machine. Scrub one file
      of each format and one scan with Tesseract installed. Record the result in
      `docs/packaging.md`, and change "builds" to "works" only where it did.
- [ ] Do the same for the Linux `.deb` on Ubuntu 24.04.
- [ ] Build Intel macOS on an Intel machine (not `macos-15-intel`, which is a
      billed runner) and launch it.
- [ ] Keep the code-signing decision, and state in `docs/packaging.md` what an
      unsigned build costs a user on each platform (Gatekeeper, SmartScreen).
      Cedreon is signed, and that difference is felt at first launch.

---

## Definition of done, per item

- `python3 scripts/ci.py check` is green, including the dependency audit.
- `uv run pytest -q` is green **with** the `ner` extra, not only the fast suite.
  G2 and G3 touch the path the model feeds.
- `freedocs benchmark` has every column unchanged. None of this work should move
  detection. If a column moves, attribute the change before merging (see the
  chunk-boundary note).
- `npm run check` (all four catalogues complete) and `npm test` are green.
- The `CLAUDE.md` paragraph for the item is written in the house style: why,
  what was tried, and what failed.
- Each item lands as its own `feature/` branch into `develop`. The `post-merge`
  hook bumps the dev counter, so versions are never edited by hand.

## Decisions

1. ~~G2, where the mapping lives~~: decided. The user chooses per text between
   none (the default), in memory, and a key file.
2. ~~G3, plaintext or encrypted~~: decided. Encrypted, unlocked once per session,
   edited in the window.
3. ~~G4, now or later~~: decided. Deferred until someone asks.
4. ~~G3, term-list toggle default~~: decided. On once a list is unlocked, with
   visible counts. See G3, Window.

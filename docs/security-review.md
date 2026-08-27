# Security review

A source review of the whole project, and the record of what was done about it.
Seventeen findings, thirteen closed, two closed in part, one deliberately left
open with its reasoning and one bounded by decision. Everything below names the file, the failure, the fix and how
the fix was checked.

Read against `bc50560`, so the line numbers are that commit's; the fixes moved
most of them. No fuzzing, no CVE scan and no cryptographic test-vector work was
run — the first is still open, the second is now a gate step, and the third is
not this project's to do (the primitives are `hashlib.scrypt` and
`cryptography`'s AES-GCM).

## Why the threat model is unusual

FreeDocs inverts the usual trust relationship of a document tool. Its premise is
that a file too sensitive to hand to a language model can be handed to *this*
program instead, and two consequences follow that would be cosmetic elsewhere.

**Every input is hostile by definition.** The app exists to be pointed at
documents from outside, and it parses them with C libraries — MuPDF, libxml2,
zlib — in a process holding the user's own privileges.

**Detecting less is a security failure, not a quality one.** A build that finds
fewer identifiers, or an artefact that carries a value the tool claimed to have
removed, is a leak. That is why binary integrity and report content are
confidentiality properties here, and why "it still worked" is not evidence that a
model was intact.

The full threat model, what is in scope and what is not, is in
[SECURITY.md](../SECURITY.md).

## The findings

| | Finding | Severity | OWASP | Status |
|---|---|---|---|---|
| M1 | The scrub report carried values the scrub removed | High | A09 | Fixed |
| M2 | Untrusted parsers, no limits, no restart | High | A06/A05 | Fixed; OS confinement open |
| M3 | A hostile key file could hang the engine | Medium-High | A05 | Fixed |
| M4 | The window held a security rule | Medium | A04 | Fixed |
| M5 | The passphrase check was skipped for two of three sources | Medium | A04 | Fixed |
| M6 | The restored document was written world-readable | Medium | A01 | Fixed |
| M7 | The webview is the path-authorisation boundary | Medium | A01 | **Open, by decision** |
| M8 | The SSRF guard accepted any scheme and an empty host | Medium | A10 | Fixed |
| M9 | Model integrity was size-checked, never hash-checked | Medium | A08 | Fixed |
| M10 | The passphrase variable was inherited by subprocesses | Low | A04 | Fixed |
| M11 | The passphrase file's permissions were not checked | Low | A04 | Fixed |
| M12 | Error and traceback channels were unaudited | Low | A09 | Fixed |
| M13 | `rpc.inspect` omitted the hidden inventory | Low | parity | Fixed |
| M14 | Output writes followed symlinks | Low | A01 | Fixed |
| M15 | CSP and capability breadth | Low | A05 | Fixed in part, by decision |
| M16 | Nothing let a user verify a download, and no dependency audit | Medium | A08 | Fixed |
| M17 | A chosen Tesseract is an exec-adjacent primitive, and an in-app installer was refused | Low | A05 | Bounded, by decision |

---

### M1 — The scrub report carried values the scrub removed

**High · A09 · Fixed in `dd077c7`**

`build_report` wrote two fields verbatim to a JSON file on disk: every
`HiddenItem.detail` and every handler warning. Three producers put document
content into them, and each string was one the scrub had just removed *for being
identifying*:

- `formats/ooxml/xlsx.py:277` warned `"renamed " + …` with the **original** sheet
  and table names — the names the rename existed to take out.
- `formats/ooxml/xlsx_hidden.py:117` set `detail` to the hidden sheet's name, by
  explicit design.
- `formats/pdf.py:501` listed the embedded filenames, which routinely name a
  person or a case.

**Why the existing test could not see it.**
`test_report_contains_no_confidential_values` searches the report for the
canaries, and every canary is an identifier inside the document's *body*. A sheet
name and an attachment name are not text in the document at all, so a body canary
passes straight over both. The two new guards use **structural** canaries — a
sheet name, an attachment name — because nothing else can reach those channels.

**Why the restore side was already right.** `ef38aef`, three commits earlier, had
made `build_restore_report` carry `handler_warnings` as a count, because on a
restore a placeholder's replacement *is* the original value and PyMuPDF's "does
not fit" warning therefore names the IBAN it dropped. The discipline existed; it
had not been applied backwards.

**The fix is not the obvious one.** Counting the scrub side too was rejected after
surveying all nine `warn()` sites: only one carried a value, and the same list
holds the OCR warning that names every machine-read page — the one warning a
reader has to act on, which CLAUDE.md explicitly forbids removing. So the
*producer* was fixed and the channel kept its sentences. Where a name really is
the useful half, the warning now reports what the thing is called **now**: a
placeholder is a label the scrubbed workbook already publishes to anyone who
opens it, and it is also what a broken formula refers to.

The rule is written on `HiddenItem` and on `FormatHandler.warn()`, where the next
handler author will meet it: **`detail` and `warn()` are descriptions, never
values.** Say how many, say where, say what kind.

**Verified.** Both new tests confirmed red against the parent commit — the failure
printed the leaked filename verbatim. By hand: a workbook with a visible sheet
named `RSSMRA85T10A562S` and a `veryHidden` sheet named `CHE-116.281.710`,
scrubbed with `--report`, then `grep -c` for both names in the report → **0**,
with the actionable half still present.

---

### M2 — Untrusted parsers, full privileges, no limits, no restart

**High · A06/A05 · Fixed in `6a2913e` and `479f589`; OS confinement open**

`router.handler_for` read the whole file with `path.read_bytes()`, and
`OoxmlPackage.open` ran `testzip()` and then `archive.read()` on **every** entry
into a dict. No file-size cap, no per-entry cap, no page cap, nothing. Measured
before the fix: a **0.20 MB** container took **334 MB** of resident memory — about
1000:1, which makes a 20 MB email attachment 20 GB.

The engine is single-threaded with no cancel by design, so exhausting it is
exhausting the whole session, and `Engine::_child` was never reaped or respawned —
so the session stayed dead while every later request waited out the 600-second
timeout.

`core/limits.py` is now the one place a ceiling is written down, because the
router, the OOXML container, the PDF handler and `core/mapping.py` all ask. Each
number carries its measurement.

**The least obvious one is the PDF.** The cost of reading a PDF is not bounded by
its size: 200 000 distinct pages fit in 21 MB and extract in eleven seconds, which
is survivable — until OCR's measured 24 ms a page makes it eighty minutes and
`harden_for_verification` reads every page again.

**A nested package spends the parent's budget.** A chart's workbook is a zip
inside a zip and the outer package counts it as one still-compressed part, so
`nested_handlers` passes what it has already spent and re-raises `InputTooLarge`
ahead of its broad `except Exception`. A *malformed* embedding is one part of a
document the rest of which can still be scrubbed; an embedding built to exhaust
the process **is** the document, and warning about it would make the nesting the
way around the limit.

**Two rules in the plan did not survive being tested.** See
[what was measured away](#what-was-measured-away).

**And a fuzzer found five more places it escaped from.** `scripts/fuzz.py`
damages real seeds and reports anything whose *type* is outside the declared set.
Its first four hundred cases produced **twenty-nine escapes**: twenty from
`scrub_hidden` calling MuPDF's `scrub()`, twelve from reading a page's contents,
one from loading a page — the translation below had been applied to `__init__` and
`extract` only — plus `zlib.error` and `EOFError` out of the decompressor, deeper
than `BadZipFile`, which is what a flipped bit inside a deflate stream produces.
Two more appeared at 1500 cases: `zipfile` answers an unknown compression method
with `NotImplementedError` and an encrypted entry with a bare `RuntimeError`. Not
one of the five is something anyone would have thought to write a test for, which
is the argument for the fuzzer in a sentence. All four shapes are deterministic
tests now, because the fuzzer is deliberately not in the gate. After the fixes:
7500 cases across five seeds, zero escapes.

**A second finding fell out of writing those tests**: a parser's own exception
escaped untranslated. MuPDF answers a page tree whose kids are all one object with
`RuntimeError: code=7: Invalid number of pages`; `zipfile` answers a lying header
with `BadZipFile: Bad CRC-32`; the three OOXML handlers answered a zip missing its
main part with a bare `ValueError`. None is in `REFUSALS`, so from the CLI each was
a traceback and over the pipe `rpc.handle` rendered it into a response as a
sentence about somebody else's internals. All are `MalformedDocument` now.

**The sidecar half** (`479f589`): the reader thread now reports the end of the
pipe, the child is reaped — its exit status is the only account of *how* it died,
and a signal reads very differently from a clean exit — and every waiting request
fails at once instead of sitting out ten minutes. The next request starts a new
process, lazily, bounded at three restarts a session because the realistic cause is
a document the parser cannot survive and retrying that is a crash loop paying for a
GLiNER2 load every time round.

**Verified.** `tests/test_hostile_input.py`, fourteen cases, written before the
limits. `cargo test`'s five lifecycle cases run a real child process — a `/bin/sh`
script that answers, or dies on cue. Writing that fake found a genuine bug in the
first version of the sidecar fix: starting the reader *before* installing the
process in the slot reintroduces the exact ten-minute hang the commit removes.

---

### M3 — A hostile key file could hang the engine

**Medium-High · A05 · Fixed in `688712d`**

`read_key_map` derives its key from the parameters the **file** declares, so that
a key file written by a build with different settings still opens. `SCRYPT_MAXMEM`
bounded two of the three by accident — scrypt's cost is `n·r·p` and only `n` and
`r` touch memory — and **nothing bounded `p`**. A `.fdmap` declaring `p = 2**24`
grinds inside `hashlib.scrypt` for hours.

Reachable exactly as the feature intends to be used: a key file is a thing people
send each other, and opening one is a passphrase attempt against somebody else's
bytes.

The band is per-field ceilings plus a ceiling on the product, checked separately
so a single absurd value is named as itself. Also from the same audit: a size cap
before `read_text`, which takes the whole file into memory and hands it to
`json.loads` to take again; and a non-numeric `occurrences` that reached a bare
`int()` whose `ValueError` `rpc.handle` renders as a message about Python's
integer parsing.

**Verified.** The parametrised test asserts the property that matters — *no
derivation was started* — by making `hashlib.scrypt` explode if it is reached. A
timing assertion would be flaky, and "it finished quickly" is a weaker claim than
"no work began". By hand: a `.fdmap` with `p = 2**24` is refused in **0.1 ms**.

---

### M4 — The window held a security rule

**Medium · A04 · Fixed in `162ca85`**

`MIN_PASSPHRASE = 8` was declared in `core/mapping.py:67` and again in
`app/src/lib/app.svelte.ts:476`. `capabilities` published `mapping_available` and
not the floor, so the window invented one — the single place this app held a rule
about the engine, against the standing invariant that the app carries messages and
nothing else.

The failure it sets up: raise the floor in Python, and the window goes on
accepting eight characters, the engine refuses inside the `scrub` request, and the
refusal arrives after the scrubbed copies are on disk.

`passphrase_min_characters` is now published the way `preview_max_characters`
already was. With no capabilities answer the window treats *no* passphrase as long
enough, which disables the button rather than restating the number.

**Verified.** `test_capabilities_publishes_the_passphrase_floor` asserts against
`core.mapping.MIN_PASSPHRASE` rather than against `8`, so the two cannot drift
apart in the way the test exists to stop.

---

### M5, M10, M11 — The key file's passphrase

**Medium and Low · A04 · Fixed in `2d30315`**

**M5.** `_passphrase` (`cli.py:344`) called `check_passphrase` only on the
interactive `getpass` branch, so a passphrase from `--map-passphrase-file` or from
`FREEDOCS_MAP_PASSPHRASE` was returned unexamined. `write_key_map` checks again, so
nothing weak was ever written — but it raises `ValueError` from inside the per-file
loop, which `_cmd_scrub` does not catch, so the run died on a traceback **with the
scrubbed copy already on disk**. That is verbatim the failure the comment above
`_map_target` says the resolution order prevents.

**M10.** `FREEDOCS_MAP_PASSPHRASE` was read and left in the environment, so it was
inherited by everything the process spawns — and PyMuPDF shells out to Tesseract on
every scanned page. `/proc/<pid>/environ` is owner-only, so this was not a
cross-user leak; it was an unnecessary copy of the key to every value in the
document, in processes with no business holding it.

**M11.** A group- or world-readable `--map-passphrase-file` was read without
comment. `ssh` refuses a private key in that state; this warns instead, because
the mode may belong to a shared checkout or a mount the user does not control.

**Verified.** By hand: `FREEDOCS_MAP_PASSPHRASE=short freedocs scrub f.txt -o out/
--map k` prints the refusal, exits 1, and leaves `out/` empty — where before it
wrote the scrubbed copy and then tracebacked.

---

### M6 and M14 — Output permissions and symlinks

**Medium and Low · A01 · Fixed in `69ecd39`**

The key file was meticulously `0o600` by a function whose comments explain exactly
why. The **restored** document — which is the originals, reassembled — was written
with `write_bytes` at whatever the umask said, and so was the report. Two adapters
produce those artefacts, so the rule had to land in one place or become two rules.

`core/outputs.py` is that place, and the rule is **what the file contains, not
which command produced it**. Anything the document could be reconstructed from is
owner-only: the key file, a restored document, and the report — which carries no
values since M1, but does carry where each one was and what the source was called.
A file this tool exists to hand to somebody else is left to the umask, and the
scrubbed copy is the only one of those.

Every output also goes through `O_NOFOLLOW`, because `write_bytes` after
`mkdir(parents=True, exist_ok=True)` follows a symbolic link. **`O_EXCL` was
rejected** despite being stronger: re-running a scrub into the same output
directory is ordinary use, and turning that into a refusal buys nothing the
symlink guard does not.

On Windows this protects the path and not the mode — `O_NOFOLLOW` does not exist
there and `os.open`'s mode argument controls only the read-only attribute. Stated
in the module rather than implied.

**Verified.** By hand, one scrub and one restore:

```
out/  0755   out/f.txt    0644     <- the artefact that exists to be sent
keys/ 0700   keys/f.fdmap 0600
back/ 0700   back/f.txt   0600     <- the originals, reassembled
             scrub.json / restore.json 0600
```

Asserted on **both** adapters, because `15ee0e1` was an entire commit about two
adapters over one engine and five of its seven fixes were the same defect on the
untested side.

---

### M7 — The webview is the path-authorisation boundary

**Medium · A01 · Open, by decision**

`engine_request` (`app/src-tauri/src/lib.rs:22`) forwards an arbitrary `method`
and arbitrary `params` to an engine that trusts its caller by design. So
`inspect {path, include_text: true}` is an arbitrary-file-read primitive and
`scrub {paths, output_dir}` an arbitrary-write one; `map` and `restore` add two
more. The renderer is clean today — no `@html`, no `eval`, a tightened CSP — so
this is defence in depth against a webview CVE. It is the confused-deputy shape,
and Rust is where the user's actual consent lives.

**Why it is open.** The cheap fix — Rust keeps the set of paths the dialog
returned and rejects anything outside it — requires moving the file dialog out of
the webview, and it leaves the engine holding filesystem authority that a sandbox
would then have to describe. The shape that closes this *and* the sandbox gap
below is to remove that authority: the shell reads the bytes and writes the
output, the engine only computes. Its cost is the transport — the channel is
newline-delimited JSON and a 400 MB PDF in base64 is a 533 MB line — so it is its
own piece of work rather than a patch, and it is recorded as such.

This is also why `core:default` was **not** narrowed in M15. What that would
defend against is injected JavaScript after a webview compromise, and such
JavaScript can already call `engine_request`. Narrowing `core:path` beside it is
closing a window in a house with no door.

---

### M8 — The SSRF guard accepted any scheme and an empty host

**Medium · A10 · Fixed in `d5a07f0`**

`_is_local` (`detect/llm_review.py:129`) returned `True` when the parsed hostname
was empty and never looked at the scheme, while the host arrives off the wire and
goes to `urllib.request.urlopen`. Two mistakes that compound: an empty hostname is
what `urlparse` gives for `http://:11434` **and** for `file:///etc/passwd`, so a
file read passed the loopback guard.

The loopback rule now lives once, in `core/egress.py`, and the review layer calls
it. Two copies of a rule is how the guard on the one component that talks to the
network gets walked past.

**Verified.** Five parametrised cases red against the parent commit, plus a
control asserting the three forms everybody actually uses still pass — a guard
that refuses the normal configuration is not a guard, it is an outage.

---

### M9 — Model integrity was size-checked, never hash-checked

**Medium · A08 · Fixed in `259ac43`**

`model_manifest.verify` could always hash and nothing ever asked it to.
`diagnostics._weights` checked sizes; the loader checked that `config.json`
existed. So the manifest caught a payload cut short and not one that was altered.

Those are different failures and the second is worse. A truncated copy fails deep
inside `from_pretrained` and looks broken — bad, but loud. A payload whose bytes
changed while its length did not **loads perfectly and detects less**, and
silently detecting less is this tool's defining failure.

Hashing runs at **load**, once, and costs 0.7 seconds on the real 1.2 GB payload —
measured, beside a model load that already takes several. Two things are
deliberately not refused: a repository id, since the hub checks its own blobs; and
a directory with no manifest, since `FREEDOCS_NER_MODEL` is also how a developer
points at a checkout.

**Verified.** One bit flipped in `model.safetensors`, length unchanged:

```
doctor            [ok  ] NER layer   weights bundled in /tmp/tampered
doctor --hashes   [warn] NER layer   model.safetensors does not match its recorded SHA-256
scrub                    refused before loading, exit 2, nothing written
```

---

### M12 — Error and traceback channels were unaudited

**Low · A09 · Fixed in `a59e217`**

`engine.rs` inherits stderr on purpose, so a Python traceback reaches the terminal
a developer is watching. In a bundled `.app` there is no terminal: the parent is
launchd, and everything written to stderr goes to the operating system's unified
log — **on disk**, readable by anyone who can read the machine's logs. An
exception's own message is part of a traceback, and a parser's message can quote
the document it was reading. A disk channel nobody had audited, in a tool whose
central rule is that values may reach the pipe and must not reach the disk.

A frozen build now prints the exception's type and how to ask for more;
`FREEDOCS_DEBUG=1` restores the traceback. Nothing is lost either way: the full
message still travels the response, which is local.

**The other half turned out thinner than the review claimed, and the honest fix
was the reasoning rather than the code.** `StaleOverride` quotes two strings and
the comment defending that was right about one: `kept.text` is the caller's own.
`actual` is a slice of the document *as it is now*, which the caller has by
definition not seen — that is why the check fired. It stays quoted, because the
justification is the channel and not the value: it travels the local pipe, which
already carries matched text and, on request, the whole extracted document. What
it must never do is reach a report or the traceback sink, and a leak-suite test
now pins both directions.

---

### M13 — `rpc.inspect` omitted the hidden inventory

**Low · parity · Fixed in `41c73d1`**

`freedocs inspect` has named the thumbnail, the comments, the tracked changes and
the metadata since `15ee0e1`; `rpc.inspect` never carried them. So the window's
Review step was silent about exactly the leak users do not expect, and the only
place to learn a thumbnail was going was the result page — after the decision had
been made.

A missing field rather than missing work: `Scrubber.read` already calls
`scrub_hidden`. And it is safe to render **because of M1** — `detail` is a
description and never a value now. Before that, it quoted a hidden sheet's name.

---

### M15 — Shell and CSP breadth

**Low · A05 · Fixed in part, by decision, in `62da6a0`**

The CSP declared `default-src` and `style-src` and stopped, so `object-src`,
`base-uri`, `form-action` and `frame-ancestors` fell back to permissive defaults.
All four are `'none'` now — the app has no objects, no base tag, no forms, and is
never framed.

The two plugins are narrowed to the single command each is used for:
`dialog:allow-open` and `opener:allow-reveal-item-in-dir`, replacing `default`
sets that also carried `save`, `ask`, `confirm`, `message`, `open-url` and
`open-path`. Checkable rather than hopeful — the build fails on a permission name
that does not exist.

`core:default` is left whole. See M7 for why.

---

### M16 — Nothing let a user verify a download, and the gate had no audit

**Medium · A08 · Fixed in `6d9ff30`, `b0f9e46`, `bb5a57e`**

The installers are unsigned by decision — an Apple Developer ID and a Windows
certificate are both annual bills on a project this size. With GitHub Actions
switched off, `scripts/ci.py` is the gate, and it ran lint, format, the suite, the
leak checks, the corpus check, the frontend and `cargo test` — **and no dependency
audit**. The dormant workflows declared no `permissions:`, pinned every action to
a mutable tag, and omitted `--locked` from both `uv sync` calls.

**The audit** now runs `pip-audit` over the *lockfile* — `check` omits the `ner`
extra, so an environment audit would skip torch — plus `npm audit --omit=dev` and
`cargo audit`. No ignore list, and that was measured: `cargo audit` fails only on
vulnerabilities and this tree has zero, plus seventeen *warnings* that are the
unmaintained GTK3 bindings and the `glib` unsoundness `dependabot.yml` explains
cannot be fixed from here. `-D warnings` would turn a standing fact into a red
gate.

**The manifest** comes from `scripts/provenance.py`: `SHA256SUMS` and a CycloneDX
SBOM per stack, made by the same command on the same machine that produced the
artefact, because with no runner there is nothing else to attach them to. Running
it once found two things that would have been published — `hdiutil`'s
`rw.<pid>.<name>.dmg` shadow files, which are a half-written copy of the artefact
being hashed, and two `target/` trees holding the same version, which would put
two hashes under one name. Both are refused rather than resolved by modification
time.

**The workflows** were hardened while dormant, which is when it is free. Every
action pinned to a commit SHA with the tag kept as a comment —
`dtolnay/rust-toolchain@stable` was a *branch* — `permissions: contents: read` at
workflow level raised to `write` only on the job that opens a draft release, and
`--locked` on both syncs.

Be precise about what a checksum is worth: it detects a truncated download or a
bad mirror. It does **not** protect against anyone who could replace the download
and the checksum together. That is what a signature would be for, and there is
none.

---

## What was measured away

Four rules were written into the plan, tested first, and then not built. This is
the same outcome the chunk-artifact defence had, and it is why the tests come
first.

**An inflation-ratio check on OOXML containers.** Real Office files sit at 22–24:1,
so any ratio loose enough to pass them passes a bomb of the same shape, and the
absolute ceilings already refuse that bomb. The ratio would only have added a way
to refuse a legitimate text-heavy spreadsheet.

**A size-counting stream wrapper.** The objection to checking `ZipInfo.file_size`
before reading is that the header is attacker-controlled. Measured: `ZipExtFile`
decompresses at most the declared number of bytes and then fails the CRC, so a
header claiming 1 KB for a 20 MB payload yields *no* bytes rather than 20 MB of
them. A test pins that, because it is somebody else's implementation detail.

**`RLIMIT_AS`.** This process reserves **425 GB** of address space on macOS before
importing anything, which is ordinary allocator behaviour. Any ceiling is either
useless or fatal at startup, and `core/limits.py` already bounds what an input can
drive.

**An entity-expansion defence and a dangling-`[Content_Types].xml` defence.** Both
were already closed — `resolve_entities=False` yields zero characters from a
nested-entity document, and an override naming an absent part is simply a
declaration about nothing. Both are kept as standing test cases, because the
obvious way to write a package reader gets the second one wrong.

## What is still open

**Filesystem confinement**, and the reason is architectural rather than "nobody
has tested it". Landlock's rules are applied once, are irreversible, and name
paths that must be known *before* the process restricts itself — and this engine
is one long-lived process serving a whole session, so when it could restrict
itself the user has chosen nothing. `$HOME` separates nothing, denying writes
breaks an output directory chosen later, and lazy imports mean a ruleset missing
part of `site-packages` fails halfway through one scrub on one format rather than
at startup. macOS is blocked further back: the hardened runtime is applied by code
signing. The shape that works is the same one M7 needs. `core/sandbox.py` carries
the full reasoning and `freedocs doctor` prints what is and is not enforced, so the
absence cannot be read as presence.

**Signing.** Unsigned installers stay unsigned. `SHA256SUMS` and an SBOM are what
is offered instead, and SECURITY.md says plainly what that does and does not
prove.

**The platform matrix.** Everything here was verified on macOS arm64. This project
builds on Linux and Windows and has never been launched on either, and the local
gate cannot change that — say "builds", not "works".

## Reproducing the verification

```bash
python3 scripts/ci.py check           # the whole gate, including the audit
python3 scripts/fuzz.py --cases 5000  # deliberately not in the gate; see M2
cd engine && uv run pytest -q -m leak # the standing questions
uv run freedocs doctor --hashes       # what this machine enforces, and the payload
```

The by-hand checks are quoted in each finding above, and each of the nineteen
commits on this work names the one it was verified with.

---

### M17 — A chosen Tesseract, and the installer that was refused

**Low · A05 · Bounded, by decision**

Two related questions, raised by giving the window a way to repair a missing OCR
layer.

#### What `use_tesseract` actually grants

`_adopt()` in `formats/pdf.py` prepends a chosen binary's **directory** to this
process's `PATH`, and PyMuPDF then executes `tesseract` by bare name out of it. So
the RPC method that hands the engine a path is not an ordinary setting: it is
exec-adjacent for the engine process.

**M7 does not cover this, and citing it would be the mistake.** `engine_request`
gives the webview arbitrary file read and write as the user, which is strictly
more reachable but a *different class* — read and write is not execute. The
argument that a missing door licenses new windows proves too much.

What bounds it is not a permission list. Two facts do, and both are checks the
environment variable route already had to pass:

- The target must already carry the executable bit, decided by `_is_executable`.
  Nothing in the engine ever chmods.
- It must already be **named** `tesseract`, decided by `_resolvable_by_name`.

Nothing reachable over the pipe writes a file satisfying both: `scrub` writes
documents at the umask with the input's extension. The second check was added by
this work and is the more interesting one — see below.

**A file picker created the first reachable path to a real defect.** Before it,
every caller of `_adopt` supplied a path already named `tesseract`:
`_SYSTEM_BINARIES` names it literally, and `FREEDOCS_TESSERACT` is set by a script
that knows the name. A person choosing from a dialog does not. `tesseract-5.3.4`
is runnable, so it passed `_is_executable`, `tesseract_binary()` returned it and
`ocr_unavailable_reason()` therefore reported OCR **available** — while PyMuPDF
resolved `tesseract` in that directory and found a different build or nothing. The
capability and the refusal disagreeing is the one thing that module exists to
prevent, and it would have surfaced as a scan failing inside Tesseract after the
window promised otherwise. `_adopt` now returns None instead of adopting, before
the side effect.

**A refusal is a field in the response, not a raised error.** Raising was the
obvious shape and it is the wrong one: the window would render an error and then
separately re-ask `capabilities`, and those two answers could disagree. One
payload carrying the refusal *and* the resulting state makes that impossible by
construction — the two state fields are the same two expressions `capabilities`
publishes, read from the same process after the attempt. There is no `force` or
`trust` parameter, because one would restore exactly the disagreement being
designed out.

The generalisation is refused outright: **no `set_env`, no `configure`.** A method
that set an arbitrary variable would let injected JavaScript set `FREEDOCS_DEBUG`,
which `_report_crash` reads per crash — restoring full tracebacks to a stderr the
shell inherits, on a packaged build, which is verbatim the regression `7afeb24`
closed. It would also let it repoint `FREEDOCS_NER_MODEL`, clear
`HF_HUB_OFFLINE`, or set `PATH` directly. A dispatch-table test asserts no method
changes the environment except the one that says so in its name.

#### Why the app does not run a package manager

An in-app "install Tesseract for me" was designed and then refused. The reasoning
is recorded because the request will come again.

**`core/egress.py` is structurally blind to it.** It patches
`socket.socket.connect` inside the *engine*; an installer spawned by the shell is
a sibling process. So the app would gain a network path its own enforcement cannot
observe, while `capabilities.network_blocked` kept reporting `true` and
`core/sandbox.describe()` kept rendering "outbound network off except loopback".
That is worse than an unenforced claim — it is an enforced-*looking* claim with
the hole next door.

**The honest correction has nowhere to live.** It could only come from the shell,
while `network_blocked` and `hardening` come from Python. Two sources of truth
about hardening is the "two answers that can disagree" shape refused everywhere
else in this codebase, and there is no clean place to put the sentence.

**Elevation is not a subset of the existing primitive.** `engine_request` is
bounded by the user's own authority. `sudo apt` or an elevated `winget` is not, and
teaching users to elevate for a document anonymiser is a net negative even when it
works.

**It cannot work where it is most needed.** The incident that prompted all of this
was a Finder launch with launchd's `PATH` — where `brew` is not on `PATH` either.
The app would have to hardcode `/opt/homebrew/bin/brew`, `/usr/local/bin/brew`,
MacPorts: a second copy of the `_SYSTEM_BINARIES` table, in the shell, about the
host.

**And only one platform branch survived review.** Debian's `deb.depends` already
makes the package manager the installer; anything else on Linux needs root.
Windows would ship untested on a platform this project says "builds" and not
"works" for. A feature with one live branch is not worth a new exec surface.

What ships instead is a *guided* install, which is a complete path from "OCR
missing" to "OCR available" without leaving the window except to paste one line:
the engine detects which package manager is present and names the exact command,
language data included; the window offers Copy and Check again; and Locate skips
the install for a Tesseract already on the machine. `docs/scanned-pdfs.md` has the
detail.

**Also fixed while here, and it is the same failure one step out.**
`_layers_check` composed its own `"uv sync --extra ner"` instead of going through
`_sync_fix`, so it was the one check still printing advice a packaged user cannot
act on — the defect the window's own comment documented as known. The replacement
test loops over every check rather than naming that one, so the next hardcoded fix
fails too.


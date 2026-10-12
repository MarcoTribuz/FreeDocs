# Security

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository:
**Security → Report a vulnerability**. That keeps the report private until there
is a fix.

Please do not open a public issue for anything that lets confidential data survive
a scrub, and **do not attach a real document** — to a private report either.
Describe the shape of the failing input and, where you can, build a synthetic file
that reproduces it. `engine/tests/conftest.py` shows how: real-shaped identifiers
with correct check digits, belonging to nobody.

Expect an acknowledgement within a week. This is a small project with one
maintainer, so a fix may take longer than that; you will be told which it is.

A source review of the whole project, with every finding, what was done about it
and what is deliberately still open, is in
[docs/security-review.md](docs/security-review.md).

## The threat model

FreeDocs exists because a document has to be handed to a language model and its
confidential data must not go with it. Everything below follows from that.

- **Nothing leaves the machine, and the process now refuses to.** No network call
  is part of a scrub. That used to be a property of the code as written; the
  engine now blocks outbound connections that are not to this machine, with one
  named exception — fetching the model weights, which an installer build does on
  first use. The optional review layer talks to a local Ollama, and a non-loopback
  host is refused unless the caller explicitly passes `--review-remote`.

  Be precise about what that is worth: it stops the *accidental* call, which is
  the realistic one — a dependency checking for its own updates while it holds a
  page of your contract. It is not a defence against hostile code, because a C
  extension can open a socket without going through Python's, and the PDF and XML
  parsers are C. `freedocs doctor` prints what is enforced and what is not.
- **A crash cannot write this process's memory to disk.** Core dumps are turned
  off, which matters more since the key file exists: a dump can contain the
  passphrase and every value the scrub removed.
- **The re-identification mapping never reaches disk unless you ask for it, by
  name.** By default, placeholder-to-original lives in memory for one run and is
  destroyed in a `finally` block, including when a stage raises: there is no key to
  leak, and no way to restore the values afterwards — by anyone, including you.
  That is anonymisation and it is still the default.

  `scrub --map` turns one run into *pseudonymisation* instead. It writes a **key
  file**, which is the placeholder-to-original mapping for that one document. It is
  encrypted with a passphrase (scrypt, then AES-256-GCM with the cleartext header
  bound as associated data), written mode `0600`, and refused inside the output
  directory unless you say you meant it — because the accident that happens is
  zipping the output folder and sending the scrubbed document along with the key
  to undo it. There is **no unencrypted form** of this file, and no
  `--map-passphrase` argument: a passphrase on a command line is in the shell
  history and visible in `ps`.

  What that shifts onto you: **a key file is as confidential as the original
  document.** It is not a report and must not be treated as one. Keep it away from
  the scrubbed copy, and never send the two together.

  See [docs/restore.md](docs/restore.md).
- **The report carries counts and positions, never values.** So does
  `Leak.describe()`: an error about confidential values surviving must not carry
  them, because that message travels to stderr and through the RPC layer.

  A value does not have to be in the document's *text* to be a value, and that is
  where this leaked once: a hidden sheet's name, the names of the sheets a scrub
  renamed, and a PDF's embedded filenames all reached the JSON report, and every
  one of them is exactly the identifying string the scrub had removed. The rule
  now, enforced at the producers: a hidden-content detail and a handler warning
  are **descriptions**, never values. Where a name really is the useful half, the
  report says what the thing is called *now* — a placeholder is a label the
  scrubbed output already publishes.
- **A restored document is written mode `0600`, and so is the report.** The rule
  is what the file holds: anything the document could be reconstructed from is
  owner-only, and only the scrubbed copy — the artefact the tool exists to hand
  over — is left to your umask. Every output is opened `O_NOFOLLOW`, so a symlink
  planted where an output file belongs is refused rather than followed.
- **A key file's own parameters are bounded before they are used.** Opening one
  means deriving a key from the numbers it declares, and this engine is
  single-threaded with no cancel — so a `.fdmap` declaring an absurd scrypt work
  factor would have been a denial of service against the whole session. Outside
  the accepted band it is refused as malformed, before any derivation runs.
- **A document that cannot be read safely is refused, not attempted.** Every
  input is hostile by definition — this tool exists to be pointed at files from
  outside, and it parses them with C libraries. There are ceilings on the input's
  size, on one Office part, on a container's parts added up (an embedded workbook
  spends the same budget) and on a PDF's page count, all in one module. Breaching
  one names the file and stops that file; the rest of the batch continues. A
  parser's own error is translated too, so a document built to break the reader
  produces a refusal rather than a traceback.
- **The engine is a pipe, never a socket.** It reads and writes files named by
  whoever is on the other end, so its only safe caller is a parent process that
  already has the user's permission. Do not expose it on a port.

  Being explicit about the consequence, because it is the one thing here that is
  defence in depth rather than a defence: the desktop shell forwards a method and
  its parameters to that engine, so a compromised webview is a compromised
  filesystem. The renderer is clean — no `@html`, no `eval`, a tightened CSP —
  and the honest fix is architectural rather than a permission list. See
  [docs/security-review.md](docs/security-review.md).
- **The engine can be told to forget.** One process serves the whole session, and
  the extracted text it caches is a *superset* of the findings: it holds whatever
  no layer detected. The desktop app releases it whenever a document leaves the
  screen.
- **The extracted document text is opt-in and never written anywhere.**
  `inspect` returns it only when a caller asks (`include_text`), because it is a
  *superset* of the findings: it contains the confidential text no layer detected.
  A test asserts it cannot reach a report, a warning or an error payload.
- **The output is verified, and a failure writes nothing.** Stage 6 re-opens what
  was written, re-extracts it including hidden parts, and searches for every value
  that should be gone. A survivor exits non-zero. A nearly-clean file is more
  dangerous than an obviously dirty one, because it gets sent.

## What is in scope

- A confidential value surviving a scrub in a way the tool did not report — in the
  visible text, in a hidden part, in metadata, in an embedded object, or in the
  pixels of a redacted scan.
- Anything that writes the placeholder-to-original mapping, or a confidential
  value, to disk, to a log, to a report or into an error message. The opt-in key
  file narrows this bullet and does not remove it. Still in scope: a key file
  written when no caller named a path and a passphrase; a key file that is not
  encrypted, or whose cleartext header carries a value; a passphrase or an original
  value reaching a report, a log, stderr or an RPC error payload; and a key file
  that opens without its passphrase.
- The engine performing a network request during a scrub, or the review layer
  reaching a non-loopback host without `--review-remote`.
- An output file that verification passed but that still contains a value it
  claimed to have removed — that is a bug in the check itself, and the most serious
  class here.
- Path handling that lets a crafted document cause a write outside the output
  directory, or a parser crash that is exploitable rather than merely a crash.

## What is not a vulnerability

These are documented limits, reported by the tool itself. They are still worth
discussing in a public issue — just not as security reports.

- **A quasi-identifier surviving.** "The only female partner in the Lugano office,
  hired in March 2019" identifies someone with no direct identifier in it. Those
  are flagged and reported, never silently rewritten, and the caveat is in every
  report.
- **A value OCR misread on a scan.** A tax number with one character misread fails
  its checksum, is never detected, and survives. Inherent to redacting an image;
  every machine-read page is named in a warning that says to check it by eye.
- **A detector miss the report names.** Place names that double as surnames are the
  known weak spot, and the numbers are published in
  [docs/benchmark.md](docs/benchmark.md).
- **Over-redaction.** Removing something that was not confidential is a quality
  problem, not a security one.
- **A build without the NER extra finding less.** That is expected, and every
  report states which layers were loaded.
- **A broken Excel formula after a sheet was renamed.** Deliberate, and reported as
  a warning: leaving the identifying name would fail the leak check.
- **A key file being readable by someone who has it and its passphrase.** That is
  what it is for. Losing control of the file is a handling problem; the tool's job
  is to make sure the file cannot be read *without* the passphrase, and to refuse
  to put it next to the document it undoes.
- **A restore leaving a placeholder in the document.** Placeholders are matched
  literally, so a token the model translated, reformatted or invented is reported
  and left alone. Guessing which value a damaged token meant would put somebody
  else's data in the document, which is the failure worth avoiding; a visible
  placeholder is not.

## Supported versions, and verifying a build

The newest release on `main`, which is where the newest release tag lives. From
1.0.0 the project follows Semantic Versioning, and what that version number
promises — the CLI, the placeholder shape, the key file and term list formats,
the report — is listed in [CHANGELOG.md](CHANGELOG.md#what-10-commits-to).
Development happens on `develop` and its `feature/*` branches, which carry a
`-dev.N` version and are not supported; a `release/*` or `hotfix/*` branch is
short-lived and exists only to reach the next tag. See
[docs/gitflow.md](docs/gitflow.md). There is no long-term maintenance branch
for an older minor version, so a fix ships in the next release rather than
being backported.

**The installers are unsigned**, and that is a decision rather than an oversight:
an Apple Developer ID and a Windows code-signing certificate are both annual
bills on a project this size. So macOS Gatekeeper and Windows SmartScreen will
both warn, and neither warning is wrong — you are being told nobody has vouched
for the file. What is offered instead:

```bash
shasum -a 256 -c SHA256SUMS       # or: sha256sum -c SHA256SUMS
```

`SHA256SUMS` and a CycloneDX SBOM per stack are published with each build, made
by `python3 scripts/provenance.py` on the same machine and in the same command
that produced the artefact. Be clear about what that proves: it detects a
truncated download or a bad mirror. It does **not** protect against anyone who
could replace the download and the checksum together.

That is what the **build attestation** is for. From the release after 1.0.2, every installer
built by `.github/workflows/app.yml` carries a Sigstore-signed statement that it
came out of that workflow, at that commit, on a GitHub-hosted runner, recorded
in a public transparency log:

```bash
gh attestation verify FreeDocs_<version>_x64-setup.exe -R MarcoTribuz/FreeDocs
```

A file that was swapped after the build has no attestation, and one cannot be
made for it without this repository's workflow. What it does not prove: that the
code at that commit is safe, or anything about a file built on someone's own
machine — and it is not code signing, so Gatekeeper and SmartScreen still warn.
1.0.2 and earlier predate it and have checksums only.

**Every pull request and every push to `main` runs CI**: lint, format, the suite on the declared Python floor and on
3.12, on Linux and Windows, the leak checks, the corpus check, the frontend and a
dependency audit. GitHub Actions was switched off from August to October 2026,
while the repository was private and its allowance ran out; releases from that
period were gated by `python3 scripts/ci.py check` on one machine. That script
also runs `cargo audit`, which no workflow does, and `cargo test`, which only the bundle
workflow does. If you
build from source, run it.

## A note on the dependencies

The detection stack pulls in torch, transformers and gliner2, and the PDF layer
uses PyMuPDF. Model weights are fetched from the Hugging Face Hub on first use, so
that first run is the one moment a default installation touches the network. If
that matters in your environment, pre-populate the cache on a machine that is
allowed to, and check `freedocs doctor` on the machine that is not.

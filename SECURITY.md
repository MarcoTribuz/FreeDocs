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

## The threat model

FreeDocs exists because a document has to be handed to a language model and its
confidential data must not go with it. Everything below follows from that.

- **Nothing leaves the machine.** No network call is part of a scrub. The optional
  review layer talks to a local Ollama, and a non-loopback host is refused unless
  the caller explicitly passes `--review-remote`.
- **The re-identification mapping never reaches disk.** Placeholder-to-original
  lives in memory for one run and is destroyed in a `finally` block, including when
  a stage raises. Scrubbing is anonymisation, not pseudonymisation: there is no key
  to leak, and no way to restore the values afterwards.
- **The report carries counts and positions, never values.** So does
  `Leak.describe()`: an error about confidential values surviving must not carry
  them, because that message travels to stderr and through the RPC layer.
- **The engine is a pipe, never a socket.** It reads and writes files named by
  whoever is on the other end, so its only safe caller is a parent process that
  already has the user's permission. Do not expose it on a port.
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
  value, to disk, to a log, to a report or into an error message.
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

## Supported versions

Pre-1.0, so: the current `main`. There are no maintained release branches yet, and
no signed installers — the CI builds are unsigned artefacts.

## A note on the dependencies

The detection stack pulls in torch, transformers and gliner2, and the PDF layer
uses PyMuPDF. Model weights are fetched from the Hugging Face Hub on first use, so
that first run is the one moment a default installation touches the network. If
that matters in your environment, pre-populate the cache on a machine that is
allowed to, and check `freedocs doctor` on the machine that is not.

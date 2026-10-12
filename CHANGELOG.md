# Changelog

Versions follow [Semantic Versioning](https://semver.org). How a version is
reached — branches, the development counter, tags — is in
[docs/gitflow.md](docs/gitflow.md).

## What 1.0 commits to

From 1.0.0 on, a change to any of these is a **major** version:

- **The CLI**: the commands (`inspect`, `scrub`, `restore`, `terms`, `entities`,
  `countries`, `doctor`, `benchmark`), their flags, and their exit codes.
- **The placeholder shape**, `[ENTITY_N]` with the English stems by default,
  because `restore` and anything a user built downstream match it literally.
- **The key file (`.fdmap`) and the term list (`.fdterms`)**: a file written by
  any 1.x opens in every later 1.x. `engine/tests/fixtures/before-sealed.fdmap`
  is the standing proof for the key file.
- **The JSON report**: fields are added, never renamed or removed, and it never
  carries a value — that last part is an invariant, not a compatibility promise.

Not covered: the JSON-RPC pipe between the window and the engine (both ship in
one bundle and move together), the Python API inside `freedocs`, and detection
quality. A new model or rule that finds more is a minor version even though it
changes what a scrub removes; every figure comes from `freedocs benchmark`.

## 1.0.1 — 2026-10-12

No change to the engine or the window. The first CI run in two months found
the test suite failing on Windows and the bundle workflow failing on every
platform, so 1.0.0 had no Linux or Windows build; this is the release that has
them.

- Four tests built files that meant something else on Windows, where the
  extension decides whether a file runs, and two asserted POSIX permission
  bits. A sealed-file fixture was checked out with CRLF line endings.
- The bundle workflow ran the Rust tests before the engine sidecar existed.
- The dependency audit could not resolve torch on Linux, where the lock takes
  it from the PyTorch CPU index.

## 1.0.0 — 2026-10-12

The first stable release. No engine behaviour changed since 0.2.0; what changed
is what the project is willing to promise, and how it is run.

- **A compatibility promise**, above.
- **An Intune package for Windows.** `app/packaging/intune.py` wraps the MSI as a
  Win32 app and refuses a development version, an MSI whose `ProductVersion` or
  `UpgradeCode` disagrees with the tree, and a staging folder holding anything
  else. `bundle.windows.wix.upgradeCode` is pinned so a rename cannot fork every
  installation. See [docs/intune.md](docs/intune.md); nothing past the script's
  own checks has run on Windows yet.
- **A mark of its own.** The application icon was Tauri's default. The new one —
  a page whose middle line is a bracketed placeholder — and its SVG sources are
  in [assets/brand/](assets/brand/), with the rules for using them.
- **The repository is public and protected.** `main` and `develop` take changes
  only through a pull request with the maintainer's approval, release tags cannot
  be moved, secret scanning and private vulnerability reporting are on. See
  [docs/gitflow.md](docs/gitflow.md#what-the-server-enforces).
- **Dependencies**: torch 2.14.1, phonenumbers 9.0.40, cryptography 50.0.2,
  Tauri 2.12, Svelte 5.57, and `devalue` and `source-map-js` past their
  advisories. The benchmark is unchanged to the last digit: 99.6% of removable
  entities fully removed, 2.2% over-redaction, exact F1 0.929.

## 0.2.0 — 2026-10-05

- **Pasted text.** Scrub text pasted into the window or piped to the CLI, and
  restore the reply the same way, with no file on disk.
- **A firm-wide term list.** An encrypted `.fdterms` file of names and codes
  removed on every scrub that uses it, editable from the window. There is
  deliberately no persistent "never remove" list. See [docs/terms.md](docs/terms.md).
- **Verification knows what was left on purpose.** A correct scrub of a real
  document was refused because the suppression passes had kept a city in a
  jurisdiction clause and a common noun that matched a company name, and stage 6
  counted both as survivors. Those passes now declare what they kept, as a count
  and never a value. Chasing it found six causes, one of them a genuine leak,
  all fixed.
- **The report no longer quotes a value you asked to remove when it was not in
  the document.** It used to, which put a requested client name into the report of
  exactly the documents that did not contain it.
- **The window can repair a missing OCR layer**: locate Tesseract, re-check,
  copy the install command for this machine.
- **Dense documents**: the overlap checks were quadratic; 1 MB of text with an
  IBAN on every line went from 178 s and 14 GB to 8 s and 47 MB, with the
  benchmark byte-identical before and after.
- **One version for the whole tree**, written in nine places by
  `scripts/version.py`, and a gitflow model to advance it.

## 0.1.0 — 2026-08-24

The engine and the window, built milestone by milestone:

- Plain text, born-digital and scanned PDF (OCR, redaction to the pixels), and
  `docx`, `xlsx` and `pptx` written back in their own format, with hidden content
  — thumbnails, pivot and chart caches, tracked changes, speaker notes, embedded
  workbooks, metadata — removed and reported.
- Detection in layers: checksum-confirmed identifiers for twelve countries, a
  multilingual model for names, organisations, places and addresses in
  it/de/fr/en, propagation of confirmed values, address assembly, organisation
  gap fill and suppression of what identifies nobody.
- A verification stage that re-reads the output and refuses to write a file in
  which a removed value survives.
- An opt-in local-LLM review of the output, advisory only.
- An opt-in reverse path: an encrypted key file and `freedocs restore`.
- A Tauri desktop app in four languages, an installer per platform and a portable
  bundle with the model inside.

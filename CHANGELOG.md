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

## Unreleased

- **The first screen lists what else this computer needs.** Beside the model
  download it shows reading scanned PDFs (Tesseract) and the optional local
  review (Ollama), each with what the engine found. Where OCR is missing the row
  offers Install on a Mac with Homebrew, the exact command to copy elsewhere, and
  Check again and Locate everywhere; the file step offers the same controls. When
  the model is already present and OCR is not, the screen opens once for the list
  alone. In English, Italian, German and French.
- **On a Mac with Homebrew, the window can install Tesseract.** Where OCR is
  missing and Homebrew is present, `capabilities` publishes the exact line and
  `install_tesseract` runs it: `brew install tesseract`, plus `tesseract-lang` only
  when the nine OCR languages are not already present. No other package manager is
  run, because each needs `sudo` or UAC; those stay Copy-only. This reverses part
  of M17 by decision — a first installation may reach an external source, as the
  model download does — and the bounds are recorded there.
- **Every installer carries the OCR languages, and the Windows ones carry
  Tesseract.** No CI installer had any language data before this: the sidecar
  bundles `engine/models/tessdata` and nothing filled it. `app.yml` now fetches
  the nine languages and `osd` from one pinned commit of `tesseract-ocr/tessdata`,
  each checked against a pinned SHA-256, and the build fails if one is missing.
  The Windows installers (NSIS and MSI) also ship `tesseract.exe` and its DLLs in
  `bin/`, extracted unmodified from the pinned UB Mannheim 5.4.0 installer, so a
  scanned PDF needs nothing installed on Windows and the Intune package needs no
  Tesseract dependency. Installers grow by about 169 MB of language data, and the
  Windows ones by Tesseract as well.
- **Windows finds a Tesseract installed by hand.** The search covered only a
  machine-wide install on drive `C:`, so a "just for me" install under
  `%LOCALAPPDATA%`, a `Program Files` on another drive, or Scoop left OCR reported
  missing. The locations are now read from the environment, and where winget is
  present `doctor` and the window offer its install line to copy. Also corrected:
  `docs/intune.md` said the OCR language data was inside every sidecar, and a
  CI-built installer carries none.
- **`SHA256SUMS` is written with LF on every runner.** On Windows it came out
  with CRLF, and `shasum -c --ignore-missing` then skipped the two Windows lines
  without a word. The v1.0.2 file was replaced with a normalised copy; its
  hashes did not change.
- **A release cannot be pushed without its changelog section.** `pre-push`
  refuses a release version on `main` or a `v*` tag when `CHANGELOG.md` has no
  `## X.Y.Z` section for it, and `version.py release` reminds you.

## 1.1.0 — 2026-10-12

- **A first-run screen fetches the model, with consent and progress.** Before,
  the 1.2 GB of weights were downloaded inside the first document's analysis,
  which sat still for minutes with nothing to say why. The window now says what
  is downloaded, how much and from where, shows the bytes arriving with the time
  left, and offers "Not now"; until the model is here, documents are read by the
  checksum layer only and the file step says that names and addresses are not
  being looked for. New engine methods `model_status` and `model_fetch`.
- **After the first download, the model is loaded with no network call.** A
  cached copy was handed to the loader as a repository id, which made it ask
  Hugging Face whether the copy was current at every launch. It is now loaded
  as a directory.
- **Windows: no console window.** The engine is a console program started by a
  GUI one, so Windows opened a `cmd` window beside the app for the whole
  session, and closing it stopped the engine.
- **The executable is called FreeDocs**, not `app`: the Dock and Activity
  Monitor on macOS, Task Manager on Windows.
- **Every installer carries a build attestation**, verifiable with
  `gh attestation verify`; see `SECURITY.md`.

## 1.0.2 — 2026-10-12

No change to the engine or the window. 1.0.1 fixed the test suite and still
produced no release: its tagged bundle run failed on all three platforms. This
is the first version with installers for macOS, Linux and Windows.

- `tauri-action` will not create a draft release without a release name.
- The checksum and SBOM step ran `npm` by bare name, which Windows cannot
  launch (`npm.cmd`).
- A Rust test that writes a script and runs it raced a parallel test's fork
  on Linux (`Text file busy`).

## 1.0.1 — 2026-10-12

No change to the engine or the window. The first CI run in two months found
the test suite failing on Windows and the bundle workflow failing on every
platform, so 1.0.0 had no Linux or Windows build.

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

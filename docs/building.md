# Building and launching by hand

CI builds macOS arm64, Linux and Windows, and nobody has launched the Linux or
Windows result. Intel macOS is not built at all. This page is how to close those
gaps on a real machine: build the installer there, launch it, and write down what
happened. It is item G5 of `docs/plans/cedreon-gaps.md`, and the reason it is a
checklist rather than a script is that the question is "does it work", which
only a person in front of the window can answer.

Neither PyInstaller nor Tauri cross-compiles, so **every platform is built on
itself**: a Windows installer on Windows, an Intel `.dmg` on an Intel Mac. A
build under Rosetta on Apple Silicon has not been tried and is not a substitute
until it has been launched on an Intel machine.

| Machine | Produces | Bundling time in CI | Notes |
|---|---|---|---|
| Windows 11 x64 | `.msi` and `-setup.exe` | 26 min | needs a release version, see below |
| Ubuntu 24.04 x64 | `.deb` | 13 min | no AppImage, see [packaging](packaging.md) |
| Intel Mac | `.app` and `.dmg` | 8 min on arm64 | never built anywhere yet |

Plan on **20 GB free disk** and a network connection for the first build: the
engine environment with torch, the Cargo release tree, `node_modules`, and the
1.2 GB model that the sidecar's smoke test downloads and loads. The installer
itself does not contain the model; the machine that builds it needs it once.

## Before anything: which commit

**Windows needs a numeric version.** The `.msi` is built by WiX, which accepts only
`X.Y.Z`, and `develop` always carries `0.2.0-dev.N`. So on Windows build from
`main`, a release branch, or a `v*` tag — see [gitflow](gitflow.md) for how a
release version is set. On `develop` the bundle step fails in WiX after the
sidecar has already been built. Whether the NSIS `-setup.exe` alone accepts a
prerelease version has not been tried; do not rely on it.

Linux and macOS accept a development version, so `develop` is fine there.

```bash
git clone https://github.com/MarcoTribuz/FreeDocs.git
cd FreeDocs
git checkout main            # or the tag being tested: git checkout v0.2.0
python3 scripts/version.py show -v   # write this down: it is what you are testing
```

## The same five steps on every platform

These are `.github/workflows/app.yml` in order, minus the release upload. Each
platform section below says what to install first and how its shell spells them.

1. **Engine environment**, with every extra the bundle needs:
   `uv sync --locked --extra dev --extra pdf --extra ooxml --extra ner --extra restore`
2. **Engine tests**, fast half: `uv run pytest -q -m "not slow"`. A failure here is
   worth stopping for; a bundle around a broken engine wastes the next hour.
3. **Rust bridge tests**: `cargo test` in `app/src-tauri`.
4. **The sidecar**: `uv run --with pyinstaller python packaging/build.py` in
   `engine`. It ends with a smoke test that inspects a sentence and demands a
   `PERSON` finding, round-trips a key file and a term list. If it passes, the
   bundle has its model stack and its cipher; if it fails, nothing after it is
   worth running.
5. **The installer**: `npm ci`, `npm run check`, `npm test`, then
   `npm run tauri build` in `app`, with `CI=true`.

Then, optionally, `python scripts/provenance.py --bundle-dir app/src-tauri/target/release/bundle`
writes `dist/SHA256SUMS` and the SBOMs beside what you built.

On macOS, `python3 scripts/ci.py build` runs steps 1, 4 and 5 and the checksums
in one go, after `python3 scripts/ci.py check` has run the tests. Not on Linux:
it bundles every target in `tauri.conf.json`, AppImage included, and that one
fails. Not on Windows either: its checksum step calls `python3`, which a Windows
machine usually does not have under that name, and the script has never been run
there. Both run the steps by hand, as below.

## Windows 11

Install, once, in this order:

1. **Visual Studio 2022 Build Tools** with the *Desktop development with C++*
   workload (MSVC and a Windows SDK). Rust's `x86_64-pc-windows-msvc` target links
   with it; without it `cargo` fails on `link.exe`.
2. **Rust** from <https://rustup.rs> (`rustup-init.exe`, default options).
3. **Node.js 22** from <https://nodejs.org>. CI uses 22; a newer major has not been
   tried.
4. **uv**: in PowerShell, `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
   uv installs Python 3.12 itself, from `engine/.python-version`.
5. **Git for Windows**, then allow long paths — torch and `node_modules` both
   exceed 260 characters: `git config --global core.longpaths true`.
6. **Tesseract**, for the OCR half of the launch test: the UB Mannheim installer
   (<https://github.com/UB-Mannheim/tesseract/wiki>), with the Italian, German and
   French language data ticked. The engine looks under `%ProgramFiles%` and, for a
   "just for me" install, `%LOCALAPPDATA%` by itself. How it behaves beyond being
   found is part of what this test is for.

WebView2 is part of Windows 11, so the installer needs nothing more.

Open a **new** PowerShell window after installing, so `cargo`, `node` and `uv` are
on `PATH`, then:

```powershell
cd FreeDocs\engine
uv sync --locked --extra dev --extra pdf --extra ooxml --extra ner --extra restore
uv run pytest -q -m "not slow"
cd ..\app\src-tauri
cargo test
cd ..\..\engine
uv run --with pyinstaller python packaging/build.py
cd ..\app
npm ci
npm run check
npm test
$env:CI = "true"; npm run tauri build
```

The installers land in `app\src-tauri\target\release\bundle\msi\` and
`...\bundle\nsis\`. To deploy the `.msi` through Intune, see [intune](intune.md).

## Ubuntu 24.04

```bash
sudo apt-get update
sudo apt-get install -y build-essential curl file git libssl-dev \
  libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf \
  tesseract-ocr tesseract-ocr-ita tesseract-ocr-deu tesseract-ocr-fra
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
curl -LsSf https://astral.sh/uv/install.sh | sh
# Node 22: from nodejs.org, or nvm; the distribution's own nodejs is too old
```

CI builds on Ubuntu 22.04. The package names above are that list plus the build
essentials a clean desktop install lacks; 24.04 is what a user is likely to have,
and building on it is part of the test.

```bash
cd FreeDocs
python3 scripts/ci.py check      # the tests, ~2 minutes; installs no model
cd engine
uv sync --locked --extra dev --extra pdf --extra ooxml --extra ner --extra restore
uv run --with pyinstaller python packaging/build.py
cd ../app && npm ci && CI=true npm run tauri build -- --bundles deb
```

`check` syncs the engine without the `ner` extra, deliberately, so the sync
above is what puts the model stack in before the sidecar is frozen.

`--bundles deb` matters: the default list includes AppImage, which fails in
`linuxdeploy` (see [packaging](packaging.md)). The `.deb` is in
`app/src-tauri/target/release/bundle/deb/`.

## Intel macOS

Check first that the machine really is Intel: `uname -m` must print `x86_64`.

```bash
xcode-select --install                           # the compiler and linker
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install node@22 tesseract tesseract-lang
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
cd FreeDocs
python3 scripts/ci.py check
python3 scripts/ci.py build
```

`ci.py build` sets `CI=true` itself, which is what stops the `.dmg` step hanging
on Finder automation. The `.app` and `.dmg` are in
`app/src-tauri/target/release/bundle/macos/` and `.../dmg/`.

## Launching it: the test that matters

Install the artifact the way a user would, **on a machine or an account that has
no checkout and no development tools on `PATH`**, if you have one. A build tested
beside its own source can find the repository virtualenv, and that hides a
missing piece of the bundle.

**The first launch is where unsigned costs something**, and that is part of what
to record:

- Windows: SmartScreen says "Windows protected your PC". *More info* → *Run
  anyway*. Note whether the `.msi` and the `-setup.exe` both do this.
- macOS: Gatekeeper refuses an unsigned app downloaded from the internet. Right-click
  → *Open* → *Open*, or `xattr -dr com.apple.quarantine /Applications/FreeDocs.app`.
- Linux: `sudo apt install ./FreeDocs_*.deb`. No warning; note what else apt
  pulled in.

Then, in the window:

1. **The diagnostics pane** (file step). Every check it shows, and whether *Engine
   build* names the bundled engine. A checkout path there means the test is not
   testing the bundle.
2. **First scrub with the model.** It downloads 1.2 GB on first use; note how long
   it took and whether the window said what it was doing.
3. **One file of each format**: `examples/offerta-esempio.docx`, the `.txt` beside
   it, and an `.xlsx`, a `.pptx` and a born-digital PDF of your own with invented
   data. For each: the preview shows findings, the scrub writes a file, the result
   says the verification passed, and the output opens in its own application.
4. **A scanned PDF**, with Tesseract installed. The preview names the page as
   machine-read and the output has the values blanked in the image.
5. **Text mode**: paste a paragraph, scrub it with "keep until I close FreeDocs",
   copy it, paste it back as the reply, and get the values back.
6. **Key file and restore**: scrub with a key file, switch to *Put back*, restore
   the scrubbed copy.
7. **Term list**: create one, add a value, see it removed in the preview.
8. **Language and theme**: switch to Italian and to dark mode once, to see the
   window redraw.

A step that fails is the finding. Note what the window said, in its own words, and
the output of `freedocs doctor` if the bundle's engine can be run from a terminal.

## Writing it down

Add a row per platform to *Multi-platform status, honestly* in
[packaging](packaging.md), and change "builds" to "works" **only for what was
seen working**:

```markdown
| Platform | Version | Date | Installer | Launched | Model | Formats | OCR | Text mode | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Windows 11 23H2 | 0.2.0 | 2026-10-.. | .msi | yes | yes, 4 min | txt docx xlsx pptx pdf | yes | yes | SmartScreen on first launch |
```

## When it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `failed to run command cargo metadata ... (os error 2)` | cargo is not on `PATH` in this shell | new terminal after `rustup`, or add `~/.cargo/bin` to `PATH` |
| WiX error about the version while bundling on Windows | a `-dev.N` version | build from `main` or a tag |
| `.dmg` step hangs, then `AppleEvent timed out (-1712)` | `CI` not set | `CI=true npm run tauri build` |
| `failed to run linuxdeploy` | the AppImage target | `-- --bundles deb` |
| `No space left on device` | torch, Cargo and the model together | free 20 GB; `cargo clean` in `app/src-tauri` between attempts |
| the window lacks a feature the code has | a stale sidecar in `target/debug/freedocs-engine/` answered | delete it, or set `FREEDOCS_ENGINE` |
| smoke test fails on `PERSON` | the model stack did not make it into the sidecar | `--extra ner` missing from the sync; re-run step 1 |
| "OCR not available" with Tesseract installed | the binary or the language data is not where the engine looks | `freedocs doctor` names which half; *Locate Tesseract…* in the window |

# The portable bundle

Unzip and run. No installer, no admin rights, no network, no writes outside the
folder it was unzipped into. Built alongside the installers, never instead of
them.

**CI does not build it by default.** These steps roughly double the expensive
half of `app.yml` — a second bundling pass over a 2.3 GB tree on three runners,
with macOS billed at 10× — and they emptied this private repository's Actions
allowance the first time they ran. They are gated on a `BUILD_PORTABLE`
repository variable: set it to `true` when a portable release is wanted, leave it
unset otherwise. The commands below build one locally on any platform, which is
the only place a portable bundle has actually been launched anyway.

```bash
cd engine
uv run python packaging/model.py                     # stage the weights, once
uv run --with pyinstaller python packaging/build.py   # the sidecar, as usual
cd ../app && python packaging/portable.py             # -> app/dist-portable/
```

Measured on the machine this was developed on: a 2.29 GB tree, a **1405 MB** zip,
of which 1172 MB is `model.safetensors` compressing to 1028 MB.

**A CI-built zip is smaller than that, and the difference is language data.** The
PyInstaller spec folds `engine/models/tessdata` into the sidecar when it exists,
and it exists on a machine where somebody downloaded it — 143 MB here, nothing in
CI, which never fetches it. So a CI portable build carries neither half of OCR and
a local one carries the data but still not the binary. Both are reported honestly
by `doctor`; neither is promised by `capabilities`.

## Why it needs no writable state

This is the decision the rest follows from. `GLiNER2.from_pretrained` accepts a
local directory as well as a repository id — its `download_or_local` branches on
`os.path.isdir` — so a portable copy ships the weights as five plain files and
points at them. There is no Hugging Face cache, no redirected `HF_HOME`, and
nothing to download on first run.

That is what makes the awkward platforms easy. An AppImage mounts read-only and a
macOS `.app` should not be written into; neither matters if nothing writes. So
"portable" reduces to *resources resolved relative to the executable*, which
Tauri's `resource_dir()` already does in all three shapes:

| | where `resource_dir()` points |
|---|---|
| macOS | `FreeDocs.app/Contents/Resources/` |
| Linux | `/tmp/.mount_XXXX/usr/lib/FreeDocs/` (the mounted AppImage) |
| Windows | the directory holding `FreeDocs.exe` |

and under it: `freedocs-engine/`, `ner-model/`, and on Windows `webview2/`.

There is deliberately no `tessdata/` there. The PyInstaller spec already folds the
language data into the sidecar and `_tessdata_candidates()` now looks inside it, so
a second copy beside the app would be 143 MB of the same files. `FREEDOCS_TESSDATA`
stays as a hook for a user who drops one in.

## The engine is told, never asked

`portable_env()` in `app/src-tauri/src/engine.rs` builds the sidecar's
environment from what is actually beside the app. Nothing decides "am I
portable": paths that exist are passed and paths that do not are not, which is
the rule `_tessdata_candidates()` in `formats/pdf.py` already followed.

| variable | set when | read by |
|---|---|---|
| `FREEDOCS_NER_MODEL` | `ner-model/config.json` exists | `gliner_backend.model_source()` |
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | *only* alongside a bundled model | `huggingface_hub` |
| `FREEDOCS_TESSDATA` | a `tessdata/` beside the app holds a `.traineddata` | `formats/pdf.tessdata_path()` |
| `FREEDOCS_TESSERACT` | `bin/tesseract` is a file | `formats/pdf.tesseract_binary()` |

Three things about that table are load-bearing:

**An already-set variable is never overwritten**, the same precedence
`FREEDOCS_ENGINE` has. A developer who said where the model is meant it.

**A variable naming a directory that is not there would be worse than no
variable.** `model_source()` *raises* on a path it cannot load rather than
falling back to the pinned repository id, because the fallback is a silent 1.2 GB
download on a machine with a network and a 404 about a repository nobody named on
one without.

**The offline pair is set only alongside a bundled model**, and it is what makes
"offline" true rather than merely likely: without it an air-gapped machine can
still spend a DNS timeout inside `from_pretrained` before reading weights it
already has. An installer build sets neither and downloads exactly as it did
before.

Consequence worth stating plainly: in an installer build none of these paths
exist, so the sidecar's environment is unchanged and the behaviour is byte-for-byte
what it was.

## OCR is the one thing that does not travel

PyMuPDF does not link Tesseract, it shells out to it, so the **binary cannot be
bundled** — it is a platform package. The language data can be and is.

A portable copy therefore reports OCR unavailable on a machine with no Tesseract,
and `doctor` names which half is missing. Three ways out, all the user's:

- install Tesseract with a package manager — `doctor` and the window now name the
  exact command for the manager this machine has, language data included, because
  the base package ships English only and an English-only install reads as OCR
  working. See [scanned-pdfs.md](scanned-pdfs.md);
- drop a binary at `<root>/bin/tesseract` and the app will find it — this route
  needs a restart, because `portable_env` is read once when the sidecar starts;
- point the window at one with **Locate Tesseract…**, which needs no restart:
  `FREEDOCS_TESSERACT` is re-read on every call, so the running engine adopts it
  immediately.

The third route is why `_adopt` now refuses a candidate not *named* `tesseract`.
Before a person could choose the file, every caller supplied a path that already
was — `_SYSTEM_BINARIES` names it, and a script sets the variable — so a runnable
`tesseract-5.3.4` would have been reported as working while PyMuPDF resolved the
bare name and found something else.

The first route no longer depends on the launch context: `_SYSTEM_BINARIES` in
`formats/pdf.py` lists where each package manager puts the executable, so a
Finder-launched app with `PATH=/usr/bin:/bin:/usr/sbin:/sbin` still finds a
Homebrew install. See `docs/scanned-pdfs.md`.

Both routes are validated rather than trusted, and both share a subtlety worth not
undoing: `_adopt()` puts the binary's directory on `PATH`. Nothing in the engine
runs Tesseract — PyMuPDF does, and it resolves the executable through `PATH` with
no argument for it, only for the language data. A binary that merely satisfied
`ocr_unavailable_reason()` would report OCR available and then fail on the first
scan, which is the exact shape of the bug that made that function the single
authority in the first place.

## Windows needs a WebView2 runtime, and there is no stable URL for one

Without a runtime the window silently never opens — the least diagnosable failure
this app has. So a portable Windows zip carries one at `webview2/`, and
`adopt_bundled_webview()` in `src-tauri/src/lib.rs` points the loader at it by
setting `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER`.

Two details there are not arbitrary. It runs at the top of `run()` because the
WebView2 loader reads that variable when the webview is created, which the builder
below does — a later assignment is a variable nobody reads. And it resolves its
own path from `current_exe()` rather than sharing `engine::resource_root`, because
`resource_dir()` needs a built `App` and by then it is too late.

**The runtime is not fetched automatically, and that is Microsoft's fault rather
than a shortcut.** The fixed-version package is published only as

```
.../filestreamingservice/files/<GUID>/Microsoft.WebView2.FixedVersionRuntime.<version>.x64.cab
```

where the GUID is per version and unguessable, and a version is de-listed once it
falls outside the two-newest-releases window. A hardcoded URL is a 404 waiting to
happen. The evergreen installer is no use because it installs.

So CI reads `WEBVIEW2_FIXED_RUNTIME_URL`, a repository variable, from the current
link on <https://developer.microsoft.com/microsoft-edge/webview2>. Until it is
set, the Windows zip is still built and `packaging/portable.py` says out loud that
it needs a runtime already installed on the target machine. Locally, unpack the
`.cab` into `app/src-tauri/webview2/` and the build picks it up.

## What the AppImage needed

The old failure was `failed to run linuxdeploy`, with no diagnostic of its own,
after nine minutes — which is why Linux shipped only a `.deb`. Tauri downloads
`linuxdeploy`, which is itself an AppImage and has to mount itself to run, and
`ubuntu-22.04` ships FUSE 3 only.

`appimage_env()` in `packaging/portable.py` sets:

- `APPIMAGE_EXTRACT_AND_RUN=1` — every nested AppImage tool extracts instead of
  mounting, needing no FUSE at all. First, because it is the fix that does not
  depend on the runner image.
- `NO_STRIP=true` — not caution. `freedocs-engine.spec` sets `strip=False`
  because "the engine speaks on stdout and must never be stripped of it", and a
  `linuxdeploy` strip pass would undo a stated invariant silently.
- `ARCH` explicitly.

and the build runs with `--verbose`, so the next failure has the diagnostic this
one lacked. CI also installs `libfuse2`, belt and braces. The `.deb` is built by
its own untouched step either way.

## Verifying a copy

The engine cannot tell you whether the weights are *complete* by loading them
cheaply, so `packaging/model.py` writes a `manifest.json` of every file's size and
SHA-256 beside them, and `diagnostics._weights()` checks the sizes on every
`doctor`. That is the difference between "the payload is incomplete" and "this
tool is broken" the first time a copy is truncated by a full disk or a stick
pulled mid-write.

Sizes on every call, hashes only when asked (`model.py --check --hashes`): hashing
1.2 GB catches exactly one thing a size check does not, and paying seconds of I/O
for it would make `doctor` too slow to run.

`capabilities` reports `model_source` as `"bundled"` or `"hub"` — an enum, so the
window translates it rather than quoting it, and never the path, because a local
filesystem path tells the window nothing it can act on. `doctor` is where a path
belongs.

## Stated limitations

- **Unsigned.** macOS quarantines a downloaded zip; clear it with
  `xattr -dr com.apple.quarantine FreeDocs.app`. Windows shows SmartScreen.
- **No Tesseract binary**, per the section above.
- **Theme and locale are not portable.** They live in `localStorage`, which means
  the webview's profile under the OS app-data directory keyed by
  `ch.realise.freedocs` — so a portable copy leaves those two values behind on the
  host. Deliberate: `theme.svelte.ts` resolves the preference *during module
  import* so nothing paints before it, and moving it to a file would reintroduce
  the async read at boot, and with it the flash of the wrong theme. Two enum
  values are not worth that.
- **"Builds" is not "works" for Linux and Windows.** Same caveat as the
  installers: CI produces them and nobody has launched one.
- **The model is redistributed under Apache 2.0** (`fastino/gliner2-privacy-filter-PII-multi`,
  ungated). `packaging/model.py` writes the licence text and a `NOTICE` beside the
  weights, generated by the script that produces the payload so the two cannot
  drift apart. Apache-2.0 is one-way compatible with this project's AGPL-3.0.
- **1405 MB per platform**, of which 1028 MB is a fp32 `model.safetensors` that
  barely compresses. That is inside GitHub's 2 GB per-release-asset ceiling at
  about 70% of it, so there is little headroom for a larger model. The ONNX export
  named in [packaging](packaging.md) would put the whole zip under 600 MB and
  needs a benchmark re-run to prove the published numbers hold.

# Packaging

```bash
cd engine
uv run --with pyinstaller python packaging/build.py   # -> engine/dist/freedocs-engine/
cd ../app && CI=true npm run tauri build              # -> .app and .dmg
```

Result on the machine this was developed on: a 1.0 GB `.app` and a 325 MB `.dmg`.

**One directory, not one file.** A one-file bundle unpacks half a gigabyte of
torch to a temporary directory on every launch. `tauri.conf.json` ships it as a
resource and `src-tauri/src/engine.rs` spawns the executable inside it, falling
back to the repository virtualenv — which is what makes `tauri dev` usable before
any bundle exists.

**`CI=true` is required for `tauri build`.** The `.dmg` step runs AppleScript to
arrange icons in a Finder window; without Finder automation permission it fails
with `AppleEvent timed out (-1712)` after minutes of bundling. Tauri passes
`--skip-jenkins` when `CI` is set. The `.app` is unaffected.

**`packaging/build.py` must exercise the model, not just `capabilities`.** Every
format handler and detector backend imports lazily, and `NerDetector` is
constructed without touching gliner2 — so `capabilities` cheerfully reported the
NER layer present in a bundle that had no model stack in it at all, and the first
real document failed. The smoke test now inspects a sentence with a name in it and
demands a `PERSON` finding. Anything imported inside a function needs
`collect_submodules` in the spec; PyInstaller cannot see call-time imports.

**Not in the bundle, on purpose:** the NER model (~1.2 GB, fetched to the user's
cache on first use) and Tesseract. Both absences are reported through
`capabilities`, so the app says so rather than failing mysteriously.

The obvious size win is not taken yet: torch is 501 MB of the bundle, and the NER
model would run under `onnxruntime` at roughly 15 MB. Exporting GLiNER2 to ONNX
needs re-benchmarking to prove the published numbers still hold, so it is a
measured optimisation rather than a refactor to do blind.

## Multi-platform status, honestly

`.github/workflows/app.yml` bundles macOS arm64 (`macos-15`), Linux (`.deb`) and
Windows on their own runners, because neither PyInstaller nor Tauri
cross-compiles, and all three are green. That means the sidecar builds, the smoke
test loads the model and the installer is produced. **It does not mean anyone has
launched the result anywhere but macOS.** Say "builds" and not "works" for Linux
and Windows.

Two platforms are absent and the reasons differ:

- **Linux ships a `.deb` and no AppImage.** The `.deb` bundles fine and the run
  then dies in `failed to run linuxdeploy` with no diagnostic of its own.
- **Intel macOS is not built at all.** `macos-13` was retired and the job simply
  queued forever with no runner assigned — which looks exactly like a slow build —
  while the replacement `macos-15-intel` is a billed larger runner.
  Cross-compiling from arm64 would cover the Rust half and not the sidecar, so an
  Intel bundle needs an Intel machine.

Both are gaps rather than decisions about who to support. Apple signing is opt-in
through repository secrets; an unsigned build still works for testing.

`macos-14` was working when it was replaced by `macos-15`. It is *deprecated*,
which is the state `macos-13` was in shortly before it stopped being assigned
anything, so a deprecated runner label is worth moving off before it becomes a job
that hangs instead of failing.

## CI

`.github/workflows/engine.yml` runs lint, format, the suite, the leak checks and
the corpus check on every pull request and every push to `main`: Python 3.10 and
3.12 on Linux, and 3.12 on Windows. It takes about thirty seconds. Keep all three
green — 3.10 is the declared floor in `pyproject.toml`, so avoid 3.11+ syntax, and
Windows is there because that is where the cross-platform failures have actually
been.

`--extra ner` is deliberately omitted in CI: the `slow`-marked tests skip
themselves, and detection quality is measured by `benchmark`, not asserted in CI.

**It had never passed once before 22 August 2026, and two of the reasons are worth
not reinventing.** The 3.10 job was never running 3.10: `--python` was passed to
`uv sync` and to nothing else, so the next plain `uv run` chose the runner's
default interpreter, *deleted* the virtualenv it did not recognise, made a
three-package one and died on `Failed to spawn: ruff` before linting a line.
`UV_PYTHON` is job-level for that reason; do not go back to flagging one command.
And one RPC test asked for `detectors="ner"`, which no build without the extra can
answer — a model-backed test has to skip itself or ask something the model is not
needed for.

`app.yml` is the expensive one and it does **not** run on pull requests. Bundling
is 8 minutes on macOS, 13 on Linux and 26 on Windows, three times over, and it was
running on every push to every open branch. It now runs on a push to `main`, on a
`v*` tag, and on `workflow_dispatch`. The trade is deliberate: a change that
breaks packaging is found just after it lands rather than just before, and the
engine workflow — which is what a pull request runs — covers Windows, so the class
of bug that motivated the bundle on PRs is still caught early.

Do not add a `paths` filter to it: the same filter would apply to the tag trigger,
and a release tag whose commit touches nothing under `app/` would silently skip
the build that makes the release.

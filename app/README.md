# FreeDocs — desktop app

A window around `../engine`. It holds no rules of its own: every judgement about
what is confidential, what gets removed and what the user is warned about lives in
Python. Two places deciding what an IBAN looks like is two answers that can
disagree.

## Running it

```bash
npm install
npm run tauri dev
```

No sidecar build needed. The Rust side falls back to `../engine/.venv/bin/freedocs-rpc`,
so the app runs as soon as the engine's virtualenv exists.

```bash
npm run check   # svelte-check, must be clean
```

## Building a distributable

The engine has to be frozen first, because `tauri.conf.json` ships it as a
resource and Tauri refuses to build when a declared resource is missing:

```bash
cd ../engine
uv run --with pyinstaller python packaging/build.py
cd ../app
CI=true npm run tauri build
```

`CI=true` is not decoration. Without it the `.dmg` step runs AppleScript to arrange
the icons in a Finder window, which needs Finder automation permission and times
out with `AppleEvent timed out (-1712)` in any non-interactive shell — a sandboxed
terminal, a CI runner, an SSH session. The `.app` builds either way; only the disk
image fails, and it fails after several minutes of bundling. Tauri passes
`--skip-jenkins` to `bundle_dmg.sh` when `CI` is set, which skips the cosmetic step
and produces a working, plainer image.

Result: a 1.0 GB `.app` and a 325 MB compressed `.dmg`.

Roughly 650 MB of that is the engine, and roughly 500 MB of the engine is torch.
The obvious win — running the NER model under `onnxruntime` at about 15 MB —
needs re-benchmarking to prove the quality numbers hold, so it is a measured
optimisation rather than a blind refactor.

Not in the bundle: the NER model weights (~1.2 GB, fetched to the user's cache on
first use) and Tesseract. The engine reports both absences through `capabilities`,
which is why the window can say "OCR not installed" instead of failing oddly.

## How the two halves talk

Newline-delimited JSON over the child process's stdin and stdout. One object per
line; requests carry an `id`, responses echo it, progress arrives as notifications
without one. `src/lib/engine.ts` is the whole client.

The engine is a **pipe, never a socket**. It reads and writes files named by
whoever is on the other end, so the only safe caller is a parent process that
already has the user's permission to touch them.

One engine process serves the whole session, because loading the NER model takes
seconds and running it takes milliseconds.

The protocol is tested in `../engine/tests/test_rpc.py` rather than here: it is
the only thing this app can see, and it is far cheaper to test than a window.

## Layout

- `src/lib/engine.ts` — the client, and nothing else
- `src/routes/+page.svelte` — the whole UI
- `src-tauri/src/engine.rs` — spawns the child, routes responses by id, forwards
  notifications to the window as `engine://notify`
- `src-tauri/src/lib.rs` — two commands: forward a request, report whether the
  engine started

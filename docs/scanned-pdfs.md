# Scanned PDFs: redacting pixels, not glyphs

On a scanned page there are no glyphs to delete — the text *is* the image. The
same `apply_redactions()` call blanks the image pixels inside the rectangle
(`images` defaults to `PDF_REDACT_IMAGE_PIXELS`), editing the image stream rather
than covering it, so re-running OCR on the output no longer reads the value. The
tests check exactly that: they machine-read the scrubbed file and assert the
canary is unreadable while the rest of the page still is. Checking `get_text()`
would prove nothing about a scan.

## Three things worth keeping

**The decision is per page, not per document.** Real files mix them — a contract
exported from Word with the signed page scanned back in. `page.get_images()` is
what distinguishes a scan from a genuinely blank page: OCR the first, ignore the
second. PyMuPDF returns OCR results in the page's own coordinate system with the
same `rawdict` shape as the text layer, so extraction, anchoring and redaction
stay one code path. Do not rasterise and map pixel coordinates by hand; it is the
same result with an extra transform to get wrong.

**Verification had to be made adversarial.** A scanned page is only machine-read
when its text layer looks empty, and a *redacted* scan carries the placeholders
that replaced its content — enough text to look ordinary. So verification was
inspecting the placeholders and never the pixels, and a failed pixel redaction
would have passed. `harden_for_verification()` now makes the check re-read every
imaged page, and any handler that reads less than everything for speed must
override that hook.

**OCR is a reading, not the text.** A codice fiscale with one character misread
fails its checksum, is never detected, and survives. That is inherent to
redacting a scan, so every machine-read page is named in a warning telling the
user to check it by eye. Do not remove the warning to tidy the output.

## Never return a scan as if it were processed

`extract()` raises `ScannedPdfNotSupported` when a page has no usable text layer
*and OCR is unavailable*, naming the pages and what to install, rather than
producing an untouched file the user believes was scrubbed.

`hidden_text=False` is passed to `scrub()` deliberately: an OCR layer over a scan
*is* invisible text, and deleting it blind would throw away content this pipeline
can redact properly.

## Installing OCR

OCR needs the Tesseract binary **and** its language data, and neither is
installable with pip. PyMuPDF does not link Tesseract, it shells out to it:

```bash
brew install tesseract                      # or your platform's package
cd engine && uv run python packaging/tessdata.py
```

`packaging/tessdata.py` fetches the ten files (nine languages and `osd`) from one
pinned commit of `tesseract-ocr/tessdata`, checks each against a pinned SHA-256,
and replaces a file of the same name that is not the pinned one. It is the same
script every CI build runs before bundling, so a checkout and an installer read
scans with the same bytes.

**What the installers carry.** Every installer carries the language data inside
its sidecar. The Windows installers also carry Tesseract itself — the UB Mannheim
build, extracted from its pinned installer by `app/packaging/tesseract_windows.py`
and shipped as `bin/`, where the app points the engine at it — so a scanned PDF
needs nothing installed there. macOS and Linux do not carry the binary: there it
is a platform package linked against system libraries. The `.deb` makes apt
install it through `deb.depends`, and on macOS it is one Homebrew line.

Nine languages, one per language spoken in the twelve countries whose identifiers
this build confirms. Asking for all of them at once costs almost nothing in time —
223 ms for one page with four languages, 247 ms with nine — because the document's
language is not known, and a scrubber that has to guess it before it can read the
page has an extra way to fail silently. The cost is on disk: 143 MB of language
data, against 57 MB for four. Homebrew's `tesseract-lang` works too, at 1.2 GB for
every language.

`engine/models/tessdata` is searched by default, after `FREEDOCS_TESSDATA` and
`TESSDATA_PREFIX`, and a packaged build carries the same files beside its
executable.

**`brew install tesseract` on its own is not enough, and the shortfall is
silent.** It ships `eng` and `osd`; this engine asks Tesseract for nine languages
at once. `tessdata_path()` counts a directory that holds *any* `.traineddata`, so
an English-only install makes `capabilities.ocr_available` **true** while an
Italian or German scan reads badly — and a value OCR misreads fails its checksum,
is never detected, and survives. That is the defining failure of this tool
reached by a successful install.

So every command the window offers names the language data too:
`brew install tesseract tesseract-lang`, the `tesseract-ocr-*` packages on Debian,
the `tesseract-langpack-*` ones on Fedora. `_PACKAGE_MANAGERS` in
`diagnostics.py` is that table and a test asserts every entry names at least one
language beyond the base package, so shortening a line fails the suite rather than
shipping a quiet leak.

One thing still open, recorded rather than fixed. `ocr_unavailable_reason()`
naming *which* languages are missing would close the gap properly, and that
changes the single authority's contract — it needs its own measurement of what a
partial language set actually costs. The `.deb`'s `deb.depends` lists
`tesseract-ocr` alone and that is no longer a shortfall: the languages travel in
the sidecar, which `tessdata_path()` consults before the system's directories.

## The window can act on this, and on a Mac it can install it

`freedocs doctor` and the desktop app's "What this machine can do" pane both put a
`Check.fix` beside every failure. For OCR that fix is now the command for the
package manager **this machine actually has** — detected by looking for
`/opt/homebrew/bin/brew`, `/usr/bin/apt` and the rest at absolute paths, for the
same reason `_SYSTEM_BINARIES` holds absolute paths: under a Finder launch `PATH`
is launchd's, and `shutil.which("brew")` fails on a machine that has Homebrew.
When no manager is found the advice stays generic, because naming apt on a Fedora
machine is advice that fails.

The window shows that command with a Copy button, and a **Check again** button
beside it. Re-checking works with no restart because `tesseract_binary()` and
`tessdata_path()` are resolved on every call — install Tesseract in your own
terminal, press the button, and the badge flips.

**On a Mac with Homebrew, an Install button runs it for you.** That is the one
exception, decided on 2026-10-13 and recorded in M17 of `docs/security-review.md`:
Homebrew installs as the user with no `sudo`, the line it runs is the line the
window shows, and it asks for `tesseract-lang` only when the nine languages are
not already present (every installer carries them, so normally the button runs
`brew install tesseract`). apt, dnf, pacman, MacPorts and winget stay Copy-only,
because each needs elevation. What follows is the reasoning that refused the
button everywhere, which still bounds the one place it exists.

**Nothing else runs the command for you, and that is a decision.** Spawning a package
manager would put a network call outside everything `core/egress.py` can observe,
while `capabilities` went on reporting that outbound connections are blocked — an
enforced-looking claim with the hole beside it, and the honest correction could
only come from the shell while `network_blocked` comes from Python. Two sources of
truth about hardening is the shape this project refuses everywhere else. You paste
it into a shell where the process already *is* you, which is the same reasoning
`core/sandbox.py` gives for the CLI needing no confinement.

If Tesseract is installed somewhere none of the usual locations covers, the window
also offers **Locate Tesseract…**. The engine judges the file: it must be runnable
*and* named `tesseract`, because `_adopt()` puts its directory on `PATH` and
PyMuPDF then resolves that bare name — a differently-named executable would be
reported as working and then not be the file that runs. The refusal is a field in
the response rather than an error, so the window cannot show one message while
`capabilities` says something else.

**"OCR is available" means the binary *and* the language data.** The two halves
install separately — the `.traineddata` files can be bundled, a platform package
cannot be — and `capabilities.ocr_available` used to check the data alone, which
would have made the capability true everywhere and left the window promising an
OCR the first scan could not deliver. One `ocr_unavailable_reason()` decides, so
the capability and the refusal cannot disagree, and the refusal names which half
is missing.

**The binary is looked for in the usual install locations, not only on `PATH`.**
`PATH` is a property of how the process was started, not of what is installed: a
macOS `.app` opened from Finder inherits launchd's environment, so its `PATH` is
`/usr/bin:/bin:/usr/sbin:/sbin` and a Homebrew Tesseract at `/opt/homebrew/bin`
cannot be on it whatever the user installs next. The bundle reported OCR
unavailable on a machine where `brew install tesseract` had already succeeded,
while the language-data half resolved fine — because `_SYSTEM_TESSDATA` was
already a list of locations and the binary half was `shutil.which` alone.
`_SYSTEM_BINARIES` is the matching list, tried after `FREEDOCS_TESSERACT` and
after `PATH` so that a build somebody chose still wins. A binary found off `PATH`
has its directory prepended to `PATH`, because PyMuPDF resolves the executable by
name and takes no argument for it.

On Windows the list is read from the environment rather than written as `C:\`:
`%ProgramFiles%` (and its 64-bit and x86 siblings), the per-user directories under
`%LOCALAPPDATA%` that the UB Mannheim installer's "just for me" option uses, and
Scoop's app directory. None of them puts Tesseract on `PATH` by default, and the
first version of the list covered only a machine-wide install on drive `C:` — a
Windows machine reported OCR missing after a manual per-user install. Where winget
is present, `doctor` names `winget install --exact --id UB-Mannheim.TesseractOCR`.
That is the one install line that names no language data, because the package
takes no language choice: on Windows the languages are the bundle's job. It is
also the line a Windows installer should never need, since it carries Tesseract.

Check what this machine can actually do:

```bash
uv run freedocs doctor
uv run freedocs doctor --strict   # non-zero when any optional layer is missing
```

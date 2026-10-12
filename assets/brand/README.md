# The FreeDocs mark

A page whose middle line has been taken out and replaced by a placeholder: the
bracketed bar is `[PERSON_1]`, the folded corner says *document*, and the lines
around the bar are what the tool leaves alone. That is the product in one
picture — the data goes, the document stays.

Every file here is hand-written SVG and is the **source**. Anything raster
elsewhere in the repository is generated from one of these, so change the SVG and
regenerate rather than editing a PNG.

## Files

| File | Use |
|---|---|
| `app-icon.svg` | The application icon: the mark on its tile. Source of every file in `app/src-tauri/icons/` and of `app/static/favicon.png`. |
| `mark.svg` | The mark alone, on any background. Docs, slides, the website. |
| `mark-mono.svg` | One colour, inherited from `color`. Print, embossing, a monochrome tray icon. |
| `wordmark-light.svg` | Mark and name, for light backgrounds. The README hero. |
| `wordmark-dark.svg` | The same, for dark backgrounds. |
| `social-preview.svg` / `.png` | GitHub's social preview, 1280×640. Upload the PNG under *Settings → Social preview*. |

Inside the window the mark is `app/src/lib/components/Logo.svelte`, inline so it
follows the theme. Its geometry is `mark.svg`'s; change both together.

## Colour

The brand colours **are** the window's tokens in `app/src/app.css`. There is no
second palette, so the repository and the app cannot disagree about what the
green is.

| Token | Light | Dark | Where |
|---|---|---|---|
| `--accent` | `#22785c` | `#3fbb92` | the sheet, the bar |
| gradient | `#2f9e79` → `#186049` | same | the tile, the sheet in `mark.svg` |
| `--accent-border` | `#b9e0d0` | `#1f4b3c` | the folded corner |
| `--accent-text` | `#1f6f54` | `#6fd0ab` | "Docs" in the wordmark |
| `--text` | `#12211c` | `#e9efec` | "Free" in the wordmark |

The contrast of each token is measured and written beside it in `app.css`. Pick
from there rather than eyeballing a new shade.

## Rules

- **Clear space**: at least the width of the folded corner on every side.
- **Smallest size**: 16 px tall for the mark, 24 px tall for the wordmark. Below
  that the brackets merge into the bar, which is fine for a favicon and nowhere
  else.
- **Do not** recolour the bar red or black. It is a placeholder, not a censor's
  stroke; a black bar is the overlay-rectangle redaction this tool exists to
  replace (`formats/pdf_text.py` says why).
- **Do not** put the tile behind `mark.svg` by hand; use `app-icon.svg`, whose
  margins are the ones macOS expects.
- **Wordmark type** is Helvetica Neue Bold with an Arial fallback, written as
  live text. GitHub renders it with whatever it has. For print, convert the
  text to outlines in the exported copy, not in the source.
- **No `<style>` blocks** in any of these SVGs: GitHub sanitises embedded CSS out
  of an SVG shown in a README, so presentation attributes only.

## Regenerating

```bash
cd app
npx tauri icon ../assets/brand/app-icon.svg -o /tmp/icons
# copy over only the files already in src-tauri/icons/ — the command also writes
# android/, ios/ and 64x64.png, which this project does not ship
```

`favicon.png` (64 px) and `social-preview.png` (1280 px) were rendered with
[resvg](https://github.com/linebender/resvg), which is also what `tauri icon`
uses internally, so the two agree pixel for pixel. Any SVG renderer that loads
system fonts will do.

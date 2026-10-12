# Website brief: a simple FreeDocs site on Strapi

This is a brief for whoever builds the FreeDocs website — written to be handed,
whole, to another Claude instance as its starting context. It says what the
product is, what the site must and must not claim, how the content is modelled in
Strapi, and when the work is done. Where a decision belongs to the maintainer it
is listed under *Open questions* rather than guessed.

Read the sources in *What to read first* before writing anything. The site's
whole credibility is that it says no more than the repository can prove.

---

## 1. The product in one paragraph

FreeDocs takes the confidential data out of a document before an AI ever sees
it. PDF, Word, Excel, PowerPoint and scans go in; the same file type comes out,
still formatted, with names, IBANs, tax numbers, addresses and the rest replaced
by placeholders such as `[PERSON_1]`. It runs entirely on the user's machine — no
cloud, no processor, no API key, no telemetry, no account — and the engine
refuses outbound network connections while it works. It is open source under
AGPL-3.0-or-later. It has a desktop app (macOS, Windows, Linux) and a CLI.

What sets it apart, in the repository's own terms:

- **Same format back, still formatted** — write-back edits Word runs and the PDF
  content stream instead of flattening to text.
- **Hidden copies removed** — pivot caches, chart caches, tracked deletions,
  speaker notes, thumbnails of the unredacted page, embedded workbooks.
- **A verification stage that can fail** — the output is re-read and searched for
  every removed value; a survivor means nothing is written.
- **Measured, not promised** — `freedocs benchmark` scores detection against an
  annotated corpus in four languages.
- **Twelve countries** of checksum-confirmed identifiers (ch, it, de, at, fr, be,
  es, pt, nl, pl, se, gb) and a language model reading it/de/fr/en.
- **Irreversible by default**; an opt-in encrypted key file can restore the values
  into whatever the AI returns.

**Audience.** People who must hand a document to an AI and are not allowed to
hand over its data: law firms, fiduciaries and accountants, HR, compliance and IT
in Swiss and European SMEs. Many are not developers. IT departments deploying it
centrally are a second audience (there is an MSI for Intune).

## 2. What the site is for

Four jobs, in order of importance:

1. **Explain in thirty seconds** what it does and for whom, with one real
   before/after example.
2. **Get the right installer onto the right machine**, with checksums and honest
   instructions for an unsigned app.
3. **Earn trust** with the measured numbers, the "what it does not do" list, the
   security review and the source.
4. **Say what changed** — release notes per version.

It is **not** a documentation site. The deep documentation lives in the
repository's `docs/` and the site links to it on GitHub rather than copying it:
a measurement duplicated is a measurement that disagrees with itself after the
next benchmark run. That rule is the repository's own (see `CLAUDE.md`, the
paragraph on `README.md`).

## 3. Rules the content must obey

These are not style preferences. Each one is a claim the project has decided it
cannot make, and the site breaking one would be the site lying for the product.

- **Never claim the output is guaranteed clean, compliant or "100% safe".** The
  report itself carries caveats. Use "removes", "finds", "verifies" — never
  "guarantees", "ensures compliance", "GDPR-compliant".
- **Every figure comes from a `freedocs benchmark` run** and must match the
  README exactly. Today: 99.6% of removable entities fully removed, 2.2%
  over-redaction, exact micro-F1 0.929, on 537 annotated entities across four
  languages. The corpus is small and synthetic; say so next to the numbers, as
  the tool does.
- **"Builds" is not "works".** The app is verified on macOS arm64. Linux and
  Windows installers are built but have not been launched by the maintainer. The
  download page says that per platform. No Intel macOS build exists.
- **Installers are unsigned.** Say so, explain the OS warning the user will see,
  and offer `SHA256SUMS` and the SBOM as what can be verified instead.
- **The "What it does not do" list is published, not buried.** It is the README
  section of that name; reproduce its points on the site, linked to the source.
- **No invented social proof.** No customer logos, testimonials, user counts or
  awards that do not exist.
- **Competitors are named only as the README names them**, with the gap stated
  factually and linked.

## 4. Languages

English is canonical; Italian, German and French follow — the same four as the
app's interface and the README.

- Use Strapi's i18n plugin with locales `en` (default), `it`, `de`, `fr`.
- Marketing copy is translated. **Engine output is not**: CLI transcripts, entity
  names in code blocks (`PERSON`, `IBAN`) and error messages are quoted in
  English in every locale — the app's own rule is "if it came from an enum,
  translate it; if it came from an f-string, quote it".
- Numbers are identical in every locale and formatted per locale with
  `Intl.NumberFormat` — `99.6%` in English, `99,6 %` in Italian, German and
  French. The value never differs; only its spelling does.
- The existing READMEs (`README.it.md`, `README.de.md`, `README.fr.md`) are the
  reference translations for product terminology.

## 5. Architecture

**Strapi v5 as the editing backend, a statically generated frontend, and nothing
dynamic in front of the visitor.** A privacy tool's site that sets a cookie or
loads a tracker undermines the product; a static site cannot.

- **Strapi v5** (Node, TypeScript), PostgreSQL, run in Docker. Its admin is
  private: never publicly reachable except through authentication, ideally only
  over a VPN or an IP allowlist.
- **Frontend: Astro** (static output), fetching from Strapi's REST API **at build
  time only**. The public site makes no request to Strapi. If you prefer Next.js,
  use `output: 'export'` to the same effect — but propose it, do not just switch.
- **Rebuild on publish**: a Strapi webhook on `entry.publish` /
  `entry.unpublish` triggers the static build and deploy.
- **Hosting**: any static host (Cloudflare Pages, Netlify, or a plain nginx). The
  maintainer chooses — see *Open questions*.

Non-negotiable properties of the built site:

- No analytics by default. If the maintainer asks for any, it is self-hosted and
  cookieless (Umami or Plausible self-hosted), and the privacy page says so.
- No third-party requests at all: fonts self-hosted, no Google Fonts CDN, no
  embedded YouTube, no external scripts, no chat widgets.
- A strict Content-Security-Policy (`default-src 'self'`) set by the host.
- No cookie banner, because there are no cookies.
- Works without JavaScript for reading and downloading. JS is optional
  enhancement only (e.g. the theme toggle, OS detection on the download page).

## 6. Pages

| Page | Content |
|---|---|
| **Home** | Hero (tagline, one sentence of how, primary CTA *Download*, secondary *View source*). The before/after table from the README. Three to five "what you get" blocks. The measured numbers with their caveat. "What it does not do", short, linking to the full list. Supported formats and countries. |
| **Download** | Latest release, per platform: file, size, SHA-256, a one-line honest status ("verified on macOS arm64" / "built, not yet launched by the maintainer"). How to open an unsigned app on each OS. The portable zip if a release has one. A box for IT: the Intune MSI and a link to `docs/intune.md`. Link to all releases on GitHub. Optional: detect the visitor's OS to pre-select a tab — never to hide the others. |
| **How it works** | The six stages (router → extract → detect → policy → write-back → verify) in plain language, the detection layers (checksums, language model, propagation), and what a document hides. Each section links to its file in `docs/`. |
| **Security & privacy** | The threat model summary from `SECURITY.md`: nothing leaves the machine and how that is enforced, what it does *not* protect against, the reverse path and why it is off by default, how to report a vulnerability. Link to `docs/security-review.md`. |
| **Changelog** | One entry per release, newest first, from the `Release` collection. |
| **About / Contribute** | Who maintains it, the licence, how to contribute (link to `CONTRIBUTING.md`), "never attach a real document". |
| **Privacy policy / Imprint** | Short and true: this site collects nothing. An imprint (*Impressum*) is a legal requirement in Switzerland and Germany — content supplied by the maintainer. |

Navigation: Home, How it works, Security, Changelog, Download (as a button),
GitHub link, language switcher, theme toggle.

## 7. Content model in Strapi

Keep it small. Every type below is localised unless marked otherwise.

**Single types**

- `global` — site name, tagline, navigation links, footer links, default SEO
  (title template, description, social image), GitHub URL.
- `home` — `hero` (component), `blocks` (dynamic zone, see below), SEO.
- `download-page` — intro text, per-OS install instructions (rich text, one per
  `macos` / `windows` / `linux`), IT/Intune box, SEO.
- `benchmark` — **not localised**: `coverage`, `over_redaction`, `exact_f1`,
  `entity_count`, `language_count`, `measured_on` (date), `engine_version`,
  `caveat` (text, localised via a separate field or the page that shows it).
  Edited only when a new `freedocs benchmark` run is published; the values must
  equal the README's.
- `security-page`, `how-it-works-page`, `about-page`, `privacy-page`,
  `imprint-page` — each a title, a dynamic zone of blocks, SEO.

**Collection types**

- `release` — `version` (string, SemVer, unique), `date`, `channel`
  (`stable`/`prerelease`), `notes` (rich text, localised), `highlights`
  (repeatable short text), `assets` (repeatable component `release-asset`),
  `github_url`.
- `release-asset` (component) — `platform` (`macos-arm64`, `windows-x64`,
  `linux-x64`), `kind` (`dmg`, `msi`, `nsis`, `deb`, `portable-zip`), `filename`,
  `url` (GitHub release asset URL — **do not upload binaries to Strapi**),
  `size_bytes`, `sha256`, `status` (`verified` / `built-not-launched`).
- `faq` — question, answer, `order`, `topic`.
- `limitation` — the "what it does not do" items: title, body, `doc_link`.

**Dynamic-zone blocks** (shared by every page): `rich-text`, `feature-grid`
(icon, title, text, link), `before-after` (rows of before/after cells, rendered
in a monospace face for placeholders), `stats` (reads from `benchmark`, never
typed by hand), `limitations` (references `limitation` entries), `cta`,
`code-transcript` (verbatim, never translated), `faq-list`, `comparison-table`.

**Release data should not be retyped.** Write a small script (Node, in the site
repository) that reads a GitHub release — tag, body, assets — and the release's
`SHA256SUMS` file, and creates or updates the `release` entry through Strapi's
API. A release is a draft that the bundle workflow opens and the maintainer
publishes by hand, so the script is run by hand after publishing; a person then writes the localised notes.

## 8. Visual design

The brand already exists and must be used as is: **`assets/brand/` in the
repository**, with `assets/brand/README.md` as its rules.

- Logo: `wordmark-light.svg` / `wordmark-dark.svg` in the header, `mark.svg` for
  the favicon and small placements, `social-preview.png` as the default Open
  Graph image.
- Colours are the app's tokens in `app/src/app.css`, each with its measured
  contrast ratio beside it. Copy the tokens, light and dark, rather than picking
  new shades. Accent `#22785c` (light) / `#3fbb92` (dark).
- Dark mode follows the OS and can be overridden, as the app does: a
  `data-theme` attribute and two token blocks, not a `prefers-color-scheme`
  duplicate of the palette.
- Secondary text is a colour, never an `opacity` — opacity cannot be measured for
  contrast.
- Type: the system UI stack for text (as the app), a monospace stack for
  placeholders and transcripts. If a webfont is wanted, self-host it.
- The redaction bar in the mark is a placeholder, not a black censor's stroke.
  Do not illustrate the product with black bars over text — that is the overlay
  redaction FreeDocs exists to replace.
- Calm, factual, generous whitespace. The README's tone is the model: short
  declarative sentences, numbers with their caveats, no exclamation marks.

Accessibility target: WCAG 2.2 AA. Keyboard navigable, visible focus ring, skip
link, `lang` set per locale, and code blocks in other locales marked `lang="en"`.

## 9. What to read first

From the repository (`github.com/MarcoTribuz/FreeDocs`):

- `README.md` — the positioning, the demo, the numbers, the limits. The site is
  this page, expanded and translated. Also `README.it.md`, `README.de.md`,
  `README.fr.md` for terminology.
- `SECURITY.md` — the threat model, in the words that are safe to repeat.
- `docs/architecture.md`, `docs/hidden-content.md`, `docs/benchmark.md`,
  `docs/scanned-pdfs.md`, `docs/restore.md`, `docs/terms.md` — the "How it works"
  page links to these.
- `docs/packaging.md`, `docs/portable.md`, `docs/intune.md`, `docs/building.md`
  — the download page.
- `assets/brand/` and `app/src/app.css` — the visual identity.
- The GitHub releases page — asset names and `SHA256SUMS`.

## 10. Deliverables and done

A separate repository (proposed name `freedocs-site`) containing:

1. `cms/` — Strapi v5 project with the content types above, i18n configured for
   four locales, roles locked down (public role: read-only on published content,
   no access to admin, users or upload management), a `docker-compose.yml` with
   PostgreSQL, and a seed script that loads the current README content into
   English entries.
2. `web/` — the Astro site: every page in §6, all four locales, both themes,
   built statically from Strapi.
3. `scripts/import-release` — GitHub release → Strapi `release` entry.
4. A `README.md` saying how to run both locally, how to deploy, and how the
   publish webhook triggers a rebuild.

Done means:

- `astro build` produces a site with **zero** requests to any origin but its own
  (check the network tab on every page).
- Every figure on the site equals the README's, and comes from the `benchmark`
  single type.
- Every page exists in en/it/de/fr, and a missing translation falls back to
  English visibly rather than showing an empty block.
- Lighthouse accessibility 100 on Home and Download, both themes.
- No sentence anywhere claims a guarantee, compliance or a platform status the
  repository does not state.
- The download page shows a SHA-256 next to every file and the unsigned-app
  instructions for each OS.

## 11. Open questions for the maintainer

Ask these before building; do not assume.

1. **Domain** — which one, and is it already registered?
2. **Hosting** — static host for the site (Cloudflare Pages, Netlify, own
   server?) and where Strapi runs (own VPS, Strapi Cloud?). Swiss/EU hosting
   preferred for a privacy product?
3. **Analytics** — none (recommended), or self-hosted cookieless?
4. **Imprint** — legal entity, address and contact to publish.
5. **Contact** — an email address for the site, or GitHub issues only?
6. **Blog/news** beyond the changelog — wanted, or not for now?
7. **Donations or commercial support** — anything to mention (GitHub Sponsors,
   paid support), or nothing?

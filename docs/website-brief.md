# Website brief: the FreeDocs site on Strapi and Astro

This is the complete brief for whoever builds the FreeDocs website — written to
be handed, whole, to another Claude instance as its starting context. It says
what the product is and for whom, what the site must and must not claim, how it
is positioned, what each page says, how it is found, how it is launched, how the
content is modelled in Strapi, and when the work is done. Where a decision
belongs to the maintainer it is listed under *Open questions* (§19) rather than
guessed.

Read the sources in *What to read first* (§18) before writing anything. The
site's whole credibility is that it says no more than the repository can prove.

**How to read the markers in this document**

| Marker | Meaning |
|---|---|
| *(src: `path`)* | The claim is taken from that file in the repository. Every product fact on the site needs one. |
| **[ASSUMPTION]** | A judgement made for this brief and not in the repository. Validate before relying on it. |
| **[HYPOTHESIS]** | A keyword, channel or audience guess to be checked with a tool or a test. |
| **[MAINTAINER]** | Content or a decision only the maintainer can supply. |

**Repository state when this brief was written (2026-10-12)** — verify again
before building, because several sections depend on it:

- `CHANGELOG.md` records **1.0.0 on 2026-10-12**, but `gh release list` returns
  **no published GitHub release**. The README still says "There is no signed
  release to download yet." *(src: `README.md`, `CHANGELOG.md`)*
- The GitHub repository has **no description, no topics, no homepage URL, zero
  stars, and Discussions disabled**. Those are launch prerequisites (§15.1), not
  site work, but the site's metrics and links depend on them.
- Two screenshots exist and can be reused: `docs/images/review.png` and
  `docs/images/result.png`. The social image `assets/brand/social-preview.png` is
  1280×640.

---

## Contents

1. The product in one paragraph
2. What the site is for, and how success is measured
3. Rules the content must obey (claims policy)
4. Positioning
5. Audiences: personas, jobs to be done, use cases
6. Competitive alternatives and differentiation
7. Messaging: message house, headlines, tone, vocabulary
8. Languages
9. Architecture and hosting properties
10. Information architecture and URLs
11. Page-by-page content and wireframes
12. SEO
13. Accessibility and performance
14. Visual design
15. Launch, channels and community
16. Content model in Strapi
17. Editorial workflow and content-entry guidelines
18. What to read first
19. Deliverables and definition of done
20. Open questions for the maintainer

---

## 1. The product in one paragraph

FreeDocs takes the confidential data out of a document before an AI ever sees
it. PDF, Word, Excel, PowerPoint and scans go in; the same file type comes out,
still formatted, with names, IBANs, tax numbers, addresses and the rest replaced
by placeholders such as `[PERSON_1]`. It runs entirely on the user's machine — no
cloud, no processor, no API key, no telemetry, no account — and the engine
refuses outbound network connections while it works. It is open source under
AGPL-3.0-or-later. It has a desktop app (macOS, Windows, Linux) and a CLI.
*(src: `README.md` hero and "What you get")*

What sets it apart, in the repository's own terms:

- **Same format back, still formatted** — write-back edits Word runs and the PDF
  content stream instead of flattening to text. *(src: `README.md`)*
- **Hidden copies removed** — pivot caches, chart caches, tracked deletions,
  speaker notes, thumbnails of the unredacted page, embedded workbooks.
  *(src: `README.md`, `docs/hidden-content.md`)*
- **A verification stage that can fail** — the output is re-read and searched for
  every removed value; a survivor means nothing is written. *(src: `README.md`)*
- **Measured, not promised** — `freedocs benchmark` scores detection against an
  annotated corpus in four languages. *(src: `docs/benchmark.md`)*
- **Twelve countries** of checksum-confirmed identifiers (ch, it, de, at, fr, be,
  es, pt, nl, pl, se, gb) and a language model reading it/de/fr/en.
  *(src: `README.md` "What it finds")*
- **Irreversible by default**; an opt-in encrypted key file can restore the values
  into whatever the AI returns. *(src: `README.md`, `docs/restore.md`)*
- **A compatibility promise from 1.0** — CLI commands, flags and exit codes, the
  placeholder shape, the `.fdmap`/`.fdterms` files and the JSON report are stable
  across 1.x. *(src: `CHANGELOG.md` "What 1.0 commits to")*

Two facts that bound the "offline" claim and must travel with it:

- An **installer build downloads the model weights (~1.2 GB) once, on first
  use**; that fetch is the engine's one named network exception. The **portable
  bundle** carries the model inside and needs no network at all (1405 MB).
  *(src: `SECURITY.md` threat model, `README.md` "Desktop app", `docs/portable.md`)*
- The egress block **stops the accidental call, not hostile code** — C extensions
  can open sockets without going through Python. *(src: `SECURITY.md`)*

---

## 2. What the site is for, and how success is measured

### 2.1 Jobs, in order of importance

1. **Explain in thirty seconds** what it does and for whom, with one real
   before/after example.
2. **Get the right installer onto the right machine**, with checksums and honest
   instructions for an unsigned app — or, while no release is published, an
   honest "build from source" path (§11.3).
3. **Earn trust** with the measured numbers, the "what it does not do" list, the
   security review and the source.
4. **Say what changed** — release notes per version.
5. **Be found** by people searching, in four languages, for a way to strip
   confidential data from a document before an AI sees it (§12).

It is **not** a documentation site. The deep documentation lives in the
repository's `docs/` and the site links to it on GitHub rather than copying it:
a measurement duplicated is a measurement that disagrees with itself after the
next benchmark run. That rule is the repository's own (see `CLAUDE.md`, the
paragraph on `README.md`).

### 2.2 The conversion path

There is no signup, no email capture and no account, and there must not be:
collecting a visitor's address would contradict the product. The site has two
conversions.

| Conversion | Where it happens | Measured by |
|---|---|---|
| **Primary: download** | Download page → GitHub release asset | GitHub release asset `download_count` per asset |
| **Secondary: source engagement** | "View source" → GitHub repository | Stars, forks, watchers, issues and (if enabled) discussions |

Every page has exactly one primary CTA (§11), and it points down this path.

### 2.3 Success metrics measurable without trackers

The site carries no analytics script and sets no cookie (§9). Everything below
is read from systems that already exist, at build time or by hand, and none of
it adds a request to the visitor's browser.

| KPI | Source | How to read it | Notes |
|---|---|---|---|
| Downloads per release, per platform | GitHub REST `GET /repos/{owner}/{repo}/releases` → `assets[].download_count` | Script in the site repo, run on release and weekly; optionally shown on the Download page at build time | The north-star metric. Split by platform tells you whether the "built, not launched" platforms are being used. |
| Portable vs installer share | Same, by asset kind | Same | Tells you whether offline-first users exist in number. |
| Stars, forks, watchers | `GET /repos/{owner}/{repo}` | Weekly log | Lagging awareness signal; spikes map to launches. |
| Referring sites and popular paths into GitHub | GitHub Traffic API (`/traffic/views`, `/traffic/popular/referrers`) | Needs push access; **only 14 days of history**, so archive weekly | The only referral data available without tracking the site. |
| Issues opened (bug / feature), time to first response | GitHub issues | Monthly | Product-market signal; a bug from a Windows or Linux user is also the first evidence those builds work. |
| Search impressions, clicks, queries, per locale | Google Search Console and Bing Webmaster Tools, verified by **DNS TXT record** | Monthly | No script on the page. **[MAINTAINER]** decides whether using Google's console at all is acceptable — open question 3. |
| Inbound links and mentions | Search Console links report; manual search for "FreeDocs" + each channel | Monthly | Includes AI-assistant answers (§12.11). |
| Content freshness | `benchmark.measured_on` vs latest `freedocs benchmark` run | On every release | A stale figure is a defect, not a metric. |

Not a KPI: page views, bounce rate, time on page, conversion funnels. They need
either tracking or server logs, and the brief does not assume either. If the
maintainer wants aggregate page counts, the only acceptable forms are listed in
open question 3.

**[ASSUMPTION]** Targets are not set here: there is no baseline (zero stars, no
published release). Record the first 30 days after the first published release
as the baseline and set targets from it.

---

## 3. Rules the content must obey (claims policy)

These are not style preferences. Each one is a claim the project has decided it
cannot make, and the site breaking one would be the site lying for the product.

- **Never claim the output is guaranteed clean, compliant or "100% safe".** The
  report itself carries caveats (`report.CAVEATS` in
  `engine/freedocs/report.py`, the last of which is "Review the output before
  sending it anywhere."). Use "removes", "finds", "verifies" — never
  "guarantees", "ensures compliance", "GDPR-compliant". *(src: `CLAUDE.md`
  Conventions: "Never claim the output is guaranteed clean.")*
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
- **"Offline" travels with its one exception** (§1): the installer build fetches
  the model once on first use; the portable bundle does not.
- **The egress block is described at its real strength**: it stops the accidental
  call, not hostile code. *(src: `SECURITY.md`)*

### 3.1 Forbidden claims and words

| Never write | Why | Write instead |
|---|---|---|
| "guaranteed", "100% safe", "fully anonymous", "zero risk" | The tool states it misses some entities and that re-identification remains possible *(src: `report.CAVEATS`)* | "removes", "finds", "verifies the output and refuses to write it if a removed value survived" |
| "GDPR-compliant", "nDSG/revDSG-compliant", "HIPAA-compliant", "makes you compliant" | Compliance is a property of a process, not a tool; the README says "It is not a compliance guarantee" | "keeps the document on your machine, so FreeDocs itself is not a processor of it" — and, on legal pages, "this is not legal advice" |
| "anonymised" as an unqualified promise in a headline | Legally loaded; the README's own list says re-identification risk is not eliminated | "takes the confidential data out"; use "anonymise" in body/SEO copy with the caveat nearby (§12.2) |
| "military-grade", "bank-grade", "unbreakable" | Unmeasured | Name the actual mechanism: "scrypt, then AES-256-GCM" for the key file *(src: `SECURITY.md`)* |
| "AI-powered redaction", "smart", "magic" | Vague, and the model is one of three layers that the checksums audit | "checksums first, then a multilingual language model, then the checksums audit the model" *(src: `README.md` "How it decides")* |
| "black out", "censor", images of black bars | That is the overlay redaction FreeDocs replaces *(src: `assets/brand/README.md`)* | "replaced by a placeholder", "removed from the file" |
| "works on Windows/Linux" | Not launched by the maintainer | "built for Windows/Linux; not yet launched by the maintainer" |
| "trusted by", "used by thousands", "#1" | No evidence | Nothing. Leave the space empty. |
| "detects health data / religion / nationality" | It does not *(src: `report.CAVEATS`)* | State the gap in the FAQ |
| "works with ChatGPT/Claude/Copilot" as an integration | It never talks to the model *(src: `README.md` "What it does not do")* | "you paste the scrubbed copy into whichever assistant you use" |
| Exclamation marks | Brand tone *(src: §14)* | Full stops |

### 3.2 Permitted claims and the evidence each must cite

Each claim may appear on the site only with its source linked or, for figures,
pulled from the `benchmark` single type.

| Claim (canonical English) | Evidence to cite / link |
|---|---|
| "99.6% of removable entities fully removed, at 2.2% over-redaction (exact micro-F1 0.929), on 537 annotated entities in four languages — a small, synthetic corpus." | `docs/benchmark.md`, `README.md` "Measured, not promised"; values from `benchmark` |
| "Checksums only: 70.3% / 1.1% / 0.738. Language model only: 86.6% / 1.7% / 0.793." (for the "why layers" table) | Same |
| "Place names are the weakest category: 94.3% coverage, against 100% for people." | `README.md` "What it does not do", `docs/benchmark.md` per-entity table |
| "Re-opens what it wrote and fails the run if a single removed value survived." | `README.md` "What you get", `docs/architecture.md` |
| "Same file type back, still formatted." | `README.md`, `docs/architecture.md` |
| "Removes the copies you did not know were there" + the list | `docs/hidden-content.md` |
| "Checksum-confirmed identifiers for twelve countries, forty rules." | `README.md` "What it finds"; `freedocs countries` |
| "Reads Italian, German, French and English with one model and no language hint." | `README.md` |
| "No cloud, no processor, no API key, no telemetry, no account." | `README.md` hero |
| "The engine blocks outbound connections to anything but this machine — it stops the accidental call, not hostile code." | `SECURITY.md` |
| "Irreversible by default; an encrypted key file only if you ask." | `README.md`, `docs/restore.md`, `SECURITY.md` |
| "Open source, AGPL-3.0-or-later." | `LICENSE`, `README.md` "Licence" |
| "Stable CLI, placeholders, key file and report across 1.x." | `CHANGELOG.md` |
| "An MSI for Intune deployment" — always with "not yet run end to end" | `docs/intune.md` |
| "Presidio was measured at 21.5% over-redaction" — only inside the README's comparison table, with "on an earlier, 103-entity corpus" | `README.md` "Why another one of these", `docs/benchmark.md` "Presidio" (which warns against quoting it beside the current numbers) |

---

## 4. Positioning

### 4.1 Positioning statement

> For **professionals in Swiss and European organisations who must hand a
> document to an AI but are not allowed to hand over its data** — lawyers,
> fiduciaries, HR and compliance teams — **FreeDocs is a desktop tool that takes
> the confidential data out of the document on their own machine** and gives the
> same file back, still formatted. **Unlike** cloud masking services, which see
> the document before the model does, and **unlike** text-only or overlay
> redaction tools, FreeDocs **sends the document nowhere, edits the file in
> place including its hidden copies, and refuses to write an output in which a
> removed value survived** — with its detection rate measured and published,
> and its limits listed beside it.

### 4.2 Category ("the shelf")

People will not search for "FreeDocs". They search for the task. The site should
sit on three shelves, in this order **[HYPOTHESIS]**:

1. **Document anonymisation / redaction before AI** — "anonymise a PDF before
   ChatGPT", "Dokumente anonymisieren für KI".
2. **Offline / local redaction software** — "redact documents offline",
   "PII redaction desktop app".
3. **Open-source PII detection** — the developer shelf where Presidio lives.

### 4.3 One-liners (approved)

- **Tagline:** "Take the confidential data out of a document before an AI ever
  sees it." *(src: `README.md` hero — canonical; translations in §7.2)*
- **Descriptor (≤ 60 characters, for titles):** "Offline document redaction for AI"
  **[ASSUMPTION]**
- **Elevator (one sentence):** "FreeDocs replaces the names, IBANs, tax numbers
  and addresses in a PDF, Word, Excel or PowerPoint file with placeholders, on
  your own machine, and checks its own output before writing it."

---

## 5. Audiences: personas, jobs to be done, use cases

The original brief's audience stands: people who must hand a document to an AI
and are not allowed to hand over its data — law firms, fiduciaries and
accountants, HR, compliance and IT in Swiss and European SMEs; many are not
developers; IT departments deploying centrally are a second audience.

The personas below are **[ASSUMPTION]** archetypes built from that audience and
from what the product actually does. No user research exists; treat them as
hypotheses to be revised by the first issues and conversations (§15.6).

### 5.1 Personas

| Persona | Role and setting | Wants | Fears | Fit | What the site must show them |
|---|---|---|---|---|---|
| **Avv. Chiara — the lawyer** | Partner or associate, small firm, Ticino/Lombardy or Zurich; works in Italian, German, English | Ask an AI to summarise or compare contracts, draft from precedents | Breaching professional secrecy; a cloud vendor seeing client files; a missed name | **Strong.** Contracts are prose with names, addresses, companies, IBANs; jurisdiction clauses are handled *(src: README demo, `docs/architecture.md` suppression)* | The before/after with the jurisdiction row; "nobody in between"; the verification line; the "does not do" list |
| **Markus — the fiduciary / accountant** | Treuhänder or commercialista; spreadsheets, statements, payroll, VAT | Use an AI on workbooks and financial PDFs | IBAN, AHV, VAT and tax numbers leaking; pivot caches keeping data; formulas breaking | **Strong.** Checksum-confirmed identifiers for CH/IT/DE and nine more; pivot and chart caches redacted in place *(src: `README.md`, `docs/hidden-content.md`)* — but renamed sheets break formula references *(src: README "does not do")* | The twelve countries; the xlsx hidden-copy list; the sheet-rename caveat stated plainly |
| **Sophie — HR** | HR generalist, mid-size employer, Romandy/France | Have an AI screen or summarise CVs, contracts, review notes | Employee data leaking; being blamed for a tool choice | **Good, with a stated gap.** Names, contacts, addresses, IDs go; job titles, dates and ages are flagged, not removed; nationality, religion and political affiliation are **not detected** *(src: `README.md`, `report.CAVEATS`)* | Use-case page that says exactly that; the quasi-identifier explanation |
| **Thomas — compliance officer / DPO** | Evaluates tools for the whole firm; not the daily user | A tool he can approve without a processing agreement; evidence, not promises | Approving something that claims too much; data leaving the network | **Strong as evaluator.** Threat model, security review, egress block, report with no values, benchmark *(src: `SECURITY.md`, `docs/security-review.md`)* | Security page; "what it does not protect against"; benchmark methodology; the report caveats verbatim |
| **Ana — IT administrator** | Deploys software for 20–200 seats, often via Intune | Package, verify and roll out; know what it phones home to | Unsigned binaries; unknown network traffic; per-user installs | **Partial today.** MSI for Intune exists but is not yet run end to end; installers unsigned; SBOM and SHA256SUMS provided *(src: `docs/intune.md`, `CLAUDE.md` packaging)* | IT box on Download; checksum and SBOM verification steps; `freedocs doctor`; honest Windows status |
| **Luca — the developer / power user** | Engineer or technical consultant | Script redaction in a pipeline; inspect results as JSON; reproduce the benchmark | Black boxes; unstable interfaces | **Strong.** CLI with stable commands, flags and exit codes across 1.x; JSON report; `benchmark`; restore path *(src: `CHANGELOG.md`, `docs/cli.md`)* | CLI transcript; link to `docs/cli.md`; compatibility promise; source |
| **Healthcare administrator** | Practice or clinic admin | Use an AI on letters and forms | Patient data leaking | **Weak — do not target in v1.** Names, addresses, IDs (e.g. AHV) are removed, but **there is no entity type for diagnoses or other clinical content** (`README.md` entity list), and special categories are not detected | No dedicated page. One FAQ entry stating the gap. |

**Anti-personas** — who the site should not court, and should say so where it
matters:

- Anyone who needs a **compliance guarantee** or certified de-identification
  (e.g. HIPAA Safe Harbor, court-certified redaction).
- **US-centric** identifier workflows: SSN and EIN carry no check digit, so they
  come from the model or not at all *(src: `README.md` "What it finds")*.
- Users on **Intel Macs** (no build) *(src: `README.md` "Known gaps")*.
- Anyone wanting a **hosted API** or browser tool — the premise is the opposite.
- Anyone wanting FreeDocs to **talk to the AI for them** *(src: README "does not do")*.

### 5.2 Jobs to be done

| # | Job statement | Persona(s) | Product answer *(src)* |
|---|---|---|---|
| J1 | When I need an AI's help with a client document, I want to remove what identifies the client, so I can use the AI without breaching confidentiality. | Lawyer, fiduciary, HR | Scrub with placeholders, same format back *(README)* |
| J2 | When I hand over a scrubbed file, I want to be sure nothing slipped through in places I cannot see, so a nearly-clean file does not get sent. | All | Hidden-content removal + stage 6 verification *(README, `docs/hidden-content.md`)* |
| J3 | When the AI answers with placeholders, I want the real values back in its answer, so I can use the result directly. | Lawyer, fiduciary | Opt-in `--map` key file + `freedocs restore` *(`docs/restore.md`)* |
| J4 | When I approve a tool for the firm, I want evidence of what it does and does not do, so I can defend the decision. | Compliance, IT | Threat model, security review, benchmark, caveats *(SECURITY.md, docs)* |
| J5 | When the same client names appear in every file, I want them removed every time without retyping, so nothing depends on the detector's luck. | Fiduciary, lawyer | Encrypted term list `.fdterms` *(`docs/terms.md`)* |
| J6 | When I roll a tool out to many machines, I want a package I can verify and deploy centrally. | IT | MSI for Intune, SHA256SUMS, SBOM *(`docs/intune.md`, `CLAUDE.md`)* |
| J7 | When I need to paste a paragraph rather than a file, I want it cleaned without writing anything to disk. | All | Pasted text mode *(`CHANGELOG.md` 0.2.0)* |

### 5.3 Switching forces (JTBD four forces)

| Force | Content |
|---|---|
| **Push** (away from today) | Manually deleting names in Word before pasting; a firm rule "no client documents in AI"; a cloud masking service needing a DPA; overlay redaction that leaves text selectable |
| **Pull** (towards FreeDocs) | Nothing leaves the machine; formatting survives; it checks itself; the numbers are published; free and open source |
| **Habit** (keeps them stuck) | "We just don't use AI for client work"; manual search-and-replace; trust in a known vendor |
| **Anxiety** (about switching) | "What if it misses something?" → verification + the honest list + "review the output". "Unsigned app?" → checksums + SBOM + source. "One maintainer?" → open source, AGPL, public security review. "Is it really offline?" → egress block, portable bundle, `freedocs doctor` |

### 5.4 Key use cases (for use-case pages and FAQ)

Each is phrased as something the product verifiably does; the right column is
what may not be implied.

| Use case | Formats | What happens *(src)* | Do not imply |
|---|---|---|---|
| Summarise or review a contract with an AI | docx, PDF | Names, companies, addresses, IBANs, IDs replaced; a jurisdiction city kept *(README demo)* | That the AI's legal output is correct |
| Analyse a spreadsheet or financial statement | xlsx, PDF | Identifiers checksum-confirmed; pivot/chart caches redacted in place; renamed sheets reported *(README, `docs/hidden-content.md`)* | That formulas referring to renamed sheets keep working |
| Share a slide deck with an AI | pptx | Speaker notes, hidden slides, off-canvas shapes and the workbook inside a chart handled *(README)* | — |
| Clean a scanned document | scanned PDF | OCR then redaction to the pixels; every machine-read page named in a warning *(`docs/scanned-pdfs.md`)* | That OCR reads every character correctly |
| Put real values back into the AI's answer | all | `--map` + `restore`; off by default *(`docs/restore.md`)* | That restore is lossless on spelling, or reliable on PDF (it is the weak format) |
| Remove a firm's client list from every file | all | `.fdterms` term list *(`docs/terms.md`)* | A "never redact" list — there deliberately is none |
| Second opinion on residual risk | all | Opt-in local Ollama review, advisory, never edits *(`docs/llm-review.md`)* | That the review is a detector |

### 5.5 Value proposition per persona

| Persona | Value proposition (English canonical) | Proof to show |
|---|---|---|
| Lawyer | "Ask an AI about a contract without handing it your client." | Before/after table; "nobody in between"; verification line |
| Fiduciary | "IBANs, VAT and tax numbers confirmed by their check digits — and removed from the pivot cache too." | Twelve countries; xlsx hidden-copy list |
| HR | "Names, contacts and IDs out of a CV before an AI reads it — and the job titles and dates flagged for you to judge." | Removed vs flagged table |
| Compliance | "A tool that tells you what it cannot do." | "Does not do" list; `report.CAVEATS`; security review |
| IT | "One MSI, checksums and an SBOM, and an engine that refuses to phone home." | IT box; `SHA256SUMS`; egress statement at its real strength |
| Developer | "A CLI with stable exit codes, a JSON report with no values in it, and a benchmark you can re-run." | CLI transcript; `CHANGELOG.md` 1.0 promise |

---

## 6. Competitive alternatives and differentiation

### 6.1 The alternatives a visitor actually weighs

| Alternative | Type | Where it falls short for this audience | FreeDocs answer | Source |
|---|---|---|---|---|
| **Doing nothing / not using AI** | Status quo | Forgoes the tool entirely | Makes the safe path possible | — |
| **Manual search-and-replace in Word** | Habit | Misses hidden copies (thumbnails, tracked changes, caches, metadata); slow; error-prone | Hidden-content removal + verification | `docs/hidden-content.md` |
| **Black rectangles over text / PDF overlay** | Indirect | Text stays selectable underneath | True content-stream redaction; full rewrite, never incremental save | `README.md`, `CLAUDE.md` invariants |
| **Cloud masking service** | Secondary | Receives the document before the model does → it is a data processor: DPA, sub-processor list, professional-secrecy question | Document goes nowhere | `README.md` "Nobody sits between you and the model" |
| **Open-source tools** named in the README | Direct | See table below | See table below | `README.md` "Why another one of these" |

### 6.2 Named open-source tools — exactly as the README names them

Reproduce **only** this table, linked to the README section, with no adjectives
added. **[ASSUMPTION]** Re-check each project's current formats before launch;
if a project has closed its gap, update the README first and the site second.

| Project | Formats | Detection | Gap (README wording) |
|---|---|---|---|
| rizzo-pii | txt, md, PDF | mmBERT + checksums, 22 Italian entities | no Office formats |
| A5-PII-Anonymizer | txt, docx, xlsx, csv, pdf | Piiranha ONNX | weak detector, no OCR, no pptx |
| phileas | pdf, docx, xlsx, csv, scans | regex + ML | no pptx |
| desktop-redactor | csv, json, txt | Presidio | no documents |
| Presidio | text, images, structured data | NLP + patterns | no language detection, so every language is merged: measured here at 21.5% over-redaction *(on an earlier 103-entity corpus — add this qualifier on the site, per `docs/benchmark.md`)* |

No "vs" or "alternative to X" landing pages in v1: they invite claims beyond the
README's single line per tool. Revisit only if a maintainer-approved comparison
exists (open question 9).

### 6.3 Differentiators, ranked by how hard they are to copy

1. **Verification that can fail the run** (stage 6) — most tools return output
   and stop.
2. **Format-preserving write-back including hidden copies** — the reason
   competitors emit plain text *(src: `CLAUDE.md` architecture)*.
3. **No intermediary** — local, egress-blocked.
4. **Published, re-runnable measurement with its caveat** — coverage and
   over-redaction, not just F1.
5. **Swiss/European identifier depth** — twelve countries, four languages, one
   model.
6. **Open source AGPL**, with a public security review.

---

## 7. Messaging

### 7.1 Message house

```
                 ┌──────────────────────────────────────────────────────────┐
  ROOF           │ Take the confidential data out of a document              │
  (umbrella)     │ before an AI ever sees it.                                │
                 └──────────────────────────────────────────────────────────┘
  PILLARS  ┌──────────────┬──────────────┬──────────────┬──────────────┐
           │ 1. Nobody in │ 2. The       │ 3. It checks │ 4. Measured, │
           │    between   │    document  │    its own   │    and honest│
           │              │    survives  │    work      │    about it  │
           ├──────────────┼──────────────┼──────────────┼──────────────┤
  PROOF    │ Runs on your │ Same format  │ Stage 6 re-  │ 99.6% / 2.2% │
           │ machine; no  │ back; runs,  │ opens the    │ / 0.929 on   │
           │ cloud, API   │ tables,      │ output and   │ 537 entities,│
           │ key, account,│ styles kept; │ searches for │ small and    │
           │ telemetry;   │ hidden       │ every removed│ synthetic;   │
           │ egress block │ copies       │ value; a     │ "what it does│
           │ (accidental  │ removed and  │ survivor →   │ not do" list │
           │ calls only)  │ named        │ nothing      │ published    │
           │              │              │ written      │              │
           └──────────────┴──────────────┴──────────────┴──────────────┘
  FOUNDATION   Open source, AGPL-3.0-or-later · public security review ·
               twelve countries, four languages · stable 1.x interfaces
```

Every page leads with one pillar (§11). Pillar 4 is the brand's distinctive
move: the limits are a feature, presented with the same weight as the
strengths.

### 7.2 Headline and subhead options

English is canonical. The Italian, German and French **primary** lines are the
existing README translations and are approved terminology; alternatives are for
the translator to adapt, not to translate word for word.

**Primary (approved, all locales)**

| Locale | Headline | Subhead |
|---|---|---|
| en | Take the confidential data out of a document before an AI ever sees it. | PDF, Word, Excel, PowerPoint and scans — in, redacted, and out in the same format. On your machine, with nobody in between. |
| it | Togli i dati riservati da un documento prima che un'AI li veda. | PDF, Word, Excel, PowerPoint e scansioni — entrano, escono ripuliti, nello stesso formato. Sulla tua macchina, senza nessuno in mezzo. |
| de | Vertrauliche Daten aus einem Dokument entfernen, bevor eine KI sie zu sehen bekommt. | PDF, Word, Excel, PowerPoint und Scans — rein, bereinigt, und im selben Format wieder heraus. Auf Ihrem Rechner, ohne jemanden dazwischen. |
| fr | Retirez les données confidentielles d'un document avant qu'une IA ne les voie. | PDF, Word, Excel, PowerPoint et numérisations — entrent, ressortent nettoyés, dans le même format. Sur votre machine, sans personne entre les deux. |

*(src: `README.md`, `README.it.md`, `README.de.md`, `README.fr.md` hero lines)*

**Alternatives for testing on use-case pages and launch posts** (English; each
annotated with its pillar). No A/B testing on the site itself — it would need
tracking. Use them as channel-specific headlines (§15) and compare channel
results instead.

| # | Headline | Pillar | Rationale |
|---|---|---|---|
| A | Use AI on client documents without handing over the client. | 1 | Outcome-first; strongest for lawyers and fiduciaries |
| B | Redacted, verified, and still a Word file. | 2+3 | Concrete; differentiates from text-only tools |
| C | A redaction tool that fails loudly. | 3 | Memorable for technical audiences (Show HN) |
| D | 99.6% removed. Here is the 0.4% we miss, and why. | 4 | Honesty as hook; must link the benchmark and the caveat |
| E | Nothing to sign, because the document goes nowhere. | 1 | Speaks to the DPA/processor pain *(src: README)*; avoid implying legal advice |

**Translation notes**

- German uses **Sie**, Italian uses **tu**, French uses **vous** — as the
  READMEs do. Keep it consistent across every page.
- "AI": Italian keeps **AI** (the README's choice, not "IA"); German uses
  **KI**; French uses **IA**.
- "Processor": the READMEs render it as "intermediario" (it),
  "Auftragsverarbeiter" (de), "sous-traitant" (fr). Use these — they are the
  legal terms the audience recognises.
- Placeholders (`[PERSON_1]`), entity names, CLI output and error messages are
  never translated (§8).
- Headlines may be shortened per locale for length; the meaning may not shift
  toward a guarantee. German runs ~30% longer — design for it.

### 7.3 CTAs

| CTA | Text (en) | Where | Notes |
|---|---|---|---|
| Primary | **Download for {OS}** (falls back to **Download**) | Header button, hero, page ends | Before a release exists: **Build from source** |
| Secondary | **View the source** | Hero, footer | Links to the repository |
| Trust | **See what it does not do** | Home, Security | Anchors to the limitations list |
| Proof | **Re-run the benchmark** | Benchmark | Links to `docs/benchmark.md` |
| IT | **Deploy with Intune** | Download IT box | Links to `docs/intune.md` |
| Contribute | **Report a problem — never attach a real document** | About, footer | Links to issue templates |

Avoid "Get started", "Learn more", "Try it free" (there is nothing to sign up
for and it is always free).

### 7.4 Tone of voice

The README is the model *(src: `README.md`; brief §14)*.

| Is | Is not |
|---|---|
| Calm, factual, precise | Excited, salesy |
| Short declarative sentences | Long qualifier chains |
| Specific: names the mechanism, the number and its caveat | Vague benefit language ("streamline", "seamless") |
| Candid about limits, in the same breath as strengths | Defensive, or hiding limits in a footnote |
| Respectful of non-developers: explains, then links to depth | Jargon-first |

Three rules of thumb: a number never appears without what it was measured on; a
strength never appears on a page that does not link to the limitations; every
"we remove" is backed by "and we check".

### 7.5 Vocabulary

| Use | Avoid |
|---|---|
| remove, replace with a placeholder, take out | black out, censor, mask (ambiguous) |
| find, detect, flag (for quasi-identifiers) | catch everything |
| verify, re-open, search the output | guarantee, ensure |
| confidential data, identifying data | "sensitive data" as a legal term (GDPR special categories are not detected) |
| on your machine, nothing leaves it | "secure cloud", "private cloud" |
| measured, on a small synthetic corpus | proven, certified |
| open source (AGPL-3.0-or-later) | "free forever" as a promise beyond the licence |
| key file (opt-in) | "undo", "decrypt your document" |
| built (Windows/Linux) / verified (macOS arm64) | supports, works on |

### 7.6 Glossary for translators

| Term | Meaning | it / de / fr |
|---|---|---|
| placeholder | `[PERSON_1]`-style token that replaces a value | segnaposto / Platzhalter / espace réservé — take the term the READMEs use if it differs **[ASSUMPTION]** |
| scrub | the main command; "clean" in prose | — keep `scrub` in code |
| key file | encrypted `.fdmap` that can restore values | check `README.*.md` |
| term list | encrypted `.fdterms` of always-removed values | check `README.*.md` |
| over-redaction | characters removed that were not confidential | check `README.*.md` |
| coverage | share of gold entities fully removed | check `README.*.md` |
| flagged | reported, never removed (job title, date, age, postcode) | check `README.*.md` |

---

## 8. Languages

English is canonical; Italian, German and French follow — the same four as the
app's interface and the README.

- Use Strapi's i18n with locales `en` (default), `it`, `de`, `fr`.
- Marketing copy is translated. **Engine output is not**: CLI transcripts, entity
  names in code blocks (`PERSON`, `IBAN`) and error messages are quoted in
  English in every locale — the app's own rule is "if it came from an enum,
  translate it; if it came from an f-string, quote it". Mark those blocks
  `lang="en"`.
- Numbers are identical in every locale and formatted per locale with
  `Intl.NumberFormat` — `99.6%` in English, `99,6 %` in Italian, German and
  French. The value never differs; only its spelling does. (Check the exact
  spacing rule per locale against the README translations; French and German
  use a non-breaking space before `%`.)
- The existing READMEs (`README.it.md`, `README.de.md`, `README.fr.md`) are the
  reference translations for product terminology.
- A missing translation falls back to English **visibly** (a short notice in the
  reader's language), never an empty block. A fallback page carries
  `<link rel="canonical">` to the English page and is excluded from that locale's
  sitemap until translated (§12.4).
- **[ASSUMPTION]** Translations are done by a fluent human or reviewed by one.
  Machine translation without review is not acceptable for a product whose
  credibility is precision.

---

## 9. Architecture and hosting properties

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
  `entry.unpublish` triggers the static build and deploy (§16.6).
- **Release data at build time**: the build may also read the GitHub releases API
  (asset sizes, download counts) — still build-time only.
- **Hosting**: any static host (Cloudflare Pages, Netlify, or a plain nginx). The
  maintainer chooses — see *Open questions*.

Non-negotiable properties of the built site:

- No analytics by default. If the maintainer asks for any, it is self-hosted and
  cookieless (Umami or Plausible self-hosted), and the privacy page says so.
- No third-party requests at all: fonts self-hosted, no Google Fonts CDN, no
  embedded YouTube, no external scripts, no chat widgets, no external images, no
  badges from shields.io (render them as local SVG or text).
- Links *to* GitHub are navigation, not requests, and are fine.
- A strict Content-Security-Policy set by the host (§13.3). JSON-LD blocks are
  data, not script, and are not blocked by `script-src 'self'`; any inline
  bootstrap script (e.g. theme initialisation before paint) needs a `sha256-`
  hash in the CSP or moves to a same-origin file loaded in `<head>`.
- No cookie banner, because there are no cookies.
- Works without JavaScript for reading and downloading. JS is optional
  enhancement only (the theme toggle, OS detection on the download page, copy
  buttons for checksums).

---

## 10. Information architecture and URLs

### 10.1 Page hierarchy

```
/  (en, x-default)                 Home
├── /download/                     Download
├── /how-it-works/                 How it works
├── /benchmark/                    Measured, not promised
├── /security/                     Security & privacy
├── /limitations/                  What it does not do
├── /use-cases/                    Use cases (hub)            [phase 2]
│   ├── /use-cases/lawyers/
│   ├── /use-cases/fiduciaries/
│   ├── /use-cases/hr/
│   └── /use-cases/it-deployment/
├── /guides/                       Evergreen guides (hub)     [phase 2, open q. 6]
│   └── /guides/{slug}/
├── /faq/                          FAQ
├── /changelog/                    Changelog
│   └── /changelog/{version}/      One release, e.g. /changelog/1-0-0/
├── /press/                        Press kit
├── /about/                        About & contribute
├── /privacy/                      Privacy policy
└── /imprint/                      Imprint (Impressum)

/it/ … /de/ … /fr/ …               Same tree per locale, localised slugs
```

Changes against the original brief's page list, and why:

- **Benchmark** and **What it does not do** get their own pages. They are the
  trust pillar (§7.1), they are what a compliance evaluator links to, and each is
  a search landing page in its own right.
- **FAQ** is its own page (and FAQ blocks appear on Home and Download).
- **Press kit** is new (§15.5).
- **Use cases** and **Guides** are phase 2 — the site ships without them, and
  they are added when the maintainer has answered open question 6.

### 10.2 URL rules

- English at the root, other locales under a two-letter prefix: `/`, `/it/`,
  `/de/`, `/fr/`. **[ASSUMPTION]** English-at-root is chosen so the canonical
  language has the shortest URLs; the alternative (`/en/` prefix and a root
  language chooser) is worse for a no-JS site because the root would need a
  redirect or a chooser page.
- **Localised slugs**, stored per locale in Strapi (`slug` field): e.g.
  `/de/funktionsweise/`, `/it/come-funziona/`, `/fr/fonctionnement/`. They help
  local search and read naturally. Slugs are lowercase ASCII with hyphens,
  diacritics folded (`ueber`, not `über`; `securite`, not `sécurité`).
- Trailing slash on every path, enforced by the host with a 301.
- Never auto-redirect by `Accept-Language` or IP. Offer the language switcher;
  a redirect hides locales from crawlers and annoys the reader.
- Changelog version slugs replace dots with hyphens (`1-0-0`).
- A slug, once published, does not change. If it must, add a 301 in the host
  config in the same deploy.

**Proposed slug table [ASSUMPTION — translator to confirm]**

| Page | en | it | de | fr |
|---|---|---|---|---|
| Download | `download` | `scarica` | `herunterladen` | `telecharger` |
| How it works | `how-it-works` | `come-funziona` | `funktionsweise` | `fonctionnement` |
| Benchmark | `benchmark` | `benchmark` | `benchmark` | `benchmark` |
| Security | `security` | `sicurezza` | `sicherheit` | `securite` |
| Limitations | `limitations` | `limiti` | `grenzen` | `limites` |
| FAQ | `faq` | `faq` | `faq` | `faq` |
| Changelog | `changelog` | `changelog` | `changelog` | `changelog` |
| Press | `press` | `stampa` | `presse` | `presse` |
| About | `about` | `chi-siamo` | `ueber` | `a-propos` |
| Privacy | `privacy` | `privacy` | `datenschutz` | `confidentialite` |
| Imprint | `imprint` | `note-legali` | `impressum` | `mentions-legales` |

### 10.3 Navigation

- **Header** (in this order): logo → Home; How it works; Benchmark; Security;
  Changelog; **Download** (button, rightmost); GitHub icon link (with an
  accessible name); language switcher; theme toggle.
- **Footer**, four columns: *Product* (How it works, Benchmark, What it does not
  do, Changelog, Download) · *Trust* (Security, Security review on GitHub,
  Licence, SBOM/SHA256SUMS of the latest release) · *Project* (About, Press kit,
  Contributing, Report a vulnerability, GitHub) · *Legal* (Privacy, Imprint).
- **Language switcher** links to the *same page* in the other locale (from the
  hreflang set), labelled in each language's own name (English, Italiano,
  Deutsch, Français), never by flags.
- **Breadcrumbs** on depth ≥ 2 pages (changelog entries, use cases, guides).

### 10.4 Internal linking

| From | Must link to |
|---|---|
| Every page with a figure | `/benchmark/` and `/limitations/` |
| Home | Download, How it works, Benchmark, Limitations, Security |
| How it works | each relevant `docs/*.md` on GitHub; Benchmark; Limitations |
| Benchmark | `docs/benchmark.md`; Limitations; How it works (layers) |
| Security | `SECURITY.md`; `docs/security-review.md`; Limitations; Download (checksums) |
| Download | Security (verification); FAQ (unsigned app); `docs/intune.md`; `docs/portable.md` |
| Changelog entry | Download (if latest); GitHub release; relevant docs |
| Use case / guide | Download; Limitations; the one or two How-it-works sections it relies on |

Anchor text is descriptive ("what a document hides", not "click here"). No
orphan pages: the build fails if a published page has no inbound internal link
(§19).

---

## 11. Page-by-page content and wireframes

Each page lists its goal, the pillar it leads with, its sections in order, its
primary and secondary CTA, and the sources it draws from. Copy shown is the
English canonical draft and may be refined in the copy-editing pass; figures
are always pulled from `benchmark`.

### 11.1 Home

- **Goal:** explain in thirty seconds; send to Download.
- **Leads with:** pillar 1, then all four.
- **Primary CTA:** Download for {OS}. **Secondary:** View the source.

| # | Section | Content |
|---|---|---|
| 1 | **Hero** | Headline + subhead (§7.2). Line under the CTA: "Free and open source · AGPL-3.0 · macOS, Windows, Linux · no account". Image: `docs/images/review.png` with the README's caption reworded short. |
| 2 | **Before / after** | The README table, four rows, including the jurisdiction row, with the two-sentence explanation under it ("The city in the party's address is gone; the same city in the governing-law clause is untouched…" and the three-runs note). Link: "Reproduce it with the sample file" → `examples/offerta-esempio.docx`. |
| 3 | **What you get** (feature grid, five) | Same format back · The copies you did not know were there · A verification stage that can fail · Numbers you can re-run · Irreversible by default. One sentence each from the README, each linking to its doc. |
| 4 | **Nobody in between** | The README paragraph on processors, ending with the egress statement at its real strength and a link to Security. |
| 5 | **Measured, not promised** (stats block) | 99.6% · 2.2% · 0.929 · 537 entities / 4 languages. Caveat directly under the numbers, same font size as body: "The corpus is small and synthetic — these numbers rank configurations against each other and are not a published benchmark result." CTA: See the benchmark. |
| 6 | **What it does not do** (short) | Four of the eight points as one-liners (re-identification, OCR, place names, not a compliance guarantee) + "See all eight". |
| 7 | **What it finds** | Formats; removed vs flagged; twelve countries (country names as text, not flag emoji, for screen readers — flags may be decorative alongside); four languages. |
| 8 | **FAQ** (3–5 items) | From the FAQ collection, `topic = home`. |
| 9 | **Final CTA** | "Download" + "Read the security model". |

Wireframe (desktop; mobile stacks in the same order):

```
┌─────────────────────────────────────────────────────────────────┐
│ [FreeDocs]  How it works  Benchmark  Security  Changelog [Download] ⌥ EN ◐ │
├─────────────────────────────────────────────────────────────────┤
│  Take the confidential data out of a document     ┌───────────┐ │
│  before an AI ever sees it.                       │ review.png│ │
│  PDF, Word, Excel… On your machine…               │           │ │
│  [Download for macOS]  [View the source]          └───────────┘ │
│  Free · AGPL-3.0 · macOS, Windows, Linux · no account           │
├─────────────────────────────────────────────────────────────────┤
│  Before                         │ After                         │
│  Realise Consulting SA …        │ [ORGANISATION_1] …            │
│  …il foro competente è Zurigo.  │ …il foro competente è Zurigo. │
│  ↳ Why the last row matters (2 sentences)  · Try the sample file│
├─────────────────────────────────────────────────────────────────┤
│  ▢ Same format   ▢ Hidden copies   ▢ Verification   ▢ …         │
├─────────────────────────────────────────────────────────────────┤
│  99.6 %      2.2 %          0.929      537 / 4                  │
│  removed     over-redacted  F1         entities / languages     │
│  Small, synthetic corpus — ranks configurations, not a result.  │
├─────────────────────────────────────────────────────────────────┤
│  What it does not do  · · · ·            [See all eight →]      │
└─────────────────────────────────────────────────────────────────┘
```

### 11.2 How it works

- **Goal:** make the mechanism understandable to a non-developer and checkable
  by a developer.
- **Leads with:** pillars 2 and 3. **Primary CTA:** Download. **Secondary:**
  Read the architecture on GitHub.

Sections: (1) the six stages router → extract → detect → policy → write-back →
verify, as a horizontal step diagram with one plain sentence each
*(src: `docs/architecture.md`)*; (2) "Three layers, and the strict one gets the
last word" — checksums, the multilingual model, the checksums auditing the model,
plus the three corrective passes *(src: README "How it decides")*; (3) what a
document hides, per format *(src: `docs/hidden-content.md`)*; (4) scans: OCR and
redaction to the pixels, with the OCR caveat *(src: `docs/scanned-pdfs.md`)*; (5)
removed vs flagged, and why quasi-identifiers are flagged; (6) the opt-in extras:
key file and restore, term list, local LLM review, pasted text — each one
sentence and a doc link. Every section ends with "Read more on GitHub →".

### 11.3 Download

- **Goal:** the right file on the right machine, verified.
- **Leads with:** trust. **Primary CTA:** the platform's download button.

| # | Section | Content |
|---|---|---|
| 1 | Latest release header | Version, date, channel, link to its changelog entry. |
| 2 | Platform tabs (all visible without JS; JS only pre-selects) | Per asset: filename, size, SHA-256 (with copy button), status line — **"Verified on macOS arm64"** / **"Built, not yet launched by the maintainer"**. No Intel macOS: say so in the macOS tab. |
| 3 | Opening an unsigned app | Per OS, rich text from `download-page`: what warning appears and how to proceed. **[MAINTAINER]** supplies or approves the exact steps per OS version. |
| 4 | Verify what you downloaded | `shasum -a 256` / `Get-FileHash` / `sha256sum` commands (verbatim, `lang="en"`); link to `SHA256SUMS` and the SBOMs on the release. |
| 5 | Portable bundle | If the release has one: "Unzip and run, no installer, no network; the model is inside, so it is ~1.4 GB." *(src: `docs/portable.md`, README)* |
| 6 | For IT | Intune MSI as a Win32 app; "not yet run end to end" *(src: `docs/intune.md`)*; `freedocs doctor --strict`. |
| 7 | First run | Installer build downloads the model once (~1.2 GB); OCR needs Tesseract installed separately with language data *(src: `CLAUDE.md` OCR notes, `docs/scanned-pdfs.md`)*. |
| 8 | Command line | Build-from-source steps from the README Quickstart, verbatim. |
| 9 | FAQ (`topic = download`) | Unsigned app, Intel Mac, offline use, OCR. |

**State with no published release** (the state on 12 October 2026, before 1.0.1 was published): sections 1, 2, 4 and 5
are replaced by a single block: "There is no signed release to download yet. You
can build it from source today:" + the README Quickstart and app build commands
+ "Watch the repository to hear about the first release." The page must be
generated in both states from data — the presence of a `release` entry decides.

### 11.4 Benchmark

- **Goal:** make the numbers checkable; turn honesty into trust.
- **Leads with:** pillar 4. **Primary CTA:** Download. **Secondary:** Re-run the
  benchmark.

Sections: headline numbers with caveat; why coverage and over-redaction come
before F1 (README wording); the three-row layer table (+ the "as a scrub applies
it" row, labelled); per-entity highlights: LOCATION 94.3% and the two named
misses explained *(src: `docs/benchmark.md`)*; what the countries cost; Presidio
note exactly as `docs/benchmark.md` frames it; "Measured on {measured_on} with
engine {engine_version}"; how to reproduce (commands, verbatim). All values from
the `benchmark` single type and its `rows`.

### 11.5 Security & privacy

- **Goal:** let a compliance officer or IT admin approve it.
- **Leads with:** pillar 1. **Primary CTA:** Read the security review.
  **Secondary:** Download.

The threat model summary from `SECURITY.md`: nothing leaves the machine and how
that is enforced (and its limit); core dumps off; the mapping never reaches disk
unless asked for by name; the key file (scrypt + AES-256-GCM, 0600, refused
inside the output folder, no plaintext form, no passphrase argument); the report
carries counts and positions, never values; what it does *not* protect against
(`docs/security-review.md`, sandbox notes); how to report a vulnerability
(private reporting; never attach a real document). Link to
`docs/security-review.md`.

### 11.6 What it does not do

- **Goal:** publish the limits as a first-class page.
- **Leads with:** pillar 4. **Primary CTA:** Download (after reading).

All eight README points as `limitation` entries, each with a doc link, plus the
`report.CAVEATS` sentences quoted verbatim in English with `lang="en"` and one
line in the reader's language explaining that this is what the tool prints in
every report. Add the stated gaps from README "Known gaps" (no Intel macOS, no
signed release, no Tesseract binary in the portable bundle).

### 11.7 Changelog (index and entry)

Index: newest first, version, date, channel badge, highlights. Entry: notes
(localised), highlights, assets with checksums (if any), GitHub release link,
"Benchmark unchanged / changed" line where the release says so.

### 11.8 FAQ

Grouped by `topic`. Starter set — every answer must be traceable:

| Question | Answer source |
|---|---|
| Does my document leave my computer? | `SECURITY.md` threat model; README hero |
| Is it really offline? | §1 exception; `docs/portable.md` |
| Does it make me GDPR / nDSG compliant? | README "not a compliance guarantee"; answer: no tool does that by itself |
| What does it miss? | `/limitations/`, benchmark |
| Can I get the real names back in the AI's answer? | `docs/restore.md` |
| Which AI assistants does it work with? | README: you paste the copy into whichever you use |
| Why is the app unsigned, and is it safe to open? | Download page; checksums + SBOM |
| Does it work on Intel Macs? | README "Known gaps": no |
| Does it detect medical data, nationality or religion? | `report.CAVEATS`; entity list |
| Which countries' ID numbers does it confirm? | README "What it finds" |
| Why is the download so large? | Model + torch *(src: README "Known gaps", `docs/packaging.md`)* |
| Do I need Python? | Installer: no **[ASSUMPTION — confirm]**; CLI from source: yes, 3.10–3.12 *(src: README badge)* |
| How do I report a bug? | `CONTRIBUTING.md`, issue templates — never attach a real document |
| What does AGPL mean for my firm? | `LICENSE`; plain-language summary **[MAINTAINER]** approves, not legal advice |

### 11.9 Press kit

Boilerplate (50 and 150 words, all four locales), fact sheet (licence, platforms
with their status, formats, countries, languages, current version, benchmark
figures with caveat), logos (`mark.svg`, `mark-mono.svg`, both wordmarks,
`app-icon.svg`) with the brand rules from `assets/brand/README.md`, the two
screenshots, the social image, maintainer name and contact **[MAINTAINER]**, and
the explicit line "No customer names or user counts are published because none
are claimed."

### 11.10 About / Contribute

Who maintains it **[MAINTAINER]**, why it exists (README "Nobody sits between
you and the model"), the licence and why AGPL (PyMuPDF), how to contribute
(`CONTRIBUTING.md`), "never attach a real document", donations or support only if
open question 7 says so.

### 11.11 Privacy policy and Imprint

Privacy: "This site sets no cookies, loads nothing from any other origin and
runs no analytics" — true only while §9 holds; if any server log or analytics is
introduced, this page changes in the same deploy. Name the host and what logs it
keeps **[MAINTAINER]**. Imprint: legal entity, address, contact — required in
Switzerland and Germany **[MAINTAINER]**.

---

## 12. SEO

### 12.1 Strategy in one paragraph

Win the **task** queries ("anonymise a PDF before ChatGPT") in four languages
with a few strong, honest pages rather than many thin ones; win the **trust**
queries ("offline redaction open source", "is X safe") with the benchmark,
limitations and security pages; and let GitHub, the launch channels and the
README carry authority back to the site. No programmatic pages, no keyword
stuffing, no doorway pages per city or profession beyond the four real use
cases.

### 12.2 Keyword clusters **[HYPOTHESIS — validate every row with a keyword tool (volume, difficulty, SERP intent) per country before writing to it]**

Search markets: CH (de/fr/it), IT, DE, AT, FR, BE, plus English-language
global. Swiss German searchers use standard German spellings (`ss` for `ß`).

| Cluster / intent | en | it | de | fr | Target page |
|---|---|---|---|---|---|
| **Task: anonymise before AI** (transactional/informational) | anonymize document before ChatGPT; remove personal data before AI; redact PDF for ChatGPT | anonimizzare documenti per ChatGPT; anonimizzare PDF prima dell'AI; togliere dati personali documento AI | Dokumente anonymisieren KI; PDF anonymisieren ChatGPT; personenbezogene Daten entfernen KI | anonymiser documents IA; anonymiser PDF ChatGPT; supprimer données personnelles avant IA | Home; guide G1 |
| **Task: redact Office formats** | redact Word document; redact Excel personal data; redact PowerPoint | oscurare dati Word; anonimizzare Excel | Word Dokument schwärzen / anonymisieren; Excel anonymisieren | caviarder document Word; anonymiser Excel | How it works; guide G3 |
| **Offline / local** | offline redaction software; local PII redaction; redact documents without cloud | anonimizzazione offline; software anonimizzare documenti locale | Anonymisierung offline; Dokumente lokal anonymisieren ohne Cloud | anonymisation hors ligne; anonymiser sans cloud | Home; Security |
| **Open source / developer** | open source PII redaction; Presidio alternative; PII detection CLI | — | Open Source Anonymisierung | anonymisation open source | How it works; Benchmark |
| **Professional context** | AI confidentiality law firm; client data ChatGPT lawyer | segreto professionale AI avvocati; dati clienti ChatGPT commercialista | Berufsgeheimnis KI Anwalt; Mandantendaten ChatGPT Treuhand | secret professionnel IA avocat; données clients ChatGPT fiduciaire | Use cases (phase 2); guide G2 |
| **Hidden data** | hidden data in Word document; remove metadata PDF; Excel pivot cache personal data | dati nascosti documento Word; rimuovere metadati PDF | versteckte Daten Word; Metadaten entfernen PDF | données cachées Word; supprimer métadonnées PDF | How it works; guide G4 |
| **Trust / evaluation** | is it safe to upload documents to ChatGPT; anonymisation vs pseudonymisation | anonimizzazione vs pseudonimizzazione | Anonymisierung vs Pseudonymisierung | anonymisation vs pseudonymisation | Guides G2, G5 |
| **Identifiers** | redact IBAN; AHV number redaction | anonimizzare codice fiscale; IBAN | AHV-Nummer schwärzen; Steuernummer entfernen | numéro AVS caviarder | How it works (countries) |
| **Brand** | FreeDocs; FreeDocs download | — | — | — | Home, Download |

Watch-outs: "FreeDocs" may collide with other products or generic phrases
("free docs") — check the SERP and claim the brand query with the Home and
Download titles. "Caviarder" (fr) and "schwärzen" (de) mean blacking out, which
is not what FreeDocs does; target them only on pages that explain the
difference.

### 12.3 On-page templates

| Element | Template | Limit |
|---|---|---|
| `<title>` | `{Page title} — FreeDocs` ; Home: `FreeDocs — {descriptor}` | ≤ 60 characters, per locale |
| meta description | One sentence of value + one of proof or caveat | 140–160 characters |
| H1 | One per page, matches the page's main query in natural language | — |
| H2/H3 | Phrased as the questions people ask where natural ("Does my document leave my computer?") | — |
| Image `alt` | Describes what the screenshot shows (reuse README alt text) | — |

Examples (en) **[ASSUMPTION — copy-edit before use]**:

| Page | Title | Description |
|---|---|---|
| Home | FreeDocs — Offline document redaction for AI | Take names, IBANs and tax numbers out of PDF, Word, Excel and PowerPoint on your own machine, before an AI sees them. Open source. |
| Download | Download FreeDocs for macOS, Windows and Linux | Installers and a portable bundle, each with its SHA-256. Unsigned — here is how to verify and open them. |
| Benchmark | Benchmark: 99.6% removed, 2.2% over-redacted — FreeDocs | How FreeDocs is measured on 537 annotated entities in four languages, what it misses, and how to re-run it. |
| Limitations | What FreeDocs does not do | The honest list: re-identification risk, OCR misreads, place names that are surnames, and why it is not a compliance guarantee. |

Figures inside titles and descriptions must be generated from `benchmark`, not
typed.

### 12.4 hreflang, canonical, sitemap, robots

- Every page emits `<link rel="alternate" hreflang="…">` for each **published**
  locale version plus `hreflang="x-default"` pointing to English, all absolute
  URLs, reciprocal on every version. Use bare language codes (`de`, not
  `de-CH`) — one German version serves CH, DE and AT. **[ASSUMPTION]** If a
  Swiss-specific German variant is ever written, add `de-CH` then.
- `<link rel="canonical">` to itself on each localised page; fallback (untranslated)
  pages canonicalise to English and are omitted from that locale's hreflang set
  and sitemap.
- `<html lang="…">` per locale.
- `sitemap-index.xml` generated by the build (Astro sitemap integration) with
  `xhtml:link` alternates and `lastmod` from Strapi `updatedAt`.
- `robots.txt`: allow all; `Sitemap:` line; disallow nothing that is public.
  The AI-crawler policy is a maintainer decision (open question 10); the
  recommendation is to allow search/citation crawlers, because a product for
  people using AI benefits from being cited by AI.
- 404 page per locale with links to Home and Download; `noindex`.
- Strapi preview builds (if any) send `X-Robots-Tag: noindex`.

### 12.5 Structured data (JSON-LD, generated from Strapi data)

Only mark up what the page visibly shows. No `aggregateRating` or `review` —
there are none, and inventing them breaks §3.

| Page | Types |
|---|---|
| Every page | `WebSite` (name, url, inLanguage), `Organization` or `Person` as publisher (**[MAINTAINER]** — open question 4), `BreadcrumbList` on depth ≥ 2 |
| Home, Download | `SoftwareApplication` |
| FAQ, and pages with a FAQ block | `FAQPage` |
| Changelog entry | `TechArticle` or `BlogPosting` with `datePublished` |
| Guides | `Article` with author and `dateModified` |

`SoftwareApplication` fields: `name` "FreeDocs"; `applicationCategory`
`"SecurityApplication"` (or `BusinessApplication`); `operatingSystem` "macOS
(Apple silicon), Windows, Linux"; `softwareVersion` from the latest `release`;
`offers` `{ "@type": "Offer", "price": "0", "priceCurrency": "CHF" }`
**[ASSUMPTION: CHF vs EUR — either is valid for price 0]**; `license`
`https://www.gnu.org/licenses/agpl-3.0.html`; `downloadUrl` the Download page;
`codeRepository`/`sameAs` the GitHub URL; `image` the social preview;
`inLanguage` `["en","it","de","fr"]`.

Note: Google shows FAQ rich results only for a narrow set of authoritative sites
since 2023, so `FAQPage` is for other search and AI engines and for clarity, not
a promise of rich results. Validate everything with the Rich Results Test and
the schema.org validator.

### 12.6 Open Graph and social cards

- Default `og:image` and `twitter:image`: `assets/brand/social-preview.png`
  (1280×640, 2:1 — fine for `summary_large_image`), copied into the site's own
  `public/` (never hot-linked from GitHub).
- `og:title`, `og:description` from the SEO component; `og:locale` per locale
  (**[ASSUMPTION]** use `en_US`/`it_IT`/`de_DE`/`fr_FR` or
  `de_CH`/`fr_CH`/`it_CH` per the maintainer's market choice) and
  `og:locale:alternate` for the others; `og:type` `website` (`article` for
  changelog entries and guides); `twitter:card` `summary_large_image`.
- Per-locale social images are optional: the current PNG contains English text
  **[ASSUMPTION — check `social-preview.svg`]**. If localised versions are made,
  generate them from the SVG source per the brand rules.
- `og:image:alt` set on every page.

### 12.7 Content plan: evergreen guides (phase 2, open question 6)

Each guide answers one real question, links to the product only where it helps,
and states the limits. Written in English first, then translated — not
separate, keyword-chasing pages per locale. Dated, with "Last reviewed".

| # | Working title (en) | Primary cluster | Persona | Evidence it draws on |
|---|---|---|---|---|
| G1 | How to remove confidential data from a document before using ChatGPT, Claude or Copilot | Task | All | README, How it works |
| G2 | Anonymisation vs pseudonymisation: what changes when you keep a key | Trust | Compliance, lawyer | `SECURITY.md`, `docs/restore.md` — **legal review [MAINTAINER]** |
| G3 | What a Word, Excel or PowerPoint file hides, and why deleting the visible text is not enough | Hidden data | All | `docs/hidden-content.md` |
| G4 | Why black boxes on a PDF are not redaction | Hidden data / Office | Lawyer | `CLAUDE.md` invariant on overlays, `formats/pdf_text.py` reasoning |
| G5 | How to measure a redaction tool: coverage, over-redaction, and why F1 comes third | Trust / dev | Compliance, dev | `docs/benchmark.md` |
| G6 | Checksums for Swiss, Italian and German identifiers: why an AHV number or codice fiscale can be confirmed and a US SSN cannot | Identifiers | Fiduciary, dev | README "What it finds", `docs/benchmark.md` |
| G7 | Scanned documents and OCR: what can go wrong when redacting a scan | Task | All | `docs/scanned-pdfs.md` |
| G8 | Quasi-identifiers: why removing every name is not anonymisation | Trust | HR, compliance | README "does not do", `docs/llm-review.md` |

Cadence **[ASSUMPTION]**: one guide a month after launch, in four languages,
only if a translator is available; a guide that exists only in English is
published in English only (no fallback copies).

### 12.8 AI search and machine-readable files

FreeDocs' audience uses AI assistants; being cited correctly by them matters.

- Each key page opens with a self-contained 40–60-word answer paragraph that
  states what, for whom, and the main caveat — written for people first.
- Publish `/llms.txt` (English) per llmstxt.org: one paragraph of what FreeDocs
  is, the claims policy summary (what it does not claim), and links to Home,
  Download, How it works, Benchmark, Limitations, Security and the GitHub docs.
  Generated at build time from Strapi so its figures match.
- Comparison tables and the limitations list as real HTML tables and lists,
  not images.
- Freshness: show "Measured on" and "Last updated" dates.
- Monitor monthly by hand: ask ChatGPT, Perplexity, Gemini and Claude the
  top ten cluster queries per language; record whether FreeDocs is mentioned
  and whether the description is *accurate*. An inaccurate AI description
  (e.g. "guarantees GDPR compliance") is a defect to correct at the source
  pages.

### 12.9 Off-site SEO

The GitHub repository is the strongest asset: set its description, topics
(`redaction`, `anonymization`, `pii`, `gdpr`, `privacy`, `pdf`, `docx`, `xlsx`,
`pptx`, `offline`, `llm`, `tauri` **[ASSUMPTION]**) and homepage URL to the site;
link the site from the README hero. Directory listings (§15.3) and launch posts
provide the first links.

---

## 13. Accessibility and performance

### 13.1 Accessibility: WCAG 2.2 AA

Keyboard navigable, visible focus ring (the app's), skip link, `lang` set per
locale, and code blocks in other locales marked `lang="en"`. In addition:

- Landmarks (`header`, `nav`, `main`, `footer`), one H1, no skipped heading
  levels.
- Target size ≥ 24×24 CSS px (2.5.8); focus not obscured by sticky header
  (2.4.11).
- Tabs on Download are real buttons with `aria-selected` and work without JS
  (all panels visible as sections when JS is off).
- Before/after table is a real `<table>` with headers; placeholders in
  `<code>`.
- Country lists name countries in text; emoji flags only as `aria-hidden`
  decoration.
- Contrast taken from the app's measured tokens; no `opacity` for text.
- `prefers-reduced-motion` respected; no autoplay.
- Language switcher links carry `hreflang` and `lang` attributes.
- Checksums are selectable text, with a copy button that announces success via
  a polite live region.

### 13.2 Performance budgets (per page, mobile, throttled 4G)

| Metric | Budget |
|---|---|
| LCP | ≤ 1.5 s (Core Web Vitals "good" is 2.5 s; a static site should beat it) |
| CLS | ≤ 0.05 |
| INP | ≤ 100 ms |
| Total transfer, excluding the hero screenshot | ≤ 150 KB |
| JavaScript | ≤ 15 KB compressed, none render-blocking |
| CSS | ≤ 30 KB compressed, critical CSS inlined or one file |
| Images | AVIF/WebP with PNG fallback, `width`/`height` set, responsive `srcset`; hero image ≤ 120 KB at mobile width |
| Fonts | System stack (zero font bytes); if a webfont is added, one self-hosted WOFF2 subset ≤ 30 KB, `font-display: swap` |

### 13.3 Security headers (set by the host)

```
Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self';
  script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none';
  frame-ancestors 'none'; upgrade-insecure-requests
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()
X-Content-Type-Options: nosniff
Strict-Transport-Security: max-age=31536000; includeSubDomains
Cross-Origin-Opener-Policy: same-origin
```

Adjust only by adding hashes for any inline script (§9). Publish a
`/.well-known/security.txt` pointing to GitHub's private vulnerability
reporting.

---

## 14. Visual design

The brand already exists and must be used as is: **`assets/brand/` in the
repository**, with `assets/brand/README.md` as its rules.

- Logo: `wordmark-light.svg` / `wordmark-dark.svg` in the header, `mark.svg` for
  the favicon and small placements, `social-preview.png` as the default Open
  Graph image. Clear space at least the width of the folded corner; mark ≥ 16 px,
  wordmark ≥ 24 px tall.
- Colours are the app's tokens in `app/src/app.css`, each with its measured
  contrast ratio beside it. Copy the tokens, light and dark, rather than picking
  new shades. Accent `#22785c` (light) / `#3fbb92` (dark).
- Dark mode follows the OS and can be overridden, as the app does: a
  `data-theme` attribute and two token blocks, not a `prefers-color-scheme`
  duplicate of the palette.
- Secondary text is a colour, never an `opacity` — opacity cannot be measured for
  contrast.
- Type: the system UI stack for text (as the app), a monospace stack for
  placeholders and transcripts. If a webfont is wanted, self-host it. The
  wordmark is Helvetica Neue Bold live text in the SVG; for the site, inline the
  SVG as provided.
- The redaction bar in the mark is a placeholder, not a black censor's stroke.
  Do not illustrate the product with black bars over text — that is the overlay
  redaction FreeDocs exists to replace. Never recolour the bar red or black.
- Placeholders such as `[PERSON_1]` are the visual motif: monospace, accent tint
  background, as in the app's highlight layer.
- Calm, factual, generous whitespace. The README's tone is the model: short
  declarative sentences, numbers with their caveats, no exclamation marks.
- Screenshots: `docs/images/review.png` and `result.png`. The README notes the
  output path in `result.png` was painted over to avoid publishing a username —
  any new screenshot must get the same care.

---

## 15. Launch, channels and community

### 15.1 Readiness gate (before any public announcement)

The site can be built before these are done; it should not be *announced*
before them.

- [ ] A **published GitHub release** with installers, `SHA256SUMS` and SBOMs
      (today: none published). **[MAINTAINER]**
- [ ] README "Desktop app" section updated to point at the release and the site.
- [ ] Repository description, topics and homepage URL set.
- [ ] Decision on **GitHub Discussions** (today: disabled) — open question 8.
- [ ] Issue templates reviewed (they already exist: `bug_report.yml`,
      `feature_request.yml`) and carry the "never attach a real document" rule.
- [ ] Site live in four locales, all §19 checks green.
- [ ] Press kit page live.
- [ ] Imprint and privacy page live with maintainer-supplied details.
- [ ] At least one person other than the maintainer has installed from the
      release on Windows or Linux — or the "built, not launched" wording stays
      and launch copy leads with macOS and the CLI. **[ASSUMPTION]**

### 15.2 Sequencing **[ASSUMPTION]**

1. **Soft launch (week 0):** publish the release and the site; share with a few
   friendly professionals per persona; collect issues.
2. **Developer launch (week 1–2):** Show HN, relevant subreddits, GitHub
   visibility — the audience that will test Windows and Linux builds and
   scrutinise the claims.
3. **Professional launch (week 3–6):** LinkedIn in it/de/fr/en, legal-tech and
   fiduciary communities, privacy newsletters, Swiss/Italian professional
   associations.
4. **Ongoing:** every release is a small launch (§15.4).

### 15.3 Channels

| Channel | Audience | Angle / headline (§7.2) | Notes and rules |
|---|---|---|---|
| **GitHub** (owned) | Developers, evaluators | README is the landing page | Releases, topics, social preview uploaded under Settings → Social preview *(src: `assets/brand/README.md`)* |
| **Hacker News — Show HN** (rented) | Developers, privacy-minded | C ("fails loudly") or B; title `Show HN: FreeDocs – remove confidential data from documents before an LLM sees them` **[ASSUMPTION]** | Must be something people can try now → requires a published release or a clean source build. Maintainer posts and answers in person; lead the first comment with the limits and the benchmark caveat. No vote solicitation. |
| **Reddit** (rented) **[HYPOTHESIS]** | r/privacy, r/opensource, r/LocalLLaMA (local Ollama review), r/selfhosted (borderline: desktop, not self-hosted), r/gdpr, r/LawFirm or r/legaltech, r/Switzerland only if rules allow | Problem-first post, not an ad | Read each sub's self-promotion rules first; one sub per day; answer every comment. |
| **Product Hunt** (rented) | Early adopters | A or E | Lower priority **[ASSUMPTION]**: audience skews SaaS. Needs the gallery (screenshots, social image) and a maker comment stating limits. |
| **LinkedIn** (rented) | Lawyers, fiduciaries, HR, compliance in CH/IT/DE/FR | A, D, E; native posts in each language | Maintainer's personal profile; posts about the problem (client data in AI) with the before/after table as image (with alt text). Use the `linkedin-*` skills for drafting if available. |
| **Legal-tech and privacy newsletters, professional associations** (borrowed) **[HYPOTHESIS]** | Professionals | "Local, verified, measured" | Research candidates per country (Swiss legal-tech community, Italian Ordini/commercialisti networks, German Legal Tech community, French legaltech associations, IAPP chapters). Pitch with the press kit; never pay for placement. |
| **Directories** (borrowed) | Searchers, AI engines | Neutral listing | alternativeto.net (as alternative to Presidio and similar), awesome-lists for privacy/redaction on GitHub, Open Source Software directories. Use consistent description text from the press kit. |
| **Tech press** (borrowed) **[HYPOTHESIS]** | Professionals, IT | Swiss angle | heise/c't (de), Swiss IT press (Inside IT, Netzwoche), Italian and French tech press — pitch only after the release is public and checked. |

**Not used:** paid ads (they need tracking pixels to be worth it and would
contradict §9), influencer payments, fake upvotes, astroturfing.

### 15.4 Release-note cadence

There is no fixed cadence in the repository (0.1.0 on 2026-08-24, 0.2.0 on
2026-10-05, 1.0.0 on 2026-10-12 — *src: `CHANGELOG.md`*). Do not promise one. For
every published release:

1. `scripts/import-release` creates the `release` entry (§16.4).
2. A person writes the localised `notes` and 1–3 `highlights` per locale from
   `CHANGELOG.md`.
3. If the benchmark changed, the `benchmark` single type is updated in the same
   publish, and the README already matches.
4. Tier the announcement: **major** (new format, new country, new platform
   status) → changelog + LinkedIn + newsletter pitch; **minor** → changelog +
   one post; **patch** → changelog only.

### 15.5 Community

- Issues are the main channel; respond within a week (matches `SECURITY.md`'s
  acknowledgement promise for vulnerabilities **[ASSUMPTION]** as a general
  target).
- Discussions if enabled: categories Q&A, Ideas, Show and tell — with the "never
  attach a real document" rule pinned.
- Label `good first issue` for contributors; link `CONTRIBUTING.md`.
- Thank first-time contributors in release notes (only with their consent to be
  named).

### 15.6 Learning loop

After each launch step, record: downloads per platform (§2.3), stars delta,
issues opened by persona type (inferred from the issue text only — never ask for
identity), and which headline was used where. Revise personas (§5) and the FAQ
from what people actually ask.

---

## 16. Content model in Strapi

Keep it small. Every type below is localised unless marked otherwise.

### 16.1 Shared components

- **`shared.seo`** (used by every page type and every localisable entry that has
  a URL):

  | Field | Type | Rules |
  |---|---|---|
  | `metaTitle` | string | required, max 60 |
  | `metaDescription` | text | required, 50–160 |
  | `ogImage` | media (image) | optional; falls back to `global.defaultSeo.ogImage` |
  | `ogImageAlt` | string | required if `ogImage` set |
  | `canonicalUrl` | string | optional override; default is the page's own URL |
  | `noindex` | boolean | default false |
  | `keywords` | string | **internal only**, not rendered — records the target cluster from §12.2 |
  | `structuredDataOverride` | json | optional, rarely used; validated at build |

- **`shared.hero`** — `headline`, `subhead`, `primaryCta` (`shared.link`),
  `secondaryCta`, `image`, `imageAlt`, `note`.
- **`shared.link`** — `label`, `url`, `kind` (`internal`/`github-doc`/`external`),
  `docPath` (for `github-doc`, e.g. `docs/benchmark.md`, resolved against
  `global.githubUrl` at build).

### 16.2 Single types

- `global` — site name, tagline, descriptor, navigation links, footer columns,
  `defaultSeo` (`shared.seo`), title template, GitHub URL, security.txt contact,
  `fallbackNotice` (localised text shown on untranslated pages).
- `home` — `hero` (component), `blocks` (dynamic zone, see below), SEO.
- `download-page` — intro text, `noReleaseText` (rich text, the state with no
  published release), per-OS install instructions (rich text, one per `macos` /
  `windows` / `linux`), `verifyInstructions`, `firstRunText`, IT/Intune box, SEO.
- `benchmark` — **not localised**: `coverage`, `over_redaction`, `exact_f1`,
  `entity_count`, `removable_entity_count` (485), `language_count`,
  `location_coverage` (94.3), `report_only_recall` (92.3), `rows` (repeatable
  component `benchmark-row`: `layers_key` enum `l1|ner|all|all_min_conf`,
  `coverage`, `over_redaction`, `exact_f1`, `command`), `measured_on` (date),
  `engine_version`, `source_url` (link to `docs/benchmark.md` at the tag). The
  caveat text lives on the localised `benchmark-page`. Edited only when a new
  `freedocs benchmark` run is published; the values must equal the README's.
- `benchmark-page` — title, intro, `caveat` (localised), blocks, SEO.
- `security-page`, `how-it-works-page`, `limitations-page`, `faq-page`,
  `press-page`, `about-page`, `privacy-page`, `imprint-page` — each a title, a
  `slug`, a dynamic zone of blocks, SEO.

### 16.3 Collection types

- `release` — **`version` and `date`, `channel`, `assets`, `github_url` are not
  localised** (set the fields' i18n option off); `notes` (rich text) and
  `highlights` (repeatable short text) are localised. `version` (string, SemVer,
  unique), `date`, `channel` (`stable`/`prerelease`), `benchmark_changed`
  (boolean), `assets` (repeatable component `release-asset`).
- `release-asset` (component) — `platform` (`macos-arm64`, `windows-x64`,
  `linux-x64`), `kind` (`dmg`, `msi`, `nsis`, `deb`, `appimage`,
  `portable-zip`), `filename`, `url` (GitHub release asset URL — **do not upload
  binaries to Strapi**), `size_bytes`, `sha256`, `status` (`verified` /
  `built-not-launched`). `status` defaults to `built-not-launched` for every
  platform except `macos-arm64`; changing it requires the maintainer.
- `faq` — question, answer, `order`, `topic` (`home`, `download`, `security`,
  `privacy-law`, `product`), `source_path` (internal: the repo file that backs
  the answer).
- `limitation` — the "what it does not do" items: title, body, `doc_link`,
  `order`, `show_on_home` (boolean).
- `use-case` (phase 2) — `slug`, persona, problem, what happens, what it does not
  do (relation to `limitation`), blocks, SEO.
- `guide` (phase 2, open question 6) — `slug`, title, summary (the 40–60-word
  answer), body (blocks), `last_reviewed`, `author` (relation or text),
  `sources` (repeatable `shared.link`), SEO.

### 16.4 Dynamic-zone blocks (shared by every page)

`rich-text`, `feature-grid` (icon, title, text, link), `before-after` (rows of
before/after cells, rendered in a monospace face for placeholders), `stats`
(reads from `benchmark`, never typed by hand), `benchmark-table` (renders
`benchmark.rows`), `limitations` (references `limitation` entries),
`cta`, `code-transcript` (verbatim, never translated, rendered `lang="en"`),
`faq-list` (by topic), `comparison-table` (the README table only),
`doc-link-list` (GitHub doc links), `caveat` (a styled caveat that cannot be
smaller than body text), `image` (with required alt).

**Release data should not be retyped.** Write a small script (Node, in the site
repository) that reads a GitHub release — tag, body, assets — and the release's
`SHA256SUMS` file, and creates or updates the `release` entry through Strapi's
API. A release is a draft that the bundle workflow opens and the maintainer
publishes by hand, so the script is run by hand after publishing; a person then
writes the localised notes. The script must refuse to create an entry for an
unpublished (draft) GitHub release and must fail if any asset lacks a
`SHA256SUMS` line.

### 16.5 Localisation configuration

- i18n plugin: locales `en` (default), `it`, `de`, `fr`.
- Per field, localisation on or off as stated above; numbers, versions, hashes,
  URLs and enums are never localised.
- `slug` is localised and unique per locale.
- The Astro build fetches each locale with `?locale=xx&status=published` and
  falls back to `en` per entry, marking the page as a fallback (§8).

### 16.6 Roles, permissions and webhooks

| Role | Rights |
|---|---|
| **Public** (API, unauthenticated) | **None.** The build authenticates with a read-only API token; nothing is public, because nothing needs to be. **[ASSUMPTION]** stricter than the original brief's "read-only on published content" — equivalent for visitors (they never call Strapi) and smaller attack surface. |
| **Build token** (API token, read-only) | `find`/`findOne` on all content types; no upload, users or admin access |
| **Import token** (API token, custom) | `create`/`update` on `release` only, used by `scripts/import-release` |
| **Editor** (admin) | Create and edit all localised content; publish; cannot edit `benchmark` or `release-asset.status` |
| **Maintainer** (admin, Super Admin) | Everything, including `benchmark`, `status`, roles, webhooks |
| **Translator** (admin, optional) | Edit content in assigned locales only (Strapi locale-level permissions) |

- Disable the Users & Permissions registration endpoint; no public uploads.
- Admin behind VPN or IP allowlist and SSO/2FA where available.
- Webhook on `entry.publish`, `entry.unpublish`, `entry.delete` (and
  `media.update` if images change) → the static host's build hook URL, with a
  secret header. Debounce rebuilds (e.g. the host's build queue) so a batch of
  translations triggers one build.
- Database backups daily; the content is also re-creatable from the seed script
  plus the release importer.

**Note on Strapi v5 editions [ASSUMPTION — verify the current licence]**: Draft
& Publish and i18n are in the Community edition; Review Workflows and Content
History are paid features. The workflow in §17 works with Draft & Publish alone.

---

## 17. Editorial workflow and content-entry guidelines

### 17.1 Workflow

1. Write or change the **English** entry; save as draft.
2. **Claims check** against §3 (checklist below) — by someone other than the
   writer where possible.
3. Publish English.
4. Translate into it/de/fr using the README translations as terminology; save
   drafts; a fluent reviewer checks; publish per locale.
5. Webhook rebuilds; spot-check the built page in both themes.

A change to a figure follows a different path: the README changes first (via a
`freedocs benchmark` run), then the maintainer edits `benchmark`, then the site
rebuilds — never the other way round.

### 17.2 Claims checklist (every entry, every locale)

- [ ] No word from the forbidden list (§3.1), in any language (e.g. "garantito",
      "garantiert", "garanti", "conforme GDPR", "DSGVO-konform", "conforme au
      RGPD").
- [ ] Every product fact has a `source_path` or links to its source.
- [ ] Every figure is a `stats`/`benchmark-table` block, not typed text.
- [ ] Platform status is the asset's `status`, not prose.
- [ ] Any strength is on a page that links to `/limitations/`.
- [ ] Engine output, entity names and placeholders are untranslated and inside a
      `code-transcript` or `<code>`.
- [ ] No black-bar imagery; screenshots contain no real paths or usernames.

### 17.3 Content-entry guidelines

- Sentences under ~25 words; one idea per paragraph; no exclamation marks.
- Headlines in sentence case.
- Every image has alt text that describes what it shows; decorative images have
  empty alt.
- Links: descriptive anchor text; GitHub doc links via `shared.link.kind =
  github-doc`, so the base URL lives in one place.
- Dates in ISO in the CMS, formatted per locale on the page.
- Numbers never typed in prose except where the page quotes the README verbatim
  inside a `code-transcript`.
- Never paste real document content into the CMS — examples come from
  `examples/offerta-esempio.*` or other synthetic data.

---

## 18. What to read first

From the repository (`github.com/MarcoTribuz/FreeDocs`):

- `README.md` — the positioning, the demo, the numbers, the limits. The site is
  this page, expanded and translated. Also `README.it.md`, `README.de.md`,
  `README.fr.md` for terminology.
- `CHANGELOG.md` — versions, dates and the 1.0 compatibility promise.
- `SECURITY.md` — the threat model, in the words that are safe to repeat.
- `engine/freedocs/report.py` — `CAVEATS` and `KEY_FILE_CAVEAT`, the tool's own
  statement of its limits.
- `docs/architecture.md`, `docs/hidden-content.md`, `docs/benchmark.md`,
  `docs/scanned-pdfs.md`, `docs/restore.md`, `docs/terms.md`,
  `docs/llm-review.md`, `docs/cli.md` — the "How it works" page links to these.
- `docs/security-review.md` — the Security page links to it.
- `docs/packaging.md`, `docs/portable.md`, `docs/intune.md`, `docs/building.md`
  — the download page.
- `assets/brand/` and `app/src/app.css` — the visual identity.
- `docs/images/review.png`, `docs/images/result.png` — screenshots.
- `examples/offerta-esempio.docx` — the reproducible demo.
- `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/` — the About page.
- The GitHub releases page — asset names and `SHA256SUMS` (none published at the
  time of writing).

---

## 19. Deliverables and definition of done

A separate repository (proposed name `freedocs-site`) containing:

1. `cms/` — Strapi v5 project with the content types above, i18n configured for
   four locales, roles locked down (§16.6), a `docker-compose.yml` with
   PostgreSQL, and a seed script that loads the current README content into
   English entries (and the README translations into it/de/fr where they map
   one to one).
2. `web/` — the Astro site: every page in §10 marked for v1, all four locales,
   both themes, built statically from Strapi; `robots.txt`, sitemap, `llms.txt`,
   `security.txt`, 404 pages, host header config (§13.3).
3. `scripts/import-release` — GitHub release → Strapi `release` entry.
4. `scripts/metrics` — reads release download counts, stars and (with a token)
   GitHub traffic, and appends to a CSV in the repository (§2.3).
5. `scripts/check-claims` — greps built HTML in all locales for the forbidden
   words (§3.1) and for any percentage not produced by the `benchmark` data; runs
   in the build.
6. A `README.md` saying how to run both locally, how to deploy, how the publish
   webhook triggers a rebuild, and how to update the benchmark.

### Done means

**Content and claims**

- [ ] Every figure on the site equals the README's, and comes from the
      `benchmark` single type; `check-claims` passes.
- [ ] No sentence anywhere, in any locale, claims a guarantee, compliance or a
      platform status the repository does not state.
- [ ] The "What it does not do" page lists all eight README points and links
      each to its source; Home links to it.
- [ ] The download page shows a SHA-256 next to every file and the unsigned-app
      instructions for each OS — and renders the "no release yet" state correctly
      when no `release` entry exists.
- [ ] "Offline" is never stated without the first-run model download note
      nearby (or the portable bundle named).

**Localisation**

- [ ] Every page exists in en/it/de/fr, and a missing translation falls back to
      English visibly rather than showing an empty block.
- [ ] Engine output and entity names are in English with `lang="en"` in every
      locale.
- [ ] Numbers are formatted per locale from identical values.

**SEO**

- [ ] Every page has a unique `<title>` (≤ 60) and meta description
      (50–160) per locale.
- [ ] hreflang is reciprocal and complete for published locales, with
      `x-default`; canonicals are self-referencing (fallbacks → English).
- [ ] Sitemap lists every indexable URL with alternates; `robots.txt` references
      it; no published page is `noindex` by accident.
- [ ] JSON-LD validates (Rich Results Test, schema.org validator) and matches
      visible content; no ratings or reviews.
- [ ] OG/Twitter tags present on every page; the social image is served from the
      site's own origin.
- [ ] No orphan pages; no broken internal or GitHub-doc links (link checker in
      the build).

**Privacy and security**

- [ ] `astro build` produces a site with **zero** requests to any origin but its
      own (check the network tab on every page, both themes, all locales).
- [ ] No cookies set; no `localStorage` use except the theme preference.
- [ ] Security headers from §13.3 are present (check with `curl -I`); CSP
      reports no violations in the console.
- [ ] Strapi admin is not reachable from the public internet without the
      allowlist/VPN; the public API role has no permissions.

**Accessibility and performance**

- [ ] Lighthouse accessibility 100 on Home and Download, both themes; ≥ 95 on
      every other page.
- [ ] Keyboard-only walkthrough of Home → Download → copy a checksum works; focus
      always visible and never hidden by the sticky header.
- [ ] Axe (or equivalent) reports zero serious/critical issues on every template.
- [ ] Performance budgets in §13.2 met on Home, Download and Benchmark (Lighthouse
      mobile, throttled); Lighthouse performance ≥ 95.
- [ ] Every page readable and every download reachable with JavaScript
      disabled.

---

## 20. Open questions for the maintainer

Ask these before building; do not assume.

1. **Domain** — which one, and is it already registered? Separate domains or
   subpaths per language? (This brief assumes one domain with locale prefixes.)
2. **Hosting** — static host for the site (Cloudflare Pages, Netlify, own
   server?) and where Strapi runs (own VPS, Strapi Cloud?). Swiss/EU hosting
   preferred for a privacy product? What access logs does the host keep, and for
   how long (the privacy page must say)?
3. **Analytics** — none (recommended), or self-hosted cookieless (Umami or
   Plausible self-hosted)? Separately: is verifying the domain in **Google Search
   Console** and **Bing Webmaster Tools** (DNS record, no script on the page)
   acceptable? It is the only source of search-query data without tracking.
4. **Imprint and publisher identity** — legal entity, address and contact to
   publish; is the publisher a person or an organisation (affects
   `Organization`/`Person` structured data and the press kit)?
5. **Contact** — an email address for the site, or GitHub issues only?
6. **Guides / blog** beyond the changelog — wanted (§12.7), and is a translator
   available for it/de/fr? Who reviews the legal-adjacent guides (G2, G8)?
7. **Donations or commercial support** — anything to mention (GitHub Sponsors,
   paid support), or nothing?
8. **GitHub Discussions** — enable as the community channel, or issues only?
9. **Comparison content** — keep competitors to the README table only (this
   brief's default), or approve dedicated "alternative to" pages?
10. **AI crawlers** — allow GPTBot, ClaudeBot, PerplexityBot and
    Google-Extended in `robots.txt` (recommended for citation), block training
    crawlers only, or block all?
11. **First release and launch date** — when will the first GitHub release be
    published, and should the public launch (§15.2) wait for a Windows/Linux
    install report from someone other than the maintainer?
12. **Market emphasis** — is Switzerland the primary market (affects `og:locale`,
    currency in structured data, which press and associations to pitch first)?
13. **Use-case pages** — which personas get a page in phase 2 (this brief
    proposes lawyers, fiduciaries, HR, IT deployment; healthcare deliberately
    excluded)?

# Architecture

Six stages. Only `pipeline.py` knows the order:

```
router -> extract -> detect -> policy -> write-back -> verify
```

Stages 3, 4 and 6 are format-agnostic and shared. Adding a format means
implementing `extract`, `write_back` and `scrub_hidden` in
`formats/base.FormatHandler` and nothing else — format knowledge never leaks
into `detect/`, `core/policy.py` or `verify.py`.

There is a second, optional direction with five stages of its own, and only
`restore.py` knows *those*:

```
router -> extract -> match -> write-back -> verify
```

It shares four of the names and every mechanism: `plan_edits` does not care which
way text is going, so writing a value over a placeholder is the same machinery
that wrote a placeholder over a value. `FormatHandler` gains no method for it. See
[the reverse path](restore.md).

## The offset map, and why it is the load-bearing piece

The interesting problem is that the text a model reads and the bytes a writer
edits are not the same object. Word can store `Mario Rossi` as three separate
runs; a detector needs it joined, a writer needs it split. Flatten it naively and
the formatting is gone, which is why so many tools output plain text.

`core/stream.py` solves it with an offset map. Extraction appends anchored chunks
to a flat string, and each `Anchor` records where its characters came from — a
`part` plus an opaque `locator` that only the handler interprets. Detection runs
on the flat text. `TextStream.plan_edits()` translates the resulting spans back
into per-anchor edits, placing the replacement in the first anchor an edit
touches and clearing the rest, so surviving runs keep their own properties and no
new run has to be invented.

Two consequences worth knowing before touching that file:

- **Separator text goes in through `add_filler()`, not `add()`.** Filler has no
  source location, so an edit landing only on filler raises rather than silently
  writing nowhere.
- **Separator choice is not cosmetic.** Cache values are joined with `\n`,
  spreadsheet cells within a row with `\t`. Joining two independent cached
  amounts with a tab is what produced a credit-card false positive on a chart.
- **Detectors must produce character offsets.** This is why a generative LLM
  cannot be the primary detector: no reliable offsets, nothing to anchor.

`TextStream.part_at` is a bisect rather than a scan. The version it replaced
walked every anchor once per finding, which on a 200-page PDF is tens of
thousands of anchors times hundreds of findings — exactly the document the
preview is for.

## Detection layers

`detect/registry.py` merges the layers and resolves overlaps by precedence
(L1 > L2 > L3), then span length, then confidence. Two edits may never touch the
same characters.

### L1 — validators: regex nominates, checksum decides

`detect/validators.py`. Forty rules over twelve countries: national identity and
social-security numbers, tax numbers, VAT numbers, company-register numbers, plus
IBAN mod-97 and Luhn, which are the same everywhere. Every validator comes from
[`python-stdnum`](https://arthurdejong.org/python-stdnum/), which ships 201 number
modules across 87 countries — extending the coverage was populating a table, not
training anything.

**Confidence per rule is a measurement, not a judgement.** Each validator was run
against 20 000 randomly generated format-plausible values to count how many it
accepts. A rule whose pattern demands a literal prefix (`CHE`, `756`, `DE`, `ATU`)
stays at full confidence even on a one-in-ten check digit, because the prefix
discards almost every candidate before the checksum runs. A digits-only rule gets
a confidence tied to what its check digit actually does, and the weakest ones sit
below the default threshold: found and reported, never removed, unless a word
naming them is nearby.

**A validator that accepts most of what it sees is not a validator.**
`stdnum.us.ssn` accepts 89% of random values of its shape, `us.ein` 83%,
`at.businessid` 100%, `de.handelsregisternummer` 90% — they check format, or need
a court's city. Those identifiers are not in the rule table and must not be added
by tightening a regex to compensate. The model answers for them, and the report
says so.

Two mechanisms in `Rule` exist because of specific bugs:

- **`shrink_to_fit`** — the IBAN pattern is deliberately greedy and absorbs
  trailing digits; mod-97 then decides where the IBAN really ends. Without it,
  `CH93 0076 2011 6238 5295 7` was truncated to 20 characters and rejected.
- **`confidence_without_context`** — eleven digits passing an 11-digit Luhn is
  weak evidence, so partita IVA and card numbers drop below full confidence when
  no keyword is nearby, and `Policy.min_confidence` makes the call.

**Context keywords come in two kinds and need opposite matching.**
`detect/keywords.py` splits every family into `*_STEMS`, matched as substrings,
and `*_CODES`, matched as whole words. Whole-word matching for everything lost
four cases the corpus already carried (`karte` is the tail of `Firmenkarte`,
`card` the head of `cards`); substring matching for everything fires `iva` inside
`arriva`, `vat` inside `salvataggio`, `nif` inside `definisce`. Both tables are
the union across the languages covered, because the engine does not know which
one it is reading.

Phone detection uses [`phonenumbers`](https://github.com/daviddrysdale/python-phonenumbers)
with `Leniency.STRICT_GROUPING`. Do not loosen it: under `VALID` the Italian
numbering plan reads `03.03.2024` as a phone number, and business documents are
full of dates. One region-less pass finds every number written in international
format; one pass per country finds the locally-written ones, and dedup is on
*overlap* rather than an identical span, because three plans read
`044 910 55 66` and disagree about where it ends.

### L2 — NER encoder

`detect/ner.py` plus `detect/backends/`. GLiNER2 on an `mdeberta-v3-base`
encoder, so one model covers Italian, German, French and English with no language
hint, for names, organisations, locations, addresses and job titles. Backends are
swappable so the choice rests on benchmark output rather than on taste;
`presidio_backend.py` is the measured alternative and stays installable so the
comparison stays reproducible.

`NerDetector.min_score` defaults to 0.5 because a threshold sweep on the corpus
was flat from 0.2 to 0.6 and degraded above it — not because 0.5 looked sensible.
`MAX_CHUNK_CHARS` is 1200 for the same kind of reason: removable coverage is flat
from 800 to 1500 and falls above it, while over-redaction improves monotonically
with size and flag-only recall collapses. See [benchmark.md](benchmark.md) for
the sweep and for the noise floor any future tuning has to clear.

### L2.5 — value propagation

`detect/propagate.py`. A value identified once is identified: every other
occurrence of it in the document is redacted too. It runs after overlap
resolution, then resolves again. Values shorter than three characters do not
spread, and a legal form never spreads at any length — a document where a
detector claims a bare `Ltd` would otherwise spread it to every other `Ltd` on
the page, which is not a second sighting of anything.

This is the cheapest large win in the pipeline. Most residual misses are repeat
mentions: the model finds `Anna Bianchi` in the attendee list and scores the same
name below threshold eight lines later.

### L2.55 — addresses

`detect/addresses.py`. **The postal code is the part of an address that needs no
model.** GLiNER2 found thirty-six of forty-one annotated addresses and all five
misses failed the same way: it returned the city as a LOCATION and dropped the
street, so the house number, street and postcode stayed in the document. This
pass finds the code first and reads outwards, assembling
`<street> <number>, <code> <city>` and the British inversion, and absorbing a
LOCATION it fully contains. It took ADDRESS coverage from 87.8% to 100% and
LOCATION precision from 0.73 to 0.82.

A comma is not enough to find the left edge — `residence Meir 78, 2000 Antwerpen`
has no comma before the street — so the scan is a token walk with an explicit
vocabulary: capitalised words, house numbers, the connectors inside a street name,
and the lowercase words that *are* street types in the languages covered.

### L2.6 — organisations from their legal form

`detect/organisations.py` nominates a company name from the legal form that
follows it, and **only where no layer claimed those characters**. It is a gap
fill, not a detector. Run as a peer it was strictly worse: German capitalises
common nouns, so the backward scan produced `Kunde Nordwind Logistik GmbH`, which
beat the model's correct span because the longer span wins at equal precedence.
Short legal forms are matched case-sensitively for the same class of reason: `sa`
is a French possessive, `ab` a Swedish preposition.

### L2.7 — suppression

`detect/suppress.py` removes findings that name something real and identify
nobody, and it is split across propagation because the two halves answer
different questions. `drop_non_identifying` judges a *value* — a bare country
name identifies nobody anywhere — so it runs on both sides and cannot spread.
`drop_jurisdiction_mentions` judges an *occurrence* — the same city is
confidential in the party's address and not in "the courts of Zurich" — so it
runs after propagation only.

Filtering jurisdictions first was measured and cost three covered entities:
`Basel`, `Genève` and `Milano` are each found by the model *only* in the clause,
and that sighting is the template propagation needs to reach the same city in the
address twenty lines up.

City-states stay in. Luxembourg, Monaco, Singapore, San Marino and Andorra name a
city as often as a country, and this list drops findings outright, so an ambiguous
name in it would be a leak.

### L3 — LLM review, opt-in and advisory

`detect/llm_review.py`, off by default, not part of the registry: it produces no
spans and drives no edits. See [llm-review.md](llm-review.md).

## L1 gets the last word on L2's structured claims

`registry.drop_unconfirmed_structured` discards a NER finding labelled IBAN,
card, codice fiscale, partita IVA, AHV, UID or CH VAT when the matching checksum
rejects the text. GLiNER2 labelled two adjacent chart amounts a credit card at
0.87 confidence; no threshold separates that from a real finding, and Luhn
settles it in one call.

`confirms()` checks the checksum only, not the regex, so the model can still
contribute a real identifier written in a format the L1 pattern would not
nominate. And it needs to know *which* country, which it usually does not: a tax
number is claimed by the twelve countries here and by none of the other hundred
and eighty, so a Brazilian CPF the model correctly spotted passes no check digit
this build knows. Without a country there is no opinion, and the finding
survives.

The one thing refused before any checksum runs is a **digit-free** identifier
claim. `cittadinanza italiana` came back NATIONAL_ID at 0.79 and `Turkish` at
0.52, both above the default threshold, and each was replaced with
`[NATIONAL_ID_1]` — worse than an ordinary false positive, because it destroys
the sentence's meaning *and* files a nationality as an identifier.

## Diacritics fold in exactly one place

Everything that matches prose against a table folds diacritics through the single
function in `core/text.py`. Two copies of that function are two answers to the
same question, which is how the bug got in: one pass folded and another merely
casefolded, so five keyword entries never met the `sécurité sociale` or
`numéro de TVA` a real document contains, and seven weak rules across six
countries were inert as a result.

The legal-form tables are deliberately **not** folded — they gained `sàrl`,
`s.à r.l.` and `s.à.r.l.` as listed spellings instead, because
`organisations.py` matches short forms case-sensitively on purpose and folding a
candidate to compare it would throw that distinction away.

## Anonymisation by default, pseudonymisation on request

Values are replaced with typed placeholders — `[PERSON_1]`, `[IBAN_2]` — stable
within a document, so the text still reads coherently. The mapping lives in
memory for one run and is destroyed in a `finally` block, including when a stage
raises. By default nothing is written, so there is no key to leak and the scrub
cannot be undone by anyone, including the person who ran it.

`scrub --map` writes an encrypted **key file** for that one document, and
`freedocs restore` uses it to put the values back into whatever came back from the
model. That is pseudonymisation, and it is off by default because it creates the
one artifact this tool otherwise never produces. See
[the reverse path](restore.md).

Three things about it are structural rather than incidental:

- **`SurrogateAllocator` is not involved and gains no accessor.** The key file is
  built from a finished `ScrubResult`, whose `Decision` rows carry the original in
  `finding.text` and the placeholder in `replacement`. So the line that destroys
  the allocator's mapping is exactly where it was, and `pipeline.py` does not
  import `core/mapping.py` at all: the reverse direction is a front-end decision
  about a finished result, not a branch inside the pipeline.
- **The round trip is lossy on spelling.** `policy._normalise` casefolds and
  collapses whitespace, so `Mario Rossi`, `MARIO ROSSI` and `Mario  Rossi` share
  one placeholder and only one of them can come back — the first in document
  order. `MapEntry.variants` counts the collapse and the key file warns when it
  happened.
- **Restore verifies both directions.** Placeholder gone *and* value present.
  `PdfTextHandler` replaces text by stamping a redaction annotation, and PyMuPDF
  silently drops a replacement that does not fit its rectangle — so on a PDF the
  common failure is the token removed and the value never written, which a
  one-directional check reads as success.

**Placeholder families were considered and declined, and a key file does not
reopen the question.** `[ORGANISATION_1]` / `[_1a]` / `[_1b]` for `Acme`,
`Acme Corp.` and `Acme Corporation` would tell the model reading the output that
those are one company — and would equally tell any reader that those three strings
are related, which is a re-identification thread this tool cannot take back. The
threat model of the *shared* artifact is what settles this, and a key file does
not change it: the scrubbed document still goes to a third party who does not have
the key, while anyone who does have it already holds every value. Flat numbering
stays.

**The type says what a number is for; the country lives on the finding.**
`NATIONAL_ID`, `TAX_ID`, `VAT_ID`, `COMPANY_ID` rather than one enum member per
country per number. The country reaches the report and never the placeholder:
`[TAX_ID_DE_1]` would hand the reader of the scrubbed text one more thing to
re-identify with.

## The human override

`core/overrides.py` carries what a person decided after reading the preview:
occurrences to leave alone, and values to remove that no detector nominated.
Every other control in the engine can only cause a value to be *removed*; this is
the one that can cause a value to stay, so the burden of proof sits on that side.

- **`Layer.HUMAN` outranks `VALIDATOR`.** An override a checksum could overrule is
  a suggestion, not a control.
- **A keep is a span, a removal is a value.** The window lists one row per
  occurrence, and it must be a range, because the same city is confidential in a
  party's address and not in a jurisdiction clause. A removal has no row to point
  at, so it names a string and every occurrence goes.
- **A kept span carries the text it covered, and a mismatch raises.** Offsets come
  from a previous extraction and nothing guarantees the file is unchanged.
- **Decisions are scoped per document**, because a span is an offset into one
  extraction.
- **Stage 6 gets a count, not an exemption.** Verification is value-based and an
  override is occurrence-based, so `verify_output` permits each value exactly as
  many times as were kept. A write-back that quietly failed on the *other*
  occurrence is still a hard failure.
- **`EntityType.OTHER` is reachable only through an override.** A caller who has
  not said what a value *is* has still said it must go. No detector produces it:
  a detector that cannot name what it found has not found anything.

## Verification

Stage 6 re-opens the output, re-extracts it — hidden parts included — and
searches for every value that was supposed to be gone. In strict mode a survivor
raises `LeakDetected`, and the CLI writes nothing. A nearly-clean file is more
dangerous than an obviously dirty one, because it gets sent.

`Leak.describe()` is value-free: that message travels to stderr and through the
RPC layer, and an error about confidential values surviving must not carry them.

The reverse direction has its own check in `restore.py`, and it is not this one
run backwards. It asks two questions — is the placeholder gone, *and* did the
value arrive — because a handler that silently drops a replacement satisfies the
first and fails the second, and only the pair catches it.

It also handles the failure the other way round, on purpose. A scrub that leaks
writes nothing, because a nearly-clean document gets sent. A restore that left one
`[IBAN_1]` behind has produced the caller's best artifact and its defect is
visible in it, so the file **is** written, every problem is reported, and the exit
code is `5` — distinct from `3` because the handling is distinct.

# Measured, not estimated

```bash
cd engine
uv run freedocs benchmark
```

`corpus/{de,en,fr,it}.txt` holds **537 annotated entities** across Italian,
German, French and English business documents, of which **485 are entities the
policy actually removes** and 52 are `REPORT_ONLY` types it flags and never
deletes. The documents cover the twelve supported countries, so a rule for one of
them is measured rather than asserted.

`freedocs benchmark` prints the counts it actually loaded. **Trust that line over
any figure written down here** — this page is a snapshot of a run on
2026-08-23, and the corpus grows.

## The headline is not F1

For redaction the numbers that matter are **coverage** (gold entities *fully*
removed — a partial span is a leak, because `Rossi` left behind still identifies
someone) and **over-redaction** (characters removed that were not confidential — a
detector that redacts the page leaks nothing and is useless).

| Layers | Coverage | Over-redaction | Exact micro-F1 | Command |
|---|---|---|---|---|
| L1 checksums only | 70.3% | 1.1% | 0.738 | `--detectors l1` |
| NER only | 86.6% | 1.7% | 0.793 | `--detectors ner` |
| **Everything (default)** | **99.6%** | **2.2%** | **0.929** | *(no flag)* |
| Everything, as a scrub applies it | 99.6% | 2.0% | 0.933 | `--apply-min-confidence 0.5` |

`evaluate()` calls `detect()` directly, so `Policy.min_confidence` is **not**
applied by default: the bare command measures the detector, the last row measures
what the pipeline would actually do. Do not tune a corpus trap against a
threshold that is not in the loop.

Coverage is scored over the **removable** entities. The `REPORT_ONLY` types are
counted apart, at **92.3% found**, and marked in the not-covered list so nobody
reads one as a leak: "share fully removed" says nothing true about them in either
direction, since finding every job title makes no document safer and missing one
leaks nothing. They had been quietly inflating the headline. `coverage_all` is
kept for comparison with figures published before the split.

## Per entity type

```
entity                  gold  pred   cover      P      R     F1
ADDRESS                   45    45  100.0%   1.00   1.00   1.00
COMPANY_ID                28    27  100.0%   1.00   0.96   0.98
CREDIT_CARD               12    12  100.0%   1.00   1.00   1.00
EMAIL                     39    39  100.0%   1.00   1.00   1.00
IBAN                      23    23  100.0%   1.00   1.00   1.00
IP_ADDRESS                20    24  100.0%   0.83   1.00   0.91
JOB_TITLE                 52    52   92.3%   0.92   0.92   0.92
LOCATION                  35    33   94.3%   0.85   0.80   0.82
MAC_ADDRESS               12    12  100.0%   1.00   1.00   1.00
NATIONAL_ID               34    44  100.0%   0.75   0.97   0.85
ORGANISATION              45    52  100.0%   0.83   0.96   0.89
PERSON                   106   104  100.0%   1.00   0.98   0.99
PHONE                     35    55  100.0%   0.64   1.00   0.78
TAX_ID                    20    30  100.0%   0.67   1.00   0.80
URL                       12    12  100.0%   1.00   1.00   1.00
VAT_ID                    19    19  100.0%   1.00   1.00   1.00
```

Both remaining leaks are a `LOCATION`: `Lyon` and `Firenze`, each of which also
appears in the same document as somebody's surname. Note *which* half fails — the
model finds `Nathalie Lyon` and `Roberto Firenze` and never the bare place, so
there is no confirmed occurrence for propagation to copy either. That is a
disambiguation no pattern can make, and at 99.6% coverage it is most of what is
left to find. Keep these collisions when editing the corpus; they are the
finding.

`Zug` and `Sion` looked like the same case and were not. They were already
confirmed findings elsewhere, and the only thing keeping them in their documents
was the propagation length floor — a sweep over 5, 4, 3 and 2 recovers `Sion` at
4 and `Zug` at 3, moves over-redaction not one character at any floor, and gains
nothing further at 2. So the floor is 3, and the legal forms that motivated a
higher one are excluded by name instead.

## What the countries cost

```bash
uv run freedocs benchmark --countries ch,it
```

Switzerland and Italy alone: 97.7% coverage at 1.9% over-redaction, exact F1
0.881. Enabling the other ten takes over-redaction from 1.9% to 2.2% and buys 1.9
points of coverage plus 0.048 of F1.

Per-country precision is where a weak check digit shows:

```
ch 1.00   de 1.00   fr 1.00   be 1.00   nl 1.00   pt 1.00   se 1.00
it 0.92   pl 0.62   at 0.58   gb 0.55   es 0.40   us 0.00 (1 prediction)
```

The four at the bottom carry the rules whose validators accept 8–10% of random
values of the right shape. Those are the rules that stay below the default
threshold unless a keyword sits beside them — which means at default settings
they are inert, and the benchmark is charging for work the pipeline never does.

## The over-redaction is nearly all ambiguity with no checksum behind it

A four-part firmware version is indistinguishable from an IPv4 address; an
eight-digit customer number is a valid Italian landline. That is why IP and PHONE
precision sit where they do, and no regex can settle either.

**A phone number written the way a local writes it is only findable by that
country's plan, and that is what those plans cost.** The region-less pass alone
reaches 82.9% PHONE coverage at precision 1.00; all thirteen national plans reach
97.1% at 0.67. All of them are on, because a number a scrub leaves behind gets
sent while an over-redacted order number is read and shrugged at.

## Presidio

Absent from the table on purpose. It was measured on the earlier 103-entity
corpus at 55.3% coverage and **21.5%** over-redaction, and quoting that figure
beside numbers from a different corpus would compare two annotations rather than
two detectors. Re-running it needs the `ner-presidio` extra:

```bash
uv run freedocs benchmark --detectors "all:gliner2,all:presidio"
```

The finding that mattered has not changed, and it is why the option still exists
to be re-measured: Presidio lost on *over-redaction*, not on recall. It has no way
to know the document's language, so every configured language is run and merged,
and PERSON precision fell to 0.28. Removing a fifth of a document for nothing
destroys it.

Do not add a language-detection step to make it viable. A detector guessing the
language is one more thing that fails silently on short or mixed text.

## Rules the corpus enforces

**Gold offsets are derived, never hand-written.** `corpus/*.txt` uses inline
`[LABEL:text]` markup. Hand-maintained offsets rot silently — insert a word and
every number after it is wrong — and then the benchmark measures the annotation
instead of the model. An unknown label is an error, not a skip: a dropped
annotation gets scored as a detector hallucination.

**Canaries must pass their real checksums.** A test value with a bad check digit
is rejected by the validator, so nothing is detected, nothing leaks, and the leak
test passes while proving nothing. `test_corpus.py` asserts that every annotated
identifier is actually accepted by L1, so a bad value cannot make a detector look
worse than it is.

**But "L1 rejects it" and "the value is fake" are different failures.** That test
used to cover PHONE, and it forbade a case worth having: `+39 0444 512 337` is a
valid Italian number that `STRICT_GROUPING` declines. Asserting it away would hide
a real gap in L1 — one GLiNER2 in fact closes. So phone canaries are checked with
`phonenumbers.is_valid_number` instead.

**At twelve countries a value broken for one checksum is often valid for
another.** `192598180` was written in as a rejected Polish REGON and is a valid
Portuguese NIF; `4360730410` was a rejected Polish NIP and is a valid British UTR.
A trap has to be checked against every rule, which a test enforces.

**An adversarial case must be a realistic string a checksum rejects**, never a
valid identifier relabelled as ordinary text: three of the traps first written
here reused the digits of an annotated identifier elsewhere, which made one string
both confidential and not.

**The files carry their accents, and that is load-bearing.** They were ASCII until
the tables that match prose were found to be comparing unaccented entries against
text that has accents in it, and an ASCII corpus cannot show that failure at all.
The accents were added one codepoint for one codepoint (`numero` → `numéro`) so no
gold offset moved and no chunk boundary shifted.

**The four files each end with a governing-law and payment block, added
unannotated.** Those clauses are the cases `detect/suppress.py` is paid to pass,
and they are why `Basel`, `Genève`, `Lugano` and `Milano` each appear both as
somebody's location and as a jurisdiction. Do not annotate them, and do not delete
them: without a document where the same string is confidential in one sentence and
not in the next, nothing there can be measured at all.

## Adding corpus text moves NER chunk boundaries, and that alone changes coverage

Appending six lines to `corpus/fr.txt` cost the annotated
`Meir 78, 2000 Antwerpen` two lines above it: the final `iter_chunks` window
moved and GLiNER2 stopped returning an address it had returned before. Verified by
re-running with the new rules disabled. So when the corpus grows, attribute the
delta before believing it — a rule and a boundary shift look identical in the
headline.

**Three entities is the noise floor on this corpus.** Prepending 137, 411 and 700
characters of unannotated text to shift every boundary moves the same
configuration between 473 and 477 of 480 removable entities. Any future tuning of
a chunking parameter needs that shift control, not just a better headline — it is
what turned an apparent win for `CHUNK_OVERLAP` of 400 over 200 into a wash on
coverage and a consistent loss on over-redaction.

The same control is what settled `MAX_CHUNK_CHARS` at 1200: removable coverage is
flat from 800 to 1500 (474 to 477 of 480) and falls above it, over-redaction
improves monotonically with size (752 characters at 800, 493 at 3600), and
flag-only recall collapses (96.2% at 1500, 76.9% at 3600). It also disproved the
reason the old comment gave for staying low: a name placed at increasing depth in
a single call still comes back at 9815 characters, with the score decaying only
0.997 to 0.954. The ceiling is a quality trade, not a token limit.

## Measurements that said "do not build it"

**A labelled-field extractor.** The obvious missing layer would anchor on
`Registered address:` and `Authorised signatory:`. It was tested before being
written: `corpus/en.txt` and `corpus/de.txt` now end with a tab-separated
onboarding form and a signature block, and GLiNER2 found all sixteen annotated
entities in them with no false positive on any label. A harder probe put a
spreadsheet header 1900 characters and one chunk away from its name column: all
four names came back at 0.91 to 1.00. The reason is structural — `core/stream.py`
keeps a label and its value adjacent in the flat text, so the label is in the
window anyway, and the model reads the name rather than the label. The form block
stays in the corpus so the absence stays a measurement rather than an assumption.

**Special categories.** Nationality, religion and political affiliation are GDPR
Article 9 data and there is no entity type for them. Asking GLiNER2 for them
works on a sentence that discloses one — `deutscher Staatsangehöriger` at 0.96,
`nationalité algérienne` at 0.81, `SPD` as a political affiliation at 0.97. On the
corpus it returns eleven findings and **none of them is that**: every one is an
adjective modifying a thing (`deutsche Konto`, `Swiss identification number`
four times). Business documents use nationality words that way almost
exclusively, and asking cost two covered entities, 101 characters of
over-redaction and 5.8 points of flag-only recall, because three more labels shift
the model's output distribution. If it is revisited, the shape that avoids the
interference is a second `predict` call with only those labels, merged as a strict
gap fill that never competes.

**Chunk-artifact rejection.** A finding whose span starts or ends mid-word is the
signature of a chunk-boundary hit, and the fallback in `iter_chunks` can cut
mid-word, so the defence looked free. There are **zero** such findings across the
corpus. The test was written first, and it said not to build the rule.

**A currency rule for the suppression layer.** GLiNER2 never tagged "Swiss
francs", "francs suisses" or "United States dollars" at all, because there is no
nationality entity type for "Indian" in "Indian Rupees" to land on.

## The standing caveat

The corpus is small and synthetic. These numbers rank configurations against each
other; they are not a published benchmark result, and the tool says so every time
it prints them.

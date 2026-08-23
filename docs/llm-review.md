# The second opinion

```bash
uv run freedocs review-models                          # what Ollama has pulled
uv run freedocs scrub doc.docx -o out/ --review qwen3-coder:latest
```

Off by default. It takes tens of seconds, it needs a local model nobody is obliged
to have, and it changes nothing in the output.

## What it is for

The one thing nothing else in this project can do. The checksum and NER layers
cover almost the whole corpus at low over-redaction, and what they cannot fix is
not a missed span — it is a document with every name removed that still says
"the only female partner in the Lugano office, hired in March 2019". No single
redaction repairs that. A reader can notice it; a span-based detector cannot.

Asked of a real local model, on a document whose every direct identifier was
already a placeholder, it returned exactly that:

```
[quasi_identifier] "l'unica donna partner dell'ufficio di Lugano"
    -> role plus location identifies one person
[quasi_identifier] '84 anni, residente a Bedigliora (312 abitanti)'
    -> age plus a town of 312 people
```

## It is not a detector, and must not become one

It has no offsets, and the anchors are the only route from a finding to a run or a
rectangle. It runs after `verify`, on the text `verify` already re-extracted from
the output — re-extracting a scanned PDF would mean OCRing every page a third
time, which is what `VerifyResult.extracted` exists for.

Four properties to preserve:

- **It never edits.** The output is already written when the review runs. Its
  findings are for a human, and the report says so.
- **A skipped review does not look like a clean one.** `ReviewOutcome.ran` is
  separate from an empty list of concerns, because "Ollama was not running" and
  "the reviewer had no objection" are different facts and the second is
  reassuring. Collapsing them lets a silently skipped review read as a clean bill
  of health.
- **A non-loopback host is refused** unless the caller passes `--review-remote`.
  This is a tool whose premise is that documents do not leave the machine, so a
  review host on the network is a decision, not a default. Pointing `OLLAMA_HOST`
  at a GPU box has to be deliberate — and the refusal says why: scrubbed is not
  the same as harmless, since this layer exists precisely because
  quasi-identifiers survive a scrub.

  `_is_local` deliberately does not resolve hostnames: whether one still points at
  loopback tomorrow is not this code's call. Listing a host's models is refused on
  the same terms and from the same message, because offering a choice the scrub
  then rejects reads as a bug rather than as the rule it is, and asking a machine
  which models it has is still talking to it.
- **An unreachable Ollama is reported, never raised.** `review_outcome` converts
  `OllamaUnavailable` into a stated fact: a missing advisory layer must not fail a
  scrub that otherwise worked.

## Where Ollama lives is configuration, not a rule

`capabilities` reports the default host so the app can prefill it instead of
holding a second copy, and the `review_models` method answers for one named host.
Without it, an Ollama on a non-default port left the window showing an empty list
with no way to correct it — which reads as "this build cannot review" when the
truth is "look somewhere else".

`allow_remote` stays reachable over the pipe with no control in the window: the
opt-in belongs to a caller that states it, not to a checkbox.

## Two implementation notes

The response schema is passed to Ollama and enforced server-side, so "the model
ignored the format" cannot happen; `_parse_concerns` is defence, not parsing. Its
quotes come from the *scrubbed* text, which is why they are safe to print and to
put in the report.

It reads the first 12 000 characters. A model handed forty pages returns
generalities, and the report says when only part was covered.

# What this changes

<!-- One paragraph. What was wrong or missing, and what the change does about it. -->

## Why this way

<!-- The part worth keeping. If you tried a simpler approach and it failed, say so
     here and in a comment next to the code — that is the convention in this
     repository. -->

## Checks

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run pytest -q -m "not slow"`
- [ ] `uv run pytest -q` with the `ner` extra installed, or a note on why not
- [ ] `npm run check && npm test` in `app/`, if the app was touched
- [ ] No real document, and no real personal data, in any file added

## If a detector changed

Paste the benchmark line before and after — `uv run freedocs benchmark`:

```
before:
after:
```

Coverage and over-redaction are the figures that decide it. **Three entities is
the noise floor on this corpus**, so a smaller delta is not a result; and if the
corpus grew in this PR, attribute the change before believing it, because adding
text moves NER chunk boundaries and that alone shifts coverage.

## If this adds a rule that can keep a value in the document

Suppression rules, keyword gates and confidence changes all fall here. Name the
corpus case that motivated it. This is the one direction where a wrong rule turns
a working scrub into a leak, so the burden of proof runs the other way.

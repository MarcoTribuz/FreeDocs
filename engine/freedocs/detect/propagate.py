"""Carry a confirmed value across the whole document.

Measured on the corpus, every residual miss of the L1+GLiNER2 combination was a
*second* mention: the model found "Anna Bianchi" in the attendee list and missed
the same name eight lines later. Model confidence varies with context, so the
same string is above threshold in one sentence and below it in another.

The fix does not need a better model. A value identified once is identified: if
"Anna Bianchi" is a person at character 40, the identical string at character 900
is the same person. This pass copies each confirmed finding to every other
occurrence of its text.

It is deliberately literal. Matching is exact up to case, with word boundaries,
and only for values long enough to be distinctive — inference about *similar*
strings ("A. Bianchi", "Bianchi") belongs to a model that can weigh context, not
to a string search that would quietly redact the wrong words.

That last restriction is what still keeps two entities leaking. ``Lyon`` and
``Firenze`` are each confidential in the corpus as a place, and each appears in
the same document only *inside* a longer finding — ``Nathalie Lyon``,
``Roberto Firenze``. Propagating a substring of a person's name to every place it
occurs is exactly the inference refused above, so those two stay for a model to
find. ``Zug`` and ``Sion`` were a different failure and are fixed: both were
already standalone findings elsewhere and only the length floor stopped them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..core.findings import Finding, Span
from .suppress import LEGAL_FORMS

#: Values shorter than this are not propagated, measured rather than assumed. The
#: floor was 5, and it was the only reason ``Zug`` and ``Sion`` leaked: both were
#: already confirmed findings elsewhere in their document, so nothing but the
#: length test stood between them and the occurrence that survived. A sweep over
#: 5, 4, 3 and 2 recovers ``Sion`` at 4 and ``Zug`` at 3, moves over-redaction not
#: one character at any floor, and gains nothing further at 2.
#:
#: Half of the original justification was wrong: short strings do not in fact
#: match "inside unrelated words", because the pattern below is bounded by
#: ``(?<!\w)``/``(?!\w)`` and never matched ``Zug`` in ``Zugang``. The other half
#: was right, and 3 rather than 2 is where it bites — the named risk is the
#: two-letter legal forms ``AG``, ``SA``, ``BV``, ``AB``, which stay out by
#: length, and ``Ltd``, which is three and is excluded by name below.
MIN_PROPAGATION_LENGTH = 3

#: A legal form is never a propagation template, whatever its length. This is the
#: one part of the old floor's reasoning that survived measurement: a document
#: where a detector claims a bare ``Ltd`` spreads it to every other ``Ltd`` on the
#: page, which is not a second sighting of anything. It does not happen on the
#: corpus — no detector claims a bare legal form there — so this is a guard
#: against a case built to break it rather than one observed in the wild, and the
#: table is the shared one so a form known to ``suppress`` cannot be unknown here.
_EXCLUDED_VALUES = frozenset(form.casefold() for form in LEGAL_FORMS)

#: Propagated findings are marked with this suffix, so a report can distinguish
#: "the model saw this" from "we inferred this from an earlier mention".
DETECTOR_SUFFIX = "+propagated"


def propagate_known_values(
    text: str,
    findings: Sequence[Finding],
    *,
    min_length: int = MIN_PROPAGATION_LENGTH,
) -> list[Finding]:
    """Return ``findings`` plus the occurrences they imply.

    Confidence is inherited from the originating finding rather than invented:
    the evidence for the copy is exactly the evidence for the original.
    """
    if not findings:
        return list(findings)

    out = list(findings)
    occupied = [(f.span.start, f.span.end) for f in findings]

    # One entry per distinct value, keeping the most confident sighting as the
    # template. Sorted for determinism: two runs must produce identical output.
    templates: dict[str, Finding] = {}
    for finding in findings:
        value = finding.text.strip()
        if len(value) < min_length:
            continue
        if value.casefold().rstrip(".") in _EXCLUDED_VALUES:
            continue
        key = value.casefold()
        best = templates.get(key)
        if best is None or finding.confidence > best.confidence:
            templates[key] = finding

    for key in sorted(templates):
        template = templates[key]
        pattern = re.compile(rf"(?<!\w){re.escape(template.text.strip())}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            out.append(
                Finding(
                    span=Span(*span),
                    entity=template.entity,
                    text=text[match.start() : match.end()],
                    layer=template.layer,
                    detector=f"{template.detector}{DETECTOR_SUFFIX}",
                    confidence=template.confidence,
                    country=template.country,
                )
            )
    return sorted(out, key=lambda f: (f.span.start, f.span.end))

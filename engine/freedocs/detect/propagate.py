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
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..core.findings import Finding, Span

#: Values shorter than this are not propagated. Two- and three-character strings
#: ("AG", "SA", "Ltd") appear inside unrelated words and in every company name in
#: the document; spreading them would redact the page.
MIN_PROPAGATION_LENGTH = 5

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

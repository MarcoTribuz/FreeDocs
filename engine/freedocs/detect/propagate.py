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
from bisect import bisect_left, bisect_right, insort
from collections.abc import Iterable, Sequence

from ..core.findings import PROPAGATED_SUFFIX, Finding, Span
from ..core.policy import REPORT_ONLY
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
#: "the model saw this" from "we inferred this from an earlier mention". Defined
#: in :mod:`freedocs.core.findings` because ``suppress`` reads it too and this
#: module already imports from ``suppress``.
DETECTOR_SUFFIX = PROPAGATED_SUFFIX


def value_occurrences(text: str, value: str) -> list[tuple[int, int]]:
    """Every place ``value`` occurs as a whole value, up to case.

    One definition of that boundary, because two would be two answers to the
    same question - and both callers act on it: this module copies a finding
    onto each occurrence, and ``registry.displace_report_only`` decides whether
    a flagged finding is standing on one.

    ``[^\\W_]`` is a word character that is not an underscore, so a letter or a
    digit either side refuses and an underscore does not. That last part is what
    plain ``\\w`` got wrong: a filename is a sequence of words and ``_`` is what
    separates them, so ``SWICA`` sat inside
    ``2022-03-23_swica_resume_etude.pdf`` on a real document, removed everywhere
    else, and stage 6 counts substrings so it found the survivor and was right
    to. ``.`` and ``-`` were never the problem, being outside ``\\w`` already,
    and ``Zug`` still does not match inside ``Zugang``.
    """
    pattern = re.compile(rf"(?<![^\W_]){re.escape(value.strip())}(?![^\W_])", re.IGNORECASE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


class Occupied:
    """A set of half-open character ranges, asked "does this overlap any of them".

    Both passes that locate occurrences used to answer that with a scan of every
    range so far, once per occurrence, and on a dense document that is the whole
    cost: 1 MB of pasted text carrying one IBAN a line held 10 526 findings,
    ``displace_report_only`` built a list of 110 million ranges out of them and
    the inspect took 178 s and 14 GB. The ranges are kept merged and sorted, so a
    query is two bisections and the answer is the one the scan gave.
    """

    def __init__(self, spans: Iterable[tuple[int, int]] = ()) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []
        #: Empty ranges, kept apart because merging cannot represent them. The
        #: scan this replaced counted ``(p, p)`` as overlapping any query strictly
        #: around ``p``, and the answer must stay the one it gave.
        self._points: list[int] = []
        for start, end in spans:
            self.add(start, end)

    def overlaps(self, start: int, end: int) -> bool:
        # Merged and sorted, so the ends rise with the starts: the last range
        # starting before `end` is the one reaching furthest right of them.
        index = bisect_left(self._starts, end)
        if index > 0 and self._ends[index - 1] > start:
            return True
        point = bisect_right(self._points, start)
        return point < len(self._points) and self._points[point] < end

    def add(self, start: int, end: int) -> None:
        if start == end:
            insort(self._points, start)
            return
        if start > end:
            return
        # Every range overlapping [start, end) is folded into it, and a range
        # merely touching it is not. Folding [a, b) and [b, c) into [a, c) would
        # make an empty query at b overlap, which the scan said it did not.
        low = bisect_right(self._ends, start)
        high = bisect_left(self._starts, end)
        if low < high:
            start = min(start, self._starts[low])
            end = max(end, self._ends[high - 1])
        self._starts[low:high] = [start]
        self._ends[low:high] = [end]


def _placement_order(template: Finding, key: str) -> tuple[int, int, str]:
    """Which template gets first refusal on a stretch of characters.

    Placement settles a contest, so the order may not be the alphabet - which is
    what it was, for determinism, and determinism was the only requirement it
    met. On a real document ``employeur`` was a JOB_TITLE template and
    ``Etat-employeur`` an ORGANISATION one. ``employeur`` sorts first, took the
    characters, and the removable copy then found the span occupied and skipped
    it - so the company name stayed in the document with a flagged job title
    sitting on it. :func:`resolve_overlaps` would have settled that pair the
    other way, by span length, but it never saw the pair: the copy it would have
    preferred was never made.

    Two criteria and one tie-break. A ``REPORT_ONLY`` template never takes
    characters from a removable one, which is the rule already written down for
    overlaps - a flagged finding winning one stops a real value being removed.
    Then the longer value, which is what makes this order agree with the
    resolution that follows it rather than contradict it. The key last, so two
    runs still produce identical output.
    """
    return (1 if template.entity in REPORT_ONLY else 0, -len(key), key)


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
    occupied = Occupied((f.span.start, f.span.end) for f in findings)

    # One entry per distinct value, keeping the most confident sighting as the
    # template.
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

    for key in sorted(templates, key=lambda k: _placement_order(templates[k], k)):
        template = templates[key]
        for span in value_occurrences(text, template.text):
            if occupied.overlaps(*span):
                continue
            occupied.add(*span)
            out.append(
                Finding(
                    span=Span(*span),
                    entity=template.entity,
                    text=text[span[0] : span[1]],
                    layer=template.layer,
                    detector=f"{template.detector}{DETECTOR_SUFFIX}",
                    confidence=template.confidence,
                    country=template.country,
                )
            )
    return sorted(out, key=lambda f: (f.span.start, f.span.end))

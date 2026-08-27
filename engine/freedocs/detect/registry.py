"""Combines the detection layers into one non-overlapping set of findings.

Layers disagree, and they must: a checksum-validated IBAN and a NER model that
read the same digits as a phone number are both doing their job. Overlaps have
to be resolved before write-back, because two edits touching the same characters
cannot both be applied.

Resolution order, applied to each overlap:

1. Higher layer precedence wins (L1 validator > L2 NER > L3 LLM review).
2. Then the longer span, so "Via Roma 12, 6900 Lugano" beats "Lugano".
3. Then the higher confidence.
4. Then the earlier start, purely so the result is deterministic.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ..core.findings import Finding, Layer
from ..core.policy import REPORT_ONLY
from .addresses import fill_address_gaps
from .organisations import fill_organisation_gaps
from .propagate import propagate_known_values, value_occurrences
from .suppress import Suppression, drop_jurisdiction_mentions, drop_non_identifying
from .validators import CHECKSUM_VERIFIABLE, COUNTRY_ISSUED, confirms


class Detector(Protocol):
    """Anything that can find confidential data in a flat string."""

    def detect(self, text: str) -> list[Finding]: ...


def _sort_key(finding: Finding) -> tuple[int, int, float, int]:
    return (
        -finding.precedence,
        -len(finding.span),
        -finding.confidence,
        finding.span.start,
    )


#: Every type whose value is a number or code. A model claim of one of these
#: containing no digit at all is answerable without any checksum, which matters
#: because :func:`confirms` deliberately gives no opinion on a country-issued
#: type it has no country for.
_STRUCTURED = COUNTRY_ISSUED | CHECKSUM_VERIFIABLE


def drop_unconfirmed_structured(findings: Iterable[Finding]) -> list[Finding]:
    """Discard model claims about identifiers that a checksum rejects.

    A model asked for "credit card number" will sometimes oblige. GLiNER2
    labelled two chart amounts, ``1500`` and ``2300``, as a card number at 0.87
    confidence — high enough that no threshold separates it from a real finding,
    and Luhn settles it in one call. L1 findings are exempt: they *are* the
    checksum.

    A digit-free claim is refused first, and separately, because ``confirms``
    cannot refuse it: a country-issued type arriving without a country gets no
    opinion by design, so ``cittadinanza italiana`` came back NATIONAL_ID at 0.79
    and ``Turkish`` at 0.52 — both above ``Policy.min_confidence``, both removed,
    each replaced by ``[NATIONAL_ID_1]``. That is worse than a false positive: it
    deletes a sentence's meaning and reports a nationality as an identifier. No
    identifier this tool covers is written without a digit, and the corpus agrees
    — every annotated identifier in it contains one.
    """
    kept: list[Finding] = []
    for finding in findings:
        if finding.layer is Layer.VALIDATOR:
            kept.append(finding)
            continue
        if finding.entity in _STRUCTURED and not any(char.isdigit() for char in finding.text):
            continue
        verdict = confirms(finding.entity, finding.text, finding.country)
        if verdict is False:
            continue
        kept.append(finding)
    return kept


def resolve_overlaps(findings: Iterable[Finding]) -> list[Finding]:
    """Drop the weaker of every overlapping pair, keeping the result stable.

    Greedy by design: findings are considered strongest-first, and a finding is
    kept only if it touches nothing already kept. With a handful of layers over
    document-sized text this is fast enough to be uninteresting, and it is much
    easier to reason about than an interval tree.
    """
    kept: list[Finding] = []
    for finding in sorted(findings, key=_sort_key):
        if any(finding.span.overlaps(other.span) for other in kept):
            continue
        kept.append(finding)
    return sorted(kept, key=lambda f: f.span.start)


@dataclass
class DetectorRegistry:
    """Runs every configured detector and returns one coherent finding list."""

    detectors: list[Detector] = field(default_factory=list)
    #: Copy each confirmed value to its other occurrences in the document. On by
    #: default because every residual miss measured on the corpus was a repeat
    #: mention the model scored differently the second time.
    propagate: bool = True
    #: Limitations of this particular configuration, in plain language. Carried
    #: into the report so that a registry assembled without a layer cannot look
    #: like a registry that simply found nothing.
    notes: list[str] = field(default_factory=list)

    def add(self, detector: Detector) -> DetectorRegistry:
        self.detectors.append(detector)
        return self

    def detect(self, text: str) -> list[Finding]:
        """The findings to act on.

        Kept as the whole answer for every caller that has always had it -
        ``benchmark`` above all, where a changed signature would move measured
        numbers for a change that touched no detector.
        """
        return self.detect_with_suppressions(text)[0]

    def detect_with_suppressions(self, text: str) -> tuple[list[Finding], list[Suppression]]:
        """The findings to act on, and the occurrences deliberately left behind.

        The second half exists for stage 6. Verification searches for *values*
        while the two passes in :mod:`freedocs.detect.suppress` judge
        *occurrences*, so a city removed in a party's address and kept in the
        governing-law clause is a value the output still contains - reported as
        a leak, and nothing written, on a file where every rule did exactly what
        it was designed to do. That was found on a real document, not here.

        Only those two passes are declared, and widening the list reopens the
        hole this closes. Findings are dropped in three other places and none of
        them leaves characters in the output: ``drop_unconfirmed_structured``
        throws away a claim a checksum refused, which is a value nothing removed
        anywhere; ``resolve_overlaps`` throws away the loser of a contest whose
        winner covers the same characters; and ``fill_address_gaps`` absorbs a
        LOCATION into the ADDRESS that contains it. Allowing any of those would
        permit text in the output that nothing accounted for.

        Nothing is stored on the instance. One registry serves a whole session
        and a batch is more than one file, so a remembered list would check the
        second document against the first document's suppressions - the shape
        :meth:`freedocs.core.overrides.Override.for_path` exists to prevent.
        """
        suppressed: list[Suppression] = []
        raw: list[Finding] = []
        for detector in self.detectors:
            raw.extend(detector.detect(text))
        resolved = resolve_overlaps(drop_unconfirmed_structured(raw))
        # A company name nominated by its legal form is added only where nothing
        # else claimed those characters, so this runs after resolution rather
        # than as another detector: see `organisations.fill_organisation_gaps`
        # for what happened when it competed on equal terms.
        # Addresses first: the span is the largest of the three and it absorbs
        # the city the model returned instead of the whole thing, so the
        # organisation pass sees the characters already claimed.
        resolved = fill_address_gaps(text, resolved)
        resolved, dropped = drop_non_identifying(fill_organisation_gaps(text, resolved))
        suppressed.extend(dropped)
        # Before propagation, and that ordering is the whole mechanism: dropping
        # the flagged occurrence is what unoccupies those characters so the copy
        # can land on them with the removable label.
        resolved = displace_report_only(text, resolved)
        if not self.propagate:
            return resolved, _first_per_span(suppressed)
        # Propagate after resolution, so a value that lost an overlap contest is
        # not spread across the document under the wrong label. Resolve again
        # afterwards: a propagated span can still collide with a longer finding.
        #
        # Suppression is split across the two sides of propagation because the
        # two questions it answers behave differently. A value that identifies
        # nobody is filtered on both sides, so it cannot spread. A value that is
        # only unwanted *here* — a city in a governing-law clause — is filtered
        # afterwards only: it is still the sighting that lets propagation reach
        # the same city in the party's address. See `detect.suppress`.
        propagated = resolve_overlaps(propagate_known_values(text, resolved))
        kept, dropped = drop_non_identifying(propagated)
        suppressed.extend(dropped)
        kept, dropped = drop_jurisdiction_mentions(kept, text)
        suppressed.extend(dropped)
        return kept, _first_per_span(suppressed)


def displace_report_only(text: str, findings: Iterable[Finding]) -> list[Finding]:
    """Drop a flagged finding standing on an occurrence of a removable value.

    ``REPORT_ONLY`` means "say it is here, never delete it", and that holds for a
    value only ever seen as one of those types: a job title alone identifies
    nobody, and deleting one hides residual risk instead of surfacing it. It
    stops holding the moment the same characters are a company two paragraphs
    down. There the flagged sighting is one mislabelled occurrence, and leaving
    it produces a survivor with a clean-looking verification in front of it -
    stage 6 searches for *values*, so it finds the leftover and blames the
    removal that worked.

    The question is **overlap, not spelling**, and that distinction is the whole
    fix. ``Etat-employeur`` came back ORGANISATION at 0.87 in one sentence of a
    real document, and in the other the model claimed only the nine characters
    ``employeur`` as a JOB_TITLE. A first version of this rule compared the two
    findings' text, found ``employeur`` != ``Etat-employeur``, and left the case
    exactly as it was. What matters is that the flagged span sits inside the
    stretch propagation is about to claim - so occurrences are located with
    :func:`propagate.value_occurrences`, the same boundary propagation itself
    uses, because two definitions of it would be two answers.

    Ordering is load bearing: this runs *before* propagation, and unoccupying
    those characters is what lets the copy land on them with the removable label.

    Three things it deliberately does not do. It never runs the other way - a
    removable finding is never displaced by a flagged value elsewhere, which is
    the direction that would *create* the leak. It drops the whole flagged
    finding rather than the overlapping part, because a finding cannot be split;
    the cost is a lost flag where a real job title happened to contain a company
    name, which is a flag and never a removal. And a flagged finding overlapping
    nothing is untouched, which is the category doing its job.
    """
    findings = list(findings)
    claimed: list[tuple[int, int]] = []
    for finding in findings:
        if finding.entity not in REPORT_ONLY:
            claimed.extend(value_occurrences(text, finding.text))
    return [
        finding
        for finding in findings
        if not (
            finding.entity in REPORT_ONLY
            and any(finding.span.start < end and start < finding.span.end for start, end in claimed)
        )
    ]


def _first_per_span(suppressed: Iterable[Suppression]) -> list[Suppression]:
    """One entry per set of characters, keeping the rule that got there first.

    ``drop_non_identifying`` runs on both sides of propagation, and it has to:
    a value that identifies nobody must not spread, and a propagated copy must
    not survive the pass that would have dropped the original. So the same
    characters can be dropped twice - once as the model found them, once as
    propagation put them back. Counting both would permit the value twice in an
    output that contains it once, and the allowance is a count, so the spare one
    is a hole a failed write-back could sit in unnoticed.
    """
    seen: set[tuple[int, int]] = set()
    out: list[Suppression] = []
    for entry in suppressed:
        key = (entry.finding.span.start, entry.finding.span.end)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return sorted(out, key=lambda entry: entry.finding.span.start)


def summarise(findings: Sequence[Finding]) -> dict[str, int]:
    """Count findings per entity type, for the report and the CLI summary."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.entity.value] = counts.get(finding.entity.value, 0) + 1
    return dict(sorted(counts.items()))

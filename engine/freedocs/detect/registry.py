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
from .addresses import fill_address_gaps
from .organisations import fill_organisation_gaps
from .propagate import propagate_known_values
from .suppress import drop_jurisdiction_mentions, drop_non_identifying
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
        resolved = drop_non_identifying(fill_organisation_gaps(text, resolved))
        if not self.propagate:
            return resolved
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
        return drop_jurisdiction_mentions(drop_non_identifying(propagated), text)


def summarise(findings: Sequence[Finding]) -> dict[str, int]:
    """Count findings per entity type, for the report and the CLI summary."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.entity.value] = counts.get(finding.entity.value, 0) + 1
    return dict(sorted(counts.items()))

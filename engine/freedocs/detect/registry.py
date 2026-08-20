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

from ..core.findings import Finding


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

    def add(self, detector: Detector) -> DetectorRegistry:
        self.detectors.append(detector)
        return self

    def detect(self, text: str) -> list[Finding]:
        raw: list[Finding] = []
        for detector in self.detectors:
            raw.extend(detector.detect(text))
        return resolve_overlaps(raw)


def summarise(findings: Sequence[Finding]) -> dict[str, int]:
    """Count findings per entity type, for the report and the CLI summary."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.entity.value] = counts.get(finding.entity.value, 0) + 1
    return dict(sorted(counts.items()))

"""The six stages, in order, for one document.

    router -> extract -> detect -> policy -> write-back -> verify

Only this module knows the order. Handlers know their format, detectors know
their patterns, and neither knows about the other.

The allocator is closed in a ``finally`` block, so the placeholder-to-original
mapping is destroyed even when a stage raises. That is deliberate: a crashed run
must not leave a re-identification key in a live process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core.findings import Finding
from .core.policy import Action, Policy, SurrogateAllocator
from .core.stream import Edit
from .detect.registry import DetectorRegistry
from .detect.validators import ValidatorDetector
from .formats.base import FormatHandler, HiddenItem
from .formats.router import handler_for
from .verify import LeakDetected, VerifyResult, verify_output


@dataclass(frozen=True)
class Decision:
    """A finding plus what the policy decided to do about it."""

    finding: Finding
    action: Action
    replacement: str | None


@dataclass
class ScrubResult:
    source: Path
    format_name: str
    output: bytes
    decisions: list[Decision]
    hidden_removed: list[HiddenItem]
    verify: VerifyResult
    source_chars: int
    #: Compromises the format handler had to make. Never silently dropped.
    warnings: list[str] = field(default_factory=list)

    @property
    def removed(self) -> list[Finding]:
        return [d.finding for d in self.decisions if d.action in _REWRITING_ACTIONS]

    @property
    def reported(self) -> list[Finding]:
        return [d.finding for d in self.decisions if d.action is Action.REPORT]


_REWRITING_ACTIONS = frozenset({Action.REDACT, Action.SURROGATE})


def default_registry() -> DetectorRegistry:
    """The detector set for M0: checksum-backed validators only.

    L2 (NER) and L3 (LLM review) register themselves here in their milestones.
    Shipping L1 alone is honest rather than half-finished: it finds every
    structured identifier it claims to, and finds no names at all.
    """
    return DetectorRegistry([ValidatorDetector()])


@dataclass
class Scrubber:
    policy: Policy = field(default_factory=Policy)
    registry: DetectorRegistry = field(default_factory=default_registry)
    #: Raise on a failed leak check instead of returning the result. On by
    #: default because a caller who forgets to inspect ``verify.ok`` would
    #: otherwise ship a leaking file.
    strict: bool = True

    def scrub_file(self, path: Path) -> ScrubResult:
        return self.scrub(handler_for(path))

    def scrub(self, handler: FormatHandler) -> ScrubResult:
        hidden = handler.scrub_hidden()
        stream = handler.extract()
        findings = self.registry.detect(stream.text)

        allocator = SurrogateAllocator()
        try:
            decisions = self._decide(findings, allocator)
            edits = [
                Edit(span=d.finding.span, replacement=d.replacement)
                for d in decisions
                if d.replacement is not None
            ]
            output = handler.write_back(stream.plan_edits(edits))
        finally:
            allocator.close()

        removed = [d.finding for d in decisions if d.action in _REWRITING_ACTIONS]
        verify = verify_output(type(handler), handler.path, output, removed)

        result = ScrubResult(
            source=handler.path,
            format_name=handler.name,
            output=output,
            decisions=decisions,
            hidden_removed=hidden,
            verify=verify,
            source_chars=len(stream.text),
            warnings=list(handler.warnings),
        )
        if self.strict and not verify.ok:
            raise LeakDetected(verify)
        return result

    def _decide(self, findings: list[Finding], allocator: SurrogateAllocator) -> list[Decision]:
        decisions: list[Decision] = []
        for finding in findings:
            action = self.policy.action_for(finding)
            replacement: str | None = None
            if action in _REWRITING_ACTIONS:
                # M0 has no surrogate generator yet, so SURROGATE degrades to a
                # placeholder rather than silently keeping the real value.
                replacement = allocator.placeholder_for(finding.entity, finding.text)
            decisions.append(Decision(finding=finding, action=action, replacement=replacement))
        return decisions

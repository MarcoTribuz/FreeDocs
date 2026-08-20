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

from .core.errors import MissingDependency
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


#: Layer combinations addressable by name, for the CLI and the benchmark.
LAYER_SPECS = ("l1", "ner", "all")


def build_registry(spec: str = "l1") -> DetectorRegistry:
    """Assemble a registry from a layer name, optionally naming a NER backend.

    Accepts ``l1``, ``ner``, ``all``, and a ``ner:<backend>`` suffix form such as
    ``all:presidio``. Named combinations exist so the benchmark can measure one
    layer in isolation: a number for "L1 alone" is what makes a number for
    "L1 plus NER" mean anything, and measuring only the combination hides which
    layer regressed.
    """
    layer, _, backend = spec.partition(":")
    if layer == "l1":
        if backend:
            raise ValueError("the l1 layer has no backend to choose")
        return DetectorRegistry([ValidatorDetector()])
    if layer not in {"ner", "all"}:
        raise ValueError(
            f"unknown detector spec {spec!r}; expected one of {', '.join(LAYER_SPECS)}"
        )

    # Imported here, not at module scope: the NER backends pull in torch, and a
    # plain text scrub must not pay that import cost or fail without it.
    from .detect.ner import NerDetector

    ner = NerDetector(backend_name=backend) if backend else NerDetector()
    return DetectorRegistry([ValidatorDetector(), ner] if layer == "all" else [ner])


#: What the user loses when the NER layer is unavailable. Measured on the corpus:
#: L1 alone covers 36.9% of gold entities, L1 with GLiNER2 covers 99.0%.
NO_NER_NOTE = (
    "the NER layer is not installed, so names, organisations, locations, "
    "addresses and job titles are NOT being detected - install the 'ner' extra; "
    "measured coverage falls from 99% to 37% without it"
)


def default_registry() -> DetectorRegistry:
    """Every available layer, with any absence stated rather than hidden.

    ``all`` is the default because the measured difference is not marginal:
    checksums alone leave roughly two thirds of the confidential entities in a
    business document untouched. When the NER extra is missing the registry falls
    back to L1 and carries :data:`NO_NER_NOTE`, which reaches the report and the
    CLI. Degrading quietly would be the one outcome worse than refusing.
    """
    try:
        return build_registry("all")
    except MissingDependency:
        registry = build_registry("l1")
        registry.notes.append(NO_NER_NOTE)
        return registry


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
            # Handler compromises and detector-configuration gaps land in the
            # same place: both are things the output does not show on its own.
            warnings=list(handler.warnings) + list(self.registry.notes),
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

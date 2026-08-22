"""The stages, in order, for one document.

    router -> extract -> detect -> policy -> write-back -> verify -> [review]

Only this module knows the order. Handlers know their format, detectors know
their patterns, and neither knows about the other.

The review is in brackets because it is optional and changes nothing: it reads the
scrubbed text and reports what a human should look at. It is skipped when
verification failed, since nothing is written in that case and there would be no
file to review.

The allocator is closed in a ``finally`` block, so the placeholder-to-original
mapping is destroyed even when a stage raises. That is deliberate: a crashed run
must not leave a re-identification key in a live process.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .core.errors import MissingDependency
from .core.findings import Finding
from .core.overrides import Override
from .core.policy import Action, Policy, SurrogateAllocator, placeholder_labels
from .core.stream import Edit, TextStream
from .detect.llm_review import LlmReviewer, ReviewOutcome
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


@dataclass(frozen=True)
class Extraction:
    """What a file gave up before any detector looked at it.

    Split out so a caller can hold on to it: extracting a scanned PDF means
    OCRing every page, and a preview that is re-taken every time the user excuses
    one occurrence would pay that again for a file that has not changed.
    """

    format_name: str
    stream: TextStream
    hidden: list[HiddenItem]
    #: Compromises the handler had to make while reading. Never silently dropped.
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Inspection:
    """What would be removed, without writing anything."""

    extraction: Extraction
    findings: list[Finding]
    #: What the *configuration* has to say: the registry's notes and any value a
    #: caller asked to remove that is not in this document.
    #:
    #: Kept apart from the handler's own warnings rather than merged, because the
    #: two are collected at different times. A handler goes on warning during
    #: write-back — a placeholder shrunk to fit, a renamed sheet, an embedded
    #: workbook — so a snapshot taken at extraction time is complete for a
    #: preview and short for a scrub. Merging them here dropped three of those,
    #: and the tests said so.
    notes: list[str]

    @property
    def stream(self) -> TextStream:
        return self.extraction.stream

    @property
    def warnings(self) -> list[str]:
        """Everything a preview should say. Complete as of extraction."""
        return [*self.extraction.warnings, *self.notes]


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
    #: The optional review of the scrubbed text. ``None`` when nobody asked for
    #: one, which is not the same as a review that found nothing.
    review: ReviewOutcome | None = None

    @property
    def removed(self) -> list[Finding]:
        return [d.finding for d in self.decisions if d.action in _REWRITING_ACTIONS]

    @property
    def reported(self) -> list[Finding]:
        return [d.finding for d in self.decisions if d.action is Action.REPORT]


_REWRITING_ACTIONS = frozenset({Action.REDACT, Action.SURROGATE})


#: Layer combinations addressable by name, for the CLI and the benchmark.
LAYER_SPECS = ("l1", "ner", "all")


#: What a narrowed country selection costs, stated in the report rather than
#: left for the reader to remember. Measured on the corpus: every country on
#: covers 53.7% of the removable entities with L1 alone, Switzerland and Italy
#: alone 46.6%, and the difference is entirely identifiers and locally-written
#: phone numbers from the countries that were switched off.
def narrowed_note(countries: Sequence[str]) -> str:
    named = ", ".join(sorted(country.upper() for country in countries))
    return (
        f"identifiers and national phone numbers are only being looked for in: "
        f"{named} - numbers from any other country are NOT being detected by the "
        f"checksum layer"
    )


def build_registry(spec: str = "l1", *, countries: Sequence[str] | None = None) -> DetectorRegistry:
    """Assemble a registry from a layer name, optionally naming a NER backend.

    Accepts ``l1``, ``ner``, ``all``, and a ``ner:<backend>`` suffix form such as
    ``all:presidio``. Named combinations exist so the benchmark can measure one
    layer in isolation: a number for "L1 alone" is what makes a number for
    "L1 plus NER" mean anything, and measuring only the combination hides which
    layer regressed.

    ``countries`` narrows the checksum layer and the phone numbering plans to
    those countries. None means every supported country, which is the default
    everywhere: a caller obliged to name its countries to be safe would produce a
    silent leak by naming the wrong ones. A narrowed run says so in the registry
    notes, which reach the report and the window — the same channel a missing NER
    layer uses, and for the same reason.
    """
    layer, _, backend = spec.partition(":")
    selection = tuple(countries) if countries is not None else None
    if selection is not None and not selection:
        raise ValueError("no countries selected; omit the option to use all of them")

    def validator() -> ValidatorDetector:
        return ValidatorDetector(countries=selection)

    def with_notes(registry: DetectorRegistry) -> DetectorRegistry:
        if selection is not None:
            registry.notes.append(narrowed_note(selection))
        return registry

    if layer == "l1":
        if backend:
            raise ValueError("the l1 layer has no backend to choose")
        return with_notes(DetectorRegistry([validator()]))
    if layer not in {"ner", "all"}:
        raise ValueError(
            f"unknown detector spec {spec!r}; expected one of {', '.join(LAYER_SPECS)}"
        )

    # Imported here, not at module scope: the NER backends pull in torch, and a
    # plain text scrub must not pay that import cost or fail without it.
    from .detect.ner import NerDetector

    ner = NerDetector(backend_name=backend) if backend else NerDetector()
    # The NER layer is not narrowed: the model reads names and addresses and has
    # no notion of which country issued them, so a country selection has nothing
    # to say to it.
    return with_notes(DetectorRegistry([validator(), ner] if layer == "all" else [ner]))


#: What the user loses when the NER layer is unavailable. Measured on the corpus:
#: L1 alone covers 53.7% of the removable gold entities, L1 with GLiNER2 and
#: propagation covers 97.6%.
NO_NER_NOTE = (
    "the NER layer is not installed, so names, organisations, locations, "
    "addresses and job titles are NOT being detected - install the 'ner' extra; "
    "measured coverage falls from 98% to 54% without it"
)


def default_registry(countries: Sequence[str] | None = None) -> DetectorRegistry:
    """Every available layer, with any absence stated rather than hidden.

    ``all`` is the default because the measured difference is not marginal:
    checksums alone leave roughly two thirds of the confidential entities in a
    business document untouched. When the NER extra is missing the registry falls
    back to L1 and carries :data:`NO_NER_NOTE`, which reaches the report and the
    CLI. Degrading quietly would be the one outcome worse than refusing.
    """
    try:
        return build_registry("all", countries=countries)
    except MissingDependency:
        registry = build_registry("l1", countries=countries)
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
    #: Optional L3 review of the scrubbed text. Off by default: it takes tens of
    #: seconds, it needs a local model nobody is obliged to have, and it changes
    #: nothing in the output. It is a second opinion for a human, not a stage.
    reviewer: LlmReviewer | None = None
    #: What a caller decided after reading the preview: occurrences to leave alone
    #: and values to remove that no detector nominated. Empty by default, and
    #: applied between detection and policy rather than inside the registry — it
    #: is not a detector, and the registry has already resolved overlaps by the
    #: time a person has an opinion.
    overrides: Override = field(default_factory=Override)

    def scrub_file(self, path: Path) -> ScrubResult:
        return self.scrub(handler_for(path))

    def inspect_file(self, path: Path) -> Inspection:
        return self.detect_in(self.read(handler_for(path)))

    def read(self, handler: FormatHandler) -> Extraction:
        """Stages one and two: route and extract, hidden content included.

        Separated from detection so the expensive half can be reused. Note the
        order: ``scrub_hidden`` runs *before* ``extract``, because a scan's OCR
        layer is itself invisible text and dropping hidden content afterwards
        would throw away what this pipeline can redact properly.
        """
        hidden = handler.scrub_hidden()
        stream = handler.extract()
        return Extraction(
            format_name=handler.name,
            stream=stream,
            hidden=hidden,
            warnings=tuple(handler.warnings),
        )

    def detect_in(self, extraction: Extraction) -> Inspection:
        """Stage three plus the human's decisions, on text already extracted.

        One implementation, used by both the preview and the scrub. They used to
        be two, in two modules, which is how a preview comes to show findings the
        scrub that follows it does not agree with.
        """
        text = extraction.stream.text
        findings = self.overrides.apply(text, self.registry.detect(text))
        return Inspection(
            extraction=extraction,
            findings=findings,
            notes=[
                *self.registry.notes,
                # "Removed" and "was not there" look identical in the output, and
                # a caller who pasted a value expects to hear which happened.
                *(
                    f"the value {value!r} was asked to be removed but does not "
                    f"appear in this document"
                    for value in self.overrides.unmatched(text)
                ),
            ],
        )

    def scrub(self, handler: FormatHandler) -> ScrubResult:
        inspection = self.detect_in(self.read(handler))
        stream = inspection.stream
        findings = inspection.findings
        hidden = inspection.extraction.hidden

        allocator = SurrogateAllocator(placeholder_labels(self.policy.placeholder_locale))
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
        verify = verify_output(
            type(handler),
            handler.path,
            output,
            removed,
            kept=[kept.text for kept in self.overrides.keep],
        )

        result = ScrubResult(
            source=handler.path,
            format_name=handler.name,
            output=output,
            decisions=decisions,
            hidden_removed=hidden,
            verify=verify,
            source_chars=len(stream.text),
            # Read from the live handler, not from the extraction snapshot: a
            # handler warns during write-back too, and those are the warnings
            # that say a placeholder did not fit or a sheet was renamed.
            warnings=[*handler.warnings, *inspection.notes],
            review=self._review(verify),
        )
        if self.strict and not verify.ok:
            raise LeakDetected(verify)
        return result

    def _review(self, verify: VerifyResult) -> ReviewOutcome | None:
        """Ask the reviewer about the scrubbed text, if there is one to ask.

        Runs on the text ``verify`` already re-extracted from the output: that is
        both the right text — what a reader of the scrubbed file would see — and
        one already paid for, since re-extracting a scanned PDF would mean OCRing
        every page a third time.

        Skipped when verification failed. Nothing is written in that case, so a
        review would spend tens of seconds on a file that does not exist.
        """
        if self.reviewer is None or not verify.ok:
            return None
        return self.reviewer.review_outcome(verify.extracted)

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

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

An opt-in key file changes nothing here, and that is why this module does not
import ``core/mapping.py``. A caller who asked for one builds it from the
``ScrubResult`` this function returns, whose ``Decision`` rows carry the original
in ``finding.text`` and the placeholder in ``replacement``. So the reverse
direction is a front-end decision about a finished result, not a branch inside
the pipeline, and the line that destroys the allocator's mapping stays exactly
where it is. The reverse path itself lives in ``restore.py``, which knows its own
five stages and shares four of these names.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .core.errors import MissingDependency
from .core.findings import Finding
from .core.overrides import Override, TermsUse
from .core.policy import Action, Policy, SurrogateAllocator, placeholder_labels
from .core.stream import Edit, TextStream
from .detect.llm_review import LlmReviewer, ReviewOutcome
from .detect.registry import DetectorRegistry
from .detect.suppress import Suppression
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

    #: The handler that read it, kept because write-back goes through the same
    #: object: its parsed state is where the edits land.
    handler: FormatHandler
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
    #: What the *configuration* has to say: the registry's notes. Value-free, so
    #: they may travel anywhere a warning does, the report included.
    #:
    #: Kept apart from the handler's own warnings rather than merged, because the
    #: two are collected at different times. A handler goes on warning during
    #: write-back — a placeholder shrunk to fit, a renamed sheet, an embedded
    #: workbook — so a snapshot taken at extraction time is complete for a
    #: preview and short for a scrub. Merging them here dropped three of those,
    #: and the tests said so.
    notes: list[str]
    #: Occurrences the detection layer dropped on purpose and which therefore
    #: stay in the output: a city in a governing-law clause, a lowercase word
    #: that is also a company name. Carried out of the registry rather than
    #: recomputed, because stage 6 has to be told about exactly these and a
    #: second opinion about which they are would be a second rule.
    suppressed: list[Suppression] = field(default_factory=list)
    #: Values a caller asked to remove that appear nowhere in this document.
    #: Kept apart from ``notes`` because these *are* values: somebody thought
    #: each one confidential enough to name. They used to be folded into
    #: ``notes`` as a quoting sentence, and from there into ``ScrubResult.warnings``
    #: and the JSON report - so a value reached disk exactly when it was absent
    #: from the document it was reported against. One list of client names over
    #: a folder of contracts wrote most of that list into every report.
    unmatched: list[str] = field(default_factory=list)
    #: The term list's counts for this document, or ``None`` when no list was
    #: used - which is not the same as a list that matched nothing.
    terms: TermsUse | None = None

    @property
    def stream(self) -> TextStream:
        return self.extraction.stream

    @property
    def warnings(self) -> list[str]:
        """Everything a preview should say. Complete as of extraction.

        Quotes the unmatched values. A preview travels the local pipe, which
        already carries every matched value, and a caller who pasted a name
        needs to hear *which* one was not found.
        """
        return [*self.extraction.warnings, *self.notes, *map(unmatched_note, self.unmatched)]


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
    #: Occurrences left in the output on purpose. Reported rather than merely
    #: allowed: without this the change that stopped these failing verification
    #: would have turned a loud refusal into a silence, and a reader who is told
    #: nothing believes the city is gone from the document when it is not.
    suppressed: list[Suppression] = field(default_factory=list)
    #: Requested removals that matched nothing. Values, so the report carries
    #: only their count; see ``Inspection.unmatched``.
    unmatched: list[str] = field(default_factory=list)
    #: See ``Inspection.terms``.
    terms: TermsUse | None = None

    @property
    def caller_warnings(self) -> list[str]:
        """``warnings`` plus a sentence naming each unmatched value.

        For the console and the local pipe, which already carry matched text,
        and for nothing that reaches disk. ``build_report`` reads ``warnings``.
        """
        return [*self.warnings, *map(unmatched_note, self.unmatched)]

    @property
    def removed(self) -> list[Finding]:
        return [d.finding for d in self.decisions if d.action in _REWRITING_ACTIONS]

    @property
    def reported(self) -> list[Finding]:
        return [d.finding for d in self.decisions if d.action is Action.REPORT]


_REWRITING_ACTIONS = frozenset({Action.REDACT, Action.SURROGATE})


#: The stages, in the order this module runs them.
#:
#: Published only through the events a run emits, never as a list a caller can
#: draw a stepper from ahead of time: that stepper would be wrong for a run
#: without a review and wrong for every inspection, which runs three of these.
STAGES = ("router", "extract", "detect", "policy", "write-back", "verify")
REVIEW_STAGE = "review"

#: An inspection stops after detection. Reporting six stages and finishing at
#: three would be a bar that stops halfway and calls itself done.
INSPECT_STAGES = ("router", "extract", "detect")


@dataclass(frozen=True)
class StageEvent:
    """Where a run has got to.

    There is no ``percent`` field and there will not be one: how long detection
    takes next to extraction on a document nobody has seen is not a fact this
    module has. ``index``/``count`` counts *stages*, which is honest as such, and
    the field names are what stop a consumer turning it into a time estimate by
    accident.

    ``done``/``of`` are set only where a stage has a real unit to count — pages,
    so far — and left None elsewhere rather than filled with a guess.
    """

    stage: str
    index: int
    count: int
    done: int | None = None
    of: int | None = None
    detail: str = ""


ProgressFn = Callable[[StageEvent], None]


def unmatched_note(value: str) -> str:
    """The sentence for a requested removal that matched nothing.

    It quotes the value, so it belongs on a channel that already carries values
    and never in a report. "Removed" and "was not there" look identical in the
    output, which is why the caller is told at all.
    """
    return f"the value {value!r} was asked to be removed but does not appear in this document"


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


#: What each layer name covers, in the words the report already uses. Published
#: so a caller offering the choice can explain it instead of showing three
#: opaque strings, and kept beside LAYER_SPECS so a fourth spec cannot ship
#: unexplained — a test pins that the two agree.
LAYER_SPEC_NOTES: dict[str, str] = {
    "l1": (
        "checksums only: identifiers, IBANs, card numbers and phone numbers. "
        "Measured coverage of the removable entities in the corpus: 53.7%. Names, "
        "organisations, locations and addresses are NOT detected"
    ),
    "ner": (
        "the multilingual model only: names, organisations, locations, addresses "
        "and job titles, with no checksum to confirm a structured claim"
    ),
    "all": (
        "every layer, plus value propagation and the three correction passes. "
        "Measured coverage of the removable entities in the corpus: 99.6%"
    ),
}


def country_coverage(
    countries: Sequence[str] | None = None, min_confidence: float = 0.5
) -> dict[str, object]:
    """What each country actually gets, and what narrowing to some of them costs.

    Composed here rather than in the CLI or the RPC layer, because both need the
    same answer and "supported" means two different things: twelve countries have
    identifiers a checksum confirms, and the United States is in the list for its
    numbering plan and the model alone. An undifferentiated list of chips lets a
    reader believe a US social security number is checksum-confirmed, which is
    exactly the misreading ``freedocs countries`` was written to prevent.

    ``min_confidence`` is not applied to anything — it is used to say which rules
    a threshold has switched off. A rule below the threshold is inert unless a
    keyword is beside it, and that is the design; a slider over the threshold
    with no way to see what it silenced is a mystery control.
    """
    from .detect.validators import (
        MEDIUM_CHECK,
        STRONG_CHECK,
        SUPPORTED_COUNTRIES,
        WEAK_CHECK,
        build_rules,
    )

    try:
        rules = build_rules()
    except MissingDependency:
        rules = []

    selected = tuple(countries) if countries else None
    out = []
    for code in SUPPORTED_COUNTRIES:
        own = [rule for rule in rules if rule.country == code]
        out.append(
            {
                "code": code,
                "selected": selected is None or code in selected,
                # False for the United States, and the reason it is a separate
                # field: its numbers have no check digit at all, so `stdnum`
                # accepts 89% and 83% of random values of their shape.
                "checksum_confirmed": bool(own),
                "phone_plan": True,
                "entities": sorted({rule.entity.value for rule in own}),
                "rules": [
                    {
                        "name": rule.name,
                        "entity": rule.entity.value,
                        "confidence_without_context": rule.confidence_without_context,
                        "needs_context": rule.confidence_without_context < 1.0,
                        "inert_without_context": (rule.confidence_without_context < min_confidence),
                    }
                    for rule in own
                ],
                "detail": (None if own else "phone numbers and the NER layer only"),
            }
        )

    return {
        "default_min_confidence": 0.5,
        "min_confidence": min_confidence,
        "selected": list(selected) if selected else None,
        "excluded": [code for code in SUPPORTED_COUNTRIES if selected and code not in selected],
        # Said while the choice is being made, not afterwards in a report the
        # reader has already decided is clean.
        "note": narrowed_note(selected) if selected else None,
        "confidence_levels": [
            {
                "name": "strong",
                "value": STRONG_CHECK,
                "accepts": "under 1% of format-plausible values",
                "meaning": "redacted even with no keyword nearby",
            },
            {
                "name": "medium",
                "value": MEDIUM_CHECK,
                "accepts": "1% to 5%",
                "meaning": "redacted by default, dropped by any raised threshold",
            },
            {
                "name": "weak",
                "value": WEAK_CHECK,
                "accepts": "over 5%",
                "meaning": "found and reported, never redacted without a keyword nearby",
            },
        ],
        "countries": out,
    }


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
    #: Where to report stage progress. None means nobody is listening, which is
    #: the CLI and every test: the callback is optional so adding it changed no
    #: existing caller.
    progress: ProgressFn | None = None

    def scrub_file(self, path: Path) -> ScrubResult:
        return self.scrub(path)

    def inspect_file(self, path: Path) -> Inspection:
        return self.detect_in(self.read(path))

    def _announce(
        self,
        plan: Sequence[str],
        stage: str,
        *,
        done: int | None = None,
        of: int | None = None,
        detail: str = "",
    ) -> None:
        if self.progress is None:
            return
        self.progress(
            StageEvent(
                stage=stage,
                index=plan.index(stage) + 1,
                count=len(plan),
                done=done,
                of=of,
                detail=detail,
            )
        )

    def read(
        self, source: Path | FormatHandler, plan: Sequence[str] = INSPECT_STAGES
    ) -> Extraction:
        """Stages one and two: route and extract, hidden content included.

        Takes a path as well as a handler, so that routing happens *inside* the
        stage that reports it. A caller that opened the handler itself would be
        doing the router's work and the run would report a stage it never ran.

        Separated from detection so the expensive half can be reused. Note the
        order: ``scrub_hidden`` runs *before* ``extract``, because a scan's OCR
        layer is itself invisible text and dropping hidden content afterwards
        would throw away what this pipeline can redact properly.
        """
        if isinstance(source, Path):
            self._announce(plan, "router")
            handler = handler_for(source)
        else:
            handler = source

        self._announce(plan, "extract")
        handler.set_progress(
            lambda done, of, detail: self._announce(
                plan, "extract", done=done, of=of, detail=detail
            )
        )
        try:
            hidden = handler.scrub_hidden()
            stream = handler.extract()
        finally:
            # The handler outlives this method — `scrub` writes back through it —
            # and a callback left behind would report extraction progress during
            # a later stage.
            handler.set_progress(None)

        return Extraction(
            handler=handler,
            format_name=handler.name,
            stream=stream,
            hidden=hidden,
            warnings=tuple(handler.warnings),
        )

    def detect_in(self, extraction: Extraction, plan: Sequence[str] = INSPECT_STAGES) -> Inspection:
        """Stage three plus the human's decisions, on text already extracted.

        One implementation, used by both the preview and the scrub. They used to
        be two, in two modules, which is how a preview comes to show findings the
        scrub that follows it does not agree with.
        """
        self._announce(plan, "detect")
        text = extraction.stream.text
        detected, suppressed = self.registry.detect_with_suppressions(text)
        findings = self.overrides.apply(text, detected)
        return Inspection(
            extraction=extraction,
            findings=findings,
            suppressed=suppressed,
            notes=list(self.registry.notes),
            unmatched=self.overrides.unmatched(text),
            terms=self.overrides.terms_use(findings),
        )

    def scrub(self, source: Path | FormatHandler) -> ScrubResult:
        # Six stages, seven with a reviewer. The plan comes from this run rather
        # than from a constant, so a caller drawing a stepper from it cannot show
        # a review step for a run that has no reviewer.
        plan = (*STAGES, REVIEW_STAGE) if self.reviewer is not None else STAGES

        inspection = self.detect_in(self.read(source, plan), plan)
        handler = inspection.extraction.handler
        stream = inspection.stream
        findings = inspection.findings
        hidden = inspection.extraction.hidden

        self._announce(plan, "policy")
        allocator = SurrogateAllocator(placeholder_labels(self.policy.placeholder_locale))
        try:
            decisions = self._decide(findings, allocator)
            edits = [
                Edit(span=d.finding.span, replacement=d.replacement)
                for d in decisions
                if d.replacement is not None
            ]
            self._announce(plan, "write-back")
            output = handler.write_back(stream.plan_edits(edits))
        finally:
            allocator.close()

        self._announce(plan, "verify")
        removed = [d.finding for d in decisions if d.action in _REWRITING_ACTIONS]
        verify = verify_output(
            type(handler),
            handler.path,
            output,
            removed,
            # Two sources, one mechanism, and the discipline is the same for
            # both: an allowance is a count granted by something that named the
            # occurrence. A person naming one in the preview is the original
            # case; the suppression passes are the second, and they name spans
            # too. Nothing else may add to this list - see
            # `DetectorRegistry.detect_with_suppressions` for the three places
            # that drop a finding without leaving anything behind.
            kept=[
                *(kept.text for kept in self.overrides.keep),
                *(entry.finding.text for entry in inspection.suppressed),
            ],
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
            review=self._review(verify, plan),
            suppressed=inspection.suppressed,
            unmatched=inspection.unmatched,
            terms=inspection.terms,
        )
        if self.strict and not verify.ok:
            raise LeakDetected(verify)
        return result

    def _review(self, verify: VerifyResult, plan: Sequence[str] = STAGES) -> ReviewOutcome | None:
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
        self._announce(plan, REVIEW_STAGE)
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

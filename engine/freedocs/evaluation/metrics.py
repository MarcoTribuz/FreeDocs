"""Scoring, framed around what redaction actually needs.

Plain entity-level F1 is the wrong headline number for this tool. Two examples
show why:

* A detector predicts ``Rossi`` where the gold entity is ``Mario Rossi``. Under
  exact matching that is a miss, which is right, but under any partial-credit
  scheme it looks like a near-hit. For redaction it is a **leak**: the surname
  stays in the document and still identifies the person.
* A detector predicts ``LOCATION`` where the gold label is ``ADDRESS``. Exact
  matching calls it a miss on both counts. For redaction it is a **success**: the
  characters get removed either way.

So the primary metrics here are coverage-based and label-blind:

``leaks``
    Gold entities not *fully* covered by predicted spans. The safety number. One
    leak matters more than a hundred over-redactions.
``over_redacted_chars``
    Predicted characters that overlap no gold entity. The utility number: a
    detector that redacts the whole page leaks nothing and is useless.

Conventional exact precision/recall/F1 per entity type is reported alongside,
because it is what makes two models comparable to published figures.

One more split matters. Some entity types are ``REPORT_ONLY``: the policy flags
them and never removes them, because deleting a date or a job title hides residual
risk instead of surfacing it. Scoring those under "share fully removed" says
nothing true in either direction — a model that finds every job title has not made
the document safer, and one that finds none has not leaked. They were nearly a
tenth of the corpus and were silently inflating the headline, so coverage is
reported over the removable entities and the report-only ones are counted apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..core.findings import Finding
from ..core.policy import REPORT_ONLY
from .corpus import CorpusDocument, GoldEntity


def _coverage_mask(length: int, findings: Iterable[Finding]) -> bytearray:
    """One byte per character, 1 where some finding covers it."""
    mask = bytearray(length)
    for finding in findings:
        start = max(0, finding.span.start)
        end = min(length, finding.span.end)
        for index in range(start, end):
            mask[index] = 1
    return mask


def _is_covered(mask: bytearray, gold: GoldEntity) -> bool:
    return all(mask[index] for index in range(gold.span.start, gold.span.end))


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


@dataclass(frozen=True)
class EntityScore:
    """Per-entity-type tallies. ``exact`` requires both span and label to match."""

    entity: str
    gold: int = 0
    predicted: int = 0
    exact: int = 0
    covered: int = 0

    @property
    def precision(self) -> float:
        return self.exact / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.exact / self.gold if self.gold else 0.0

    @property
    def f1(self) -> float:
        return _f1(self.precision, self.recall)

    @property
    def coverage(self) -> float:
        """Share of gold entities fully removed, whatever label was assigned."""
        return self.covered / self.gold if self.gold else 0.0


@dataclass
class Evaluation:
    """The result of running one detector over one or more corpus documents."""

    documents: int = 0
    gold_total: int = 0
    predicted_total: int = 0
    #: Gold entities that survived, in corpus order. The list, not just a count:
    #: knowing *what* leaks is what tells you which layer to fix.
    leaks: list[tuple[str, GoldEntity]] = field(default_factory=list)
    over_redacted_chars: int = 0
    gold_chars: int = 0
    total_chars: int = 0
    per_entity: dict[str, EntityScore] = field(default_factory=dict)
    per_language: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Per issuing country: findings that landed on an annotation, and findings
    #: made. Precision, not coverage — the corpus annotates *what* a value is and
    #: never *whose* it is, so there is no per-country denominator to recall
    #: against. Precision is the half that answers the question a country
    #: selection actually raises: does switching this one on cost anything.
    per_country: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Gold entities the policy would actually remove, and how many of those were
    #: covered. Tracked separately because a REPORT_ONLY entity cannot leak: it is
    #: never removed by design, so counting it as covered or as a leak is noise.
    removable_gold: int = 0
    removable_covered: int = 0
    report_only_gold: int = 0
    report_only_covered: int = 0

    @property
    def covered_total(self) -> int:
        return self.gold_total - len(self.leaks)

    @property
    def coverage(self) -> float:
        """Share of *removable* gold entities fully removed. The safety number.

        Over the removable subset rather than everything, because the alternative
        lets a model score well on entities the tool was never going to touch.
        """
        return self.removable_covered / self.removable_gold if self.removable_gold else 0.0

    @property
    def coverage_all(self) -> float:
        """The same over every annotation, kept for comparison with older runs."""
        return self.covered_total / self.gold_total if self.gold_total else 0.0

    @property
    def report_only_recall(self) -> float:
        """Share of flag-only entities found. Not safety: whether the flag appears."""
        return self.report_only_covered / self.report_only_gold if self.report_only_gold else 0.0

    @property
    def over_redaction_rate(self) -> float:
        """Share of the document wrongly removed. The cost side of coverage."""
        return self.over_redacted_chars / self.total_chars if self.total_chars else 0.0

    @property
    def exact_f1(self) -> float:
        """Micro-averaged exact F1, for comparison with published numbers."""
        exact = sum(score.exact for score in self.per_entity.values())
        precision = exact / self.predicted_total if self.predicted_total else 0.0
        recall = exact / self.gold_total if self.gold_total else 0.0
        return _f1(precision, recall)


def evaluate(
    documents: Sequence[CorpusDocument],
    predict: object,
) -> Evaluation:
    """Score ``predict`` over ``documents``.

    ``predict`` is anything with ``detect(text) -> list[Finding]``, so a single
    detector, a registry of layers, or a whole pipeline can be measured with the
    same harness and the numbers stay comparable.
    """
    result = Evaluation()
    scores: dict[str, dict[str, int]] = {}

    def bump(entity: str, key: str, amount: int = 1) -> None:
        scores.setdefault(entity, {"gold": 0, "predicted": 0, "exact": 0, "covered": 0})
        scores[entity][key] += amount

    for document in documents:
        findings = predict.detect(document.text)  # type: ignore[attr-defined]
        mask = _coverage_mask(len(document.text), findings)
        gold_mask = _coverage_mask(
            len(document.text),
            [_as_finding(gold) for gold in document.entities],
        )

        result.documents += 1
        result.gold_total += len(document.entities)
        result.predicted_total += len(findings)
        result.total_chars += len(document.text)
        result.gold_chars += sum(gold_mask)
        result.over_redacted_chars += sum(
            1 for index in range(len(document.text)) if mask[index] and not gold_mask[index]
        )

        exact_pairs = {(f.span.start, f.span.end, f.entity.value) for f in findings}
        leaked_here = 0
        for gold in document.entities:
            label = gold.entity.value
            bump(label, "gold")
            if (gold.span.start, gold.span.end, label) in exact_pairs:
                bump(label, "exact")
            covered = _is_covered(mask, gold)
            if covered:
                bump(label, "covered")
            else:
                leaked_here += 1
                result.leaks.append((document.language, gold))
            if gold.entity in REPORT_ONLY:
                result.report_only_gold += 1
                result.report_only_covered += covered
            else:
                result.removable_gold += 1
                result.removable_covered += covered
        for finding in findings:
            bump(finding.entity.value, "predicted")
            if finding.country:
                on_gold, made = result.per_country.get(finding.country, (0, 0))
                hit = any(
                    gold.span.start < finding.span.end and finding.span.start < gold.span.end
                    for gold in document.entities
                )
                result.per_country[finding.country] = (on_gold + hit, made + 1)

        result.per_language[document.language] = (
            len(document.entities) - leaked_here,
            len(document.entities),
        )

    result.per_entity = {
        entity: EntityScore(entity=entity, **tallies) for entity, tallies in sorted(scores.items())
    }
    return result


def _as_finding(gold: GoldEntity) -> Finding:
    """Reuse the coverage-mask code for gold spans by wrapping them as findings."""
    from ..core.findings import Layer

    return Finding(
        span=gold.span,
        entity=gold.entity,
        text=gold.text,
        layer=Layer.VALIDATOR,
        detector="gold",
    )


def format_evaluation(result: Evaluation, title: str) -> str:
    """A console table. Coverage first, because coverage is the point."""
    lines = [
        f"{title}",
        f"  {result.documents} document(s), {result.gold_total} gold entities, "
        f"{result.predicted_total} predictions",
        "",
        f"  coverage        {result.coverage:6.1%}   "
        f"({result.removable_covered}/{result.removable_gold} removable entities fully removed)",
        f"  leaks           {result.removable_gold - result.removable_covered:6d}   "
        "removable entities left partly or wholly intact",
        f"  over-redaction  {result.over_redaction_rate:6.1%}   "
        f"({result.over_redacted_chars} chars removed that were not confidential)",
        f"  flag-only found {result.report_only_recall:6.1%}   "
        f"({result.report_only_covered}/{result.report_only_gold} reported, never removed)",
        f"  exact micro-F1  {result.exact_f1:6.3f}   span and label both correct",
        "",
        f"  {'entity':<22} {'gold':>5} {'pred':>5} {'cover':>7} {'P':>6} {'R':>6} {'F1':>6}",
    ]
    for score in result.per_entity.values():
        lines.append(
            f"  {score.entity:<22} {score.gold:>5} {score.predicted:>5} "
            f"{score.coverage:>7.1%} {score.precision:>6.2f} {score.recall:>6.2f} "
            f"{score.f1:>6.2f}"
        )

    if result.per_language:
        lines.append("")
        lines.append("  coverage by language")
        for language, (covered, total) in sorted(result.per_language.items()):
            share = covered / total if total else 0.0
            lines.append(f"    {language:<6} {share:>6.1%}  ({covered}/{total})")

    if result.per_country:
        lines.append("")
        lines.append("  precision by issuing country")
        # Precision only. The corpus says what a value is, never whose, so there
        # is no denominator to recall a country against — and precision is what
        # the question "should I switch this country on" actually asks.
        for country, (on_gold, made) in sorted(result.per_country.items()):
            share = on_gold / made if made else 0.0
            lines.append(
                f"    {country:<6} {share:>6.2f}  ({on_gold}/{made} landed on an annotation)"
            )

    if result.leaks:
        lines.append("")
        lines.append("  entities not fully covered")
        for language, gold in result.leaks:
            # Marked rather than dropped: a missed job title is worth seeing, but
            # calling it a leak would be wrong — the policy never removes one.
            note = "  (flag only, not a leak)" if gold.entity in REPORT_ONLY else ""
            lines.append(f"    {language:<4} {gold.entity.value:<22} {gold.text!r}{note}")
    return "\n".join(lines)

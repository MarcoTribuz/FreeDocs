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
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..core.findings import Finding
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

    @property
    def covered_total(self) -> int:
        return self.gold_total - len(self.leaks)

    @property
    def coverage(self) -> float:
        """The headline safety number: share of gold entities fully removed."""
        return self.covered_total / self.gold_total if self.gold_total else 0.0

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
            if _is_covered(mask, gold):
                bump(label, "covered")
            else:
                leaked_here += 1
                result.leaks.append((document.language, gold))
        for finding in findings:
            bump(finding.entity.value, "predicted")

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
        f"({result.covered_total}/{result.gold_total} gold entities fully removed)",
        f"  leaks           {len(result.leaks):6d}   gold entities left partly or wholly intact",
        f"  over-redaction  {result.over_redaction_rate:6.1%}   "
        f"({result.over_redacted_chars} chars removed that were not confidential)",
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

    if result.leaks:
        lines.append("")
        lines.append("  leaked entities")
        for language, gold in result.leaks:
            lines.append(f"    {language:<4} {gold.entity.value:<22} {gold.text!r}")
    return "\n".join(lines)

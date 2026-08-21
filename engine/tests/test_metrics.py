"""The scoring itself, checked against cases where F1 and safety disagree."""

from __future__ import annotations

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.evaluation.corpus import CorpusDocument, GoldEntity
from freedocs.evaluation.metrics import evaluate


class Fixed:
    """A detector that returns whatever it was constructed with."""

    def __init__(self, *findings: Finding) -> None:
        self._findings = list(findings)

    def detect(self, text: str) -> list[Finding]:
        return list(self._findings)


def gold(text: str, start: int, entity: EntityType) -> GoldEntity:
    return GoldEntity(span=Span(start, start + len(text)), entity=entity, text=text)


def found(text: str, start: int, entity: EntityType, score: float = 1.0) -> Finding:
    return Finding(
        span=Span(start, start + len(text)),
        entity=entity,
        text=text,
        layer=Layer.NER,
        detector="test",
        confidence=score,
    )


def document(text: str, *entities: GoldEntity) -> CorpusDocument:
    return CorpusDocument(name="t.txt", language="it", text=text, entities=entities)


TEXT = "Il cliente Mario Rossi vive a Lugano."
PERSON = gold("Mario Rossi", 11, EntityType.PERSON)
PLACE = gold("Lugano", 30, EntityType.LOCATION)


def test_exact_prediction_scores_perfectly():
    result = evaluate(
        [document(TEXT, PERSON, PLACE)],
        Fixed(
            found("Mario Rossi", 11, EntityType.PERSON), found("Lugano", 30, EntityType.LOCATION)
        ),
    )
    assert result.coverage == 1.0
    assert result.leaks == []
    assert result.over_redacted_chars == 0
    assert result.exact_f1 == 1.0


def test_a_partial_span_is_a_leak_not_a_near_miss():
    """ "Rossi" removed and "Mario" left behind still identifies the person."""
    result = evaluate([document(TEXT, PERSON)], Fixed(found("Rossi", 17, EntityType.PERSON)))
    assert result.coverage == 0.0
    assert [g.text for _, g in result.leaks] == ["Mario Rossi"]


def test_the_wrong_label_still_counts_as_covered():
    """For redaction the characters leave the document either way."""
    result = evaluate(
        [document(TEXT, PERSON)], Fixed(found("Mario Rossi", 11, EntityType.ORGANISATION))
    )
    assert result.coverage == 1.0
    assert result.leaks == []
    # ...but it is not an exact match, and the conventional number says so.
    assert result.exact_f1 == 0.0


def test_a_wider_span_covers_the_gold_and_costs_over_redaction():
    result = evaluate(
        [document(TEXT, PERSON)],
        Fixed(found("cliente Mario Rossi", 3, EntityType.PERSON)),
    )
    assert result.coverage == 1.0
    assert result.over_redacted_chars == len("cliente ")


def test_redacting_everything_leaks_nothing_and_is_still_bad():
    """Coverage alone can be gamed; over-redaction is why it is reported beside it."""
    result = evaluate([document(TEXT, PERSON, PLACE)], Fixed(found(TEXT, 0, EntityType.PERSON)))
    assert result.coverage == 1.0
    assert result.over_redaction_rate > 0.4


def test_detecting_nothing_leaks_everything():
    result = evaluate([document(TEXT, PERSON, PLACE)], Fixed())
    assert result.coverage == 0.0
    assert len(result.leaks) == 2
    assert result.over_redacted_chars == 0


def test_per_entity_tallies_are_kept_separately():
    result = evaluate(
        [document(TEXT, PERSON, PLACE)],
        Fixed(found("Mario Rossi", 11, EntityType.PERSON)),
    )
    assert result.per_entity["PERSON"].coverage == 1.0
    assert result.per_entity["LOCATION"].coverage == 0.0
    assert result.per_entity["PERSON"].recall == 1.0


def test_per_language_coverage_is_reported():
    documents = [
        CorpusDocument("it.txt", "it", TEXT, (PERSON,)),
        CorpusDocument("de.txt", "de", TEXT, (PERSON,)),
    ]
    result = evaluate(documents, Fixed(found("Mario Rossi", 11, EntityType.PERSON)))
    assert result.per_language == {"it": (1, 1), "de": (1, 1)}


def test_predictions_outside_the_text_do_not_crash_the_mask():
    """A backend returning an offset past the end must not take the run down."""
    result = evaluate(
        [document(TEXT, PERSON)], Fixed(found("x" * 5, len(TEXT) + 10, EntityType.PERSON))
    )
    assert result.coverage == 0.0
    assert result.over_redacted_chars == 0


# -- report-only entities are scored apart ------------------------------------

JOB = gold("direttore", 0, EntityType.JOB_TITLE)


def test_coverage_ignores_entities_the_policy_never_removes():
    """A found job title has not made the document safer, so it cannot flatter.

    JOB_TITLE is REPORT_ONLY: the policy flags it and leaves it in place. Counting
    it as covered was inflating the headline with work the pipeline does not do.
    """
    text = "direttore Mario Rossi a Lugano"
    person = gold("Mario Rossi", 10, EntityType.PERSON)
    result = evaluate(
        [CorpusDocument("it.txt", "it", text, (JOB, person))],
        Fixed(found("direttore", 0, EntityType.JOB_TITLE)),
    )
    # One removable entity, missed. Finding only the job title must not rescue it.
    assert result.removable_gold == 1
    assert result.coverage == 0.0
    assert result.report_only_gold == 1
    assert result.report_only_recall == 1.0


def test_a_missed_report_only_entity_is_not_counted_as_a_leak():
    text = "direttore Mario Rossi a Lugano"
    person = gold("Mario Rossi", 10, EntityType.PERSON)
    result = evaluate(
        [CorpusDocument("it.txt", "it", text, (JOB, person))],
        Fixed(found("Mario Rossi", 10, EntityType.PERSON)),
    )
    assert result.coverage == 1.0
    assert result.report_only_recall == 0.0


def test_coverage_over_everything_stays_available_for_comparison():
    """Older runs quoted the all-entity figure; it is kept rather than rewritten."""
    text = "direttore Mario Rossi a Lugano"
    person = gold("Mario Rossi", 10, EntityType.PERSON)
    result = evaluate(
        [CorpusDocument("it.txt", "it", text, (JOB, person))],
        Fixed(found("Mario Rossi", 10, EntityType.PERSON)),
    )
    assert result.coverage == 1.0
    assert result.coverage_all == 0.5

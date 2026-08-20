"""Overlap resolution: two edits can never touch the same characters."""

from __future__ import annotations

import pytest

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.registry import drop_unconfirmed_structured, resolve_overlaps, summarise


def make(
    start: int, end: int, entity: EntityType, layer: Layer, confidence: float = 1.0
) -> Finding:
    return Finding(
        span=Span(start, end),
        entity=entity,
        text="x" * (end - start),
        layer=layer,
        detector="test",
        confidence=confidence,
    )


def test_validator_beats_ner_on_the_same_span():
    """A checksum-confirmed IBAN outranks a model that read it as a phone number."""
    iban = make(0, 21, EntityType.IBAN, Layer.VALIDATOR)
    phone = make(0, 21, EntityType.PHONE, Layer.NER)
    assert resolve_overlaps([phone, iban]) == [iban]


def test_longer_span_wins_within_a_layer():
    full = make(0, 24, EntityType.ADDRESS, Layer.NER)
    part = make(18, 24, EntityType.LOCATION, Layer.NER)
    assert resolve_overlaps([part, full]) == [full]


def test_higher_confidence_wins_when_length_ties():
    weak = make(0, 10, EntityType.PERSON, Layer.NER, confidence=0.6)
    strong = make(0, 10, EntityType.PERSON, Layer.NER, confidence=0.9)
    assert resolve_overlaps([weak, strong]) == [strong]


def test_non_overlapping_findings_all_survive_in_position_order():
    second = make(20, 30, EntityType.EMAIL, Layer.VALIDATOR)
    first = make(0, 10, EntityType.IBAN, Layer.VALIDATOR)
    assert resolve_overlaps([second, first]) == [first, second]


def test_adjacent_findings_do_not_count_as_overlapping():
    left = make(0, 5, EntityType.PERSON, Layer.NER)
    right = make(5, 10, EntityType.PERSON, Layer.NER)
    assert len(resolve_overlaps([left, right])) == 2


def test_resolution_is_deterministic_regardless_of_input_order():
    findings = [
        make(0, 10, EntityType.PERSON, Layer.NER),
        make(5, 15, EntityType.ORGANISATION, Layer.NER),
        make(12, 20, EntityType.LOCATION, Layer.VALIDATOR),
    ]
    assert resolve_overlaps(findings) == resolve_overlaps(list(reversed(findings)))


def test_summarise_counts_per_entity():
    findings = [
        make(0, 5, EntityType.EMAIL, Layer.VALIDATOR),
        make(10, 15, EntityType.EMAIL, Layer.VALIDATOR),
        make(20, 25, EntityType.IBAN, Layer.VALIDATOR),
    ]
    assert summarise(findings) == {"EMAIL": 2, "IBAN": 1}


# -- checksum verification of model claims ------------------------------------


def make_text(text: str, entity: EntityType, layer: Layer) -> Finding:
    return Finding(
        span=Span(0, len(text)),
        entity=entity,
        text=text,
        layer=layer,
        detector="test",
        confidence=0.9,
    )


def test_a_model_claim_a_checksum_rejects_is_dropped():
    """GLiNER2 labelled two chart amounts as a card number at 0.87 confidence.

    No threshold separates that from a real finding; Luhn does, in one call.
    """
    pytest.importorskip("stdnum")
    bogus = make_text("1500\t2300", EntityType.CREDIT_CARD, Layer.NER)
    assert drop_unconfirmed_structured([bogus]) == []


def test_a_model_claim_a_checksum_accepts_is_kept():
    """The model may spot a real identifier the L1 pattern would not nominate."""
    pytest.importorskip("stdnum")
    real = make_text("4111111111111111", EntityType.CREDIT_CARD, Layer.NER)
    assert drop_unconfirmed_structured([real]) == [real]


def test_validator_findings_are_never_second_guessed():
    """They are the checksum; re-running it on them proves nothing."""
    finding = make_text("whatever", EntityType.IBAN, Layer.VALIDATOR)
    assert drop_unconfirmed_structured([finding]) == [finding]


def test_types_without_a_checksum_are_left_alone():
    """No validator covers a person's name, so there is no opinion to apply."""
    finding = make_text("Mario Rossi", EntityType.PERSON, Layer.NER)
    assert drop_unconfirmed_structured([finding]) == [finding]

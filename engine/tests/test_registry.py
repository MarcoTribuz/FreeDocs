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


def make_text(text: str, entity: EntityType, layer: Layer, country: str | None = None) -> Finding:
    return Finding(
        span=Span(0, len(text)),
        entity=entity,
        text=text,
        layer=layer,
        detector="test",
        confidence=0.9,
        country=country,
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


def test_a_digit_free_identifier_claim_is_refused():
    """``confirms`` cannot refuse this one, and the consequence is a bad edit.

    A country-issued type arriving from the model without a country gets no
    opinion by design, so ``cittadinanza italiana`` came back NATIONAL_ID at 0.79
    and ``Turkish`` at 0.52 — both above ``Policy.min_confidence``. Each was
    removed and replaced with ``[NATIONAL_ID_1]``, which destroys the sentence and
    files a nationality as an identifier.
    """
    for value in ("cittadinanza italiana", "Turkish", "nationalite algerienne"):
        finding = make_text(value, EntityType.NATIONAL_ID, Layer.NER)
        assert drop_unconfirmed_structured([finding]) == []


def test_a_digit_free_claim_is_refused_for_every_structured_type():
    for entity in (
        EntityType.TAX_ID,
        EntityType.VAT_ID,
        EntityType.COMPANY_ID,
        EntityType.IBAN,
        EntityType.CREDIT_CARD,
    ):
        finding = make_text("no digits here", entity, Layer.NER)
        assert drop_unconfirmed_structured([finding]) == []


def test_the_digit_rule_does_not_touch_a_free_text_type():
    """A person or a company is named in letters. Only the code types are numbers."""
    for entity in (EntityType.PERSON, EntityType.ORGANISATION, EntityType.LOCATION):
        finding = make_text("Nordwind Logistik", entity, Layer.NER)
        assert drop_unconfirmed_structured([finding]) == [finding]


def test_an_identifier_written_in_letters_and_digits_survives():
    """The codice fiscale is mostly letters, and it is still an identifier."""
    pytest.importorskip("stdnum")
    finding = make_text("RSSMRA85T10A562S", EntityType.TAX_ID, Layer.NER)
    assert drop_unconfirmed_structured([finding]) == [finding]


# -- checksum verification when the type belongs to a country ------------------


def test_a_country_issued_claim_without_a_country_is_left_alone():
    """`TAX_ID` covers twelve countries here and none of the other hundred-odd.

    A Brazilian CPF a model correctly spotted passes no check digit this build
    knows, and "nobody we cover accepts it" is not evidence against a number from
    a country nobody taught us. Without a country there is no opinion to give.
    """
    pytest.importorskip("stdnum")
    cpf = make_text("123.456.789-09", EntityType.TAX_ID, Layer.NER)
    assert drop_unconfirmed_structured([cpf]) == [cpf]


def test_a_country_issued_claim_with_a_country_is_checked_against_it():
    pytest.importorskip("stdnum")
    from .conftest import CANARIES

    real = make_text(CANARIES["IT_CODICE_FISCALE"], EntityType.TAX_ID, Layer.NER, "it")
    assert drop_unconfirmed_structured([real]) == [real]

    wrong_check_digit = make_text("RSSMRA85T10A562A", EntityType.TAX_ID, Layer.NER, "it")
    assert drop_unconfirmed_structured([wrong_check_digit]) == []


def test_a_country_we_have_no_rule_for_yields_no_opinion():
    """Naming a country is not the same as covering it."""
    pytest.importorskip("stdnum")
    finding = make_text("12345678901", EntityType.TAX_ID, Layer.NER, "br")
    assert drop_unconfirmed_structured([finding]) == [finding]


def test_the_country_neutral_types_still_need_no_country():
    """Mod-97 and Luhn do not care where the number was issued.

    This is the half that must not regress: the card rule is the reason this
    whole mechanism exists, and its findings never carry a country.
    """
    pytest.importorskip("stdnum")
    bogus = make_text("1500\t2300", EntityType.CREDIT_CARD, Layer.NER)
    assert drop_unconfirmed_structured([bogus]) == []
    dashed = make_text("CH93-0076-2011-6238-5295-7", EntityType.IBAN, Layer.NER)
    assert drop_unconfirmed_structured([dashed]) == [dashed]

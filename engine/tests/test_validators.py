"""L1: does each checksum-backed rule find its canary and reject near misses?"""

from __future__ import annotations

import pytest

from freedocs.core.findings import EntityType, Layer

pytest.importorskip("stdnum", reason="python-stdnum is required for the L1 layer")

from freedocs.detect.validators import ValidatorDetector

from .conftest import CANARIES, NEAR_MISSES


@pytest.fixture(scope="module")
def detector() -> ValidatorDetector:
    return ValidatorDetector()


@pytest.mark.parametrize("entity,value", sorted(CANARIES.items()))
def test_each_canary_is_detected(
    detector: ValidatorDetector, entity: str, value: str, document: str
):
    found = detector.detect(document)
    matched = [f for f in found if f.entity.value == entity]
    assert matched, f"{entity} canary {value!r} was not detected"
    # The span must cover the value, or write-back would corrupt the document.
    assert any(value in f.text or f.text in value for f in matched)


def test_detected_spans_match_the_document_text(detector: ValidatorDetector, document: str):
    """A span that disagrees with its text would splice the wrong characters."""
    for finding in detector.detect(document):
        assert document[finding.span.start : finding.span.end] == finding.text


@pytest.mark.parametrize("value", NEAR_MISSES)
def test_near_misses_are_rejected(detector: ValidatorDetector, value: str):
    text = f"Riferimento: {value} - fine"
    findings = detector.detect(text)
    offenders = [f for f in findings if value in f.text]
    assert not offenders, f"{value!r} failed its checksum but was reported as {offenders}"


def test_all_findings_are_layer_one(detector: ValidatorDetector, document: str):
    assert {f.layer for f in detector.detect(document)} == {Layer.VALIDATOR}


def test_partita_iva_without_context_is_low_confidence(detector: ValidatorDetector):
    """Eleven digits passing an 11-digit Luhn is weak evidence on its own."""
    bare = detector.detect(f"Riga 4 {CANARIES['IT_PARTITA_IVA']} 250 pezzi")
    matches = [f for f in bare if f.entity is EntityType.IT_PARTITA_IVA]
    assert matches and all(f.confidence < 1.0 for f in matches)

    with_context = detector.detect(f"Partita IVA {CANARIES['IT_PARTITA_IVA']}")
    matches = [f for f in with_context if f.entity is EntityType.IT_PARTITA_IVA]
    assert matches and all(f.confidence == 1.0 for f in matches)


def test_clean_text_produces_nothing(detector: ValidatorDetector):
    assert detector.detect("Il preventivo per il progetto e stato approvato in riunione.") == []


def test_phone_number_is_detected():
    detector = ValidatorDetector()
    pytest.importorskip("phonenumbers")
    findings = detector.detect("Chiamare il +41 44 668 18 00 entro venerdi.")
    assert any(f.entity is EntityType.PHONE for f in findings)


@pytest.mark.parametrize("date", ["03.03.2024", "15/04/2024", "2024-04-15", "1.12.2023"])
def test_dates_are_not_mistaken_for_phone_numbers(detector: ValidatorDetector, date: str):
    """Under the looser VALID leniency the IT plan reads dot-dates as numbers."""
    findings = detector.detect(f"Ordine 90210 del {date}, 250 pezzi")
    assert not [f for f in findings if f.entity is EntityType.PHONE]


def test_national_format_number_is_still_detected(detector: ValidatorDetector):
    """Strict grouping must not cost us correctly written local numbers."""
    findings = detector.detect("Ufficio di Roma: 06 6982 1234")
    assert any(f.entity is EntityType.PHONE for f in findings)


def test_iban_is_detected_when_followed_by_other_digits(detector: ValidatorDetector):
    """The IBAN pattern is greedy; mod-97 has to decide where it ends."""
    findings = detector.detect(f"IBAN {CANARIES['IBAN']} importo 4500 EUR")
    ibans = [f for f in findings if f.entity is EntityType.IBAN]
    assert len(ibans) == 1
    assert ibans[0].text == CANARIES["IBAN"]

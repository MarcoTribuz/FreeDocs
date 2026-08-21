"""L1: does each checksum-backed rule find its canary and reject near misses?"""

from __future__ import annotations

import pytest

from freedocs.core.findings import EntityType, Layer

pytest.importorskip("stdnum", reason="python-stdnum is required for the L1 layer")

from freedocs.detect.validators import ValidatorDetector

from .conftest import CANARIES, CANARY_TYPES, NEAR_MISSES


@pytest.fixture(scope="module")
def detector() -> ValidatorDetector:
    return ValidatorDetector()


@pytest.mark.parametrize("canary,value", sorted(CANARIES.items()))
def test_each_canary_is_detected(
    detector: ValidatorDetector, canary: str, value: str, document: str
):
    entity, country = CANARY_TYPES[canary]
    found = detector.detect(document)
    matched = [f for f in found if f.entity.value == entity]
    assert matched, f"{canary} canary {value!r} was not detected as {entity}"
    # The span must cover the value, or write-back would corrupt the document.
    covering = [f for f in matched if value in f.text or f.text in value]
    assert covering
    # And the finding must say which country issued it, or the report cannot.
    assert {f.country for f in covering} == {country}


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
    matches = [f for f in bare if f.entity is EntityType.VAT_ID]
    assert matches and all(f.confidence < 1.0 for f in matches)

    with_context = detector.detect(f"Partita IVA {CANARIES['IT_PARTITA_IVA']}")
    matches = [f for f in with_context if f.entity is EntityType.VAT_ID]
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Vedi https://a.example/x.", "https://a.example/x"),
        ("Vedi https://a.example/x, poi chiudi.", "https://a.example/x"),
        ("Portale https://a.example/ attivo", "https://a.example/"),
        ("Riferimento (https://a.example/p) allegato", "https://a.example/p"),
        ("Query https://a.example/s?q=1&r=2.", "https://a.example/s?q=1&r=2"),
    ],
)
def test_a_url_does_not_swallow_the_punctuation_after_it(
    detector: ValidatorDetector, text: str, expected: str
):
    """Running greedily to the next space took the full stop with the address.

    The replacement then ate the punctuation as well, and the span never matched
    the corpus annotation, which is how this was found. A trailing slash is part
    of the URL and has to survive.
    """
    urls = [f for f in detector.detect(text) if f.entity is EntityType.URL]
    assert [f.text for f in urls] == [expected]


# -- narrowing the rule set by country ----------------------------------------


def test_narrowing_to_a_country_keeps_the_country_neutral_rules():
    """An IBAN, a card number and an email address are the same everywhere.

    Only the country-tied rules may be switched off, or narrowing the selection
    would quietly stop detecting things that have nothing to do with the choice.
    """
    from freedocs.detect.validators import build_rules

    narrowed = build_rules(["it"])
    assert {rule.country for rule in narrowed} == {None, "it"}
    neutral = {rule.name for rule in build_rules([])}
    assert neutral == {rule.name for rule in narrowed if rule.country is None}
    assert "iban-mod97" in neutral


def test_narrowing_preserves_rule_order():
    """Order is load-bearing: IBAN must be nominated before the digits inside it.

    Filtering a list cannot reorder it, and this pins that property so a future
    rewrite into a dict or a per-country registry cannot silently lose it.
    """
    from freedocs.detect.validators import build_rules

    everything = [rule.name for rule in build_rules()]
    for selection in ([], ["ch"], ["it"], ["ch", "it"]):
        kept = [rule.name for rule in build_rules(selection)]
        assert kept == [name for name in everything if name in set(kept)]


def test_a_country_is_matched_case_insensitively():
    from freedocs.detect.validators import build_rules

    assert [rule.name for rule in build_rules(["CH"])] == [
        rule.name for rule in build_rules(["ch"])
    ]


def test_narrowing_the_detector_stops_finding_the_other_country(document: str):
    """The Swiss canary must disappear when only Italy is asked for."""
    italian_only = ValidatorDetector(countries=("it",))
    entities = {f.entity for f in italian_only.detect(document)}
    assert EntityType.TAX_ID in entities
    assert EntityType.NATIONAL_ID not in entities
    assert EntityType.IBAN in entities


def test_an_explicit_rule_list_wins_over_the_country_selection():
    """A caller handing over rules has already made the choice."""
    from freedocs.detect.validators import build_rules

    only_iban = [rule for rule in build_rules() if rule.name == "iban-mod97"]
    detector = ValidatorDetector(rules=only_iban, countries=("de",))
    assert detector.rules == only_iban


# -- context vocabulary --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Die Firmenkarte 5454545454545454 lautet auf Ursula Hofer.",
        "Zugeteilte Zahlungskarten: 5454545454545454",
        "Payment cards issued: 5454545454545454",
        "Cartes de paiement attribuees: 5454545454545454",
        "Kreditkarte 5454545454545454",
    ],
)
def test_a_context_stem_is_found_inside_a_compound_or_a_plural(
    detector: ValidatorDetector, text: str
):
    """German glues the word to another one and every language inflects it.

    All five of these appear in the corpus, and requiring a whole word lost every
    one of them: `karte` is the tail of `Firmenkarte`, and `card` is a prefix of
    `cards`. This is why stems are matched as substrings.
    """
    cards = [f for f in detector.detect(text) if f.entity is EntityType.CREDIT_CARD]
    assert cards, "no card detected at all"
    assert cards[0].confidence == 1.0


@pytest.mark.parametrize(
    "text",
    [
        "Il pacco arriva domani, rif 00743110157 in fattura.",
        "Nel salvataggio 00743110157 va controllato.",
    ],
)
def test_a_context_code_does_not_fire_inside_an_ordinary_word(
    detector: ValidatorDetector, text: str
):
    """`iva` inside `arriva`, `vat` inside `salvataggio`.

    Eleven digits passing an eleven-digit Luhn is weak evidence, and an unrelated
    verb is not the corroboration the rule is asking for. Codes are therefore
    matched as whole words, unlike the stems above.
    """
    matched = [f for f in detector.detect(text) if f.entity is EntityType.VAT_ID]
    assert matched, "the candidate should still be nominated, only with less confidence"
    assert matched[0].confidence == pytest.approx(0.55)


@pytest.mark.parametrize(
    "text",
    [
        "Partita IVA 00743110157 del fornitore.",
        "P.IVA 00743110157 del fornitore.",
        "VAT 00743110157 supplier.",
        "MWST 00743110157",
    ],
)
def test_a_context_code_still_fires_when_it_stands_alone(detector: ValidatorDetector, text: str):
    """Including when punctuation surrounds it: `\\b` after the dot in `p.iva`
    would demand a word character that is not there, which is why the pattern
    uses lookarounds."""
    matched = [f for f in detector.detect(text) if f.entity is EntityType.VAT_ID]
    assert matched and matched[0].confidence == 1.0

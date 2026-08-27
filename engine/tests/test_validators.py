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
    """A value that fails its check digit must not be reported as that identifier.

    Scoped to the checksum-backed types on purpose. `36574261800` is a German
    IdNr with the last digit changed, both tax checksums refuse it, and the
    Italian numbering plan then recognises it as a dialable mobile number —
    which it is, `365` being a real prefix. That is a different claim by a
    different detector for its own good reason, and the corpus already carries
    the same phenomenon as a documented trap: an eight-digit customer number
    that is a valid Italian landline, which is half of why PHONE precision sits
    at 0.83. Asserting it away here would be asserting that the world is tidier
    than it is.
    """
    from freedocs.detect.validators import CHECKSUM_VERIFIABLE

    text = f"Riferimento: {value} - fine"
    findings = detector.detect(text)
    offenders = [f for f in findings if value in f.text and f.entity in CHECKSUM_VERIFIABLE]
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The case from a real document: a footnote's hyperlink target, which
        # `add_relationship_targets` anchors out of `word/_rels`. It carries the
        # author's Windows account name, which no amount of reading the visible
        # document reveals.
        (
            "Fonte file:///C:\\Users\\eigenheerk\\Downloads\\etude.pdf consultata",
            "file:///C:\\Users\\eigenheerk\\Downloads\\etude.pdf",
        ),
        ("Vedi file:///home/mario/relazione.docx.", "file:///home/mario/relazione.docx"),
        ("Allegato (file:///srv/dati/x.pdf) accluso", "file:///srv/dati/x.pdf"),
    ],
)
def test_a_local_file_url_is_an_address_too(detector: ValidatorDetector, text: str, expected: str):
    """`file://` is a URL scheme and the rule read only `http` and `https`.

    Found on a document whose footnotes carried three web links, all removed,
    beside a `file:///C:\\Users\\<account>\\...` target that was not - so the
    scrub took the harmless addresses and left the one naming a person. The
    backslashes are why this is not covered by the existing pattern by accident:
    a Windows path has none of the characters the rule ends on.
    """
    urls = [f for f in detector.detect(text) if f.entity is EntityType.URL]
    assert [f.text for f in urls] == [expected]


def test_a_bare_windows_path_is_not_claimed(detector: ValidatorDetector):
    """A stated gap, pinned so it cannot be mistaken for coverage.

    `C:\\Users\\name\\file.pdf` with no scheme, and a UNC `\\\\server\\share\\name`,
    both name a person as surely as the `file://` form does and neither is a
    URL. Covering them means an entity type of their own - a new member, a label
    in four locales, corpus annotations - and there is no corpus case for it
    yet. `formats/ooxml/common.py` already names UNC targets as a place
    usernames hide; this is where that gap is recorded.
    """
    text = "Copia in C:\\Users\\eigenheerk\\Downloads\\etude.pdf e su \\\\srv01\\share\\kolb"
    assert [f for f in detector.detect(text) if f.entity is EntityType.URL] == []


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


# -- phone numbers -------------------------------------------------------------


def test_an_international_number_needs_no_region(detector: ValidatorDetector):
    """Which is why one region-less pass replaces N passes for this whole class.

    A number written with its own country code is unambiguous, so any region
    argument parses it — including None. Verified across the supported plans:
    every one of them matches `+41 44 123 45 67`.
    """
    findings = [
        f
        for f in detector.detect("Anruf unter +41 44 123 45 67 heute")
        if f.entity is EntityType.PHONE
    ]
    assert [f.detector for f in findings] == ["phonenumbers-international"]
    # No country: the prefix already says where it is from, and claiming to know
    # would be this rule's opinion rather than the number's.
    assert findings[0].country is None


@pytest.mark.parametrize(
    ("text", "region"),
    [
        ("Direktwahl 044 910 55 66 intern", "ch"),
        ("Zentrale 030 26550 in Hamburg", "de"),
        ("Linea diretta 02 8632 1470 senza prefisso", "it"),
        ("Direct line 020 7183 8750 without a country code", "gb"),
    ],
)
def test_a_locally_written_number_is_only_found_by_a_national_plan(
    detector: ValidatorDetector, text: str, region: str
):
    """The region-less pass finds none of these, which is what the plans buy.

    Measured on the corpus: the region-less pass alone reaches 82.9% PHONE
    coverage at precision 1.00, all thirteen plans reach 97.1% at 0.67. The
    coverage is the side that matters here — a number a scrub leaves behind is a
    leak, and a document written by a local for locals is full of them.
    """
    phones = [f for f in detector.detect(text) if f.entity is EntityType.PHONE]
    assert phones, "no phone found at all"
    assert phones[0].detector != "phonenumbers-international"
    # Several plans can read the same digits; only one finding may come out.
    assert len(phones) == 1


def test_two_plans_reading_the_same_digits_produce_one_finding(
    detector: ValidatorDetector,
):
    """`044 910 55 66` is claimed by the Swiss, German and Swedish plans.

    They do not agree on where the number ends, so the old dedup on an identical
    span let the near-misses through, and they reached the registry as an
    intra-L1 contest at equal precedence and equal confidence, settled by span
    start. One set of digits is one phone number.
    """
    phones = [
        f
        for f in detector.detect("Direktwahl 044 910 55 66 intern")
        if f.entity is EntityType.PHONE
    ]
    assert len(phones) == 1
    assert phones[0].text == "044 910 55 66"


def test_narrowing_the_countries_narrows_the_numbering_plans():
    swiss_only = ValidatorDetector(countries=("ch",))
    assert swiss_only.phone_regions == ("CH",)
    findings = [
        f
        for f in swiss_only.detect("Linea diretta 02 8632 1470 senza prefisso")
        if f.entity is EntityType.PHONE
    ]
    assert not findings, "the Italian plan should not be consulted for a Swiss-only run"


def test_the_supported_countries_and_the_rules_agree():
    """Every country with a rule must be listed, and the extras explained.

    `SUPPORTED_COUNTRIES` drives the CLI's validation, the RPC `capabilities`
    answer and the chips in the window, so a country with rules that is missing
    from it is unreachable, and one in it with no rules has to be there for a
    reason. The United States is the only such case: a numbering plan and the
    model, no checksum. See the labels in backends/gliner_backend.
    """
    from freedocs.detect.validators import SUPPORTED_COUNTRIES, build_rules

    with_rules = {rule.country for rule in build_rules() if rule.country}
    assert with_rules <= set(SUPPORTED_COUNTRIES)
    assert set(SUPPORTED_COUNTRIES) - with_rules == {"us"}
    assert list(SUPPORTED_COUNTRIES) == sorted(SUPPORTED_COUNTRIES)

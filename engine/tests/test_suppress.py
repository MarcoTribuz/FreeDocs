"""What the suppression passes must remove, and what they must never touch.

Suppression is the one kind of rule that can turn a working scrub into a leak, so
these tests are written from the leak side first: every case where a value stays
comes before the cases where it goes.
"""

from __future__ import annotations

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.suppress import (
    LEGAL_FORMS,
    drop_jurisdiction_mentions,
    drop_non_identifying,
)


def finding(text: str, entity: EntityType, start: int = 0) -> Finding:
    return Finding(
        span=Span(start, start + len(text)),
        entity=entity,
        text=text,
        layer=Layer.NER,
        detector="test",
        confidence=0.9,
    )


def located_in(text: str, value: str, entity: EntityType = EntityType.LOCATION) -> Finding:
    return finding(value, entity, start=text.index(value))


# ── What must survive ────────────────────────────────────────────────────────


def test_a_city_is_kept():
    """The corpus annotates thirty cities. None of them may be suppressed."""
    for city in ("Lugano", "Basel", "Firenze", "Geneve", "Zug", "Preston"):
        kept = drop_non_identifying([finding(city, EntityType.LOCATION)])
        assert [f.text for f in kept] == [city]


def test_a_city_state_is_kept_because_the_name_is_ambiguous():
    """Luxembourg names a city as often as a country; dropping it is a leak."""
    for name in ("Luxembourg", "Monaco", "Singapore", "San Marino", "Andorra"):
        assert drop_non_identifying([finding(name, EntityType.LOCATION)])


def test_a_capitalised_company_name_is_kept():
    for name in ("Alpin Treuhand AG", "Northwind Polska sp. z o.o.", "Northwind Group"):
        assert drop_non_identifying([finding(name, EntityType.ORGANISATION)])


def test_a_lowercase_name_carrying_a_legal_form_is_kept():
    """A legal form is stronger evidence than a lowercase first letter."""
    kept = drop_non_identifying([finding("sp. z o.o.", EntityType.ORGANISATION)])
    assert kept


def test_checksum_backed_types_are_never_looked_at():
    """A suppression rule that second-guesses a check digit is a bug."""
    identifier = finding("CHE-116.281.710", EntityType.COMPANY_ID)
    assert drop_non_identifying([identifier]) == [identifier]


def test_an_address_in_a_governing_law_document_still_goes():
    """A party's own address is not a jurisdiction, whatever else the page says.

    The clause and the address sit in the same document and often the same
    paragraph; only the words immediately around the finding may decide.
    """
    text = (
        "This agreement is governed by the laws of England. "
        "The supplier's registered address is Gewerbestrasse 9, 9000 St. Gallen."
    )
    address = located_in(text, "Gewerbestrasse 9, 9000 St. Gallen", EntityType.ADDRESS)
    assert drop_jurisdiction_mentions([address], text) == [address]


def test_the_seat_of_a_company_is_not_the_seat_of_an_arbitration():
    """``Sitz in Basel`` is the party's own office and has to be removed."""
    text = "Die Gesellschaft hat ihren Sitz in Basel."
    city = located_in(text, "Basel")
    assert drop_jurisdiction_mentions([city], text) == [city]


# ── What must go ─────────────────────────────────────────────────────────────


def test_a_bare_country_name_is_dropped():
    for name in ("Portugal", "Netherlands", "Poland", "Sweden", "United Kingdom"):
        assert drop_non_identifying([finding(name, EntityType.LOCATION)]) == []


def test_the_country_list_reads_every_language_the_tool_covers():
    for name in ("Deutschland", "Svizzera", "Pays-Bas", "Hiszpania", "Sverige"):
        assert drop_non_identifying([finding(name, EntityType.LOCATION)]) == []


def test_a_lowercase_common_noun_is_not_an_organisation():
    """Both cases are GLiNER2 false positives on the corpus."""
    for text in ("cost centre 30-412/2201", "service achats"):
        assert drop_non_identifying([finding(text, EntityType.ORGANISATION)]) == []


def test_a_governing_law_jurisdiction_is_dropped_in_four_languages():
    cases = (
        ("The courts of London shall have exclusive jurisdiction.", "London"),
        ("Gerichtsstand ist Basel.", "Basel"),
        ("Les tribunaux de Geneve sont seuls competents.", "Geneve"),
        ("Il foro competente e Lugano.", "Lugano"),
    )
    for text, city in cases:
        assert drop_jurisdiction_mentions([located_in(text, city)], text) == []


def test_the_seat_of_an_arbitration_is_dropped():
    cases = (
        ("Any arbitration shall be seated in Geneva.", "Geneva"),
        ("Ein Schiedsverfahren findet in Zurich statt.", "Zurich"),
        ("Tout arbitrage siege a Lausanne.", "Lausanne"),
        ("Ogni arbitrato ha sede a Milano.", "Milano"),
    )
    for text, city in cases:
        assert drop_jurisdiction_mentions([located_in(text, city)], text) == []


def test_an_accented_clause_matches_the_unaccented_pattern():
    """The tables are written unaccented and the window is folded to match.

    Written down because the equivalent tables in ``detect.keywords`` are matched
    against raw text, where the accented spelling silently never matches.
    """
    text = "Le present contrat est régi par le droit de Genève."
    assert drop_jurisdiction_mentions([located_in(text, "Genève")], text) == []


def test_a_jurisdiction_named_after_the_finding_is_dropped():
    text = "Any dispute is subject to England law."
    assert drop_jurisdiction_mentions([located_in(text, "England")], text) == []


def test_the_legal_form_table_covers_the_supported_countries():
    """One table, so a form the nominating pass knows cannot be unknown here."""
    for form in ("ag", "gmbh", "srl", "sarl", "sp. z o.o.", "bv", "ab", "lda", "ltd"):
        assert form in LEGAL_FORMS

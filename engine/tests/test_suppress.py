"""What the suppression passes must remove, and what they must never touch.

Suppression is the one kind of rule that can turn a working scrub into a leak, so
these tests are written from the leak side first: every case where a value stays
comes before the cases where it goes.
"""

from __future__ import annotations

from dataclasses import replace

from freedocs.core.findings import (
    PROPAGATED_SUFFIX,
    EntityType,
    Finding,
    Layer,
    Span,
)
from freedocs.detect.suppress import (
    JURISDICTION,
    LEGAL_FORMS,
    NON_IDENTIFYING,
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


def keeps(findings) -> list[Finding]:
    """The kept half only, for the tests that are about what goes and what stays.

    Both passes return ``(kept, suppressed)`` since stage 6 has to be told which
    occurrences it may find in the output. The tests below predate that and are
    about the rule itself, so they unwrap here rather than repeating it.
    """
    return drop_non_identifying(findings)[0]


def keeps_after_jurisdiction(findings, text: str) -> list[Finding]:
    return drop_jurisdiction_mentions(findings, text)[0]


# ── What must survive ────────────────────────────────────────────────────────


def test_a_city_is_kept():
    """The corpus annotates thirty cities. None of them may be suppressed."""
    for city in ("Lugano", "Basel", "Firenze", "Geneve", "Zug", "Preston"):
        kept = keeps([finding(city, EntityType.LOCATION)])
        assert [f.text for f in kept] == [city]


def test_a_city_state_is_kept_because_the_name_is_ambiguous():
    """Luxembourg names a city as often as a country; dropping it is a leak."""
    for name in ("Luxembourg", "Monaco", "Singapore", "San Marino", "Andorra"):
        assert keeps([finding(name, EntityType.LOCATION)])


def test_a_capitalised_company_name_is_kept():
    for name in ("Alpin Treuhand AG", "Northwind Polska sp. z o.o.", "Northwind Group"):
        assert keeps([finding(name, EntityType.ORGANISATION)])


def test_a_lowercase_name_carrying_a_legal_form_is_kept():
    """A legal form is stronger evidence than a lowercase first letter."""
    kept = keeps([finding("sp. z o.o.", EntityType.ORGANISATION)])
    assert kept


def test_checksum_backed_types_are_never_looked_at():
    """A suppression rule that second-guesses a check digit is a bug."""
    identifier = finding("CHE-116.281.710", EntityType.COMPANY_ID)
    assert keeps([identifier]) == [identifier]


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
    assert keeps_after_jurisdiction([address], text) == [address]


def test_the_seat_of_a_company_is_not_the_seat_of_an_arbitration():
    """``Sitz in Basel`` is the party's own office and has to be removed."""
    text = "Die Gesellschaft hat ihren Sitz in Basel."
    city = located_in(text, "Basel")
    assert keeps_after_jurisdiction([city], text) == [city]


# ── What must go ─────────────────────────────────────────────────────────────


def test_a_bare_country_name_is_dropped():
    for name in ("Portugal", "Netherlands", "Poland", "Sweden", "United Kingdom"):
        assert keeps([finding(name, EntityType.LOCATION)]) == []


def test_the_country_list_reads_every_language_the_tool_covers():
    for name in ("Deutschland", "Svizzera", "Pays-Bas", "Hiszpania", "Sverige"):
        assert keeps([finding(name, EntityType.LOCATION)]) == []


def test_a_lowercase_common_noun_is_not_an_organisation():
    """Both cases are GLiNER2 false positives on the corpus."""
    for text in ("cost centre 30-412/2201", "service achats"):
        assert keeps([finding(text, EntityType.ORGANISATION)]) == []


def test_a_governing_law_jurisdiction_is_dropped_in_four_languages():
    cases = (
        ("The courts of London shall have exclusive jurisdiction.", "London"),
        ("Gerichtsstand ist Basel.", "Basel"),
        ("Les tribunaux de Geneve sont seuls competents.", "Geneve"),
        ("Il foro competente e Lugano.", "Lugano"),
    )
    for text, city in cases:
        assert keeps_after_jurisdiction([located_in(text, city)], text) == []


def test_the_seat_of_an_arbitration_is_dropped():
    cases = (
        ("Any arbitration shall be seated in Geneva.", "Geneva"),
        ("Ein Schiedsverfahren findet in Zurich statt.", "Zurich"),
        ("Tout arbitrage siege a Lausanne.", "Lausanne"),
        ("Ogni arbitrato ha sede a Milano.", "Milano"),
    )
    for text, city in cases:
        assert keeps_after_jurisdiction([located_in(text, city)], text) == []


def test_an_accented_clause_matches_the_unaccented_pattern():
    """The tables are written unaccented and the window is folded to match.

    Written down because the equivalent tables in ``detect.keywords`` are matched
    against raw text, where the accented spelling silently never matches.
    """
    text = "Le present contrat est régi par le droit de Genève."
    assert keeps_after_jurisdiction([located_in(text, "Genève")], text) == []


def test_a_jurisdiction_named_after_the_finding_is_dropped():
    text = "Any dispute is subject to England law."
    assert keeps_after_jurisdiction([located_in(text, "England")], text) == []


def test_the_legal_form_table_covers_the_supported_countries():
    """One table, so a form the nominating pass knows cannot be unknown here."""
    for form in ("ag", "gmbh", "srl", "sarl", "sp. z o.o.", "bv", "ab", "lda", "ltd"):
        assert form in LEGAL_FORMS


# ── What was suppressed has to be reported ───────────────────────────────────
#
# Stage 6 searches for *values* while both passes below judge *occurrences*, so
# an occurrence left in place reads as a survivor of a value removed elsewhere.
# `verify_output` already knows how to be told about that - the allowance the
# human override uses - but nothing was telling it. These tests pin the half
# that was missing: each pass says what it dropped, so the pipeline can grant an
# allowance for exactly those occurrences and no others.


def test_drop_non_identifying_reports_the_country_it_dropped():
    country = finding("Switzerland", EntityType.LOCATION)
    city = finding("Lugano", EntityType.LOCATION, start=40)
    kept, suppressed = drop_non_identifying([country, city])
    assert [f.text for f in kept] == ["Lugano"]
    assert [(s.rule, s.finding.text) for s in suppressed] == [(NON_IDENTIFYING, "Switzerland")]


def test_drop_non_identifying_reports_the_lowercase_noun_it_dropped():
    """The case that made this necessary, and it needs no propagation to happen.

    ``Réalise`` is a company and ``réalise`` is a verb. The rule is
    case-sensitive on purpose; verification casefolds on purpose. Neither is
    wrong and together they turn a correct suppression into a reported leak.
    """
    company = finding("Réalise", EntityType.ORGANISATION)
    verb = finding("réalise", EntityType.ORGANISATION, start=60)
    kept, suppressed = drop_non_identifying([company, verb])
    assert [f.text for f in kept] == ["Réalise"]
    assert [(s.rule, s.finding.text) for s in suppressed] == [(NON_IDENTIFYING, "réalise")]


def test_dropping_nothing_reports_nothing():
    """A vacuous allowance is worse than none: it would hide the next leak."""
    kept, suppressed = drop_non_identifying([finding("Lugano", EntityType.LOCATION)])
    assert len(kept) == 1
    assert suppressed == []


def test_drop_jurisdiction_mentions_reports_the_occurrence_it_dropped():
    text = "Les tribunaux de Lausanne sont seuls competents."
    clause = located_in(text, "Lausanne")
    kept, suppressed = drop_jurisdiction_mentions([clause], text)
    assert kept == []
    assert [(s.rule, s.finding.text) for s in suppressed] == [(JURISDICTION, "Lausanne")]


def test_a_suppression_carries_the_finding_and_not_a_copy_of_its_text():
    """The pipeline needs the span to deduplicate; the report needs the entity.

    Carrying the whole finding is what lets one occurrence dropped by two passes
    grant one allowance rather than two.
    """
    text = "Les tribunaux de Lausanne sont seuls competents."
    clause = located_in(text, "Lausanne")
    _, suppressed = drop_jurisdiction_mentions([clause], text)
    assert suppressed[0].finding is clause
    assert suppressed[0].finding.entity is EntityType.LOCATION


# ── A place name is capitalised, and a common noun is not ────────────────────


def test_a_lowercase_word_is_not_a_place():
    """`canton` came back LOCATION at 0.52 on a real document.

    It was removed - `le seul [LOCATION_4] qui garantit 730 jours` - and stage 6
    then counted `cantonale` and `cantonal` as survivors of it. Three reported
    leaks, none of them confidential, and a scrub that wrote nothing.

    Same argument as the organisation arm above: a place name is a proper noun
    and is capitalised in all four languages the model reads, German included.
    """
    for word in ("canton", "commune", "administration cantonale", "arrondissement"):
        assert keeps([finding(word, EntityType.LOCATION)]) == []


def test_a_place_with_a_lowercase_article_is_kept():
    """The counter-case, and it is a real one in Romandy.

    `la Chaux-de-Fonds`, `le Locle` and `les Diablerets` are towns, and mid
    sentence the article is lowercase. So the test is not the first character -
    which is what the organisation arm uses - but whether the span contains a
    capitalised word at all.
    """
    for name in ("la Chaux-de-Fonds", "le Locle", "les Diablerets", "den Haag"):
        assert keeps([finding(name, EntityType.LOCATION)])


def test_a_place_in_capitals_is_kept():
    assert keeps([finding("GENEVE", EntityType.LOCATION)])


def test_an_address_is_never_judged_on_its_capitals():
    """Addresses are assembled by `detect/addresses.py` around a postal code.

    Its span starts wherever the street name starts, and a street type is a
    lowercase word in French and Italian - `rue`, `via`, `chemin`. Judging that
    span by capitalisation would drop the one finding in this file that was
    built from structure rather than from a model's guess.
    """
    assert keeps([finding("rue du Simplon 12, 1006 Lausanne", EntityType.ADDRESS)])
    assert keeps([finding("via Nassa 5, 6900 Lugano", EntityType.ADDRESS)])


# ── A propagated copy is not a fresh claim ───────────────────────────────────


def propagated(text: str, entity: EntityType, start: int = 0) -> Finding:
    found = finding(text, entity, start)
    return replace(found, detector=f"{found.detector}{PROPAGATED_SUFFIX}")


def test_a_propagated_lowercase_organisation_is_kept():
    """The rule judges a model's claim, and a copy is not one.

    `SWICA` was confirmed as an organisation at its own spelling, and
    propagation then reached the lowercase `swica` inside
    `2022-03-23_swica_resume_etude.pdf`. Re-judging that copy by its initial
    applies the rule to the case it was not written for - the model claiming a
    common noun is a company - and the result was worse than the original bug:
    the copy was dropped, the drop granted stage 6 an allowance, and the
    insurer's name shipped in a document whose verification said "no leak".
    """
    kept, suppressed = drop_non_identifying([propagated("swica", EntityType.ORGANISATION)])
    assert [f.text for f in kept] == ["swica"]
    assert suppressed == []


def test_a_propagated_lowercase_place_is_kept():
    kept, _ = drop_non_identifying([propagated("sion", EntityType.LOCATION)])
    assert [f.text for f in kept] == ["sion"]


def test_a_fresh_lowercase_claim_is_still_dropped():
    """The half that must not move: this is what the rule is for."""
    assert keeps([finding("service achats", EntityType.ORGANISATION)]) == []
    assert keeps([finding("canton", EntityType.LOCATION)]) == []


def test_a_propagated_country_is_still_dropped():
    """The country arm judges the *value*, so a copy of it is no better.

    `Suisse` narrows a population by millions whoever found it, and unlike the
    lowercase arms this one is not about who made the claim.
    """
    kept, suppressed = drop_non_identifying([propagated("Suisse", EntityType.LOCATION)])
    assert kept == []
    assert len(suppressed) == 1

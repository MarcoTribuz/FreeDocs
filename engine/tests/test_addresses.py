"""The postal-code pass: what it assembles, and what it refuses to touch."""

from __future__ import annotations

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.addresses import fill_address_gaps


def existing(text: str, value: str, entity: EntityType, confidence: float = 0.95) -> Finding:
    start = text.index(value)
    return Finding(
        span=Span(start, start + len(value)),
        entity=entity,
        text=value,
        layer=Layer.NER,
        detector="gliner2",
        confidence=confidence,
    )


def addresses(text: str, findings=()) -> list[str]:
    return [
        f.text for f in fill_address_gaps(text, list(findings)) if f.entity is EntityType.ADDRESS
    ]


# ── The shapes the twelve countries actually write ───────────────────────────


def test_every_postal_code_shape_in_the_corpus_is_assembled():
    cases = {
        "Bahnhofstrasse 12, 8001 Zurich": "Switzerland",
        "Hafenstrasse 118, 20359 Hamburg": "Germany",
        "Getreidegasse 21, 5020 Salzburg": "Austria",
        "14 rue de la Paix, 75002 Paris": "France, number first",
        "Calle Serrano 41, 28001 Madrid": "Spain",
        "Via Garibaldi 42, 20121 Milano": "Italy",
        "Rua do Ouro 112, 1100-063 Lisboa": "Portugal",
        "Keizersgracht 204, 1016 DX Amsterdam": "Netherlands",
        "ulica Prosta 51, 00-838 Warszawa": "Poland",
        "Kungsgatan 18, 111 35 Stockholm": "Sweden",
        "14 Kingsway, London WC2B 6LH": "United Kingdom, code last",
        "Unit 7 Ashford Park, Manchester M15 4TQ": "United Kingdom, unit prefix",
    }
    for address, country in cases.items():
        assert addresses(f"Sitz: {address}. Weiter im Text.") == [address], country


def test_a_multi_word_city_survives():
    text = "Gewerbestrasse 9, 9000 St. Gallen ist die Adresse."
    assert addresses(text) == ["Gewerbestrasse 9, 9000 St. Gallen"]


def test_an_elided_article_does_not_end_the_street():
    """``Rue de l'Industrie 9`` was the one annotated address still missed.

    The token starts lowercase, so every other rule in the walk rejected it.
    """
    for text in (
        "Rue de l'Industrie 9, 2800 Delemont",
        "Via dell'Artigianato 9, 36100 Vicenza",
    ):
        assert addresses(f"a {text}.") == [text]


# ── The left edge, which is the part a comma cannot find ─────────────────────


def test_a_stray_noun_before_the_street_is_not_absorbed():
    """There is no comma before the street here, only a word that is not one."""
    text = "residence Meir 78, 2000 Antwerpen"
    assert addresses(text) == ["Meir 78, 2000 Antwerpen"]


def test_the_street_does_not_reach_across_a_line_break():
    text = "Rechnung 4711\nBahnhofstrasse 12, 8001 Zurich"
    assert addresses(text) == ["Bahnhofstrasse 12, 8001 Zurich"]


def test_a_sentence_boundary_does_not_join_two_cities():
    """``Corso Umberto I 118, 80138 Napoli. Codice`` was one address once."""
    text = "Corso Umberto I 118, 80138 Napoli. Codice fiscale folgt."
    assert addresses(text) == ["Corso Umberto I 118, 80138 Napoli"]


def test_a_trailing_full_stop_is_not_part_of_the_address():
    text = "Sitz Bahnhofstrasse 12, 8001 Zurich."
    assert all(not a.endswith(".") for a in addresses(text))


def test_a_house_number_is_required():
    """Without one the pattern matches every capitalised word beside a number."""
    assert addresses("Musterstrasse, 8001 Zurich") == []


def test_a_comma_is_required():
    """Every invoice line in the corpus is a number beside a capitalised word."""
    assert addresses("Artikel 90210 Bari") == []


# ── Filling gaps, never competing ────────────────────────────────────────────


def test_an_address_the_model_already_assembled_is_left_alone():
    """The token walk cannot beat the model where the model spoke.

    It produced ``Sitz Fabrikweg 210, 5000 Aarau`` against the model's correct
    span, which would have traded three exact spans for nothing.
    """
    text = "Sitz Fabrikweg 210, 5000 Aarau"
    found = [existing(text, "Fabrikweg 210, 5000 Aarau", EntityType.ADDRESS)]
    assert addresses(text, found) == ["Fabrikweg 210, 5000 Aarau"]


def test_a_city_inside_the_address_is_absorbed():
    """The model's half-answer: the city, without the street that leaks."""
    text = "Rua do Ouro 112, 1100-063 Lisboa"
    found = [existing(text, "Lisboa", EntityType.LOCATION)]
    result = fill_address_gaps(text, found)
    assert [f.text for f in result] == ["Rua do Ouro 112, 1100-063 Lisboa"]
    assert [f.entity for f in result] == [EntityType.ADDRESS]


def test_anything_that_is_not_a_city_blocks_the_candidate():
    """A person overlapping an address shape means the shape is wrong."""
    text = "Anna Bianchi 12, 8001 Zurich"
    found = [existing(text, "Anna Bianchi", EntityType.PERSON)]
    assert addresses(text, found) == []


def test_a_partial_overlap_with_a_city_also_blocks():
    """Absorption is for a city the address fully contains, not a straddle."""
    text = "Bahnhofstrasse 12, 8001 Zurich"
    outside = Finding(
        span=Span(text.index("Zurich"), len(text) + 4),
        entity=EntityType.LOCATION,
        text="Zurich" + " ??!",
        layer=Layer.NER,
        detector="gliner2",
        confidence=0.9,
    )
    assert addresses(text + " ??!", [outside]) == []

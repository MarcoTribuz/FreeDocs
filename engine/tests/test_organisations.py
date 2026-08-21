"""The legal-form pass fills gaps; it must not compete with the model."""

from __future__ import annotations

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.organisations import fill_organisation_gaps


def model_found(text: str, value: str, entity: EntityType) -> Finding:
    start = text.index(value)
    return Finding(
        span=Span(start, start + len(value)),
        entity=entity,
        text=value,
        layer=Layer.NER,
        detector="gliner2:organization",
        confidence=0.99,
    )


def names(text: str, findings=()) -> list[str]:
    return [f.text for f in fill_organisation_gaps(text, list(findings))]


def test_the_name_the_model_never_saw_is_found():
    """The corpus case this pass exists for: GLiNER2 returns nothing here."""
    text = "Poland: Northwind Polska sp. z o.o., ulica Prosta 51, 00-838 Warszawa."
    assert "Northwind Polska sp. z o.o." in names(text)


def test_a_heading_before_the_name_is_not_swallowed():
    text = "Poland: Northwind Polska sp. z o.o."
    assert names(text) == ["Northwind Polska sp. z o.o."]


def test_the_model_wins_wherever_it_spoke():
    """German capitalises common nouns, so the backward scan cannot be trusted.

    Run as a peer detector this pass produced ``Kunde Nordwind Logistik GmbH``
    and beat the model's correct span on length alone. Restricted to gaps it
    adds nothing here.
    """
    text = "Der Kunde Nordwind Logistik GmbH hat bezahlt."
    existing = [model_found(text, "Nordwind Logistik GmbH", EntityType.ORGANISATION)]
    assert names(text, existing) == ["Nordwind Logistik GmbH"]


def test_an_overlap_with_any_type_blocks_the_candidate():
    """An overlap means some layer already has an opinion about those chars."""
    text = "Anna Bianchi SA"
    existing = [model_found(text, "Anna Bianchi", EntityType.PERSON)]
    assert names(text, existing) == ["Anna Bianchi"]


def test_a_name_does_not_reach_across_a_line_break():
    """The flattened stream joins unrelated cells with a separator.

    A backward scan that crossed one would fuse two cells into a company name.
    """
    text = "Rechnung\nAlpin Treuhand AG"
    assert names(text) == ["Alpin Treuhand AG"]


def test_a_short_form_is_matched_only_in_its_own_spelling():
    """``sa`` is a French possessive, ``ab`` a Swedish preposition.

    Case-insensitive matching on a two-letter legal form turns every sentence
    into a company name.
    """
    assert names("Le fournisseur a resilie sa commande.") == []
    assert names("Leverantoren skickade fakturan ab lagret.") == []


def test_a_connector_inside_a_name_is_kept():
    text = "Vignoble Bertrand et Fils SA"
    assert names(text) == ["Vignoble Bertrand et Fils SA"]


def test_a_connector_never_starts_a_name():
    text = "les parts et Fils SA"
    assert names(text) == ["Fils SA"]


def test_a_reference_number_before_the_name_is_not_absorbed():
    """Digits stop the scan: every invoice line has a number in front of a name."""
    text = "Position 4711 Metallbau Ostschweiz AG"
    assert names(text) == ["Metallbau Ostschweiz AG"]


def test_a_legal_form_with_nothing_in_front_produces_nothing():
    assert names("GmbH") == []
    assert names("die GmbH") == []

"""Accented spellings must reach the tables that are written without accents.

Every table in the engine that matches prose — the context keywords, the country
names, the legal forms — is written unaccented, because writing each entry twice
is a second place to forget one. That only works if the *comparison* folds, and
for a long time it did not: ``Rule.confidence_at`` plain-casefolded its window,
so ``numero de tva`` never met the ``numéro de TVA`` a French document contains.
Every test here is a spelling a real document in one of the twelve covered
countries actually uses.
"""

from __future__ import annotations

import pytest

from freedocs.core.text import fold_diacritics
from freedocs.detect import organisations, suppress
from freedocs.detect.validators import build_rules


@pytest.fixture(scope="module")
def rules() -> dict:
    return {rule.name: rule for rule in build_rules(None)}


def _confidence(rule, template: str, value: str) -> float:
    text = template.format(v=value)
    start = text.index(value)
    return rule.confidence_at(text, start, start + len(value))


class TestFold:
    def test_diacritics_are_stripped_and_case_folded(self):
        assert fold_diacritics("Numéro de TVA") == "numero de tva"
        assert fold_diacritics("SÉCURITÉ Sociale") == "securite sociale"
        assert fold_diacritics("gültig") == "gultig"

    def test_compatibility_forms_fold_too(self):
        # NFKD rather than NFD, so a ligature is the same phrase.
        assert fold_diacritics("ﬁscal") == "fiscal"

    def test_plain_ascii_is_unchanged_beyond_case(self):
        # The corpus was ASCII throughout when this landed, which is precisely
        # why the gap stayed invisible: folding must be a no-op there.
        assert fold_diacritics("Numero de TVA") == "numero de tva"


class TestContextKeywords:
    """The measured gap: five table entries a real document spells with accents."""

    @pytest.mark.parametrize(
        ("rule_name", "template", "value"),
        [
            ("fr-nir", "Numéro de sécurité sociale : {v}", "1 84 12 75 116 001 42"),
            ("fr-nif", "Numéro fiscal du salarié : {v}", "1234567890124"),
            ("be-nn", "Numéro national : {v}", "85073003328"),
        ],
    )
    def test_an_accented_label_gives_full_confidence(self, rules, rule_name, template, value):
        assert _confidence(rules[rule_name], template, value) == 1.0

    def test_the_unaccented_spelling_still_works(self, rules):
        # Folding must not trade one spelling for the other: plenty of real
        # documents are typed without accents, and the corpus was until now.
        plain = "Numero de securite sociale : {v}"
        assert _confidence(rules["fr-nir"], plain, "1 84 12 75 116 001 42") == 1.0

    def test_a_weak_rule_with_no_keyword_at_all_stays_weak(self, rules):
        # The fold must widen what counts as context, not remove the gate.
        rule = rules["fr-nir"]
        assert _confidence(rule, "Référence interne : {v}", "1 84 12 75 116 001 42") == (
            rule.confidence_without_context
        )

    def test_an_accented_word_cannot_invent_a_code_match(self, rules):
        # Codes are matched whole-word on the same folded window. Folding must not
        # let `iva` inside an accented word claim a partita IVA.
        rule = rules["it-partita-iva-luhn11"]
        assert _confidence(rule, "La merce arrivò ieri, quantità {v}", "12345678903") == (
            rule.confidence_without_context
        )


class TestCountryNames:
    """A bare country name identifies nobody, in whatever spelling it arrives."""

    @pytest.mark.parametrize(
        "name",
        ["Österreich", "Suède", "Grèce", "Türkiye", "Węgry", "Irlande", "Danemark"],
    )
    def test_an_accented_country_name_is_still_a_country_name(self, name):
        assert suppress._is_country(name)

    @pytest.mark.parametrize("name", ["Zurich", "Genève", "Basel", "Firenze"])
    def test_a_city_is_not_swept_up_by_the_fold(self, name):
        # The leak side first: folding widens the country list, and a city that
        # folded into it would be dropped outright.
        assert not suppress._is_country(name)


class TestLegalForms:
    """``Sàrl`` is what a Romandy or Luxembourg company registers under."""

    @pytest.mark.parametrize(
        "candidate",
        ["Alpina Sàrl", "Alpina SÀRL", "Alpina S.à r.l.", "Alpina S.à.r.l.", "Alpina Sarl"],
    )
    def test_an_accented_legal_form_is_recognised(self, candidate):
        assert suppress._has_legal_form(candidate)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("La société Alpina Sàrl a signé le mandat.", "Alpina Sàrl"),
            ("Le mandat de Genève Services Sàrl court un an.", "Genève Services Sàrl"),
            ("Contrat avec Meyer S.à r.l. daté du 3 mars.", "Meyer S.à r.l."),
            ("Accord avec Berner SÀRL pour la maintenance.", "Berner SÀRL"),
        ],
    )
    def test_the_gap_fill_nominates_a_name_ending_in_an_accented_form(self, text, expected):
        # Not measurable on the corpus: GLiNER2 returns
        # `Jurassienne Technique Sàrl` at 0.996, so the gap fill never runs there.
        # The unit is the only place this can be shown.
        found = organisations.fill_organisation_gaps(text, [])
        assert [text[f.span.start : f.span.end] for f in found] == [expected]


class TestKnownCollision:
    """Pinned, not fixed: two rules that tie and cannot be separated by evidence.

    ``228722377`` in ``corpus/fr.txt`` is an annotated SIREN with the word
    ``SIREN`` six characters in front of it. It is also a valid Austrian TIN, and
    once the window folds, the ``numéro fiscal`` labelling the *next* number in
    the same list gives ``at-tin`` its context too. Both rules then stand at
    precedence VALIDATOR, the same span and confidence 1.0, so the winner is
    whichever the rule table lists first — a decision nobody made.

    The characters are removed either way, so this is a report attribution defect
    and not a leak. Fixing it properly means letting the tie-break see *how far*
    away each rule's own keyword is, which needs a new field on ``Finding`` and a
    measurement of its own. Pinned here so it cannot change silently.
    """

    def test_both_rules_claim_the_value(self, rules):
        assert rules["fr-siren"].validate("228722377")
        assert rules["at-tin"].validate("228722377")

    def test_the_french_keyword_gives_the_austrian_rule_its_context(self, rules):
        text = "Autres références: SIREN 228722377, SIRET 34962329809439, numéro fiscal"
        start = text.index("228722377")
        assert rules["at-tin"].confidence_at(text, start, start + 9) == 1.0
        assert rules["fr-siren"].confidence_at(text, start, start + 9) == 1.0

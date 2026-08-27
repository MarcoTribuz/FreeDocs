"""Overlap resolution: two edits can never touch the same characters."""

from __future__ import annotations

import pytest

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.registry import (
    DetectorRegistry,
    displace_report_only,
    drop_unconfirmed_structured,
    resolve_overlaps,
    summarise,
)


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


class TestWhatGrantsAnAllowance:
    """Which dropped findings leave characters behind, and which do not.

    Stage 6 searches for values and two passes here judge occurrences, so an
    occurrence left in place has to be declared or it reads as a leak. The
    declaration is dangerous in exactly one direction: every finding named here
    becomes a value stage 6 is permitted to find in the output, so the list must
    be the two passes that leave text behind and nothing else.

    Three of the five places `detect` drops a finding must never appear:

    * `drop_unconfirmed_structured` throws away a model claim a checksum
      refused - a different value, never removed anywhere, so there is nothing
      to allow.
    * `resolve_overlaps` throws away the loser of a contest whose winner covers
      the same characters, which are removed either way.
    * `fill_address_gaps` absorbs a LOCATION inside an ADDRESS, same argument.

    Widening this past the two suppression passes reopens the hole the whole
    change exists to close.
    """

    def _registry(self, findings_for):
        class Stub:
            def detect(self, text: str):
                return findings_for(text)

        return DetectorRegistry(detectors=[Stub()])

    def _spans(self, text: str, value: str, entity: EntityType, confidence: float = 0.9):
        out = []
        start = text.find(value)
        while start != -1:
            out.append(
                Finding(
                    span=Span(start, start + len(value)),
                    entity=entity,
                    text=value,
                    layer=Layer.NER,
                    detector="stub",
                    confidence=confidence,
                )
            )
            start = text.find(value, start + 1)
        return out

    def test_detect_stays_the_kept_half(self):
        """`benchmark` and every existing caller go through `detect`.

        It has to keep answering exactly what it answered before, or the measured
        numbers move for a change that touched no detector.
        """
        text = "Bureau a Lugano. Les tribunaux de Lugano sont seuls competents."
        registry = self._registry(lambda t: self._spans(t, "Lugano", EntityType.LOCATION))
        kept, _ = registry.detect_with_suppressions(text)
        assert registry.detect(text) == kept

    def test_a_jurisdiction_mention_is_declared(self):
        text = "Bureau a Lugano. Les tribunaux de Lugano sont seuls competents."
        registry = self._registry(lambda t: self._spans(t, "Lugano", EntityType.LOCATION))
        kept, suppressed = registry.detect_with_suppressions(text)
        assert [f.span.start for f in kept] == [text.index("Lugano")]
        assert [s.finding.span.start for s in suppressed] == [text.rindex("Lugano")]

    def test_a_refused_checksum_claim_is_not_declared(self):
        """The model's card claim is a value nothing removed. Allowing it would
        permit that text in the output for free."""
        pytest.importorskip("stdnum")
        text = "Totali di riga 1500\t2300 nel grafico."
        registry = self._registry(lambda t: self._spans(t, "1500\t2300", EntityType.CREDIT_CARD))
        kept, suppressed = registry.detect_with_suppressions(text)
        assert kept == []
        assert suppressed == []

    def test_an_overlap_loser_is_not_declared(self):
        """Its characters are removed by the winner, so there is nothing to allow."""
        text = "Contatto Mario Rossi a Milano."

        def findings(t: str):
            return [
                Finding(
                    span=Span(9, 20),
                    entity=EntityType.PERSON,
                    text="Mario Rossi",
                    layer=Layer.NER,
                    detector="stub",
                    confidence=0.9,
                ),
                Finding(
                    span=Span(15, 20),
                    entity=EntityType.ORGANISATION,
                    text="Rossi",
                    layer=Layer.NER,
                    detector="stub",
                    confidence=0.8,
                ),
            ]

        _, suppressed = self._registry(findings).detect_with_suppressions(text)
        assert suppressed == []

    def test_one_occurrence_dropped_twice_is_declared_once(self):
        """`drop_non_identifying` runs on both sides of propagation.

        A lowercase organisation is dropped before propagation, the capitalised
        template then propagates onto the same characters, and the second pass
        drops it again. Counting both would permit the value twice in an output
        that contains it once - and the allowance is a count, so the second one
        is a hole a failed write-back could hide in.
        """
        text = "Realise SA a livre le rapport. La societe realise les travaux."
        registry = self._registry(
            lambda t: (
                self._spans(t, "Realise", EntityType.ORGANISATION)
                + self._spans(t, "realise", EntityType.ORGANISATION)
            )
        )
        _, suppressed = registry.detect_with_suppressions(text)
        starts = [s.finding.span.start for s in suppressed]
        assert starts == sorted(set(starts))
        assert starts == [text.index("realise", text.index("societe"))]

    def test_no_state_survives_between_calls(self):
        """One registry serves a whole session, and a batch is more than one file.

        State on the instance would check the second document against the first
        document's suppressions - the shape `Override.for_path` exists to stop.
        """
        registry = self._registry(lambda t: self._spans(t, "Lugano", EntityType.LOCATION))
        first = "Les tribunaux de Lugano sont seuls competents."
        registry.detect_with_suppressions(first)
        _, suppressed = registry.detect_with_suppressions("Bureau a Lugano.")
        assert suppressed == []


class TestReportOnlyCollision:
    """A flagged occurrence must not shelter a value that goes everywhere else.

    `REPORT_ONLY` means "say it is here, never delete it": a job title alone
    identifies nobody, and deleting one hides residual risk instead of surfacing
    it. That reasoning holds for a value only ever seen as a job title. It does
    not hold when the *same characters* are a company two paragraphs down -
    there the flagged sighting is the model having mislabelled one occurrence,
    and leaving it is a leak with a clean verification in front of it.

    Found on a real document: `Etat-employeur` came back ORGANISATION at 0.87 in
    one sentence, and in the other the model claimed only the nine characters
    `employeur` as a JOB_TITLE. Propagation cannot fix it - the span is occupied,
    so the copy is skipped - and matching the two by *text* cannot either, which
    is the version of this rule that shipped first and did not close the case.
    The question is whether a flagged finding is standing **on an occurrence of**
    a removable value, not whether it spells one.

    `CLAUDE.md` calls the shape out in the special-categories note, from the
    other direction: "a REPORT_ONLY finding winning an overlap against a LOCATION
    would stop that LOCATION being removed, which is a leak".
    """

    #: `employeur` inside the first occurrence, the whole value in the second.
    TEXT = (
        "Le cout total direct de l'absence pour l'Etat-employeur s'eleve a 136 millions.\n"
        "L'Etat-employeur a donc subi une hausse de 19,4% en trois ans.\n"
    )

    def at(self, text: str, value: str, entity: EntityType, confidence: float, *, last=False):
        start = text.rindex(value) if last else text.index(value)
        return Finding(
            span=Span(start, start + len(value)),
            entity=entity,
            text=value,
            layer=Layer.NER,
            detector="stub",
            confidence=confidence,
        )

    def test_a_flagged_finding_standing_on_a_removable_value_goes(self):
        """The real case: the flagged span is *part of* the occurrence, not equal to it."""
        flagged = self.at(self.TEXT, "employeur", EntityType.JOB_TITLE, 0.68)
        company = self.at(self.TEXT, "Etat-employeur", EntityType.ORGANISATION, 0.87, last=True)
        kept = displace_report_only(self.TEXT, [flagged, company])
        assert kept == [company]

    def test_the_exact_spelling_case_still_works(self):
        flagged = self.at(self.TEXT, "Etat-employeur", EntityType.JOB_TITLE, 0.68)
        company = self.at(self.TEXT, "Etat-employeur", EntityType.ORGANISATION, 0.87, last=True)
        assert displace_report_only(self.TEXT, [flagged, company]) == [company]

    def test_a_flagged_finding_standing_on_nothing_survives(self):
        """The whole point of REPORT_ONLY, and it must not be collateral damage."""
        text = "La Directrice des finances a valide le rapport de Nordwind Logistik.\n"
        flagged = self.at(text, "Directrice des finances", EntityType.JOB_TITLE, 0.8)
        company = self.at(text, "Nordwind Logistik", EntityType.ORGANISATION, 0.9)
        findings = [flagged, company]
        assert displace_report_only(text, findings) == findings

    def test_the_reverse_never_happens(self):
        """A removable finding is never displaced by a flagged value elsewhere.

        This direction is the leak. Nothing in the rule may be symmetric.
        """
        text = "L'Etat-employeur paie. Le poste d'Etat-employeur est vacant.\n"
        company = self.at(text, "Etat-employeur", EntityType.ORGANISATION, 0.9)
        flagged = self.at(text, "Etat-employeur", EntityType.JOB_TITLE, 0.8, last=True)
        assert company in displace_report_only(text, [company, flagged])

    def test_the_occurrence_is_matched_the_way_propagation_matches_one(self):
        """One definition of the boundary, or the two passes disagree.

        `employeur` inside `Etat-employeur` is an occurrence of neither value;
        what makes the flagged finding lose is that it *overlaps* an occurrence
        of `Etat-employeur`, which is the span propagation is about to claim.
        """
        text = "Le sous-employeur paie. L'Etat-employeur aussi.\n"
        flagged = self.at(text, "employeur", EntityType.JOB_TITLE, 0.7)
        company = self.at(text, "Etat-employeur", EntityType.ORGANISATION, 0.9)
        # `sous-employeur`: the hyphen is outside `\w`, so `employeur` there *is*
        # a whole value - but the removable value is `Etat-employeur`, which does
        # not occur at that offset, so the flagged finding stands.
        assert flagged in displace_report_only(text, [flagged, company])

    def test_propagation_then_puts_the_removable_label_there(self):
        """Displacing alone would leave the characters unclaimed by anything."""

        outer = self

        class Stub:
            def detect(self, text: str):
                return [
                    outer.at(text, "employeur", EntityType.JOB_TITLE, 0.68),
                    outer.at(text, "Etat-employeur", EntityType.ORGANISATION, 0.87, last=True),
                ]

        kept, _ = DetectorRegistry(detectors=[Stub()]).detect_with_suppressions(self.TEXT)
        assert [(f.span.start, f.entity) for f in kept] == [
            (self.TEXT.index("Etat-employeur"), EntityType.ORGANISATION),
            (self.TEXT.rindex("Etat-employeur"), EntityType.ORGANISATION),
        ]

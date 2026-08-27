"""Value propagation: the pass that took corpus coverage from 94% to 99%."""

from __future__ import annotations

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.propagate import (
    DETECTOR_SUFFIX,
    MIN_PROPAGATION_LENGTH,
    propagate_known_values,
)


def found(
    text: str, start: int, entity: EntityType = EntityType.PERSON, score: float = 0.9
) -> Finding:
    return Finding(
        span=Span(start, start + len(text)),
        entity=entity,
        text=text,
        layer=Layer.NER,
        detector="stub:person",
        confidence=score,
    )


def texts(findings: list[Finding]) -> list[tuple[int, str]]:
    return [(f.span.start, f.text) for f in findings]


def test_a_second_mention_is_added():
    """The exact failure measured on the corpus: found once, missed later."""
    text = "Anna Bianchi apre. Poi Anna Bianchi chiude."
    result = propagate_known_values(text, [found("Anna Bianchi", 0)])
    assert texts(result) == [(0, "Anna Bianchi"), (23, "Anna Bianchi")]


def test_the_copy_keeps_the_original_label_and_confidence():
    text = "Acme Group paga. Acme Group fattura."
    template = found("Acme Group", 0, EntityType.ORGANISATION, score=0.72)
    copy = propagate_known_values(text, [template])[1]
    assert copy.entity is EntityType.ORGANISATION
    assert copy.confidence == 0.72
    assert copy.detector.endswith(DETECTOR_SUFFIX)


def test_propagation_is_case_insensitive_but_reports_the_real_text():
    text = "Anna Bianchi firma. ANNA BIANCHI in maiuscolo."
    result = propagate_known_values(text, [found("Anna Bianchi", 0)])
    assert texts(result) == [(0, "Anna Bianchi"), (20, "ANNA BIANCHI")]


def test_word_boundaries_are_respected():
    """Without boundaries "Conti" would redact "Continua" and "raccontino"."""
    text = "Giuseppe Conti parla. Continua la riunione. Il racconti-no."
    result = propagate_known_values(text, [found("Conti", 9)], min_length=5)
    assert texts(result) == [(9, "Conti")]


def test_short_values_are_not_propagated():
    """A two-letter legal form is in every company name on the page."""
    text = "Acme SA paga. Beta SA incassa. Gamma SA fattura."
    result = propagate_known_values(text, [found("SA", 5, EntityType.ORGANISATION)])
    assert len(result) == 1


def test_the_minimum_length_keeps_two_letter_forms_out():
    assert len("SA") < MIN_PROPAGATION_LENGTH


def test_a_legal_form_is_never_a_template_whatever_its_length():
    """The half of the old floor's reasoning that survived measurement.

    ``Ltd`` is three characters, so length alone no longer excludes it, and a
    document where a detector claims a bare one would otherwise spread it to
    every other ``Ltd`` on the page. That is not a second sighting of anything.
    """
    text = "Ltd is the abbreviation. Ashcroft Ltd and Barrow Ltd both signed here."
    result = propagate_known_values(text, [found("Ltd", 0, EntityType.ORGANISATION)])
    assert len(result) == 1


def test_a_longer_legal_form_is_excluded_too():
    text = "Limited is written out. Ashcroft Limited and Barrow Limited signed."
    result = propagate_known_values(text, [found("Limited", 0, EntityType.ORGANISATION)])
    assert len(result) == 1


def test_a_three_letter_place_name_now_propagates():
    """Why the floor moved. ``Zug`` was a confirmed finding and leaked anyway."""
    text = "Im Lager Zug erfasst. Der Sitz ist Zug, und das Portal heisst Zugang."
    result = propagate_known_values(text, [found("Zug", 9, EntityType.LOCATION)])
    assert texts(result) == [(9, "Zug"), (35, "Zug")]


def test_the_word_boundary_still_holds_at_three_characters():
    """``Zugang`` is not a second mention of ``Zug``, and never was.

    This is the half of the old floor's justification that measurement refused:
    the pattern is bounded, so a short value never matched inside a longer word,
    and the floor of 5 was not what prevented it.
    """
    text = "Der Sitz ist Zug. Das Portal heisst Zugang und der Zugriff ist gesperrt."
    result = propagate_known_values(text, [found("Zug", 13, EntityType.LOCATION)])
    assert texts(result) == [(13, "Zug")]


def test_an_existing_finding_is_not_duplicated():
    text = "Anna Bianchi e Anna Bianchi."
    result = propagate_known_values(text, [found("Anna Bianchi", 0), found("Anna Bianchi", 15)])
    assert len(result) == 2


def test_propagation_never_overlaps_an_existing_finding():
    """A copy landing inside another finding would produce two edits on one range."""
    text = "Studio Rossi e Rossi insieme."
    findings = [found("Studio Rossi", 0, EntityType.ORGANISATION), found("Rossi", 15)]
    result = propagate_known_values(text, findings, min_length=5)
    spans = sorted((f.span.start, f.span.end) for f in result)
    for index in range(1, len(spans)):
        previous, current = spans[index - 1], spans[index]
        assert previous[1] <= current[0], f"overlap between {previous} and {current}"


def test_the_most_confident_sighting_becomes_the_template():
    text = "Mario Rossi qui. Mario Rossi la. Mario Rossi altrove."
    findings = [found("Mario Rossi", 0, score=0.4), found("Mario Rossi", 17, score=0.95)]
    result = propagate_known_values(text, findings)
    new = [f for f in result if DETECTOR_SUFFIX in f.detector]
    assert [f.confidence for f in new] == [0.95]


def test_no_findings_means_no_work():
    assert propagate_known_values("qualsiasi testo", []) == []


def test_output_is_ordered_by_position():
    text = "Zeta Uno e Zeta Uno e Zeta Uno"
    result = propagate_known_values(text, [found("Zeta Uno", 11)])
    starts = [f.span.start for f in result]
    assert starts == sorted(starts)


def test_result_is_deterministic():
    text = "Anna Bianchi, Marco Deluca, Anna Bianchi, Marco Deluca"
    findings = [found("Anna Bianchi", 0), found("Marco Deluca", 14)]
    first = texts(propagate_known_values(text, findings))
    second = texts(propagate_known_values(text, list(reversed(findings))))
    assert first == second


def test_regex_metacharacters_in_a_value_are_escaped():
    """A detected value is data, not a pattern."""
    text = "Codice A.B(1) e ancora A.B(1) qui."
    second = text.index("A.B(1)", 10)
    result = propagate_known_values(text, [found("A.B(1)", 7)], min_length=5)
    assert texts(result) == [(7, "A.B(1)"), (second, "A.B(1)")]


def test_a_value_propagates_across_an_underscore():
    """A filename is a sequence of words, and `_` is what separates them.

    Found on a real document: `SWICA` was removed where the model saw it and
    stayed inside
    `2022-03-23_swica_resume_etude_prescriptions_arrets_travail.pdf` two lines
    down. Stage 6 counts substrings, so it found the survivor and failed a scrub
    where every other occurrence had gone - and the name of the insurer really
    is in that filename, so it was right to.

    `.` and `-` are already outside `\\w` and always propagated; the underscore
    was the only separator this rule read as a letter.
    """
    text = "Etude SWICA de 2022.\nSource: 2022-03-23_swica_resume_etude.pdf\n"
    start = text.index("SWICA")
    found = [
        Finding(
            span=Span(start, start + 5),
            entity=EntityType.ORGANISATION,
            text="SWICA",
            layer=Layer.NER,
            detector="stub",
            confidence=0.91,
        )
    ]
    out = propagate_known_values(text, found)
    assert [f.span.start for f in out] == [start, text.index("_swica_") + 1]


def test_a_value_still_does_not_propagate_inside_a_word():
    """The half that must not move. `Zug` is not in `Zugang`."""
    text = "Sitz in Zug. Zugang nur fur Mitarbeitende."
    found = [
        Finding(
            span=Span(8, 11),
            entity=EntityType.LOCATION,
            text="Zug",
            layer=Layer.NER,
            detector="stub",
            confidence=0.9,
        )
    ]
    assert len(propagate_known_values(text, found)) == 1


def test_a_removable_template_wins_the_characters_a_flagged_one_also_wants():
    """The placement order settles a contest, so it may not be the alphabet.

    Templates were placed in sorted order, for determinism, and determinism was
    the only requirement it met. On a real document `employeur` was a JOB_TITLE
    template and `Etat-employeur` an ORGANISATION one; `employeur` sorts first,
    took the characters, and the removable copy then found the span occupied and
    skipped it. `resolve_overlaps` would have settled that pair the other way -
    longer span wins - but it never saw the pair, because the copy it would have
    preferred was never made.

    Two criteria, each with its own reason: a `REPORT_ONLY` template never takes
    characters from a removable one, which is the rule already written down for
    overlaps; and the longer value goes first, which is what makes propagation's
    order agree with the resolution that follows it.
    """
    text = (
        "Le poste d'employeur est vacant.\n"
        "Le cout pour l'Etat-employeur s'eleve a 136 millions.\n"
        "L'Etat-employeur a subi une hausse.\n"
    )

    def at(value: str, entity: EntityType, confidence: float, *, last=False) -> Finding:
        start = text.rindex(value) if last else text.index(value)
        return Finding(
            span=Span(start, start + len(value)),
            entity=entity,
            text=value,
            layer=Layer.NER,
            detector="stub",
            confidence=confidence,
        )

    contested = text.index("Etat-employeur")
    out = propagate_known_values(
        text,
        [
            at("employeur", EntityType.JOB_TITLE, 0.68),
            at("Etat-employeur", EntityType.ORGANISATION, 0.87, last=True),
        ],
    )
    landed = [f for f in out if f.span.start <= contested < f.span.end]
    assert [(f.entity, len(f.span)) for f in landed] == [(EntityType.ORGANISATION, 14)]


def test_the_longer_template_goes_first_between_two_removable_ones():
    """Same ordering, without a REPORT_ONLY type in it.

    `resolve_overlaps` prefers the longer span at equal precedence, and a copy
    that loses its characters to a shorter one is a copy that never happens - so
    the shorter template must not be able to win by sorting earlier.
    """
    text = "Alpin Treuhand est le mandant.\nContrat avec Alpin Treuhand AG signe.\n"

    def at(value: str, start: int) -> Finding:
        return Finding(
            span=Span(start, start + len(value)),
            entity=EntityType.ORGANISATION,
            text=value,
            layer=Layer.NER,
            detector="stub",
            confidence=0.9,
        )

    second = text.index("Alpin Treuhand AG")
    out = propagate_known_values(text, [at("Alpin Treuhand", 0), at("Alpin Treuhand AG", second)])
    assert len(out) == 2

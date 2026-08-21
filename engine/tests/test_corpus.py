"""The gold data has to be trustworthy before any number derived from it is."""

from __future__ import annotations

from pathlib import Path

import pytest

from freedocs.core.findings import EntityType
from freedocs.evaluation.corpus import (
    CorpusError,
    load_corpus,
    load_document,
    parse_annotated,
)


def test_markup_is_stripped_from_the_text():
    text, _ = parse_annotated("Il cliente [PERSON:Mario Rossi] paga.")
    assert text == "Il cliente Mario Rossi paga."


def test_offsets_point_at_the_annotated_text():
    text, entities = parse_annotated("Il cliente [PERSON:Mario Rossi] paga.")
    (gold,) = entities
    assert text[gold.span.start : gold.span.end] == "Mario Rossi"
    assert gold.entity is EntityType.PERSON


def test_several_annotations_on_one_line_stay_aligned():
    """The failure mode this format exists to prevent: drifting offsets."""
    text, entities = parse_annotated(
        "[PERSON:Anna Bianchi] di [ORGANISATION:Acme SA] a [LOCATION:Lugano]"
    )
    for gold in entities:
        assert text[gold.span.start : gold.span.end] == gold.text
    assert [gold.entity for gold in entities] == [
        EntityType.PERSON,
        EntityType.ORGANISATION,
        EntityType.LOCATION,
    ]


def test_annotation_spanning_a_line_break_is_preserved():
    text, entities = parse_annotated("Il [JOB_TITLE:responsabile\ntecnico] parla.")
    (gold,) = entities
    assert text[gold.span.start : gold.span.end] == "responsabile\ntecnico"


def test_text_without_annotations_parses_to_no_entities():
    text, entities = parse_annotated("Nessun dato personale qui.")
    assert text == "Nessun dato personale qui."
    assert entities == []


def test_unknown_label_is_an_error_not_a_silent_skip():
    """A dropped annotation would be scored as a detector hallucination."""
    with pytest.raises(CorpusError, match="unknown entity label"):
        parse_annotated("[TELEPATHY:qualcosa]")


def test_empty_annotation_is_an_error():
    with pytest.raises(CorpusError, match="empty annotation"):
        parse_annotated("[PERSON:]")


def test_stray_closing_bracket_is_an_error():
    with pytest.raises(CorpusError, match="unbalanced"):
        parse_annotated("testo ] sciolto")


def test_language_comes_from_the_filename(tmp_path: Path):
    path = tmp_path / "it.txt"
    path.write_text("[PERSON:Mario Rossi]\n", encoding="utf-8")
    document = load_document(path)
    assert document.language == "it"
    assert document.name == "it.txt"


def test_empty_corpus_directory_is_an_error(tmp_path: Path):
    with pytest.raises(CorpusError, match="no corpus files"):
        load_corpus(tmp_path)


# -- the shipped corpus -------------------------------------------------------


def test_shipped_corpus_covers_four_languages():
    assert {document.language for document in load_corpus()} == {"it", "de", "fr", "en"}


def test_shipped_corpus_offsets_are_all_consistent():
    for document in load_corpus():
        for gold in document.entities:
            assert document.text[gold.span.start : gold.span.end] == gold.text, (
                f"{document.name}: {gold.text!r} does not sit at its recorded offset"
            )


def test_shipped_corpus_annotates_the_entities_the_ner_layer_exists_for():
    """A corpus without names would make the NER layer look unnecessary."""
    documents = load_corpus()
    for entity in (
        EntityType.PERSON,
        EntityType.ORGANISATION,
        EntityType.LOCATION,
        EntityType.ADDRESS,
    ):
        total = sum(len(document.entities_of(entity)) for document in documents)
        assert total >= 4, f"only {total} {entity.value} annotations across the corpus"


@pytest.mark.parametrize(
    "entity",
    [
        EntityType.IBAN,
        EntityType.CH_AHV,
        EntityType.CH_UID,
        EntityType.EMAIL,
        EntityType.IT_CODICE_FISCALE,
        EntityType.IT_PARTITA_IVA,
        EntityType.CREDIT_CARD,
    ],
)
def test_shipped_corpus_identifiers_are_found_by_the_validators(entity: EntityType):
    """Every annotated identifier must pass its real checksum.

    An identifier the validator rejects would make L1 look worse than it is, and
    the whole point of the corpus is to measure rather than guess.

    PHONE is deliberately absent: see the test below. These are the types L1 owns
    from pattern to checksum, so for them a miss really is a corpus defect.
    """
    pytest.importorskip("stdnum")
    from freedocs.detect.validators import ValidatorDetector

    detector = ValidatorDetector()
    for document in load_corpus():
        found = {(f.span.start, f.span.end) for f in detector.detect(document.text)}
        for gold in document.entities_of(entity):
            assert (gold.span.start, gold.span.end) in found, (
                f"{document.name}: {gold.text!r} is annotated as {entity.value} but "
                "the validator layer does not accept it"
            )


def test_annotated_phone_numbers_are_real_numbers():
    """PHONE is checked for validity, not for detection, and the difference matters.

    The guard that matters is that a canary is a genuine number: an invented one is
    rejected, never detected, never leaks, and passes every test while proving
    nothing. Whether L1 *matches* it is a separate question with a real answer —
    the corpus carries `+39 0444 512 337`, which phonenumbers calls valid and
    STRICT_GROUPING declines, because the Italian plan groups the subscriber part
    as `512337`. That gap is a measured result about the detector, so asserting it
    away here would hide the very thing the corpus exists to show.
    """
    phonenumbers = pytest.importorskip("phonenumbers")

    for document in load_corpus():
        for gold in document.entities_of(EntityType.PHONE):
            parsed = phonenumbers.parse(gold.text, None)
            assert phonenumbers.is_valid_number(parsed), (
                f"{document.name}: {gold.text!r} is annotated as a phone number but "
                "is not a valid one"
            )

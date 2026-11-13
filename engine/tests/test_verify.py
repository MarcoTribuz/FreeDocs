"""Stage 6: what counts as a survivor, and what is only reported.

The search is a substring count and propagation matches whole words, so a
one-word value that is also part of ordinary words used to fail every scrub of
a document containing them. These pin the line now drawn: a whole-word survivor
is a leak, a one-word value inside a longer word is a warning, and a multi-word
value inside a word is still a leak, because that is fused text and not the
language.
"""

from __future__ import annotations

from pathlib import Path

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.registry import DetectorRegistry
from freedocs.formats.plaintext import PlainTextHandler
from freedocs.pipeline import Scrubber
from freedocs.report import build_report
from freedocs.verify import verify_output


def person(text: str) -> Finding:
    return Finding(
        span=Span(0, len(text)),
        entity=EntityType.PERSON,
        text=text,
        layer=Layer.NER,
        detector="gliner2:person",
    )


def found(text: str, entity: EntityType) -> Finding:
    return Finding(
        span=Span(0, len(text)),
        entity=entity,
        text=text,
        layer=Layer.VALIDATOR,
        detector="stub",
    )


def verify(output: str, *values: str, kept: tuple[str, ...] = ()):
    return verify_with(output, [person(value) for value in values], kept=kept)


def verify_with(output: str, findings: list[Finding], kept: tuple[str, ...] = ()):
    return verify_output(
        PlainTextHandler,
        Path("out.txt"),
        output.encode("utf-8"),
        findings,
        kept=kept,
    )


def test_a_one_word_value_inside_longer_words_is_reported_not_raised():
    """The real document: ``Acteurs`` was a PERSON and ``facteurs`` survived."""
    result = verify("La grille des facteurs 3P et les facteurs de bien-être.", "Acteurs")
    assert result.ok
    assert [(item.entity, item.occurrences) for item in result.embedded] == [("PERSON", 2)]


def test_the_summary_does_not_say_no_leak_alone_when_words_were_left():
    """Read alone, "no leak" means none of the strings is in the file."""
    summary = verify("La grille des facteurs 3P.", "Acteurs").summary()
    assert summary.startswith("no leak:")
    assert "1 occurrence(s) left inside longer words" in summary
    assert "inside" not in verify("Rien ici.", "Acteurs").summary()


def test_a_whole_word_survivor_is_still_a_leak():
    result = verify("Les Acteurs et les facteurs.", "Acteurs")
    assert not result.ok
    assert result.leaks[0].occurrences == 1
    assert result.embedded[0].occurrences == 1


def test_a_multi_word_value_fused_into_a_word_is_still_a_leak():
    """How ``Malakoff Humanisconsulte`` hid a company name: fused, not language."""
    result = verify("Voir Malakoff Humanisconsulte en ligne.", "Malakoff Humanis")
    assert not result.ok
    assert result.embedded == ()


def test_an_underscore_separates_so_a_filename_part_is_a_word():
    """``2022_swica_resume`` holds the insurer's name as a word: still a leak."""
    result = verify("Fichier 2022-03-23_swica_resume_etude.pdf joint.", "SWICA")
    assert not result.ok


def test_the_allowance_counts_whole_word_occurrences():
    result = verify("Zurigo, e i zurighesi; Zurigo.", "Zurigo", kept=("Zurigo",))
    assert not result.ok
    assert result.leaks[0].occurrences == 2
    assert result.leaks[0].allowed == 1


def test_the_warning_quotes_no_value():
    result = verify("Les facteurs.", "Acteurs")
    sentence = result.embedded[0].describe()
    assert "acteurs" not in sentence.casefold()
    assert "PERSON" in sentence


class _OnlyTheWholeWord:
    """A detector that finds ``Acteurs`` where it stands alone, as the model did.

    Not a removal override: those are substring instructions and would take the
    letters inside ``facteurs`` too, which is not the case being tested.
    """

    def detect(self, text: str):
        return [person("Acteurs")]


def test_a_scrub_with_only_embedded_survivors_writes_and_says_so(tmp_path: Path):
    """End to end: the file is written, the warning reaches the report value-free."""
    source = tmp_path / "note.txt"
    source.write_bytes(b"Acteurs : voir la grille des facteurs.\n")
    registry = DetectorRegistry(detectors=[_OnlyTheWholeWord()])
    result = Scrubber(registry=registry).scrub_file(source)

    assert result.verify.ok
    assert b"Acteurs" not in result.output
    assert b"facteurs" in result.output
    report = build_report(result)
    assert report["verification"]["inside_longer_words"] == [
        {"entity": "PERSON", "detector": "gliner2:person", "occurrences": 1}
    ]
    assert any("inside longer words" in warning for warning in report["warnings"])
    assert "acteurs" not in str(report).casefold().replace("facteurs", "")


def test_a_capitalised_word_at_a_sentence_start_is_still_language():
    result = verify("Facteurs de risque. Les facteurs.", "Acteurs")
    assert result.ok
    assert result.embedded[0].occurrences == 2


def test_an_identifier_fused_into_longer_text_is_still_a_leak():
    """The exemption is for prose. An IBAN run into a word is the IBAN."""
    iban = "CH9300762011623852957"
    result = verify_with(f"ref {iban}X fin", [found(iban, EntityType.IBAN)])
    assert not result.ok
    assert result.embedded == ()


def test_an_email_fused_into_longer_text_is_still_a_leak():
    email = "mario.rossi@example.com"
    result = verify_with(f"contatto:{email}x", [found(email, EntityType.EMAIL)])
    assert not result.ok


def test_a_name_joined_to_digits_is_fusion_not_language():
    result = verify("utente rossi1985 attivo", "Rossi")
    assert not result.ok
    assert result.embedded == ()


def test_camel_case_is_fusion_not_language():
    result = verify("account MarioRossi attivo", "Rossi")
    assert not result.ok


def test_an_all_lowercase_username_is_the_stated_cost():
    """Pinned so the trade cannot widen or narrow without someone deciding to."""
    result = verify("utente mrossi attivo", "Rossi")
    assert result.ok
    assert result.embedded[0].occurrences == 1


def test_all_capitals_are_fusion_not_language():
    result = verify("account MARIOROSSI attivo", "Rossi")
    assert not result.ok


def test_the_exemption_never_counts_what_the_search_did_not():
    """A padded value is searched as given, so the exemption is too.

    Both counts used to come from different searches - the substring count on
    the value as given, the exemption on it stripped - so the second could
    subtract occurrences the first never counted.
    """
    result = verify_with("Les facteurs, Acteurs.", [person(" Acteurs")])
    assert not result.ok
    assert result.leaks[0].occurrences == 1
    assert result.embedded == ()

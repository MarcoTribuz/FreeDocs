"""A suppressed occurrence must not read as a leak - and must still be reported.

The failure this file pins came from a real document. Four values "still present
in the scrubbed output" and nothing written, on a file where the engine had done
exactly what it was designed to do: it removed a city from a party's address and
left the same city in the governing-law clause, and it removed a company name
and left the identical lowercase word that is an ordinary verb. Stage 6 searches
for *values*, both of those passes judge *occurrences*, and nothing told stage 6
that the leftovers were decisions.

Stubbed detectors rather than the model, for the reason the format tests pin
``detectors="l1"``: the behaviour under test is in ``detect/suppress.py`` and
``verify.py``, neither of which knows what nominated the finding, and a model in
the loop would make the case slow and threshold-sensitive. Plain text rather
than a docx for the same reason - stages 3, 4 and 6 are format-agnostic, so a
zip container would only add a way for the test to fail for another reason.
"""

from __future__ import annotations

import re
from pathlib import Path

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.detect.registry import DetectorRegistry
from freedocs.pipeline import Scrubber
from freedocs.report import build_report

#: A city in a party's address and again in the jurisdiction clause. The first
#: is confidential, the second is what the contract is argued under, and
#: ``drop_jurisdiction_mentions`` is paid to tell them apart.
JURISDICTION_DOC = (
    "Rapport d'avancement\n"
    "Adresse du mandant: Rue du Simplon 12, 1006 Lausanne.\n"
    "Le bureau de Lausanne assure le suivi.\n"
    "Les tribunaux de Lausanne sont seuls competents.\n"
)

#: A company whose name is also an ordinary lowercase word. The rule that drops
#: the second is case-sensitive; verification casefolds. Both are correct.
LOWERCASE_DOC = (
    "Realise SA a livre le rapport d'avancement.\nLa societe realise les travaux depuis mars.\n"
)


def occurrences(text: str, value: str, entity: EntityType) -> list[Finding]:
    """Every whole-word occurrence, which is what a detector actually returns.

    Bounded rather than a plain ``find``: no model returns the ``Lausanne``
    inside ``Rapport_Lausanne_2026``, and a stub that did would quietly remove
    the one occurrence a test below depends on surviving.
    """
    return [
        Finding(
            span=Span(match.start(), match.end()),
            entity=entity,
            text=value,
            layer=Layer.NER,
            detector="stub:model",
            confidence=0.9,
        )
        for match in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", text)
    ]


def scrubber_for(value: str, entity: EntityType, **kwargs) -> Scrubber:
    class Stub:
        def detect(self, text: str) -> list[Finding]:
            return occurrences(text, value, entity)

    return Scrubber(registry=DetectorRegistry(detectors=[Stub()]), **kwargs)


def source(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "avancement.txt"
    path.write_text(text, encoding="utf-8", newline="")
    return path


# ── The failure, in both shapes ──────────────────────────────────────────────


def test_a_jurisdiction_mention_does_not_fail_the_scrub(tmp_path: Path):
    result = scrubber_for("Lausanne", EntityType.LOCATION).scrub_file(
        source(tmp_path, JURISDICTION_DOC)
    )
    assert result.verify.ok, result.verify.summary()


def test_the_jurisdiction_mention_is_still_in_the_output(tmp_path: Path):
    """The allowance must not be bought by removing the clause after all.

    Filtering the clause mention *before* propagation was measured and cost
    three covered entities on the corpus; this test is what stops the leak fix
    from quietly becoming that change.
    """
    result = scrubber_for("Lausanne", EntityType.LOCATION).scrub_file(
        source(tmp_path, JURISDICTION_DOC)
    )
    output = result.output.decode("utf-8")
    assert "Les tribunaux de Lausanne" in output
    # The address goes as a whole: `fill_address_gaps` anchors on the postal code
    # and absorbs the LOCATION it contains, which is why the city inside it is
    # not separately numbered.
    assert "Adresse du mandant: [ADDRESS_1]" in output
    assert "Le bureau de [LOCATION_1]" in output


def test_a_lowercase_copy_of_a_confirmed_name_is_removed(tmp_path: Path):
    """A confirmed company propagates onto its lowercase occurrences, and stays.

    This case used to be an allowance: the model claimed `Realise` and the
    lowercase rule dropped the propagated copy, so the copy stayed in the output
    and stage 6 had to be told to permit it. Exempting copies from that rule -
    which the `swica` filename case forced - fixes it at the root instead, and a
    removal is a better answer than a permission.

    The accepted cost is visible in the last assertion: where the value is also
    an ordinary lowercase word, that word goes too. Over-redaction rather than a
    leak, and the direction this codebase takes when unsure. It has never been
    seen on a real document; if it is, the shape of the fix is to exempt only a
    copy sitting inside a compound token - `_swica_` has a separator beside it
    and a verb in prose does not - which needs the text and a measured case.
    """
    result = scrubber_for("Realise", EntityType.ORGANISATION).scrub_file(
        source(tmp_path, LOWERCASE_DOC)
    )
    assert result.verify.ok, result.verify.summary()
    output = result.output.decode("utf-8")
    assert output.startswith("[ORGANISATION_1] SA")
    assert result.suppressed == []
    assert "La societe [ORGANISATION_1] les travaux" in output


# ── The allowance is a count, not an exemption ───────────────────────────────


def test_an_occurrence_nobody_suppressed_is_still_a_leak(tmp_path: Path):
    """The half that makes the allowance safe.

    One occurrence is a declared decision; the second is one nothing accounted
    for, and the allowance must not stretch to cover it.

    Built from the asymmetry that is still open rather than a stubbed miss.
    Propagation refuses to reach inside a longer word - `Sion` is not in
    `Sionne`, the river it stands on, exactly as `Zug` is not in `Zugang` - while
    stage 6 counts substrings. This construction has been rewritten twice as
    other cases were closed: the underscore in a filename now propagates, and a
    lowercase common noun is no longer a LOCATION at all. Whatever the right
    answer for what remains, it must not be "permitted because a clause mention
    was suppressed".
    """
    text = (
        "Bureau a Sion.\n"
        "Les tribunaux de Sion sont seuls competents.\n"
        "Le sentier longe la Sionne.\n"
    )
    scrubber = scrubber_for("Sion", EntityType.LOCATION, strict=False)
    result = scrubber.scrub_file(source(tmp_path, text))
    assert not result.verify.ok
    leak = result.verify.leaks[0]
    assert leak.occurrences == 2
    assert leak.allowed == 1


def test_nothing_suppressed_grants_nothing(tmp_path: Path):
    """A document with no clause must behave exactly as it did before."""
    text = "Bureau a Lausanne. Siege a Lausanne.\n"
    result = scrubber_for("Lausanne", EntityType.LOCATION).scrub_file(source(tmp_path, text))
    assert result.verify.ok
    assert "Lausanne" not in result.output.decode("utf-8")
    assert result.suppressed == []


# ── It has to be said out loud ───────────────────────────────────────────────


def test_the_preview_carries_what_was_suppressed(tmp_path: Path):
    """The window shows the preview; the decision has to be visible there too."""
    scrubber = scrubber_for("Lausanne", EntityType.LOCATION)
    inspection = scrubber.inspect_file(source(tmp_path, JURISDICTION_DOC))
    assert [s.rule for s in inspection.suppressed] == ["jurisdiction"]
    assert inspection.suppressed[0].finding.entity is EntityType.LOCATION


def test_the_report_says_a_value_was_left_in_place(tmp_path: Path):
    """Without this the fix turns a loud failure into a silence.

    A reader who is told nothing believes the city is gone from the document,
    and it is not.
    """
    result = scrubber_for("Lausanne", EntityType.LOCATION).scrub_file(
        source(tmp_path, JURISDICTION_DOC)
    )
    report = build_report(result, key_file=False)
    assert report["suppressed"] == [
        {"entity": "LOCATION", "rule": "jurisdiction", "occurrences": 1}
    ]


def test_the_report_still_names_no_value(tmp_path: Path):
    """The report reaches disk and gets attached to tickets."""
    import json

    result = scrubber_for("Lausanne", EntityType.LOCATION).scrub_file(
        source(tmp_path, JURISDICTION_DOC)
    )
    rendered = json.dumps(build_report(result, key_file=False))
    assert "Lausanne" not in rendered
    assert "Simplon" not in rendered


# ── A flagged occurrence of a removable value ────────────────────────────────


#: The shape found on the real document: the same string comes back JOB_TITLE in
#: one sentence and ORGANISATION in the next. The second is removed, the first is
#: `REPORT_ONLY` and kept, and stage 6 searches for values.
MISLABEL_DOC = (
    "Cout de l'absence en 2024\n"
    "Le cout total direct pour l'Etat-employeur s'eleve a 136 millions.\n"
    "L'Etat-employeur a donc subi une hausse de 19,4% en trois ans.\n"
)


def test_a_mislabelled_occurrence_does_not_survive(tmp_path: Path):
    first = MISLABEL_DOC.index("Etat-employeur")
    second = MISLABEL_DOC.rindex("Etat-employeur")

    class Mislabel:
        def detect(self, text: str) -> list[Finding]:
            return [
                Finding(
                    span=Span(first, first + 14),
                    entity=EntityType.JOB_TITLE,
                    text="Etat-employeur",
                    layer=Layer.NER,
                    detector="stub:model",
                    confidence=0.81,
                ),
                Finding(
                    span=Span(second, second + 14),
                    entity=EntityType.ORGANISATION,
                    text="Etat-employeur",
                    layer=Layer.NER,
                    detector="stub:model",
                    confidence=0.87,
                ),
            ]

    scrubber = Scrubber(registry=DetectorRegistry(detectors=[Mislabel()]))
    result = scrubber.scrub_file(source(tmp_path, MISLABEL_DOC))
    assert result.verify.ok, result.verify.summary()
    output = result.output.decode("utf-8")
    assert "Etat-employeur" not in output
    assert output.count("[ORGANISATION_1]") == 2


def test_a_job_title_nobody_else_claims_is_still_only_flagged(tmp_path: Path):
    """The rule must not turn REPORT_ONLY into REDACT for everything it touches.

    Removing a job title silently hides residual risk instead of surfacing it,
    which is the whole reason the category exists.
    """
    text = "La Directrice des finances a valide le rapport.\n"
    start = text.index("Directrice des finances")

    class OnlyFlagged:
        def detect(self, _text: str) -> list[Finding]:
            return [
                Finding(
                    span=Span(start, start + len("Directrice des finances")),
                    entity=EntityType.JOB_TITLE,
                    text="Directrice des finances",
                    layer=Layer.NER,
                    detector="stub:model",
                    confidence=0.81,
                )
            ]

    result = Scrubber(registry=DetectorRegistry(detectors=[OnlyFlagged()])).scrub_file(
        source(tmp_path, text)
    )
    assert "Directrice des finances" in result.output.decode("utf-8")
    assert len(result.reported) == 1


# ── The allowance must not shelter a propagated value ────────────────────────


def test_a_propagated_copy_in_a_filename_is_removed(tmp_path: Path):
    """The end of the chain, and the one failure widening the allowance can cause.

    `SWICA` is confirmed where the model saw it. Propagation reaches the
    lowercase copy inside the filename because `_` is a separator. If the
    lowercase rule then drops that copy, the drop is declared to stage 6 as a
    decision, verification permits the value, and the insurer's name ships in a
    document reporting no leak. Every step is a rule working as designed and the
    result is the leak the whole feature exists to prevent.
    """
    text = (
        "Etude SWICA sur les absences de longue duree.\n"
        "Source: 2022-03-23_swica_resume_etude_prescriptions.pdf\n"
    )
    result = scrubber_for("SWICA", EntityType.ORGANISATION).scrub_file(source(tmp_path, text))
    assert result.verify.ok, result.verify.summary()
    output = result.output.decode("utf-8")
    assert "swica" not in output.casefold()
    assert result.suppressed == []

"""The NER layer with the real model behind it.

Separated from the rest of the suite because it downloads roughly 1.2 GB on first
run and takes seconds per case rather than milliseconds. Skipped automatically
when the ``ner`` extra is absent, and marked ``slow`` so it can be excluded
deliberately.

Assertions stay deliberately coarse. Pinning exact spans or scores would turn one
model version's behaviour into a requirement, and the next model would "fail"
tests while being better. Quality belongs to ``freedocs benchmark``, which
measures it against labelled data and prints a number; these tests only check
that the layer is wired up and behaves sanely.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gliner2", reason="the 'ner' extra is required")

from freedocs.core.errors import MissingDependency
from freedocs.core.findings import EntityType, Layer
from freedocs.detect.propagate import DETECTOR_SUFFIX
from freedocs.pipeline import NO_NER_NOTE, Scrubber, build_registry, default_registry

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def registry():
    """Module-scoped: loading the model per test would dominate the runtime."""
    return build_registry("all")


def entities_in(registry, text: str) -> dict[EntityType, list[str]]:
    out: dict[EntityType, list[str]] = {}
    for finding in registry.detect(text):
        out.setdefault(finding.entity, []).append(finding.text)
    return out


# -- wiring -------------------------------------------------------------------


def test_the_default_stack_includes_the_ner_layer():
    """With the extra installed, a scrub must not quietly run on checksums alone."""
    from freedocs.detect.ner import NerDetector

    detectors = default_registry().detectors
    assert any(isinstance(d, NerDetector) for d in detectors)
    assert default_registry().notes == []


def test_the_default_stack_states_the_gap_when_ner_is_missing(monkeypatch):
    """A fallback nobody is told about is the failure this project refuses."""
    import freedocs.pipeline as pipeline

    original = pipeline.build_registry

    def only_l1(spec: str = "l1", *, countries=None):
        if spec == "l1":
            return original("l1", countries=countries)
        raise MissingDependency("simulated: the ner extra is not installed")

    monkeypatch.setattr(pipeline, "build_registry", only_l1)
    registry = pipeline.default_registry()
    assert registry.notes == [NO_NER_NOTE]
    # The note has to name what is missing, not just say something is.
    assert "NOT being detected" in NO_NER_NOTE
    assert "names" in NO_NER_NOTE


def test_registry_notes_reach_the_scrub_report(tmp_path: Path, monkeypatch):
    import freedocs.pipeline as pipeline

    original = pipeline.build_registry
    monkeypatch.setattr(
        pipeline,
        "build_registry",
        lambda spec="l1", *, countries=None: (
            original("l1", countries=countries)
            if spec == "l1"
            else (_ for _ in ()).throw(MissingDependency("no ner"))
        ),
    )
    path = tmp_path / "nota.txt"
    path.write_text("Nessun dato qui.\n", encoding="utf-8")

    result = Scrubber(registry=pipeline.default_registry()).scrub_file(path)
    assert NO_NER_NOTE in result.warnings


# -- behaviour ----------------------------------------------------------------


def test_a_person_name_is_detected_in_italian(registry):
    found = entities_in(registry, "Il cliente Mario Rossi ha firmato il contratto.")
    assert any("Mario Rossi" in text for text in found.get(EntityType.PERSON, []))


def test_a_person_name_is_detected_in_german(registry):
    """One multilingual model, no language hint. That is the point of GLiNER2."""
    found = entities_in(registry, "Der Kunde Andreas Meier hat den Vertrag unterschrieben.")
    assert any("Andreas Meier" in text for text in found.get(EntityType.PERSON, []))


def test_checksummed_identifiers_still_win_over_the_model(registry):
    """L1 outranks L2 on overlap, so an IBAN stays an IBAN."""
    from .conftest import CANARIES

    findings = registry.detect(f"Bonifico su {CANARIES['IBAN']} entro venerdi.")
    ibans = [f for f in findings if f.entity is EntityType.IBAN]
    assert len(ibans) == 1
    assert ibans[0].layer is Layer.VALIDATOR
    assert ibans[0].text == CANARIES["IBAN"]


def test_a_repeated_name_is_covered_at_every_mention(registry):
    """Model confidence varies with context; propagation is what closes the gap."""
    text = (
        "Presenti: Anna Bianchi e Giuseppe Conti.\n"
        "Il verbale e stato redatto in due copie.\n"
        "La revisione finale spetta a Anna Bianchi entro fine mese.\n"
    )
    spans = [f for f in registry.detect(text) if f.text == "Anna Bianchi"]
    assert len(spans) == 2, "both mentions must be found, whichever layer finds them"
    assert any(DETECTOR_SUFFIX in f.detector for f in spans) or all(
        f.layer is Layer.NER for f in spans
    )


def test_a_name_does_not_survive_an_end_to_end_scrub(tmp_path: Path):
    """The gap M2 exists to close: names used to pass straight through."""
    path = tmp_path / "verbale.txt"
    path.write_text("Il cliente Mario Rossi ha firmato il contratto.\n", encoding="utf-8")

    result = Scrubber(registry=build_registry("all")).scrub_file(path)
    output = result.output.decode("utf-8")
    assert "Mario Rossi" not in output
    assert "[PERSON_1]" in output
    assert result.verify.ok

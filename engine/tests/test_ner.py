"""The NER layer's own logic: chunking, offsets, trimming, thresholding.

None of this needs a model. Using a stub backend keeps these tests fast and, more
importantly, makes them test FreeDocs rather than test a download.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from freedocs.core.findings import EntityType, Layer
from freedocs.detect.ner import (
    CHUNK_OVERLAP,
    MAX_CHUNK_CHARS,
    NerDetector,
    RawEntity,
    iter_chunks,
)


class StubBackend:
    """Finds a fixed needle wherever it appears in whatever it is handed."""

    name = "stub"

    def __init__(self, needle: str, label: str = "person", score: float = 0.9) -> None:
        self.needle = needle
        self.label = label
        self.score = score
        self.calls: list[str] = []

    def labels(self) -> Sequence[str]:
        return [self.label]

    def predict(self, text: str) -> Sequence[RawEntity]:
        self.calls.append(text)
        out = []
        start = text.find(self.needle)
        while start >= 0:
            out.append(
                RawEntity(
                    start=start, end=start + len(self.needle), label=self.label, score=self.score
                )
            )
            start = text.find(self.needle, start + 1)
        return out


def detector(backend: object, **kwargs) -> NerDetector:
    instance = NerDetector(**kwargs)
    instance._backend = backend  # type: ignore[attr-defined]
    return instance


# -- chunking -----------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert list(iter_chunks("breve")) == [(0, "breve")]


def test_long_text_is_split_and_fully_covered():
    text = "".join(f"Frase numero {i}. " for i in range(400))
    chunks = list(iter_chunks(text))
    assert len(chunks) > 1
    for offset, chunk in chunks:
        assert text[offset : offset + len(chunk)] == chunk, "offset must locate the chunk"
    assert chunks[-1][0] + len(chunks[-1][1]) == len(text), "the tail must be covered"


def test_chunks_stay_within_the_size_limit():
    """Beyond the model's token limit input is silently truncated."""
    text = "parola " * 2000
    assert all(len(chunk) <= MAX_CHUNK_CHARS for _, chunk in iter_chunks(text))


def test_chunking_terminates_when_no_boundary_exists():
    """A boundary search that finds nothing must not stall the loop."""
    text = "x" * (MAX_CHUNK_CHARS * 3)
    chunks = list(iter_chunks(text))
    assert len(chunks) < 20
    assert chunks[-1][0] + len(chunks[-1][1]) == len(text)


def test_an_entity_on_a_chunk_boundary_is_found_once():
    filler = "Testo di riempimento. " * 60
    text = filler + "Mario Rossi" + filler
    backend = StubBackend("Mario Rossi")
    findings = detector(backend).detect(text)
    assert len(backend.calls) > 1, "the fixture must actually straddle a boundary"
    assert len(findings) == 1
    assert findings[0].text == "Mario Rossi"
    assert text[findings[0].span.start : findings[0].span.end] == "Mario Rossi"


# -- offsets and normalisation ------------------------------------------------


def test_offsets_are_absolute_not_chunk_relative():
    text = "Riempimento. " * 200 + "Anna Bianchi ancora."
    findings = detector(StubBackend("Anna Bianchi")).detect(text)
    assert findings
    for finding in findings:
        assert text[finding.span.start : finding.span.end] == "Anna Bianchi"


@pytest.mark.parametrize("suffix", [" ", ".", ",", ";", ":", ")", " .", ".\n"])
def test_trailing_punctuation_is_trimmed(suffix: str):
    """Models include the trailing comma; redacting it is pure over-redaction."""
    text = f"Il cliente Mario Rossi{suffix} paga."
    backend = StubBackend(f"Mario Rossi{suffix}")
    (finding,) = detector(backend).detect(text)
    assert finding.text == "Mario Rossi"


def test_leading_whitespace_is_trimmed():
    text = "Il cliente  Mario Rossi paga."
    (finding,) = detector(StubBackend(" Mario Rossi")).detect(text)
    assert finding.text == "Mario Rossi"


def test_a_prediction_made_only_of_punctuation_is_dropped():
    (findings) = detector(StubBackend(" , ")).detect("a , b")
    assert findings == []


def test_findings_are_labelled_as_layer_two():
    (finding,) = detector(StubBackend("Mario Rossi")).detect("Mario Rossi paga.")
    assert finding.layer is Layer.NER
    assert finding.entity is EntityType.PERSON
    assert finding.detector == "stub:person"


def test_findings_come_back_in_position_order():
    text = "Anna Bianchi e Anna Bianchi e Anna Bianchi"
    findings = detector(StubBackend("Anna Bianchi")).detect(text)
    starts = [f.span.start for f in findings]
    assert starts == sorted(starts) == [0, 15, 30]


# -- thresholds and label mapping ---------------------------------------------


def test_low_scoring_predictions_are_discarded():
    backend = StubBackend("Mario Rossi", score=0.3)
    assert detector(backend, min_score=0.5).detect("Mario Rossi paga.") == []
    assert detector(backend, min_score=0.2).detect("Mario Rossi paga.") != []


def test_an_unmapped_label_is_dropped_rather_than_guessed():
    """A mislabelled finding gets the wrong policy applied to it."""
    backend = StubBackend("Mario Rossi", label="vibe")
    assert detector(backend).detect("Mario Rossi paga.") == []


def test_backend_labels_are_mapped_case_insensitively():
    backend = StubBackend("Acme SA", label="ORGANIZATION")
    (finding,) = detector(backend).detect("Acme SA fattura.")
    assert finding.entity is EntityType.ORGANISATION


def test_empty_text_never_reaches_the_backend():
    backend = StubBackend("x")
    assert detector(backend).detect("   \n  ") == []
    assert backend.calls == []


def test_overlap_constant_is_smaller_than_the_chunk():
    """Otherwise chunking would never advance."""
    assert 0 < CHUNK_OVERLAP < MAX_CHUNK_CHARS

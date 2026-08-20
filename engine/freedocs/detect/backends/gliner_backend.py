"""GLiNER2 backend.

``fastino/gliner2-privacy-filter-PII-multi`` sits on an ``mdeberta-v3-base``
encoder, so one model covers Italian, German, French and English without being
told which it is looking at. That matters more than it sounds: the alternative
family needs the document's language named up front, and a scrubber that has to
guess the language before it can find names has an extra way to fail silently.

The model is asked for entities at a low threshold and the real filtering happens
in :class:`~freedocs.detect.ner.NerDetector`. One tuning knob, in one place,
measurable with ``freedocs benchmark``.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Sequence
from dataclasses import dataclass, field

from ...core.errors import MissingDependency
from ..ner import RawEntity

#: Roughly 1.2 GB, fetched to the Hugging Face cache on first use and never
#: bundled. Pinned by name so an upgrade is a deliberate, re-benchmarked change.
DEFAULT_MODEL = "fastino/gliner2-privacy-filter-PII-multi"

#: Requested in the model's own vocabulary; mapped to EntityType afterwards.
#: Phrases rather than bare tokens ("phone number", not "phone") because the
#: model is prompted with these strings and reads them as descriptions.
DEFAULT_LABELS: tuple[str, ...] = (
    "person",
    "organization",
    "location",
    "address",
    "email",
    "phone number",
    "iban",
    "credit card number",
    "date of birth",
    "job title",
)

#: Deliberately below any useful operating point: recall here, filtering later.
MODEL_THRESHOLD = 0.2


@dataclass
class GlinerBackend:
    name: str = "gliner2"
    model_id: str = DEFAULT_MODEL
    requested_labels: tuple[str, ...] = DEFAULT_LABELS
    threshold: float = MODEL_THRESHOLD
    _model: object | None = field(default=None, init=False, repr=False)

    def labels(self) -> Sequence[str]:
        return self.requested_labels

    @property
    def model(self) -> object:
        if self._model is None:
            self._model = self._load()
        return self._model

    def _load(self) -> object:
        try:
            from gliner2 import GLiNER2
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise MissingDependency(
                "gliner2 is required for the GLiNER2 backend; install the 'ner' extra"
            ) from exc
        # The library prints a configuration banner to stdout on load, which would
        # land in the middle of CLI output and, worse, in piped JSON.
        with contextlib.redirect_stdout(io.StringIO()):
            return GLiNER2.from_pretrained(self.model_id, map_location="cpu")

    def predict(self, text: str) -> Sequence[RawEntity]:
        result = self.model.extract_entities(  # type: ignore[attr-defined]
            text,
            list(self.requested_labels),
            threshold=self.threshold,
            include_confidence=True,
            include_spans=True,
        )
        out: list[RawEntity] = []
        for label, hits in (result or {}).get("entities", {}).items():
            for hit in hits:
                # include_spans=True is what makes this backend usable at all;
                # without offsets there is no way back to a run or a rectangle.
                if "start" not in hit or "end" not in hit:
                    continue
                out.append(
                    RawEntity(
                        start=int(hit["start"]),
                        end=int(hit["end"]),
                        label=label,
                        score=float(hit.get("confidence", 1.0)),
                    )
                )
        return out

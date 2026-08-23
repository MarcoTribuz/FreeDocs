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
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ...core.errors import MissingDependency, ModelNotFound
from ..ner import RawEntity

#: Roughly 1.2 GB, fetched to the Hugging Face cache on first use by an installed
#: or installer build. Pinned by name so an upgrade is a deliberate,
#: re-benchmarked change. A portable build carries the weights instead and names
#: the directory in ``FREEDOCS_NER_MODEL``; see :func:`model_source`.
DEFAULT_MODEL = "fastino/gliner2-privacy-filter-PII-multi"

#: Set by the app when it finds a model beside the executable. The engine never
#: works out on its own that it is portable — it is told, and only ever with a
#: path that exists, which is the same rule ``_tessdata_candidates`` follows.
MODEL_ENV = "FREEDOCS_NER_MODEL"

#: What ``GLiNER2.from_pretrained`` opens first, so what makes a directory a
#: model rather than a directory.
_MODEL_MARKER = "config.json"

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
    # Asked for because the United States has no checksummed identifier this tool
    # can validate: `stdnum.us.ssn` accepts 89% of random values of the right
    # shape and `us.ein` 83%, because neither number has a check digit. An L1
    # rule there would be a tightened regex pretending to be a validator, which
    # is what this layer exists not to be. A model reading the surrounding words
    # is the honest place for an identifier only context can distinguish.
    "social security number",
    "tax identification number",
    "national identification number",
)

#: Deliberately below any useful operating point: recall here, filtering later.
MODEL_THRESHOLD = 0.2


def model_source() -> str:
    """The local directory to load from, or the repository id to download.

    ``GLiNER2.from_pretrained`` takes either — its ``download_or_local`` branches
    on ``os.path.isdir`` — which is what lets a portable build ship a flat
    directory of weights and need no Hugging Face cache, no redirected ``HF_HOME``
    and, because nothing is fetched, no writable state anywhere.

    Resolved per call rather than read at import. ``load_backend`` is ``@cache``d,
    so a module-level ``os.environ`` read would be taken once, by whichever caller
    happened to be first, and would be invisible to a test that sets the variable
    afterwards — the same trap ``DEFAULT_LABELS`` has.

    Raises rather than falling back when the variable names something unusable:
    see :class:`~freedocs.core.errors.ModelNotFound`.
    """
    configured = os.environ.get(MODEL_ENV)
    if not configured:
        return DEFAULT_MODEL
    directory = Path(configured).expanduser()
    if not (directory / _MODEL_MARKER).is_file():
        # Not `!r`: `repr` of a Windows path doubles every backslash, so the
        # message a user is meant to act on arrives full of `\\\\`.
        raise ModelNotFound(
            f"{MODEL_ENV} names {directory}, which holds no {_MODEL_MARKER}; "
            "a bundled model directory is incomplete or the path is wrong"
        )
    return str(directory)


@dataclass
class GlinerBackend:
    name: str = "gliner2"
    #: A factory, not a constant: the answer depends on the environment the
    #: sidecar was started with, and a default evaluated at class-definition time
    #: would freeze whatever was set when the module was first imported.
    model_id: str = field(default_factory=model_source)
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

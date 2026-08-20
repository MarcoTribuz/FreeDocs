"""Presidio + spaCy backend: the lightweight candidate.

Four ``*_core_news_sm`` models plus Presidio come to a couple of hundred
megabytes with no torch, against roughly 1.2 GB and a torch runtime for GLiNER2.
For a desktop app that difference is the whole download, so the small option
deserves to be measured rather than assumed inadequate.

It carries one structural disadvantage worth stating plainly: Presidio must be
told the document's language. FreeDocs does not know it. Rather than bolt on a
language detector — another component that fails silently on short or mixed text
— every configured language is run and the results merged. That is the honest
production behaviour, so it is what gets benchmarked, and the cost shows up in
the numbers instead of being hidden behind an assumption.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ...core.errors import MissingDependency
from ..ner import RawEntity

#: spaCy model per language. The small variants: the large ones would erase the
#: size advantage that is this backend's entire reason to exist.
DEFAULT_MODELS: dict[str, str] = {
    "it": "it_core_news_sm",
    "de": "de_core_news_sm",
    "fr": "fr_core_news_sm",
    "en": "en_core_web_sm",
}

#: Presidio recognisers worth asking for. Its own pattern recognisers overlap
#: with the L1 validator layer, which is checksum-backed and strictly better, so
#: only the model-driven entities are requested here.
DEFAULT_ENTITIES: tuple[str, ...] = (
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "DATE_TIME",
    "NRP",
)


@dataclass
class PresidioBackend:
    name: str = "presidio"
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    entities: tuple[str, ...] = DEFAULT_ENTITIES
    _analyzer: object | None = field(default=None, init=False, repr=False)

    def labels(self) -> Sequence[str]:
        return self.entities

    @property
    def analyzer(self) -> object:
        if self._analyzer is None:
            self._analyzer = self._load()
        return self._analyzer

    def _load(self) -> object:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise MissingDependency(
                "presidio-analyzer and spacy are required for the Presidio backend"
            ) from exc

        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": lang, "model_name": model} for lang, model in self.models.items()
                ],
            }
        )
        return AnalyzerEngine(
            nlp_engine=provider.create_engine(),
            supported_languages=list(self.models),
        )

    def predict(self, text: str) -> Sequence[RawEntity]:
        merged: dict[tuple[int, int, str], RawEntity] = {}
        for language in self.models:
            for hit in self.analyzer.analyze(  # type: ignore[attr-defined]
                text=text, language=language, entities=list(self.entities)
            ):
                key = (hit.start, hit.end, hit.entity_type)
                # The same entity is usually found by several languages. Keep the
                # most confident reading; a language-detection step would pick one
                # arbitrarily and be wrong on mixed-language documents.
                existing = merged.get(key)
                if existing is None or hit.score > existing.score:
                    merged[key] = RawEntity(
                        start=hit.start,
                        end=hit.end,
                        label=hit.entity_type,
                        score=float(hit.score),
                    )
        return list(merged.values())

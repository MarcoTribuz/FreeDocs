"""The labelled evaluation corpus.

Gold data is written as inline markup rather than as character offsets:

    Il cliente [PERSON:Mario Rossi] risiede a [LOCATION:Lugano].

Hand-maintaining offsets is how gold data quietly rots — insert a word and every
number after it is wrong, silently, and the benchmark starts measuring the
annotation instead of the model. Markup is reviewable by eye and the offsets are
derived.

The corpus is small and entirely synthetic. Numbers measured against it say
whether one detector beats another on business-document Italian, German, French
and English; they are not a published benchmark result and should never be
quoted as one. Every identifier in it passes its real checksum, for the same
reason the unit-test canaries do: a value the validator rejects would make a
detector look worse than it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..core.findings import EntityType, Span

#: ``[LABEL:text]``. Labels are :class:`EntityType` names.
MARKUP = re.compile(r"\[([A-Z_]+):([^\]]*)\]")

#: Where the corpus files live, relative to the repository's engine directory.
CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"


class CorpusError(ValueError):
    """The markup could not be parsed, or names an entity type we do not have.

    Raised rather than skipped: an annotation the loader silently ignores is an
    entity the benchmark will score the detector as hallucinating.
    """


@dataclass(frozen=True)
class GoldEntity:
    span: Span
    entity: EntityType
    text: str


@dataclass(frozen=True)
class CorpusDocument:
    name: str
    language: str
    text: str
    entities: tuple[GoldEntity, ...]

    def entities_of(self, entity: EntityType) -> tuple[GoldEntity, ...]:
        return tuple(gold for gold in self.entities if gold.entity is entity)


def parse_annotated(markup: str) -> tuple[str, list[GoldEntity]]:
    """Turn inline markup into plain text plus gold spans over that text."""
    if "]" in MARKUP.sub("", markup):
        raise CorpusError("unbalanced ']' outside an annotation; check the markup")

    out: list[str] = []
    entities: list[GoldEntity] = []
    cursor = 0
    for match in MARKUP.finditer(markup):
        out.append(markup[cursor : match.start()])
        label, text = match.group(1), match.group(2)
        if not text:
            raise CorpusError(f"empty annotation for label {label!r}")
        try:
            entity = EntityType[label]
        except KeyError as exc:
            raise CorpusError(
                f"unknown entity label {label!r}; add it to EntityType or fix the corpus"
            ) from exc
        start = sum(len(chunk) for chunk in out)
        out.append(text)
        entities.append(GoldEntity(span=Span(start, start + len(text)), entity=entity, text=text))
        cursor = match.end()
    out.append(markup[cursor:])

    text = "".join(out)
    for gold in entities:
        actual = text[gold.span.start : gold.span.end]
        if actual != gold.text:
            raise CorpusError(
                f"offset mismatch for {gold.text!r}: the derived span holds {actual!r}"
            )
    return text, entities


def load_document(path: Path) -> CorpusDocument:
    """Load one corpus file. The stem is the language tag: ``it.txt`` -> ``it``."""
    text, entities = parse_annotated(path.read_text(encoding="utf-8"))
    return CorpusDocument(name=path.name, language=path.stem, text=text, entities=tuple(entities))


def load_corpus(directory: Path | None = None) -> list[CorpusDocument]:
    directory = directory or CORPUS_DIR
    paths = sorted(directory.glob("*.txt"))
    if not paths:
        raise CorpusError(f"no corpus files in {directory}")
    return [load_document(path) for path in paths]

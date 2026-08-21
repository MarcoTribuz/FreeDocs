"""Layer 2: the entities no checksum can confirm.

Names, organisations, locations and addresses have no check digit, so L1 cannot
touch them. The measured baseline is stark: L1 covers every structured identifier
in the corpus and exactly none of these, which is 57 of 95 gold entities left in
the document.

One requirement is absolute and shapes every backend here: a detector must return
**character offsets**. The anchors in :mod:`freedocs.core.stream` are the only
route from a detected span back into a run of a Word document or a rectangle on a
PDF page, and they are addressed by character. A model that returns entity text
without positions cannot drive an edit, which is exactly why a generative LLM
cannot serve as this layer (see :mod:`freedocs.detect.llm_review`, M8).

Backends are interchangeable so that the choice can be made on measured numbers
rather than on reputation. ``freedocs benchmark --detectors ner`` scores whichever
one is configured.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Protocol

from ..core.errors import MissingDependency
from ..core.findings import EntityType, Finding, Layer, Span

#: Longest text handed to a backend in one call, measured rather than guessed.
#: A sweep over 600-3600 characters puts removable coverage on a plateau from
#: 800 to 1500 (474-477 of 480) and degrades it above that, while over-redaction
#: falls monotonically with size (752 chars at 800, 493 at 3600) and flag-only
#: recall collapses (96.2% at 1500, 76.9% at 3600). 1200 sits in the plateau and
#: takes most of the over-redaction win before either cost starts.
#:
#: The reason originally written here — that an encoder truncates silently past
#: 512 tokens — does not hold for this backend. A name placed at increasing depth
#: in one call is still returned at 9815 characters, with the score decaying
#: 0.997 to 0.954, an order of magnitude above ``NerDetector.min_score``. The
#: ceiling is a quality trade, not a token limit, so raising it loses entities
#: rather than hiding a page.
MAX_CHUNK_CHARS = 1200

#: Overlap between consecutive chunks, so an entity straddling a boundary is seen
#: whole in at least one of them.
#:
#: 400 was tried and rejected. On the corpus as it stands it dominates 200 in
#: every column — one more entity covered, eleven fewer over-redacted characters,
#: the best exact F1 in the sweep — and none of that survives a control. Shifting
#: every boundary by prepending 137, 411 and 700 characters of unannotated text
#: makes the coverage win a wash and the over-redaction win a consistent loss
#: (620 chars against 595, averaged over the four alignments). That control is
#: the point: the same shift moves 1200/200 itself between 473 and 477 of 480, so
#: three entities is the noise floor here and no delta smaller than that is
#: readable off this corpus at all.
CHUNK_OVERLAP = 200

#: Paragraph and sentence boundaries, preferred over cutting mid-word.
_BOUNDARY = re.compile(r"\n\s*\n|(?<=[.!?])\s+")


@dataclass(frozen=True)
class RawEntity:
    """What a backend returns, before label mapping and thresholding."""

    start: int
    end: int
    label: str
    score: float


class NerBackend(Protocol):
    """A model that finds entities and says where they are."""

    #: Identifies the backend in reports and benchmark output.
    name: str

    def labels(self) -> Sequence[str]:
        """Labels this backend will be asked for, in its own vocabulary."""

    def predict(self, text: str) -> Sequence[RawEntity]:
        """Entities in ``text``, with offsets relative to ``text``."""


def iter_chunks(
    text: str, size: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> Iterator[tuple[int, str]]:
    """Yield ``(offset, chunk)`` covering ``text``, splitting on sane boundaries.

    Chunks overlap so that an entity spanning a cut is intact in one of them; the
    caller deduplicates. Cuts land on a paragraph or sentence boundary inside the
    last ``overlap`` characters when one exists, and mid-text otherwise — a
    guaranteed-progress fallback matters more than a tidy split, since a boundary
    search that finds nothing must not stall.
    """
    if len(text) <= size:
        yield 0, text
        return

    position = 0
    while position < len(text):
        end = min(position + size, len(text))
        if end < len(text):
            window = text[max(position, end - overlap) : end]
            boundaries = list(_BOUNDARY.finditer(window))
            if boundaries:
                end = max(position, end - overlap) + boundaries[-1].end()
        yield position, text[position:end]
        if end >= len(text):
            return
        position = max(position + 1, end - overlap)


#: Backend label (lowercased) to the entity type FreeDocs works in. Backends use
#: different vocabularies, and anything unmapped is dropped rather than guessed:
#: a mislabelled finding gets the wrong policy applied to it.
DEFAULT_LABEL_MAP: dict[str, EntityType] = {
    "person": EntityType.PERSON,
    "person name": EntityType.PERSON,
    "name": EntityType.PERSON,
    "full name": EntityType.PERSON,
    "per": EntityType.PERSON,
    "organization": EntityType.ORGANISATION,
    "organisation": EntityType.ORGANISATION,
    "company": EntityType.ORGANISATION,
    "org": EntityType.ORGANISATION,
    "location": EntityType.LOCATION,
    "city": EntityType.LOCATION,
    "country": EntityType.LOCATION,
    "gpe": EntityType.LOCATION,
    "loc": EntityType.LOCATION,
    "address": EntityType.ADDRESS,
    "street address": EntityType.ADDRESS,
    "postal address": EntityType.ADDRESS,
    "email": EntityType.EMAIL,
    "email address": EntityType.EMAIL,
    "phone": EntityType.PHONE,
    "phone number": EntityType.PHONE,
    "iban": EntityType.IBAN,
    "iban code": EntityType.IBAN,
    "credit card": EntityType.CREDIT_CARD,
    "credit card number": EntityType.CREDIT_CARD,
    "date": EntityType.DATE,
    "date of birth": EntityType.DATE,
    "date_time": EntityType.DATE,
    "job title": EntityType.JOB_TITLE,
    "age": EntityType.AGE,
    "postcode": EntityType.POSTCODE,
    "zip code": EntityType.POSTCODE,
    "ip address": EntityType.IP_ADDRESS,
    # Country-issued numbers a model may name but no checksum here can settle.
    # They arrive without a country, which is exactly why `confirms` gives no
    # opinion on them rather than dropping them: see validators.COUNTRY_ISSUED.
    "social security number": EntityType.NATIONAL_ID,
    "national identification number": EntityType.NATIONAL_ID,
    "national id": EntityType.NATIONAL_ID,
    "tax identification number": EntityType.TAX_ID,
    "tax number": EntityType.TAX_ID,
    "vat number": EntityType.VAT_ID,
    "company registration number": EntityType.COMPANY_ID,
}


@cache
def load_backend(name: str = "gliner2") -> NerBackend:
    """Instantiate a backend by name, loading its model. Once per process.

    Cached because the model is the expensive thing in this codebase by two
    orders of magnitude: loading GLiNER2 takes about 7.4 seconds and running it
    takes milliseconds. A fresh `NerDetector` starts with `_backend = None` and
    pays that again, and `NerDetector` is constructed once per registry — so
    anything that rebuilds a registry rebuilt the model.

    That went unnoticed until the country selection existed, because nothing
    rebuilt a registry mid-session before. `Session.registry` keys its cache on
    the countries as well as the layer spec, correctly: narrowing them changes
    which rules run. But the NER layer is *not* narrowed by country — the model
    reads names and addresses and has no notion of who issued anything — so
    every chip click in the window paid a full model load for a layer that had
    not changed. Measured over the pipe: 0.10 s for a repeated inspection, 7.4 s
    for the same inspection after one country was switched off.

    Keyed on the name alone, which is sound because that is the whole input: a
    caller wanting a different model or label set constructs the backend itself
    and hands it to `NerDetector`.
    """
    if name in {"gliner2", "gliner"}:
        from .backends.gliner_backend import GlinerBackend

        return GlinerBackend()
    if name == "presidio":
        from .backends.presidio_backend import PresidioBackend

        return PresidioBackend()
    raise MissingDependency(f"unknown NER backend {name!r}; expected 'gliner2' or 'presidio'")


@dataclass
class NerDetector:
    """Runs a NER backend over a text stream and normalises its output."""

    backend_name: str = "gliner2"
    #: Findings below this score are discarded before they reach the registry.
    #: Tuned against the corpus rather than picked: see the M2 numbers in README.
    min_score: float = 0.5
    label_map: dict[str, EntityType] = field(default_factory=lambda: dict(DEFAULT_LABEL_MAP))
    _backend: NerBackend | None = field(default=None, init=False, repr=False)

    @property
    def backend(self) -> NerBackend:
        if self._backend is None:
            self._backend = load_backend(self.backend_name)
        return self._backend

    def detect(self, text: str) -> list[Finding]:
        if not text.strip():
            return []

        seen: dict[tuple[int, int, str], Finding] = {}
        for offset, chunk in iter_chunks(text):
            for raw in self.backend.predict(chunk):
                finding = self._to_finding(raw, offset, text)
                if finding is None:
                    continue
                key = (finding.span.start, finding.span.end, finding.entity.value)
                # Overlapping chunks see the same entity twice; keep the more
                # confident reading rather than an arbitrary one.
                existing = seen.get(key)
                if existing is None or finding.confidence > existing.confidence:
                    seen[key] = finding
        return sorted(seen.values(), key=lambda f: (f.span.start, f.span.end))

    def _to_finding(self, raw: RawEntity, offset: int, text: str) -> Finding | None:
        if raw.score < self.min_score:
            return None
        entity = self.label_map.get(raw.label.strip().casefold())
        if entity is None:
            return None

        start, end = offset + raw.start, offset + raw.end
        if not 0 <= start < end <= len(text):
            return None
        # Models routinely include the trailing space or punctuation. Redacting
        # those would eat characters that were never confidential, and it shows
        # up directly in the over-redaction metric.
        surface = text[start:end]
        trimmed = surface.rstrip(" \t\n.,;:!?)")
        if not trimmed:
            return None
        end -= len(surface) - len(trimmed)
        leading = len(trimmed) - len(trimmed.lstrip(' \t\n(”"'))
        start += leading
        if start >= end:
            return None

        return Finding(
            span=Span(start, end),
            entity=entity,
            text=text[start:end],
            layer=Layer.NER,
            detector=f"{self.backend.name}:{raw.label}",
            confidence=min(1.0, max(0.0, raw.score)),
        )

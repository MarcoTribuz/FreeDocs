"""What the detectors produce, independent of any file format."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EntityType(str, Enum):
    """Categories of confidential data FreeDocs knows how to look for."""

    # Structured identifiers — validated by checksum, so precision is near 1.0.
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    IBAN = "IBAN"
    CREDIT_CARD = "CREDIT_CARD"
    IT_CODICE_FISCALE = "IT_CODICE_FISCALE"
    IT_PARTITA_IVA = "IT_PARTITA_IVA"
    CH_AHV = "CH_AHV"
    CH_UID = "CH_UID"
    CH_VAT = "CH_VAT"
    IP_ADDRESS = "IP_ADDRESS"
    MAC_ADDRESS = "MAC_ADDRESS"
    URL = "URL"

    # Free-text entities — only a NER model finds these.
    PERSON = "PERSON"
    ORGANISATION = "ORGANISATION"
    LOCATION = "LOCATION"
    ADDRESS = "ADDRESS"
    DATE = "DATE"

    # Quasi-identifiers: not identifying alone, but combined they re-identify.
    # Reported rather than removed by default.
    JOB_TITLE = "JOB_TITLE"
    AGE = "AGE"
    POSTCODE = "POSTCODE"


class Layer(str, Enum):
    """Which detection layer produced a finding. Drives conflict resolution."""

    VALIDATOR = "L1"
    NER = "L2"
    LLM_REVIEW = "L3"


#: Higher wins when two findings overlap. A checksum-validated IBAN beats a
#: model that thought the same digits were a phone number.
LAYER_PRECEDENCE: dict[Layer, int] = {
    Layer.VALIDATOR: 3,
    Layer.NER: 2,
    Layer.LLM_REVIEW: 1,
}


@dataclass(frozen=True, order=True)
class Span:
    """Half-open character range ``[start, end)`` in a :class:`TextStream`."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"span start must be >= 0, got {self.start}")
        if self.end < self.start:
            raise ValueError(f"span end {self.end} precedes start {self.start}")

    def __len__(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Span) -> bool:
        return self.start <= other.start and other.end <= self.end


@dataclass(frozen=True)
class Finding:
    """One piece of confidential data located in the flattened text."""

    span: Span
    entity: EntityType
    text: str
    layer: Layer
    detector: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if len(self.text) != len(self.span):
            raise ValueError(
                f"finding text is {len(self.text)} chars but span covers {len(self.span)}"
            )

    @property
    def precedence(self) -> int:
        return LAYER_PRECEDENCE[self.layer]

"""What to do with each finding, and what to put in its place.

FreeDocs performs *anonymisation*, not pseudonymisation: the mapping from
placeholder back to original value lives in memory for the duration of one run
and is then destroyed. Nothing is written to disk, so there is no key to steal
and the output is not personal data under GDPR Art. 4(5) reasoning.

That choice has a cost worth stating plainly: removing direct identifiers does
not remove re-identification risk from quasi-identifiers. A document stripped of
names can still say "the CFO of the Lugano branch hired in March 2024".
:data:`REPORT_ONLY` entities exist to surface exactly that, without pretending a
placeholder solved it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from types import TracebackType

from .findings import EntityType, Finding


class Action(str, Enum):
    """What the policy decided to do with a finding."""

    #: Replace with a typed placeholder such as ``[PERSONA_1]``.
    REDACT = "redact"
    #: Replace with a syntactically valid fake value, so downstream tools that
    #: validate the field (an Excel column, an IBAN check) keep working.
    SURROGATE = "surrogate"
    #: Leave the text alone but list it in the report.
    REPORT = "report"
    #: Ignore entirely.
    KEEP = "keep"


#: Entities reported but never silently rewritten. Alone they do not identify
#: anyone; together they can. The user decides.
REPORT_ONLY: frozenset[EntityType] = frozenset(
    {EntityType.JOB_TITLE, EntityType.AGE, EntityType.POSTCODE, EntityType.DATE}
)

#: Human-facing placeholder stems, in Italian to match the primary audience.
PLACEHOLDER_LABELS: dict[EntityType, str] = {
    EntityType.PERSON: "PERSONA",
    EntityType.ORGANISATION: "AZIENDA",
    EntityType.LOCATION: "LUOGO",
    EntityType.ADDRESS: "INDIRIZZO",
    EntityType.EMAIL: "EMAIL",
    EntityType.PHONE: "TELEFONO",
    EntityType.IBAN: "IBAN",
    EntityType.CREDIT_CARD: "CARTA",
    EntityType.IT_CODICE_FISCALE: "CF",
    EntityType.IT_PARTITA_IVA: "PIVA",
    EntityType.CH_AHV: "AVS",
    EntityType.CH_UID: "UID",
    EntityType.CH_VAT: "IVA_CH",
    EntityType.IP_ADDRESS: "IP",
    EntityType.MAC_ADDRESS: "MAC",
    EntityType.URL: "URL",
    EntityType.DATE: "DATA",
    EntityType.JOB_TITLE: "RUOLO",
    EntityType.AGE: "ETA",
    EntityType.POSTCODE: "CAP",
}


@dataclass(frozen=True)
class Policy:
    """Decides, per entity type, what happens and above which confidence."""

    default_action: Action = Action.REDACT
    overrides: dict[EntityType, Action] = field(default_factory=dict)
    min_confidence: float = 0.5

    def action_for(self, finding: Finding) -> Action:
        if finding.confidence < self.min_confidence:
            return Action.KEEP
        if finding.entity in self.overrides:
            return self.overrides[finding.entity]
        if finding.entity in REPORT_ONLY:
            return Action.REPORT
        return self.default_action


def _normalise(text: str) -> str:
    """Key used to decide whether two mentions are the same value.

    Case and internal whitespace are ignored so that "Mario Rossi",
    "MARIO ROSSI" and "Mario  Rossi" collapse to one placeholder. Without this
    the output reads as three different people and an LLM reasons accordingly.
    """
    return " ".join(text.casefold().split())


class SurrogateAllocator:
    """Hands out stable placeholders for one scrub run, then forgets them.

    Stability matters within a document: the same value must always become the
    same placeholder, or the text stops making sense. Forgetting matters between
    documents: the counter and the value map are process-local and cleared by
    :meth:`close`, which is what makes the scrub irreversible.
    """

    def __init__(self) -> None:
        self._labels: dict[tuple[EntityType, str], str] = {}
        self._counters: Counter[EntityType] = Counter()
        self._closed = False

    def placeholder_for(self, entity: EntityType, text: str) -> str:
        if self._closed:
            raise RuntimeError("allocator is closed; its mapping has been destroyed")
        key = (entity, _normalise(text))
        existing = self._labels.get(key)
        if existing is not None:
            return existing
        self._counters[entity] += 1
        stem = PLACEHOLDER_LABELS.get(entity, entity.value)
        label = f"[{stem}_{self._counters[entity]}]"
        self._labels[key] = label
        return label

    @property
    def distinct_values(self) -> int:
        """How many distinct originals were seen. Safe to report: it is a count."""
        return len(self._labels)

    def close(self) -> None:
        """Destroy the mapping. Called unconditionally at the end of a run."""
        self._labels.clear()
        self._counters.clear()
        self._closed = True

    def __enter__(self) -> SurrogateAllocator:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

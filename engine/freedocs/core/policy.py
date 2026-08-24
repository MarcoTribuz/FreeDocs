"""What to do with each finding, and what to put in its place.

FreeDocs performs *anonymisation* by default: the mapping from placeholder back
to original value lives in memory for the duration of one run and is then
destroyed. Nothing is written, so there is no key to steal and the output is not
personal data under GDPR Art. 4(5) reasoning.

A caller can turn one run into *pseudonymisation* instead, by naming a path and a
passphrase for an encrypted key file - see ``core/mapping.py`` and
``restore.py``. Nothing about this module changes when they do: the key file is
composed from a finished ``ScrubResult``, whose ``Decision`` rows still carry both
halves, so :class:`SurrogateAllocator` is not consulted and still forgets on the
same line. Without that explicit request the scrub remains irreversible by
anyone, including the person who ran it.

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

#: Placeholder stems per locale, and English is the default on purpose.
#:
#: The reader of a scrubbed document is usually a language model, and the stem is
#: the only thing telling it what used to be there. English is what every such
#: model reads best, and it is also the only choice that does not name one
#: audience while the tool covers thirteen countries: `[CF_1]` in a German
#: contract is a label from the wrong country, and `[PERSONA_1]` in an English
#: one reads as a woman's name.
#:
#: A locale that omits a type falls back to English, so adding a language means
#: translating what is worth translating and nothing else. The country-issued
#: types are not translated at all: one stem stands for twelve countries' worth
#: of numbers, and every national name for it would be wrong on eleven of them.
#: The country goes in the report.
PLACEHOLDER_LABELS: dict[str, dict[EntityType, str]] = {
    "en": {
        EntityType.PERSON: "PERSON",
        EntityType.ORGANISATION: "ORGANISATION",
        EntityType.LOCATION: "LOCATION",
        EntityType.ADDRESS: "ADDRESS",
        EntityType.EMAIL: "EMAIL",
        EntityType.PHONE: "PHONE",
        EntityType.IBAN: "IBAN",
        EntityType.CREDIT_CARD: "CARD",
        EntityType.NATIONAL_ID: "NATIONAL_ID",
        EntityType.TAX_ID: "TAX_ID",
        EntityType.VAT_ID: "VAT_ID",
        EntityType.COMPANY_ID: "COMPANY_ID",
        EntityType.IP_ADDRESS: "IP",
        EntityType.MAC_ADDRESS: "MAC",
        EntityType.URL: "URL",
        EntityType.DATE: "DATE",
        EntityType.JOB_TITLE: "ROLE",
        EntityType.AGE: "AGE",
        EntityType.POSTCODE: "POSTCODE",
        EntityType.OTHER: "REDACTED",
    },
    "it": {
        EntityType.PERSON: "PERSONA",
        EntityType.ORGANISATION: "AZIENDA",
        EntityType.LOCATION: "LUOGO",
        EntityType.ADDRESS: "INDIRIZZO",
        EntityType.PHONE: "TELEFONO",
        EntityType.CREDIT_CARD: "CARTA",
        EntityType.DATE: "DATA",
        EntityType.JOB_TITLE: "RUOLO",
        EntityType.AGE: "ETA",
        EntityType.POSTCODE: "CAP",
        EntityType.OTHER: "RIMOSSO",
    },
    "de": {
        EntityType.PERSON: "PERSON",
        EntityType.ORGANISATION: "FIRMA",
        EntityType.LOCATION: "ORT",
        EntityType.ADDRESS: "ADRESSE",
        EntityType.PHONE: "TELEFON",
        EntityType.CREDIT_CARD: "KARTE",
        EntityType.DATE: "DATUM",
        EntityType.JOB_TITLE: "ROLLE",
        EntityType.AGE: "ALTER",
        EntityType.POSTCODE: "PLZ",
        EntityType.OTHER: "ENTFERNT",
    },
    "fr": {
        EntityType.PERSON: "PERSONNE",
        EntityType.ORGANISATION: "SOCIETE",
        EntityType.LOCATION: "LIEU",
        EntityType.ADDRESS: "ADRESSE",
        EntityType.PHONE: "TELEPHONE",
        EntityType.CREDIT_CARD: "CARTE",
        EntityType.DATE: "DATE",
        EntityType.JOB_TITLE: "ROLE",
        EntityType.AGE: "AGE",
        EntityType.POSTCODE: "CODE_POSTAL",
        EntityType.OTHER: "SUPPRIME",
    },
}

#: The locale used when nobody chooses, and the fallback for a partial one.
DEFAULT_LOCALE = "en"

PLACEHOLDER_LOCALES: tuple[str, ...] = tuple(sorted(PLACEHOLDER_LABELS))


def placeholder_labels(locale: str = DEFAULT_LOCALE) -> dict[EntityType, str]:
    """The stems for ``locale``, completed from English.

    Resolved once per run rather than looked up per finding, so a placeholder
    cannot change wording halfway through a document.
    """
    if locale not in PLACEHOLDER_LABELS:
        raise ValueError(
            f"unknown placeholder locale {locale!r}; expected one of "
            f"{', '.join(PLACEHOLDER_LOCALES)}"
        )
    resolved = dict(PLACEHOLDER_LABELS[DEFAULT_LOCALE])
    resolved.update(PLACEHOLDER_LABELS[locale])
    return resolved


@dataclass(frozen=True)
class Policy:
    """Decides, per entity type, what happens and above which confidence."""

    default_action: Action = Action.REDACT
    overrides: dict[EntityType, Action] = field(default_factory=dict)
    min_confidence: float = 0.5
    #: Language of the placeholder stems. English by default: the reader of a
    #: scrubbed document is usually a language model, and it is the only choice
    #: that does not name one audience out of thirteen countries.
    placeholder_locale: str = DEFAULT_LOCALE

    def __post_init__(self) -> None:
        """Refuse a threshold no finding can clear, or that clears every finding.

        Confidence is a probability, so a floor outside [0, 1] is not a strict
        setting - it is a silent no-op in one direction and a silent
        keep-everything in the other. ``--min-confidence 1.5`` used to be
        accepted: every finding fell below it and became ``KEEP``, the scrub
        wrote an untouched copy, verification passed vacuously because there was
        nothing in ``removed`` to search for, and the command exited 0. This is
        the same class as the empty ``--countries`` value the CLI already
        refuses - the one kind of wrong that looks exactly like working.

        Here rather than in either caller because it is a property of the
        policy, and it was the RPC layer alone that checked it while the CLI
        constructed the same object unguarded.
        """
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence must be between 0 and 1, got {self.min_confidence}")

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
    :meth:`close`, so no re-identification key can survive in a live process -
    including through a crash, since ``pipeline.scrub`` closes in a ``finally``.

    An opt-in key file does not change that and deliberately does not go through
    here. ``core/mapping.key_map_from`` reads the finished ``ScrubResult``, which
    holds the original in ``Decision.finding.text`` and the placeholder in
    ``Decision.replacement``. So there is no accessor on this class to expose, no
    reverse index to keep, and nothing here to reopen after :meth:`close`.

    Note the mapping is also lossy on purpose: :func:`_normalise` collapses case
    and internal whitespace, so a key file can only put back one spelling of a
    value that appeared in several. ``MapEntry.variants`` counts them and says so.
    """

    def __init__(self, labels: dict[EntityType, str] | None = None) -> None:
        self._stems = labels if labels is not None else placeholder_labels()
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
        stem = self._stems.get(entity, entity.value)
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

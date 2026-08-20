"""Layer 1: structured identifiers, confirmed by checksum rather than guessed.

Every rule here is a regex paired with a real validator. The regex is deliberately
loose because its only job is to nominate candidates; the checksum decides. That
is what keeps precision near 1.0 without a model: eleven random digits look like
a partita IVA, but only one in ten passes the check digit.

Where a checksum alone is still weak evidence (any eleven digits, any sixteen
digits) the rule also looks for a nearby keyword and lowers confidence when it
finds none, leaving the final call to :class:`~freedocs.core.policy.Policy`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from ..core.errors import MissingDependency
from ..core.findings import EntityType, Finding, Layer, Span


def _require(module: str, attr: str | None = None) -> object:
    try:
        imported = __import__(module, fromlist=["_"])
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise MissingDependency(
            f"{module} is required for the L1 validator layer; install the "
            f"'freedocs' package dependencies"
        ) from exc
    return getattr(imported, attr) if attr else imported


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _compact(text: str) -> str:
    """Strip the separators humans sprinkle through identifiers."""
    return re.sub(r"[\s.\-/]", "", text)


@dataclass(frozen=True)
class Rule:
    """A candidate pattern plus the check that confirms it."""

    entity: EntityType
    name: str
    pattern: re.Pattern[str]
    validate: Callable[[str], bool]
    #: Words that, appearing near a match, make it much more likely to be real.
    context: tuple[str, ...] = ()
    #: Confidence when no context word is nearby. 1.0 means the checksum alone
    #: is conclusive; lower values push the decision to the policy threshold.
    confidence_without_context: float = 1.0
    #: How far either side of the match to look for a context word.
    context_window: int = 60
    #: When the regex is greedy enough to swallow trailing characters that are
    #: not part of the identifier, retry with progressively shorter candidates
    #: instead of discarding the match. Needed for space-separated values whose
    #: length the pattern cannot pin down on its own, such as IBANs.
    shrink_to_fit: bool = False
    #: Never trim below this many characters while shrinking.
    min_length: int = 8

    def find_valid(self, candidate: str) -> str | None:
        """The candidate itself, or its longest valid prefix, or None."""
        if self.validate(candidate):
            return candidate
        if not self.shrink_to_fit:
            return None
        for end in range(len(candidate) - 1, self.min_length - 1, -1):
            trimmed = candidate[:end].rstrip(" -.")
            if len(trimmed) < self.min_length:
                break
            if self.validate(trimmed):
                return trimmed
        return None

    def confidence_at(self, text: str, start: int, end: int) -> float:
        if not self.context or self.confidence_without_context >= 1.0:
            return 1.0
        window = text[max(0, start - self.context_window) : end + self.context_window].casefold()
        return (
            1.0
            if any(word in window for word in self.context)
            else (self.confidence_without_context)
        )


def _always(_: str) -> bool:
    return True


def _valid_ipv4(text: str) -> bool:
    parts = text.split(".")
    return len(parts) == 4 and all(part.isdigit() and int(part) <= 255 for part in parts)


def build_rules() -> list[Rule]:
    """Assemble the rule set, ordered so specific identifiers win over generic ones.

    Order matters because the registry resolves overlaps by layer and length: an
    IBAN must be nominated before the digit soup inside it can be mistaken for a
    card number.
    """
    codicefiscale = _require("stdnum.it.codicefiscale")
    iva = _require("stdnum.it.iva")
    ch_ssn = _require("stdnum.ch.ssn")
    ch_uid = _require("stdnum.ch.uid")
    iban_mod = _require("stdnum.iban")
    luhn = _require("stdnum.luhn")

    return [
        Rule(
            entity=EntityType.IBAN,
            name="iban-mod97",
            # Country code, check digits, then 11 to 30 more characters that may
            # be split into groups by single spaces. Matching character by
            # character rather than in 4-char groups is what lets a trailing
            # one-character group ("... 5295 7") be picked up.
            pattern=re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}"),
            validate=lambda m: bool(iban_mod.is_valid(_compact(m))),  # type: ignore[attr-defined]
            # The pattern is greedy and will happily absorb the digits of
            # whatever follows, so let mod-97 decide where the IBAN really ends.
            shrink_to_fit=True,
            min_length=15,
        ),
        Rule(
            entity=EntityType.CH_AHV,
            name="ch-ahv-ean13",
            # Every Swiss AHV number starts with the 756 country prefix.
            pattern=re.compile(r"\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b"),
            validate=lambda m: bool(ch_ssn.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.CH_UID,
            name="ch-uid",
            pattern=re.compile(r"\bCHE[-\s]?\d{3}[.\s]?\d{3}[.\s]?\d{3}\b", re.IGNORECASE),
            validate=lambda m: bool(ch_uid.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.IT_CODICE_FISCALE,
            name="it-codice-fiscale-cin",
            pattern=re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE),
            validate=lambda m: bool(codicefiscale.is_valid(m.upper())),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.IT_PARTITA_IVA,
            name="it-partita-iva-luhn11",
            pattern=re.compile(r"\b(?:IT)?\d{11}\b", re.IGNORECASE),
            validate=lambda m: bool(iva.is_valid(_compact(m))),  # type: ignore[attr-defined]
            # Eleven digits passing an 11-digit Luhn is weak on its own: roughly
            # one in ten random numbers of that length does.
            context=("partita iva", "p.iva", "piva", "vat", "iva", "codice impresa"),
            confidence_without_context=0.55,
        ),
        Rule(
            entity=EntityType.CREDIT_CARD,
            name="credit-card-luhn",
            pattern=re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
            validate=lambda m: bool(luhn.is_valid(_digits(m))) and 13 <= len(_digits(m)) <= 19,  # type: ignore[attr-defined]
            context=("carta", "card", "visa", "mastercard", "amex", "pan", "cvv", "scadenza"),
            confidence_without_context=0.6,
        ),
        Rule(
            entity=EntityType.EMAIL,
            name="email",
            pattern=re.compile(r"\b[\w.%+-]+@[\w-]+(?:\.[\w-]+)+\b"),
            validate=_always,
        ),
        Rule(
            entity=EntityType.URL,
            name="url",
            pattern=re.compile(r"\bhttps?://[^\s<>\"')]+", re.IGNORECASE),
            validate=_always,
        ),
        Rule(
            entity=EntityType.IP_ADDRESS,
            name="ipv4",
            pattern=re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
            validate=_valid_ipv4,
        ),
        Rule(
            entity=EntityType.MAC_ADDRESS,
            name="mac",
            pattern=re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
            validate=_always,
        ),
    ]


@dataclass
class ValidatorDetector:
    """Runs the checksum-backed rules over a flat text stream."""

    layer: Layer = field(default=Layer.VALIDATOR, init=False)
    rules: list[Rule] = field(default_factory=build_rules)
    #: Regions to try when parsing phone numbers. Swiss first, then Italian.
    phone_regions: tuple[str, ...] = ("CH", "IT")
    detect_phones: bool = True

    def detect(self, text: str) -> list[Finding]:
        findings = list(self._rule_findings(text))
        if self.detect_phones:
            findings.extend(self._phone_findings(text))
        return findings

    def _rule_findings(self, text: str) -> Iterator[Finding]:
        for rule in self.rules:
            for match in rule.pattern.finditer(text):
                accepted = rule.find_valid(match.group(0))
                if accepted is None:
                    continue
                # The span must cover exactly the accepted text: shrinking moved
                # the end, and a stale end would splice the wrong characters.
                start = match.start()
                end = start + len(accepted)
                yield Finding(
                    span=Span(start, end),
                    entity=rule.entity,
                    text=accepted,
                    layer=Layer.VALIDATOR,
                    detector=rule.name,
                    confidence=rule.confidence_at(text, start, end),
                )

    def _phone_findings(self, text: str) -> Iterator[Finding]:
        matcher_cls = _require("phonenumbers", "PhoneNumberMatcher")
        leniency = _require("phonenumbers", "Leniency")
        seen: set[tuple[int, int]] = set()
        for region in self.phone_regions:
            # STRICT_GROUPING, not VALID: business documents are full of dates,
            # and under VALID the Italian metadata happily reads "03.03.2024" as
            # a phone number. Requiring the digit grouping to match a real
            # numbering plan removes that whole class of false positive without
            # losing correctly formatted numbers.
            for match in matcher_cls(text, region, leniency=leniency.STRICT_GROUPING):  # type: ignore[operator]
                key = (match.start, match.end)
                if key in seen:
                    continue
                seen.add(key)
                yield Finding(
                    span=Span(match.start, match.end),
                    entity=EntityType.PHONE,
                    text=match.raw_string,
                    layer=Layer.VALIDATOR,
                    detector=f"phonenumbers-{region}",
                    confidence=1.0,
                )


#: Entity types a checksum can settle. If a model claims one of these and the
#: matching validator disagrees, the model is wrong: L1 scans the same text with
#: precision near 1.0, so a real one would already have been found.
CHECKSUM_VERIFIABLE = frozenset(
    {
        EntityType.IBAN,
        EntityType.CREDIT_CARD,
        EntityType.IT_CODICE_FISCALE,
        EntityType.IT_PARTITA_IVA,
        EntityType.CH_AHV,
        EntityType.CH_UID,
        EntityType.CH_VAT,
    }
)


def confirms(entity: EntityType, text: str) -> bool | None:
    """Whether a checksum accepts ``text`` as an ``entity``.

    Returns None when no validator covers the type, which the caller must read as
    "no opinion" rather than as a rejection.

    This exists because GLiNER2 labelled two chart amounts, ``1500`` and ``2300``,
    as a credit card number at 0.87 confidence. No threshold separates that from a
    real finding, but Luhn does instantly. Using L1 as a verifier for L2's
    structured claims costs one function call and removes the whole class.

    It deliberately does not require the *format* to match a rule's regex, only
    the checksum: an IBAN written with dashes is real even though the pattern
    would not nominate it, and rejecting it would lose recall the model earned.
    """
    if entity not in CHECKSUM_VERIFIABLE:
        return None
    try:
        rules = [rule for rule in build_rules() if rule.entity is entity]
    except MissingDependency:  # pragma: no cover - depends on the environment
        # Without the validators there is no second opinion to offer, and
        # withholding the finding would lose it for no reason.
        return None
    if not rules:
        return None
    candidate = text.strip()
    return any(rule.validate(candidate) for rule in rules)

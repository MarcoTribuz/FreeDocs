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
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cache

from ..core.errors import MissingDependency
from ..core.findings import EntityType, Finding, Layer, Span
from . import keywords


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
    #: ISO 3166-1 alpha-2, lowercase. None means the identifier is not tied to a
    #: country: an IBAN, a card number and an email address are the same
    #: everywhere. Only country-tied rules can be switched off by ``countries``.
    country: str | None = None
    #: Word stems that, appearing near a match, make it much more likely to be
    #: real. Matched as substrings, because German glues them to other words
    #: (``Firmenkarte``) and every language inflects them (``cards``, ``Cartes``).
    context: tuple[str, ...] = ()
    #: Acronyms and codes, matched as whole words. Kept apart from the stems
    #: above because the two need opposite treatment: ``iva`` as a substring
    #: fires inside ``arriva``, and ``karte`` as a whole word misses
    #: ``Firmenkarte``.
    context_codes: tuple[str, ...] = ()
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
        if self.confidence_without_context >= 1.0:
            return 1.0
        if not self.context and not self.context_codes:
            return 1.0
        window = text[max(0, start - self.context_window) : end + self.context_window]
        folded = window.casefold()
        if any(stem in folded for stem in self.context):
            return 1.0
        if self.context_codes and _code_pattern(self.context_codes).search(window):
            return 1.0
        return self.confidence_without_context


@cache
def _code_pattern(codes: tuple[str, ...]) -> re.Pattern[str]:
    """Match any of ``codes`` as a whole word.

    Acronyms cannot be looked for as substrings. Once the vocabulary is the union
    of nine languages the short terms are ``iva``, ``vat``, ``nif``, ``nip``,
    ``cif`` and ``cc``, and as substrings they fire inside ``arriva``,
    ``salvataggio``, ``definisce`` and ``manipolare`` — handing a candidate full
    confidence on the strength of an unrelated verb.

    Word stems are the opposite case and stay substrings: see ``Rule.context``.

    Lookarounds rather than ``\\b``, because a code may begin or end with
    punctuation — ``p.iva``, ``ust.-nr`` — and ``\\b`` after a full stop demands a
    word character that is not there.
    """
    alternatives = "|".join(re.escape(code) for code in sorted(codes, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


#: ``confidence_without_context`` for a rule whose pattern is only digits, chosen
#: by how much work the check digit actually does. Each figure below was measured
#: the same way: 20 000 randomly generated format-plausible values per validator,
#: counting how many it accepts. The anchor is the Italian partita IVA, which
#: accepts 1.05% and has shipped at 0.55 since M0.
#:
#: A rule whose pattern requires a literal prefix — CHE, 756, DE, ATU — does not
#: use these at all and stays at 1.0. The prefix throws away almost every
#: candidate before the checksum runs, which is why `ch_uid` is safe at full
#: confidence while accepting 9.09% of the numbers that reach it. Effective
#: strength is pattern specificity times checksum strength, and only the second
#: half is in this table.
STRONG_CHECK = 0.55  # accepts under 1%: redacted even with no keyword nearby
MEDIUM_CHECK = 0.5  # 1% to 5%: still redacted by default, dropped by any raised threshold
WEAK_CHECK = 0.45  # over 5%: found and reported, never redacted without a keyword


def _always(_: str) -> bool:
    return True


def _valid_ipv4(text: str) -> bool:
    parts = text.split(".")
    return len(parts) == 4 and all(part.isdigit() and int(part) <= 255 for part in parts)


def build_rules(countries: Sequence[str] | None = None) -> list[Rule]:
    """Assemble the rule set, ordered so specific identifiers win over generic ones.

    ``countries`` keeps only the rules tied to those countries, leaving the
    country-neutral ones (IBAN, card, email, URL, IP, MAC) always in. Passing
    None keeps everything, which is the default everywhere: a caller who has to
    name its countries to be safe would produce a silent leak by naming the wrong
    ones.

    Filtering a list preserves its order, so the ordering constraint below stays
    satisfied by construction however narrow the selection.
    """
    codicefiscale = _require("stdnum.it.codicefiscale")
    iva = _require("stdnum.it.iva")
    ch_ssn = _require("stdnum.ch.ssn")
    ch_uid = _require("stdnum.ch.uid")
    iban_mod = _require("stdnum.iban")
    luhn = _require("stdnum.luhn")
    de_idnr = _require("stdnum.de.idnr")
    de_stnr = _require("stdnum.de.stnr")
    de_vat = _require("stdnum.de.vat")
    at_uid = _require("stdnum.at.uid")
    at_tin = _require("stdnum.at.tin")
    at_vnr = _require("stdnum.at.vnr")
    fr_nif = _require("stdnum.fr.nif")
    fr_nir = _require("stdnum.fr.nir")
    fr_siret = _require("stdnum.fr.siret")
    fr_siren = _require("stdnum.fr.siren")
    fr_tva = _require("stdnum.fr.tva")
    be_nn = _require("stdnum.be.nn")
    be_bis = _require("stdnum.be.bis")
    be_vat = _require("stdnum.be.vat")
    es_dni = _require("stdnum.es.dni")
    es_nie = _require("stdnum.es.nie")
    es_cif = _require("stdnum.es.cif")
    pt_nif = _require("stdnum.pt.nif")
    pt_cc = _require("stdnum.pt.cc")
    nl_bsn = _require("stdnum.nl.bsn")
    nl_btw = _require("stdnum.nl.btw")
    pl_pesel = _require("stdnum.pl.pesel")
    pl_nip = _require("stdnum.pl.nip")
    pl_regon = _require("stdnum.pl.regon")
    se_pnr = _require("stdnum.se.personnummer")
    se_orgnr = _require("stdnum.se.orgnr")
    se_vat = _require("stdnum.se.vat")
    gb_vat = _require("stdnum.gb.vat")
    gb_nhs = _require("stdnum.gb.nhs")
    gb_utr = _require("stdnum.gb.utr")

    # Order matters because the registry resolves overlaps by layer and then by
    # span length. IBAN has to be nominated before the digit soup inside it can
    # be read as a card number, and the broad generic patterns have to come after
    # the national ones for the same reason. Three blocks say that out loud;
    # leaving it implicit in list position is how a later insertion breaks it.
    global_first = [
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
    ]

    national = [
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="ch",
            name="ch-ahv-ean13",
            # Every Swiss AHV number starts with the 756 country prefix.
            pattern=re.compile(r"\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b"),
            validate=lambda m: bool(ch_ssn.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.COMPANY_ID,
            country="ch",
            name="ch-uid",
            pattern=re.compile(r"\bCHE[-\s]?\d{3}[.\s]?\d{3}[.\s]?\d{3}\b", re.IGNORECASE),
            validate=lambda m: bool(ch_uid.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.TAX_ID,
            country="it",
            name="it-codice-fiscale-cin",
            pattern=re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE),
            validate=lambda m: bool(codicefiscale.is_valid(m.upper())),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="it",
            name="it-partita-iva-luhn11",
            pattern=re.compile(r"\b(?:IT)?\d{11}\b", re.IGNORECASE),
            validate=lambda m: bool(iva.is_valid(_compact(m))),  # type: ignore[attr-defined]
            # Eleven digits passing an 11-digit Luhn is weak on its own: roughly
            # one in ten random numbers of that length does.
            context=keywords.VAT_STEMS,
            context_codes=keywords.VAT_CODES,
            confidence_without_context=STRONG_CHECK,
        ),
        Rule(
            entity=EntityType.TAX_ID,
            country="de",
            name="de-idnr",
            # Eleven digits, optionally grouped 2-3-3-3 as the tax office prints
            # them. Same shape as a partita IVA, so both rules nominate the same
            # strings and both checksums get a say; the chance of one number
            # passing both is about one in thirty thousand.
            pattern=re.compile(r"\b\d{2}[ ]?\d{3}[ ]?\d{3}[ ]?\d{3}\b"),
            validate=lambda m: bool(de_idnr.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.TAX_STEMS,
            context_codes=keywords.TAX_CODES,
            confidence_without_context=STRONG_CHECK,  # accepts 0.34%
        ),
        Rule(
            entity=EntityType.TAX_ID,
            country="de",
            name="de-stnr",
            # Thirteen digits, or the slashed form a Finanzamt writes.
            pattern=re.compile(r"\b(?:\d{3}/\d{3}/\d{4}[ ]?\d|\d{13})\b"),
            validate=lambda m: bool(de_stnr.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.TAX_STEMS,
            context_codes=keywords.TAX_CODES,
            confidence_without_context=MEDIUM_CHECK,  # accepts 3.50%
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="de",
            name="de-vat",
            pattern=re.compile(r"\bDE[ ]?\d{9}\b"),
            validate=lambda m: bool(de_vat.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="at",
            name="at-uid",
            pattern=re.compile(r"\bATU[ ]?\d{8}\b", re.IGNORECASE),
            validate=lambda m: bool(at_uid.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.TAX_ID,
            country="at",
            name="at-tin",
            pattern=re.compile(r"\b(?:\d{2}-\d{3}/\d{4}|\d{9})\b"),
            validate=lambda m: bool(at_tin.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.TAX_STEMS,
            context_codes=keywords.TAX_CODES,
            confidence_without_context=MEDIUM_CHECK,  # accepts 3.97%
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="at",
            name="at-vnr",
            # Four-digit serial then a birth date as DDMMYY, which is most of
            # what the check actually tests.
            pattern=re.compile(r"\b\d{4}[ ]?\d{6}\b"),
            validate=lambda m: bool(at_vnr.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 8.39%
        ),
        Rule(
            entity=EntityType.TAX_ID,
            country="fr",
            name="fr-nif",
            pattern=re.compile(r"\b\d{13}\b"),
            validate=lambda m: bool(fr_nif.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.TAX_STEMS,
            context_codes=keywords.TAX_CODES,
            confidence_without_context=STRONG_CHECK,  # accepts 0.05%
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="fr",
            name="fr-nir",
            # Sex digit, birth year and month, then the department, which is
            # "2A" or "2B" for Corsica and digits everywhere else, then the
            # commune, the serial and two check digits.
            pattern=re.compile(
                r"\b[12][\s.]?\d{2}[\s.]?\d{2}[\s.]?(?:\d{2}|\d[AB])"
                r"[\s.]?\d{3}[\s.]?\d{3}[\s.]?\d{2}\b",
                re.IGNORECASE,
            ),
            validate=lambda m: bool(fr_nir.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=STRONG_CHECK,  # accepts 0.99%
        ),
        Rule(
            entity=EntityType.COMPANY_ID,
            country="fr",
            name="fr-siret",
            # Before SIREN, because a SIRET starts with one and the shorter
            # match would otherwise win the overlap on span length.
            pattern=re.compile(r"\b\d{3}[\s.]?\d{3}[\s.]?\d{3}[\s.]?\d{5}\b"),
            validate=lambda m: bool(fr_siret.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.COMPANY_STEMS,
            context_codes=keywords.COMPANY_CODES,
            confidence_without_context=STRONG_CHECK,  # accepts 0.98%
        ),
        Rule(
            entity=EntityType.COMPANY_ID,
            country="fr",
            name="fr-siren",
            pattern=re.compile(r"\b\d{3}[\s.]?\d{3}[\s.]?\d{3}\b"),
            validate=lambda m: bool(fr_siren.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.COMPANY_STEMS,
            context_codes=keywords.COMPANY_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 9.80%
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="fr",
            name="fr-tva",
            pattern=re.compile(
                r"\bFR[\s]?[0-9A-Z]{2}[\s]?\d{3}[\s]?\d{3}[\s]?\d{3}\b", re.IGNORECASE
            ),
            validate=lambda m: bool(fr_tva.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="be",
            name="be-nn",
            # Birth date, serial, two check digits. The BIS number for
            # non-residents has the same shape and its own check, so both rules
            # nominate the same strings and each answers for itself.
            pattern=re.compile(r"\b\d{2}[.\s]?\d{2}[.\s]?\d{2}[-.\s]?\d{3}[.\s]?\d{2}\b"),
            validate=lambda m: bool(be_nn.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=STRONG_CHECK,  # accepts 0.13%
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="be",
            name="be-bis",
            pattern=re.compile(r"\b\d{2}[.\s]?\d{2}[.\s]?\d{2}[-.\s]?\d{3}[.\s]?\d{2}\b"),
            validate=lambda m: bool(be_bis.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=STRONG_CHECK,  # accepts 0.37%
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="be",
            name="be-vat",
            pattern=re.compile(r"\bBE[\s]?0?\d{9}\b", re.IGNORECASE),
            validate=lambda m: bool(be_vat.is_valid(_compact(m))),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="es",
            name="es-dni",
            pattern=re.compile(r"\b\d{8}[-\s]?[A-Z]\b", re.IGNORECASE),
            validate=lambda m: bool(es_dni.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=MEDIUM_CHECK,  # accepts 3.83%
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="es",
            name="es-nie",
            pattern=re.compile(r"\b[XYZ][-\s]?\d{7}[-\s]?[A-Z]\b", re.IGNORECASE),
            validate=lambda m: bool(es_nie.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=MEDIUM_CHECK,  # accepts 3.86%
        ),
        Rule(
            entity=EntityType.COMPANY_ID,
            country="es",
            name="es-cif",
            pattern=re.compile(r"\b[ABCDEFGHJNPQRSUVW][-\s]?\d{7}[-\s]?[A-Z0-9]\b", re.IGNORECASE),
            validate=lambda m: bool(es_cif.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
            context=keywords.COMPANY_STEMS,
            context_codes=keywords.COMPANY_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 5.79%
        ),
        Rule(
            entity=EntityType.TAX_ID,
            country="pt",
            name="pt-nif",
            # Also the Portuguese VAT number: one number does both jobs there.
            pattern=re.compile(r"\b\d{3}[\s.]?\d{3}[\s.]?\d{3}\b"),
            validate=lambda m: bool(pt_nif.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.TAX_STEMS,
            context_codes=keywords.TAX_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 8.81%
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="pt",
            name="pt-cc",
            pattern=re.compile(r"\b\d{8}[\s]?\d[\s]?[A-Z]{2}\d\b", re.IGNORECASE),
            validate=lambda m: bool(pt_cc.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 9.76%
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="nl",
            name="nl-bsn",
            pattern=re.compile(r"\b\d{4}[\s.]?\d{2}[\s.]?\d{3}\b"),
            validate=lambda m: bool(nl_bsn.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 9.04%
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="nl",
            name="nl-btw",
            pattern=re.compile(r"\bNL[\s]?\d{9}B\d{2}\b", re.IGNORECASE),
            validate=lambda m: bool(nl_btw.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="pl",
            name="pl-pesel",
            pattern=re.compile(r"\b\d{11}\b"),
            validate=lambda m: bool(pl_pesel.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=MEDIUM_CHECK,  # accepts 1.64%
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="pl",
            name="pl-nip",
            pattern=re.compile(
                r"\b(?:PL[\s]?)?\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}\b", re.IGNORECASE
            ),
            validate=lambda m: bool(pl_nip.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
            context=keywords.VAT_STEMS,
            context_codes=keywords.VAT_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 9.11%
        ),
        Rule(
            entity=EntityType.COMPANY_ID,
            country="pl",
            name="pl-regon",
            pattern=re.compile(r"\b\d{9}\b"),
            validate=lambda m: bool(pl_regon.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.COMPANY_STEMS,
            context_codes=keywords.COMPANY_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 10.01%
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="se",
            name="se-personnummer",
            # Birth date then a four-digit serial. The company number has the
            # same shape and its own check, so both rules see every candidate.
            pattern=re.compile(r"\b\d{6}[-+\s]?\d{4}\b"),
            validate=lambda m: bool(se_pnr.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=STRONG_CHECK,  # accepts 0.35%
        ),
        Rule(
            entity=EntityType.COMPANY_ID,
            country="se",
            name="se-orgnr",
            pattern=re.compile(r"\b\d{6}[-+\s]?\d{4}\b"),
            validate=lambda m: bool(se_orgnr.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.COMPANY_STEMS,
            context_codes=keywords.COMPANY_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 10.32%
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="se",
            name="se-vat",
            pattern=re.compile(r"\bSE[\s]?\d{12}\b", re.IGNORECASE),
            validate=lambda m: bool(se_vat.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.VAT_ID,
            country="gb",
            name="gb-vat",
            pattern=re.compile(r"\bGB[\s]?\d{3}[\s]?\d{4}[\s]?\d{2}\b", re.IGNORECASE),
            validate=lambda m: bool(gb_vat.is_valid(_compact(m).upper())),  # type: ignore[attr-defined]
        ),
        Rule(
            entity=EntityType.NATIONAL_ID,
            country="gb",
            name="gb-nhs",
            # Printed 3-3-4, which is also how a North American phone number is
            # printed. STRICT_GROUPING keeps the phone matcher off most of them,
            # and the weak check digit keeps this rule below the threshold.
            pattern=re.compile(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b"),
            validate=lambda m: bool(gb_nhs.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.NATIONAL_STEMS,
            context_codes=keywords.NATIONAL_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 8.77%
        ),
        Rule(
            entity=EntityType.TAX_ID,
            country="gb",
            name="gb-utr",
            pattern=re.compile(r"\b\d{10}\b"),
            validate=lambda m: bool(gb_utr.is_valid(_compact(m))),  # type: ignore[attr-defined]
            context=keywords.TAX_STEMS,
            context_codes=keywords.TAX_CODES,
            confidence_without_context=WEAK_CHECK,  # accepts 10.42%
        ),
    ]

    global_last = [
        Rule(
            entity=EntityType.CREDIT_CARD,
            name="credit-card-luhn",
            pattern=re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
            validate=lambda m: bool(luhn.is_valid(_digits(m))) and 13 <= len(_digits(m)) <= 19,  # type: ignore[attr-defined]
            context=keywords.CARD_STEMS,
            context_codes=keywords.CARD_CODES,
            confidence_without_context=0.6,  # card, accepts under 1% via Luhn+length
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
            # The last character may not be sentence punctuation. Running greedily
            # to the next space swallowed the full stop after a URL at the end of a
            # sentence, so the replacement ate the punctuation with the address and
            # the exact span never matched the annotation. A trailing '/' is part of
            # the URL and stays.
            pattern=re.compile(r"\bhttps?://[^\s<>\"')]*[^\s<>\"'),.;:!?]", re.IGNORECASE),
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

    rules = [*global_first, *national, *global_last]
    if countries is None:
        return rules
    wanted = {country.casefold() for country in countries}
    return [rule for rule in rules if rule.country is None or rule.country in wanted]


@dataclass
class ValidatorDetector:
    """Runs the checksum-backed rules over a flat text stream."""

    layer: Layer = field(default=Layer.VALIDATOR, init=False)
    #: Countries whose identifiers to look for, or None for every country the
    #: rule set covers. Ignored when ``rules`` is passed explicitly, because a
    #: caller handing over a rule list has already made the choice.
    countries: tuple[str, ...] | None = None
    #: Left None so it can be derived from ``countries``; a default_factory runs
    #: before the other fields are readable, so it cannot see the selection.
    rules: list[Rule] | None = None
    #: Regions to try when parsing phone numbers. Swiss first, then Italian.
    phone_regions: tuple[str, ...] = ("CH", "IT")
    detect_phones: bool = True

    def __post_init__(self) -> None:
        if self.rules is None:
            self.rules = build_rules(self.countries)

    def detect(self, text: str) -> list[Finding]:
        findings = list(self._rule_findings(text))
        if self.detect_phones:
            findings.extend(self._phone_findings(text))
        return findings

    def _rule_findings(self, text: str) -> Iterator[Finding]:
        for rule in self.rules or ():
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
                    country=rule.country,
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
                    country=region.casefold(),
                )


#: Entity types a checksum can settle. If a model claims one of these and the
#: matching validator disagrees, the model is wrong: L1 scans the same text with
#: precision near 1.0, so a real one would already have been found.
#: Of those, the ones whose answer depends on knowing which country issued the
#: number. Mod-97 and Luhn do not care; a tax number's check digit is national.
COUNTRY_ISSUED = frozenset(
    {
        EntityType.NATIONAL_ID,
        EntityType.TAX_ID,
        EntityType.VAT_ID,
        EntityType.COMPANY_ID,
    }
)

CHECKSUM_VERIFIABLE = frozenset(
    {
        EntityType.IBAN,
        EntityType.CREDIT_CARD,
        EntityType.NATIONAL_ID,
        EntityType.TAX_ID,
        EntityType.VAT_ID,
        EntityType.COMPANY_ID,
    }
)


def confirms(entity: EntityType, text: str, country: str | None = None) -> bool | None:
    """Whether a checksum accepts ``text`` as an ``entity``.

    Returns None when there is no opinion to give, which the caller must read as
    "keep the finding" rather than as a rejection.

    This exists because GLiNER2 labelled two chart amounts, ``1500`` and ``2300``,
    as a credit card number at 0.87 confidence. No threshold separates that from a
    real finding, but Luhn does instantly. Using L1 as a verifier for L2's
    structured claims costs one function call and removes the whole class.

    ``country`` is what makes this answerable for the country-issued types. One
    global algorithm settles an IBAN or a card number wherever it was issued, so
    a failed check digit is a rejection and always was. A tax number is different:
    ``TAX_ID`` is claimed by the twelve countries this build covers and by none of
    the other hundred and eighty, so a Brazilian CPF a model correctly spotted
    passes no check here — and "no covered country accepts it" is not evidence
    against a number from a country nobody taught us. Without a country there is
    therefore no opinion to give, and with one the answer comes from that
    country's rules alone.

    It still does not require the *format* to match a rule's regex, only the
    checksum: an IBAN written with dashes is real even though the pattern would
    not nominate it, and rejecting it would lose recall the model earned.
    """
    if entity not in CHECKSUM_VERIFIABLE:
        return None
    if entity in COUNTRY_ISSUED and country is None:
        return None
    try:
        rules = [
            rule
            for rule in build_rules()
            if rule.entity is entity and (country is None or rule.country == country)
        ]
    except MissingDependency:  # pragma: no cover - depends on the environment
        # Without the validators there is no second opinion to offer, and
        # withholding the finding would lose it for no reason.
        return None
    if not rules:
        return None
    candidate = text.strip()
    return any(rule.validate(candidate) for rule in rules)

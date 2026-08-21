"""Canary values used across the suite.

Every identifier here passes its real checksum. That is not a detail: a canary
with a bad check digit would be rejected by the validator, nothing would be
detected, nothing would leak, and the leak test would pass while proving
nothing. The two codice fiscale values are published examples verified against
the CIN algorithm rather than invented.
"""

from __future__ import annotations

import pytest

from freedocs.pipeline import Scrubber, build_registry


def l1_scrubber(**kwargs) -> Scrubber:
    """A scrubber pinned to the checksum layer.

    Format tests use this rather than the default stack on purpose. They are
    about write-back — does the right byte range change, does the file still
    open — and a model in the loop would make them slow, network-dependent and
    sensitive to a threshold nobody changed. Detection *quality* is measured by
    ``freedocs benchmark`` against the labelled corpus, which is the right tool
    for it; asserting it in a unit test would encode one model's behaviour as a
    requirement.
    """
    return Scrubber(registry=build_registry("l1"), **kwargs)


@pytest.fixture
def scrubber() -> Scrubber:
    return l1_scrubber()


#: (canary name, literal as it appears in a document).
#:
#: The key names the canary, not the entity type. Twelve countries have a tax
#: number and they cannot all be keyed on ``TAX_ID``, so the key stays a stable
#: slug and ``CANARY_TYPES`` below says what each one is.
CANARIES: dict[str, str] = {
    "IT_CODICE_FISCALE": "RSSMRA85T10A562S",
    "IT_PARTITA_IVA": "00743110157",
    "IBAN": "CH93 0076 2011 6238 5295 7",
    "CH_AHV": "756.1234.5678.97",
    "CH_UID": "CHE-116.281.710",
    "CREDIT_CARD": "4111 1111 1111 1111",
    "EMAIL": "mario.rossi@example.com",
    "IP_ADDRESS": "192.168.13.37",
    "MAC_ADDRESS": "00:1B:44:11:3A:B7",
    "URL": "https://intranet.example.com/hr/salaries",
    "DE_IDNR": "36574261809",
    "DE_STNR": "4151081508156",
    "DE_VAT": "DE136695976",
    "AT_UID": "ATU13585627",
    "AT_TIN": "59-119/9013",
    "AT_VNR": "1237 010180",
    "FR_NIF": "3023217600053",
    "FR_NIR": "295109912611193",
    "FR_SIRET": "73282932000074",
    "FR_SIREN": "404833048",
    "FR_TVA": "FR40303265045",
    "BE_NN": "85.07.30-033 28",
    "BE_VAT": "BE403019261",
}

#: What each canary is: the ``EntityType`` name, and the issuing country when the
#: number belongs to one. A test that only knows the literal cannot tell whether
#: the right *type* was detected, which is the half that catches a rule wired to
#: the wrong entity.
CANARY_TYPES: dict[str, tuple[str, str | None]] = {
    "IT_CODICE_FISCALE": ("TAX_ID", "it"),
    "IT_PARTITA_IVA": ("VAT_ID", "it"),
    "IBAN": ("IBAN", None),
    "CH_AHV": ("NATIONAL_ID", "ch"),
    "CH_UID": ("COMPANY_ID", "ch"),
    "CREDIT_CARD": ("CREDIT_CARD", None),
    "EMAIL": ("EMAIL", None),
    "IP_ADDRESS": ("IP_ADDRESS", None),
    "MAC_ADDRESS": ("MAC_ADDRESS", None),
    "URL": ("URL", None),
    "DE_IDNR": ("TAX_ID", "de"),
    "DE_STNR": ("TAX_ID", "de"),
    "DE_VAT": ("VAT_ID", "de"),
    "AT_UID": ("VAT_ID", "at"),
    "AT_TIN": ("TAX_ID", "at"),
    "AT_VNR": ("NATIONAL_ID", "at"),
    "FR_NIF": ("TAX_ID", "fr"),
    "FR_NIR": ("NATIONAL_ID", "fr"),
    "FR_SIRET": ("COMPANY_ID", "fr"),
    "FR_SIREN": ("COMPANY_ID", "fr"),
    "FR_TVA": ("VAT_ID", "fr"),
    "BE_NN": ("NATIONAL_ID", "be"),
    "BE_VAT": ("VAT_ID", "be"),
}


#: Values that look like identifiers but must be rejected by the checksums.
NEAR_MISSES: list[str] = [
    "RSSMRA85T10A562A",  # codice fiscale with the wrong CIN
    "00743110158",  # partita IVA, last digit changed
    "CH93 0076 2011 6238 5295 8",  # IBAN failing mod-97
    "756.1234.5678.98",  # AHV with the wrong EAN-13 check digit
    "CHE-116.281.711",  # UID failing its mod-11 check
    "4111 1111 1111 1112",  # card failing Luhn
    "999.999.999.999",  # not a v4 address
    "36574261800",  # German IdNr, last digit changed
    "4151181508156",  # German Steuernummer failing its check
    "DE136695970",  # German USt-IdNr failing its check
    "ATU13585620",  # Austrian UID failing its check
    "591199010",  # Austrian Abgabenkontonummer failing its check
    "1237 010181",  # Austrian Versicherungsnummer failing its check
    "3023217600050",  # French numero fiscal failing its check
    "295109912611190",  # French NIR failing its check
    "73282932000070",  # French SIRET failing its Luhn
    "404833040",  # French SIREN failing its Luhn
    "FR40303265040",  # French TVA failing its key
    "85.07.30-033 20",  # Belgian rijksregisternummer failing its check
    "BE403019260",  # Belgian BTW failing its check
]


@pytest.fixture
def canaries() -> dict[str, str]:
    return dict(CANARIES)


@pytest.fixture
def document(canaries: dict[str, str]) -> str:
    """A plausible document containing every canary, with context words.

    Context matters for the two low-confidence rules: partita IVA and card
    numbers are only weak evidence without a nearby keyword, and a test corpus
    without those keywords would silently exercise the wrong code path.
    """
    return "\n".join(
        [
            "Scheda cliente - riservata",
            "",
            f"Codice fiscale: {canaries['IT_CODICE_FISCALE']}",
            f"Partita IVA: {canaries['IT_PARTITA_IVA']}",
            f"IBAN per il rimborso: {canaries['IBAN']}",
            f"Numero AVS: {canaries['CH_AHV']}",
            f"UID azienda: {canaries['CH_UID']}",
            f"Carta di credito: {canaries['CREDIT_CARD']}",
            f"Contatto: {canaries['EMAIL']}",
            f"Server interno {canaries['IP_ADDRESS']} MAC {canaries['MAC_ADDRESS']}",
            f"Dettagli su {canaries['URL']}",
            "",
            # The German block is here for the keywords, not for realism. Six of
            # the rules below full confidence only reach it through a word in
            # their own language, and a fixture that never supplies one would
            # exercise the wrong branch on every format test that uses this.
            "Zweigstelle Deutschland / Osterreich",
            f"Steuerliche Identifikationsnummer: {canaries['DE_IDNR']}",
            f"Steuernummer: {canaries['DE_STNR']}",
            f"USt-IdNr.: {canaries['DE_VAT']}",
            f"UID Osterreich: {canaries['AT_UID']}",
            f"Abgabenkontonummer: {canaries['AT_TIN']}",
            f"Sozialversicherungsnummer: {canaries['AT_VNR']}",
            "",
            "Succursale France / Belgique",
            f"Numero fiscal: {canaries['FR_NIF']}",
            f"Numero de securite sociale: {canaries['FR_NIR']}",
            f"SIRET: {canaries['FR_SIRET']}",
            f"SIREN: {canaries['FR_SIREN']}",
            f"Numero de TVA: {canaries['FR_TVA']}",
            f"Rijksregisternummer: {canaries['BE_NN']}",
            f"BTW-nummer: {canaries['BE_VAT']}",
            "",
        ]
    )

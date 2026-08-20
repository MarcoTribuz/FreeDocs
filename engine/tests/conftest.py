"""Canary values used across the suite.

Every identifier here passes its real checksum. That is not a detail: a canary
with a bad check digit would be rejected by the validator, nothing would be
detected, nothing would leak, and the leak test would pass while proving
nothing. The two codice fiscale values are published examples verified against
the CIN algorithm rather than invented.
"""

from __future__ import annotations

import pytest

#: (entity name, literal as it appears in a document)
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
        ]
    )

"""Context vocabulary, keyed by what an identifier is rather than by language.

Several checksums are weak on their own: roughly one in ten arbitrary numbers of
the right length passes an eleven-digit Luhn. Those rules ask whether a word that
names the identifier appears nearby, and drop their confidence when none does.

Each family comes in two tables, because two kinds of term need opposite
treatment and merging them breaks one or the other:

``*_STEMS`` are natural-language nouns, matched as **substrings**. German glues
them to other words — the corpus carries ``Firmenkarte`` and ``Zahlungskarten`` —
and every language inflects them, so the corpus also carries ``cards`` and
``Cartes``. Requiring a whole word lost all four.

``*_CODES`` are acronyms, matched as **whole words**. As substrings the short ones
fire inside ordinary vocabulary: ``iva`` in ``arriva``, ``vat`` in
``salvataggio``, ``nif`` in ``definisce``, ``nip`` in ``manipolare``.

Both tables are the union of the terms across the languages the tool covers, not
a per-language lookup. The engine does not know what language a document is in,
and it deliberately does not try to guess: a language detector is one more thing
that fails silently on short or mixed text, which is the same reason
``presidio_backend`` runs every configured language and the OCR layer asks
Tesseract for all of them at once.

Sharing one table across a family also matches what documents do. An Italian
partita IVA inside a German contract is labelled ``MwSt-Nummer``, and the number
has already passed its own country's checksum, so the keyword only has to answer
"is this a VAT number at all", never "whose".
"""

from __future__ import annotations

#: VAT and turnover-tax registration numbers.
VAT_STEMS = (
    # Italian
    "partita iva",
    # English
    "vat number",
    "vat id",
    "vat reg",
    # German (DE, AT, CH)
    "umsatzsteuer",
    "mehrwertsteuer",
    # French (FR, BE, CH)
    "numero de tva",
    # Dutch (NL, BE)
    "btw-nummer",
    "omzetbelasting",
    # Swedish
    "momsnummer",
)

VAT_CODES = (
    "p.iva",
    "piva",
    "iva",
    "vat",
    "ust-idnr",
    "ustidnr",
    "ust.-nr",
    "mwst",
    "tva",
    "nif",
    "cif",
    "btw",
    "nip",
    "moms",
)

#: Payment card numbers.
CARD_STEMS = (
    # Italian
    "carta",
    "scadenza",
    # English
    "card",
    "expiry",
    # brands, in any language
    "visa",
    "mastercard",
    "amex",
    "american express",
    "maestro",
    # German
    "kreditkarte",
    "karte",
    "gultig bis",
    # French
    "carte",
    "validite",
    # Spanish and Portuguese
    "tarjeta",
    "cartao",
    # Dutch
    "kaart",
    # Polish
    "karta",
    # Swedish
    "kort",
)

CARD_CODES = (
    "pan",
    "cvv",
    "cvc",
)


#: Personal tax numbers, and the Italian codice fiscale, which is both.
TAX_STEMS = (
    # Italian
    "codice fiscale",
    # English
    "tax number",
    "tax id",
    "tax reference",
    "taxpayer",
    # German (DE, AT)
    "steuernummer",
    "steuerliche identifikationsnummer",
    "identifikationsnummer",
    "steuer-id",
    "abgabenkontonummer",
    "steuerpflichtig",
    # French
    "numero fiscal",
    "identifiant fiscal",
    # Spanish and Portuguese
    "identificacion fiscal",
    "contribuinte",
    # Polish
    "identyfikacji podatkowej",
    # Swedish
    "skatt",
)

TAX_CODES = (
    "cf",
    "cod.fisc",
    "stnr",
    "st.-nr",
    "st-nr",
    "idnr",
    "tin",
    "utr",
    "nif",
    "nip",
)

#: Personal identity and social-security numbers.
NATIONAL_STEMS = (
    # German (CH, AT, DE)
    "sozialversicherungsnummer",
    "versicherungsnummer",
    # English
    "social security",
    "national insurance",
    "national id",
    "identity number",
    # French
    "securite sociale",
    "numero national",
    # Italian
    "previdenza",
    # Dutch
    "burgerservicenummer",
    "rijksregisternummer",
    "sofinummer",
    # The compound, not bare "bis": in German that word means "until" and is
    # everywhere, and a code matched as a whole word would fire on all of it.
    "bis-nummer",
    "bisnummer",
    # Spanish
    "identidad",
    # Portuguese
    "cidadao",
    # Swedish
    "personnummer",
)

NATIONAL_CODES = (
    "avs",
    "ahv",
    "svnr",
    "vnr",
    "vsnr",
    "ssn",
    "nir",
    "bsn",
    "niss",
    "pesel",
    "nhs",
    "dni",
    "nie",
)

#: Company and trade-register identifiers.
COMPANY_STEMS = (
    "handelsregister",
    "firmenbuchnummer",
    "unternehmens-identifikationsnummer",
    "company number",
    "registration number",
    "camera di commercio",
    "kamer van koophandel",
    "organisationsnummer",
)

COMPANY_CODES = (
    "uid",
    "ide",
    "idi",
    "fn",
    "siren",
    "siret",
    "rcs",
    "kvk",
    "regon",
    "krs",
    "orgnr",
    "cif",
    "nipc",
    "rea",
)

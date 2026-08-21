"""Street addresses, anchored on the postal code.

GLiNER2 finds thirty-six of the forty-one annotated addresses. All five it misses
fail the same way, and it is not a scoring problem: the model returns the city as
a LOCATION and drops the street entirely. ``Rua do Ouro 112, 1100-063 Lisboa``
comes back as ``Lisboa``, which means the house number, the street and the
postcode stay in the document that gets sent.

A postal code is the one part of an address that is machine-recognisable without
a model. It has a published shape per country, it is almost always adjacent to the
city, and the street sits on the other side of a comma from it. So this layer
finds the code first and reads outwards.

The direction matters and differs by country. Most of Europe writes
``<street> <number>, <code> <city>``; the United Kingdom writes
``<number> <street>, <city> <code>``. Both are handled, and the corpus carries
eight distinct code shapes across the twelve covered countries.

The left edge is the hard part, and a comma is not enough to find it. In
``residence Meir 78, 2000 Antwerpen`` there is no comma before the street, so a
regex that simply scanned back to the previous punctuation would produce
``residence Meir 78``. The scan is therefore a token walk with an explicit
vocabulary: capitalised words, house numbers, the connectors that appear inside a
street name (``de``, ``della``, ``do``) and the lowercase words that *are* street
types in the languages covered (``rue``, ``via``, ``ulica``). Anything else ends
the address, which is what stops ``residence`` and every other stray noun.

Like :mod:`freedocs.detect.organisations` it fills gaps and does not compete,
and for the same measured reason — see :func:`fill_address_gaps`. It does absorb a
LOCATION it fully contains, because that city is the address the model half-found
and leaving both would be two edits over the same characters.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..core.findings import EntityType, Finding, Layer, Span

#: Lowercase words that are part of a street name rather than the sentence around
#: it. The union across the languages covered, for the same reason as
#: :mod:`freedocs.detect.keywords`: the engine does not know which one it reads.
_STREET_WORDS = frozenset(
    {
        # French
        "rue",
        "avenue",
        "boulevard",
        "chemin",
        "route",
        "place",
        "quai",
        "impasse",
        "allee",
        "allée",
        "passage",
        "cours",
        # Italian
        "via",
        "viale",
        "corso",
        "piazza",
        "piazzale",
        "strada",
        "vicolo",
        "largo",
        "lungomare",
        "zona",
        # Spanish and Portuguese
        "calle",
        "avenida",
        "plaza",
        "paseo",
        "rua",
        "praca",
        "praça",
        "travessa",
        # Polish
        "ulica",
        "aleja",
        "ul.",
        "al.",
        "osiedle",
        # Swedish, Dutch, German — usually glued to the name, but written apart
        # often enough to be worth listing.
        "gata",
        "gatan",
        "vag",
        "vagen",
        "torg",
        "straat",
        "laan",
        "gracht",
        "plein",
        "weg",
        "strasse",
        "straße",
        "gasse",
        "platz",
        "ring",
        "damm",
        # English
        "street",
        "road",
        "lane",
        "drive",
        "close",
        "court",
        "square",
        "park",
        "way",
        "walk",
        "row",
        "hill",
        "unit",
        "floor",
        "suite",
    }
)

#: Words that appear *inside* a street name and must not stop the walk.
_CONNECTORS = frozenset(
    {
        "de",
        "des",
        "du",
        "da",
        "das",
        "do",
        "dos",
        "del",
        "della",
        "dell",
        "delle",
        "di",
        "la",
        "le",
        "les",
        "el",
        "van",
        "von",
        "der",
        "den",
        "het",
        "the",
        "of",
        "e",
        "y",
        "and",
        "et",
        "en",
        "am",
        "im",
        "zum",
        "zur",
        "auf",
    }
)

#: A city or town: up to three capitalised words, optionally led by a short
#: abbreviation so ``St. Gallen`` survives.
#:
#: No city word may carry a full stop of its own. Allowing one made
#: ``Corso Umberto I 118, 80138 Napoli. Codice`` a single address, reading the
#: sentence break as a word boundary; the three-letter cap on the abbreviation is
#: what separates ``St.`` from ``Napoli.``.
_CITY_WORD = r"[A-Z][\w'\u2019\-]*"
_CITY_ABBREV = r"(?:[A-Z][a-zA-Z]{0,2}\.[ \u00a0])?"
_CITY = rf"{_CITY_ABBREV}{_CITY_WORD}(?:[ \u00a0]{_CITY_WORD}){{0,2}}"

#: Postal codes, longest and most specific first so ``1100-063`` is not read as a
#: bare ``1100``. Every shape here is present in the corpus.
_POSTAL_CODES: tuple[str, ...] = (
    r"\d{4}-\d{3}",  # Portugal: 1100-063
    r"\d{2}-\d{3}",  # Poland: 00-838
    r"\d{4}[ \u00a0][A-Z]{2}",  # Netherlands: 1016 DX
    r"\d{3}[ \u00a0]\d{2}",  # Sweden: 111 35
    r"[A-Z]{1,2}-\d{4,5}",  # written-out prefix form: CH-8001, D-20359
    r"\d{4,5}",  # Switzerland, Germany, Austria, France, Italy, Spain
)

#: The United Kingdom, where the code follows the city instead of leading it.
_UK_POSTCODE = r"[A-Z]{1,2}\d{1,2}[A-Z]?[ \u00a0]\d[A-Z]{2}"

_CODE_THEN_CITY = re.compile(
    rf"(?:{'|'.join(_POSTAL_CODES)})[ \u00a0]+(?:{_CITY})",
)
_CITY_THEN_CODE = re.compile(
    rf"(?:{_CITY})[ \u00a0]+(?:{_UK_POSTCODE})",
)

#: One token of the street half, scanning right to left.
_TOKEN = re.compile(r"[\w'\u2019.\-]+")

#: Longest street half considered, in tokens. ``Unit 7 Ashford Park`` is four and
#: ``Chemin de la Fabrique 210`` is five; eight leaves room without letting a
#: runaway match absorb the clause in front.
_MAX_STREET_TOKENS = 8

#: A lowercase article elided onto a capitalised name: French and Italian street
#: names are full of them, and the apostrophe is what makes the token look
#: lowercase to every other rule here.
_ELIDED = re.compile(r"^[a-z]{1,4}['\u2019][A-Z]")

#: A house number: digits, optionally with a letter or a sub-unit.
_HOUSE_NUMBER = re.compile(r"^\d{1,4}(?:[a-zA-Z]|[/\-]\d{1,3})?$")


#: Names the pass in reports and in benchmark output.
DETECTOR = "postal-code"

#: Below 1.0 because nothing here is checked, only shaped. Well above
#: `Policy.min_confidence`, because the shape is specific: a house number, a
#: comma, a published code form and a capitalised city, in that order.
CONFIDENCE = 0.9

#: Types this pass may absorb. A city inside an address is the same information
#: at a worse span, so the longer finding replaces it. Nothing else is touched.
_ABSORBABLE = frozenset({EntityType.LOCATION})


def fill_address_gaps(text: str, findings: Sequence[Finding]) -> list[Finding]:
    """Return ``findings`` with the addresses no layer assembled.

    Two refusals, and both were measured rather than guessed:

    - An existing ADDRESS finding wins, always. Where GLiNER2 assembled the
      address itself its span is the better one: the token walk cannot tell a
      street name from the capitalised German noun in front of it, and it
      produced ``Sitz Fabrikweg 210, 5000 Aarau`` and
      ``Wohnsitz Getreidegasse 21, 5020 Salzburg`` against the model's correct
      spans. Competing would trade three exact spans for nothing.
    - Anything that is not a LOCATION blocks the candidate outright. A city is
      absorbed because an address contains one by definition; a person or an
      identifier overlapping an address shape means the shape is wrong.
    """
    kept = list(findings)
    absorbed: set[int] = set()
    added: list[Finding] = []

    for start, end in _candidates(text):
        blocked = False
        touching: list[int] = []
        for index, existing in enumerate(kept):
            if not (start < existing.span.end and existing.span.start < end):
                continue
            if (
                existing.entity in _ABSORBABLE
                and start <= existing.span.start
                and existing.span.end <= end
            ):
                touching.append(index)
                continue
            blocked = True
            break
        if blocked:
            continue
        absorbed.update(touching)
        added.append(
            Finding(
                span=Span(start, end),
                entity=EntityType.ADDRESS,
                text=text[start:end],
                layer=Layer.NER,
                detector=DETECTOR,
                confidence=CONFIDENCE,
            )
        )

    if not added:
        return list(findings)
    survivors = [f for index, f in enumerate(kept) if index not in absorbed]
    return sorted([*survivors, *added], key=lambda f: (f.span.start, f.span.end))


def _candidates(text: str) -> list[tuple[int, int]]:
    spans: dict[tuple[int, int], None] = {}
    for pattern in (_CODE_THEN_CITY, _CITY_THEN_CODE):
        for tail in pattern.finditer(text):
            if _is_word_char(text, tail.start() - 1):
                continue
            start = _street_start(text, tail.start())
            if start is None:
                continue
            # The city pattern cannot end on punctuation, but the postal-code
            # branch can when the code itself ends the match, so trim anyway.
            end = tail.end()
            while end > start and text[end - 1] in " \t.,;:":
                end -= 1
            spans[(start, end)] = None
    return sorted(spans)


def _is_word_char(text: str, index: int) -> bool:
    return 0 <= index < len(text) and (text[index].isalnum() or text[index] == "_")


def _street_start(text: str, tail_start: int) -> int | None:
    """Where the street half begins, or None when there is no street half.

    Requires a comma between the street and the postal code. Without it the
    pattern matches a bare number beside a capitalised word, which every invoice
    line in the corpus contains.
    """
    cursor = tail_start
    while cursor > 0 and text[cursor - 1] in {" ", "\u00a0"}:
        cursor -= 1
    if cursor == 0 or text[cursor - 1] != ",":
        return None
    cursor -= 1

    tokens: list[tuple[int, str]] = []
    saw_number = False
    saw_name = False

    while len(tokens) < _MAX_STREET_TOKENS:
        gap_start = cursor
        while cursor > 0 and text[cursor - 1] in {" ", "\u00a0"}:
            cursor -= 1
        # A newline, or a second comma, ends the street: the flattened stream
        # joins unrelated cells with separators chosen for exactly this reason.
        if cursor == gap_start and tokens:
            break
        if cursor == 0:
            break

        token = _token_ending_at(text, cursor)
        if token is None:
            break
        start, word = token

        if _HOUSE_NUMBER.match(word):
            saw_number = True
        elif word[0].isupper() or word.casefold() in _STREET_WORDS:
            saw_name = True
        elif _ELIDED.match(word):
            # An elided article glued to the name: "l'Industrie",
            # "dell'Artigianato", "d'Or". The token starts lowercase, so every
            # other branch rejects it, and `Rue de l'Industrie 9, 2800 Delemont`
            # was the one annotated address this pass still missed.
            saw_name = True
        elif word.casefold() in _CONNECTORS:
            pass
        else:
            break

        tokens.append((start, word))
        cursor = start

    # Trim leading connectors: "de la Paix" is not where an address starts.
    while tokens and tokens[-1][1].casefold() in _CONNECTORS:
        tokens.pop()
    if not tokens or not (saw_number and saw_name):
        return None
    return tokens[-1][0]


def _token_ending_at(text: str, position: int) -> tuple[int, str] | None:
    """The word immediately to the left of ``position``, with its offset."""
    end = position
    start = end
    while start > 0 and _TOKEN.fullmatch(text[start - 1]):
        start -= 1
    if start == end:
        return None
    word = text[start:end].strip(".,;:")
    if not word:
        return None
    return start + (len(text[start:end]) - len(text[start:end].lstrip(".,;:"))), word

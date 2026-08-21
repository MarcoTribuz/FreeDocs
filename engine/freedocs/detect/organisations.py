"""Company names that a model misses because it has never seen the legal form.

GLiNER2 finds thirty-six of the thirty-seven annotated organisations in the
corpus. The one it does not find at all is ``Northwind Polska sp. z o.o.`` — not
truncated, not low-scored, *absent*, while the identically shaped
``Northwind Iberia SL`` and ``Northwind Norden AB`` two lines above score 0.99.
A model's grasp of what a company name looks like is only as good as the legal
forms it saw in training, and the Polish one is written in lowercase with three
full stops.

The legal form is the part that needs no model. It is a closed, published set per
country, and a capitalised name immediately followed by one is a company name
almost by definition. So this layer nominates on the form and reads the name
backwards from it.

Two things keep it from becoming a greedy title-case matcher, which is the shape
this idea fails in:

- The scan stops at anything that is not a name token — a full stop, a colon, a
  digit, a newline, an unconnected lowercase word. ``Poland: Northwind Polska
  sp. z o.o.`` yields the company and not the heading.
- Short forms are matched case-sensitively. ``SA``, ``SL``, ``BV`` and ``AB`` are
  legal forms; ``sa`` is a French possessive, ``ab`` a Swedish preposition and
  ``se`` a pronoun in three of the languages the tool reads. Case-insensitive
  matching on a two-letter form turns every sentence into a company.

It fills gaps and does not compete. Where the model already found an
organisation overlapping the candidate, the model's span wins untouched — and
that is not politeness, it is the only thing that works. A backward scan cannot
tell a company name from the noun in front of it in German, where every common
noun is capitalised: run as a peer detector, this layer produced
``Kunde Nordwind Logistik GmbH``, ``Lieferant Technetz Systeme GmbH`` and
``Die Tochtergesellschaft Nordwind Logistik Deutschland GmbH``, each beating the
model's correct span on length alone and costing eight points of ORGANISATION
precision. Restricted to gaps, it keeps the one name the model never saw and
touches nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from ..core.findings import EntityType, Finding, Layer, Span

#: Legal forms of four or more characters, matched case-insensitively. Long
#: enough that no ordinary word collides with them in the languages covered.
_LONG_FORMS: tuple[str, ...] = (
    "gmbh",
    "sagl",
    "sarl",
    # ``Sarl`` is the anglicised spelling; ``Sàrl`` is what a Romandy or
    # Luxembourg company registers under, and it was invisible to this pass and
    # to ``suppress`` until it was listed. Listed rather than folded away: the
    # short forms below are matched case-sensitively on purpose, and folding a
    # candidate to compare it would throw that distinction away.
    "sàrl",
    "s.a.r.l.",
    "s.à r.l.",
    "s.à.r.l.",
    "spa",
    "s.p.a.",
    "srl",
    "s.r.l.",
    "srls",
    "sasu",
    "sprl",
    "bvba",
    "cvba",
    "lda",
    "l.da",
    "sp. z o.o.",
    "sp. z o. o.",
    "sp.k.",
    "sp.j.",
    "ltd",
    "ltd.",
    "limited",
    "plc",
    "plc.",
    "llp",
    "llc",
    "inc",
    "inc.",
    "corp",
    "corp.",
    "corporation",
    "oyj",
    "aps",
)

#: Legal forms of three characters or fewer, matched exactly as spelled. See the
#: module docstring: lowercasing these makes them ordinary vocabulary.
_SHORT_FORMS: tuple[str, ...] = (
    "AG",
    "SA",
    "SL",
    "SLU",
    "SAS",
    "SNC",
    "SCS",
    "BV",
    "B.V.",
    "NV",
    "N.V.",
    "AB",
    "OY",
    "A/S",
)

#: Lowercase words that appear *inside* a company name and must not stop the
#: backward scan: ``Vignoble Bertrand et Fils SA``, ``Ferrovie del Sud Srl``.
_CONNECTORS = frozenset(
    {
        "e",
        "et",
        "y",
        "and",
        "und",
        "de",
        "del",
        "della",
        "di",
        "du",
        "des",
        "da",
        "dos",
        "van",
        "von",
        "der",
        "den",
        "the",
        "&",
    }
)

#: A name is at most this many tokens long before the legal form. Five covers
#: every annotated name in the corpus and stops a runaway match from absorbing
#: the clause in front of it.
_MAX_NAME_TOKENS = 5

_FORM_PATTERN = re.compile(
    "(?:"
    + "|".join(re.escape(form) for form in sorted(_LONG_FORMS, key=len, reverse=True))
    + ")(?!\\w)",
    re.IGNORECASE,
)

_SHORT_FORM_PATTERN = re.compile(
    "(?:"
    + "|".join(re.escape(form) for form in sorted(_SHORT_FORMS, key=len, reverse=True))
    + ")(?!\\w)"
)

#: One token of a candidate name, scanning right to left: a word, an ampersand or
#: an initialism with full stops. Deliberately excludes digits — a company name
#: containing one exists, but so does every reference number in front of one.
_TOKEN = re.compile("[^\\W\\d_](?:[^\\W\\d_]|['\u2019.&-])*")


def _name_starts_at(text: str, form_start: int, floor: int) -> int | None:
    """Walk left from a legal form and return where the company name begins."""
    position = form_start
    tokens: list[tuple[int, str]] = []

    while len(tokens) < _MAX_NAME_TOKENS:
        # Only a plain space or a non-breaking space separates a name token from
        # the next. A newline, comma or full stop ends the name: the corpus has
        # "Alle wurden zuruckgewiesen.\n\nNordwind Logistik GmbH" and the
        # sentence before must not be swallowed.
        gap_end = position
        while position > floor and text[position - 1] in {" ", "\u00a0"}:
            position -= 1
        if position == gap_end and tokens:
            break
        if position <= floor:
            break

        match = None
        for candidate in _TOKEN.finditer(text, floor, position):
            if candidate.end() == position:
                match = candidate
        if match is None:
            break

        token = match.group()
        if token[0].islower() and token.casefold() not in _CONNECTORS:
            break
        tokens.append((match.start(), token))
        position = match.start()

    # Trim connectors off the front: "et Fils SA" is not a company, and neither
    # is "del Sud Srl". A name has to start with a capitalised token.
    while tokens and tokens[-1][1].casefold() in _CONNECTORS:
        tokens.pop()
    if not tokens:
        return None
    if not tokens[-1][1][0].isupper():
        return None
    return tokens[-1][0]


#: Names the pass in reports and in benchmark output.
DETECTOR = "legal-form"

#: A published legal form is strong evidence, but it is still a pattern with no
#: checksum behind it, so it does not claim the certainty an L1 rule does.
CONFIDENCE = 0.9


def fill_organisation_gaps(text: str, findings: Sequence[Finding]) -> list[Finding]:
    """Return ``findings`` plus the company names no layer claimed.

    A candidate is dropped when it touches any existing finding, whatever its
    type: an overlap means some layer already has an opinion about those
    characters, and this pass exists for the characters where none does.
    """
    occupied = [(f.span.start, f.span.end) for f in findings]
    added: list[Finding] = []
    line_starts = _line_starts(text)

    for start, end in _candidates(text, line_starts):
        if any(start < other_end and other_start < end for other_start, other_end in occupied):
            continue
        occupied.append((start, end))
        added.append(
            Finding(
                span=Span(start, end),
                entity=EntityType.ORGANISATION,
                text=text[start:end],
                layer=Layer.NER,
                detector=DETECTOR,
                confidence=CONFIDENCE,
            )
        )
    if not added:
        return list(findings)
    return sorted([*findings, *added], key=lambda f: (f.span.start, f.span.end))


def _candidates(text: str, line_starts: list[int]) -> Iterable[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    for pattern in (_FORM_PATTERN, _SHORT_FORM_PATTERN):
        for form in pattern.finditer(text):
            previous = text[form.start() - 1] if form.start() > 0 else ""
            if previous.isalnum() or previous == "_":
                continue
            floor = _floor_for(line_starts, form.start())
            start = _name_starts_at(text, form.start(), floor)
            if start is None:
                continue
            span = (start, form.end())
            if span in seen:
                continue
            seen.add(span)
            yield span


def _line_starts(text: str) -> list[int]:
    return [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]


def _floor_for(line_starts: list[int], position: int) -> int:
    """The start of the line ``position`` is on.

    A company name does not straddle a line break in the flattened text: the
    stream joins runs and cells with separators chosen for that reason, and a
    backward scan that crossed one would join two unrelated cells into a name.
    """
    floor = 0
    for start in line_starts:
        if start > position:
            break
        floor = start
    return floor

"""Findings that name something real and identify nobody.

Every layer above this one answers "is this a place, a company, a person?".
None of them answers "does knowing it get you closer to a name?", and those are
different questions. A country in a section heading, a jurisdiction in a
governing-law clause and a nationality in a currency name are all genuinely
locations; removing them costs the reader meaning and buys no privacy, and the
benchmark charges for it as over-redaction.

The passes here are the mirror image of :mod:`freedocs.detect.keywords`, which
holds vocabulary that *raises* confidence. Both tables are the union across the
languages the tool covers, for the same reason: the engine does not know which
language it is reading and deliberately does not guess.

Each rule below names the corpus cases it exists for. A rule that cannot point
at one does not belong in this file — suppression is the one kind of change that
can hide a leak, so the burden of proof runs the other way here than elsewhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..core.findings import EntityType, Finding
from ..core.text import fold_diacritics as _fold

#: Names of the two rules below, as they reach the report. A closed vocabulary
#: rather than prose, for the reason the stage names are: the window translates
#: them by key, and a sentence assembled in Python would have to be translated
#: four times or quoted in English for something that is an enum.
NON_IDENTIFYING = "non_identifying"
JURISDICTION = "jurisdiction"


@dataclass(frozen=True)
class Suppression:
    """A finding this module dropped, and which rule dropped it.

    Both passes here judge an *occurrence* while stage 6 searches for a *value*,
    so a value removed in one place and suppressed in another reads as a
    survivor of the removal. Verification already knows how to be told about
    that - it is the same allowance a human override uses - and this is what
    tells it.

    The whole finding is carried rather than its text, and both halves are load
    bearing. The span is how one occurrence dropped by two passes grants one
    allowance instead of two, and the entity is what lets the report say what
    was left behind without naming it.
    """

    rule: str
    finding: Finding


#: What the two passes return: what survives, and what was dropped with the
#: reason. Named because the alternative is repeating the tuple in four places.
Suppressing = tuple[list[Finding], list["Suppression"]]

#: Types a suppression rule may look at. Everything else is checksum-backed, and
#: a rule that second-guesses a check digit on contextual grounds is a bug: the
#: whole point of L1 is that mod-97 does not care what the sentence says.
_FREE_TEXT = frozenset(
    {
        EntityType.LOCATION,
        EntityType.ADDRESS,
        EntityType.ORGANISATION,
    }
)

#: Country names, per country, across the languages the tool reads. A bare
#: country name is not a location finding: it narrows a population by tens of
#: millions, which is why the corpus annotates thirty cities and not one country.
#:
#: Measured on the corpus: ``Portugal`` (0.97), ``Netherlands`` (0.93),
#: ``Poland`` (0.94), ``Spain``, ``Sweden`` and ``United Kingdom`` are six of the
#: fifteen LOCATION false positives, all of them section headings introducing a
#: subsidiary. Confidence does not separate them from a real city — GLiNER2 is
#: right that they are places — so a threshold cannot fix this and a list can.
#:
#: City-states are deliberately absent. Luxembourg, Monaco, Singapore, Andorra
#: and San Marino name a city as often as a country, and dropping the city would
#: be a leak. When the name is ambiguous the finding stays.
#: Written unaccented and folded on both sides. The table spells the Austrian
#: and Swedish names ``osterreich`` and ``suede``, and a plain casefold left the
#: ``Österreich``, ``Suède``, ``Grèce`` and ``Türkiye`` a real document contains
#: unmatched — so the bare country name was redacted after all, which is the
#: over-redaction this list exists to prevent.
_COUNTRY_NAMES: frozenset[str] = frozenset(
    _fold(name)
    for names in (
        ("switzerland", "schweiz", "suisse", "svizzera", "zwitserland", "szwajcaria"),
        ("italy", "italien", "italie", "italia", "wlochy"),
        (
            "germany",
            "deutschland",
            "allemagne",
            "germania",
            "alemania",
            "alemanha",
            "duitsland",
            "niemcy",
            "tyskland",
        ),
        ("austria", "osterreich", "oesterreich", "autriche", "oostenrijk", "osterrike"),
        ("france", "frankreich", "francia", "frankrijk", "francja", "frankrike"),
        ("belgium", "belgien", "belgique", "belgio", "belgica", "belgie", "belgia"),
        (
            "spain",
            "spanien",
            "espagne",
            "spagna",
            "espana",
            "espanha",
            "spanje",
            "hiszpania",
        ),
        ("portugal", "portugalia"),
        (
            "netherlands",
            "the netherlands",
            "niederlande",
            "pays-bas",
            "paesi bassi",
            "paises bajos",
            "nederland",
            "holandia",
            "nederlanderna",
            "holland",
        ),
        ("poland", "polen", "pologne", "polonia", "polska"),
        ("sweden", "schweden", "suede", "svezia", "suecia", "zweden", "szwecja", "sverige"),
        (
            "united kingdom",
            "the united kingdom",
            "great britain",
            "britain",
            "grossbritannien",
            "royaume-uni",
            "regno unito",
            "reino unido",
            "verenigd koninkrijk",
            "wielka brytania",
            "storbritannien",
            "england",
            "scotland",
            "wales",
            "schottland",
            "ecosse",
            "scozia",
        ),
        (
            "united states",
            "the united states",
            "united states of america",
            "usa",
            "vereinigte staaten",
            "etats-unis",
            "stati uniti",
            "estados unidos",
            "verenigde staten",
            "stany zjednoczone",
            "forenta staterna",
        ),
        ("ireland", "irland", "irlande", "irlanda", "ierland", "irlandia"),
        ("denmark", "danemark", "danimarca", "danmark", "dania"),
        (
            "norway",
            "norwegen",
            "norvege",
            "norvegia",
            "noruega",
            "noorwegen",
            "norwegia",
            "norge",
        ),
        ("finland", "finnland", "finlande", "finlandia"),
        ("iceland", "island", "islande", "islanda", "islandia"),
        (
            "czechia",
            "czech republic",
            "tschechien",
            "republique tcheque",
            "repubblica ceca",
            "tsjechie",
            "czechy",
        ),
        ("slovakia", "slowakei", "slovaquie", "slovacchia", "slowakije", "slowacja"),
        ("hungary", "ungarn", "hongrie", "ungheria", "hongarije", "wegry"),
        ("romania", "rumanien", "roumanie", "roemenie", "rumunia"),
        ("bulgaria", "bulgarien", "bulgarie", "bulgarije"),
        ("greece", "griechenland", "grece", "grecia", "griekenland", "grecja"),
        ("croatia", "kroatien", "croatie", "croazia", "kroatie", "chorwacja"),
        ("slovenia", "slowenien", "slovenie", "slowenie", "slowenia"),
        ("serbia", "serbien", "serbie"),
        ("estonia", "estland", "estonie"),
        ("latvia", "lettland", "lettonie", "lettonia", "lotwa"),
        ("lithuania", "litauen", "lituanie", "lituania", "litwa"),
        ("turkey", "turkiye", "turkei", "turquie", "turchia", "turkije", "turcja"),
        ("ukraine", "ukraina", "ucraina", "oekraine"),
        ("russia", "russland", "russie", "rusland", "rosja"),
        ("china", "chine", "cina", "chiny"),
        ("india", "indien", "inde", "indie"),
        ("japan", "japon", "giappone", "japonia"),
        ("canada", "kanada"),
        ("australia", "australien", "australie"),
        ("brazil", "brasilien", "bresil", "brasile", "brasil", "brazylia"),
        ("mexico", "mexiko", "mexique", "messico"),
        ("morocco", "marokko", "maroc", "marocco", "maroko"),
        ("south africa", "sudafrika", "afrique du sud", "sudafrica", "zuid-afrika"),
        (
            "european union",
            "europaische union",
            "union europeenne",
            "unione europea",
            "europese unie",
            "unia europejska",
        ),
    )
    for name in names
)

#: Legal forms, as they are written in the twelve covered countries. Used here to
#: keep the lowercase-initial rule below from firing on a real company name, and
#: exported because :mod:`freedocs.detect.organisations` nominates on the same
#: vocabulary — one table, so a form recognised by one pass cannot be unknown to
#: the other.
LEGAL_FORMS: tuple[str, ...] = (
    # Switzerland, Germany, Austria
    "ag",
    "gmbh",
    "gmbh & co. kg",
    "kg",
    "ohg",
    "eg",
    "se",
    "sagl",
    "sarl",
    # Accented spellings, listed rather than folded away. This table is matched
    # against the tail of a candidate span, and folding the candidate would cost
    # the case distinction the short forms in
    # :mod:`freedocs.detect.organisations` depend on. ``Sarl`` without the accent
    # is the anglicised form; ``Sàrl`` is what a Romandy or Luxembourg company
    # actually registers under, and neither pass saw it before it was listed.
    "s\u00e0rl",
    "s.\u00e0 r.l.",
    "s.\u00e0.r.l.",
    "sa",
    "s.a.",
    "sa.",
    # Italy
    "spa",
    "s.p.a.",
    "srl",
    "s.r.l.",
    "srls",
    "snc",
    "sas",
    "scarl",
    # France, Belgium
    "s.a.r.l.",
    "sas",
    "sasu",
    "sci",
    "scs",
    "sprl",
    "bvba",
    "cvba",
    "vof",
    # Spain, Portugal
    "sl",
    "s.l.",
    "slu",
    "sau",
    "lda",
    "l.da",
    "unipessoal lda",
    # Netherlands
    "bv",
    "b.v.",
    "nv",
    "n.v.",
    # Poland
    "sp. z o.o.",
    "sp. z o. o.",
    "spolka z o.o.",
    "s.a.",
    "sp.k.",
    "sp.j.",
    # Sweden
    "ab",
    "ab (publ)",
    "hb",
    "kb",
    # United Kingdom, Ireland
    "ltd",
    "ltd.",
    "limited",
    "plc",
    "plc.",
    "llp",
    "cic",
    # United States and generic
    "inc",
    "inc.",
    "llc",
    "corp",
    "corp.",
    "corporation",
    "co.",
    "company",
    "holding",
    "holdings",
    "group",
)

_LEGAL_FORM_TAIL = re.compile(
    r"(?:^|[\s,.])(?:"
    + "|".join(re.escape(form) for form in sorted(LEGAL_FORMS, key=len, reverse=True))
    + r")\.?\s*$",
    re.IGNORECASE,
)


#: How far back a jurisdiction phrase may start. Wide enough for
#: "Any arbitration shall be seated in <Geneva>", short enough that the clause
#: before cannot reach across a sentence.
_CONTEXT_WINDOW = 120

#: Phrases that end where the finding begins, in the four languages the model
#: reads. Anchored at the end on purpose: a window that merely *contains*
#: "Recht" would suppress the company address two lines further down, and an
#: address in a contract is exactly what has to go.
#:
#: Measured on the corpus: nine LOCATION false positives, every one a city that
#: is annotated as confidential elsewhere in the same document — ``Basel``,
#: ``Zurich``, ``London``, ``Geneva``, ``Geneve``, ``Lausanne``, ``Lugano``,
#: ``Milano`` and ``England and Wales``. That overlap is the point: the string is
#: identifying in one sentence and not in the next, so nothing about the value
#: itself can settle it and nothing but the surrounding words can.
_JURISDICTION_BEFORE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # "governed by the laws of", "regi par le droit", "regolato dal diritto",
        # "untersteht schweizerischem Recht" — the verb, then the law, then us.
        r"\b(?:governed|construed|regi|regie|regolato|disciplinato|untersteht|unterliegt)"
        r"\b[^.\n]{0,50}?\b(?:laws?\s+of|droit\s+(?:de|du|des)?|diritto\s+(?:di)?|recht"
        r"(?:s|es)?\s+(?:von|der)?)\s*(?:the\s+)?$",
        r"\b(?:laws?|legislation)\s+of\s+(?:the\s+)?$",
        r"\b(?:courts?|tribunaux|tribunali|gerichte|gerichtshof)\s+(?:of|de|des|di|in|von)"
        r"\s+(?:the\s+)?$",
        r"\bgerichtsstand\s+(?:ist|in|liegt\s+in)\s+$",
        # Italian and Spanish "competent forum is <city>".
        r"\bforo\s+competente\s+(?:e|\u00e8|di|ist)\s+$",
        r"\b(?:exclusive\s+)?jurisdiction\s+(?:of|in)\s+(?:the\s+)?$",
        # The seat of an *arbitration*, never the seat of a company: a registered
        # office is the party's own address and has to be removed, so the
        # arbitration word is required rather than the bare "Sitz in".
        r"\b(?:arbitration|arbitrage|arbitrato|arbitraje|schiedsverfahren|schiedsgericht)"
        r"\b[^.\n]{0,60}?\b(?:in|a|\u00e0)\s+$",
        r"\b(?:venue|erfullungsort|erf\u00fcllungsort)\s+(?:shall\s+be|is|ist)"
        r"\s*(?:in\s+)?$",
    )
)

#: Phrases that begin where the finding ends. "<England> law", "<Geneve> sont
#: seuls competents" — the jurisdiction reading is only visible on the right.
_JURISDICTION_AFTER: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(?:law|laws|legislation|courts?)\b",
        r"^\s*shall\s+have\s+(?:the\s+)?(?:exclusive\s+)?jurisdiction",
        r"^\s*(?:sont\s+seuls\s+competents|est\s+seul\s+competent)",
        r"^\s*(?:ist\s+zust\u00e4ndig|sind\s+zust\u00e4ndig|ist\s+zustandig)",
    )
)


def _in_jurisdiction_clause(finding: Finding, text: str) -> bool:
    """Is this a place the contract is *argued* in rather than a place someone is?

    A governing-law clause names a jurisdiction to fix which law applies.
    Removing it does not protect anybody and it changes what the sentence means,
    which is the one thing a scrubbed document must not do silently.
    """
    before = _fold(text[max(0, finding.span.start - _CONTEXT_WINDOW) : finding.span.start])
    if any(pattern.search(before) for pattern in _JURISDICTION_BEFORE):
        return True
    after = _fold(text[finding.span.end : finding.span.end + _CONTEXT_WINDOW])
    return any(pattern.search(after) for pattern in _JURISDICTION_AFTER)


def _is_country(text: str) -> bool:
    return _fold(text.strip().strip(".,;:")) in _COUNTRY_NAMES


def _has_legal_form(text: str) -> bool:
    return _LEGAL_FORM_TAIL.search(text.strip()) is not None


def _is_lowercase_common_noun(finding: Finding) -> bool:
    """``cost centre 30-412/2201`` and ``service achats`` are not companies.

    Both are GLiNER2 ORGANISATION false positives on the corpus. What separates
    them from every one of the thirty-six annotated company names is the first
    character: a company name is capitalised in all four languages the model
    reads, and German capitalises its common nouns too, so the rule cannot fire
    on a German name that a French one would survive.

    A legal form anywhere in the span vetoes the rule. ``sp. z o.o. Nordwind``
    is written that way in some registers, and a lowercase first letter is much
    weaker evidence than an explicit legal form.

    A **propagated** finding is not judged here at all, and that exemption was
    paid for. This rule answers "did the model claim a common noun is a
    company?", and a copy is not a claim: its evidence is the template it came
    from, which was confirmed at its own spelling. ``SWICA`` was confirmed as an
    organisation, propagation reached the lowercase ``swica`` inside
    ``2022-03-23_swica_resume_etude.pdf``, and this rule then dropped the copy -
    after which the drop granted stage 6 an allowance and the insurer's name
    shipped inside a document whose verification said "no leak". That is the
    allowance hiding a leak, which is the one failure widening it could cause.
    """
    if finding.entity is not EntityType.ORGANISATION or finding.is_propagated:
        return False
    stripped = finding.text.lstrip()
    if not stripped:
        return False
    first = stripped[0]
    if not first.isalpha() or not first.islower():
        return False
    return not _has_legal_form(stripped)


def _is_lowercase_place(finding: Finding) -> bool:
    """`canton` and `administration cantonale` are not places.

    A LOCATION false positive on a real document: GLiNER2 returned the French
    common noun `canton` at 0.52, just above `Policy.min_confidence`. It was
    removed - the output read `le seul [LOCATION_4] qui garantit 730 jours` -
    and stage 6 then counted `cantonale` and `cantonal` as survivors of the
    value, so a scrub with nothing confidential left in it wrote no file at all.

    The argument is the one the organisation arm above uses: a place name is a
    proper noun, capitalised in all four languages the model reads, German
    included. The **test** is not the same one, and the difference is the whole
    safety of this rule. `_is_lowercase_common_noun` looks at the first
    character; here that would drop `la Chaux-de-Fonds`, `le Locle` and `les
    Diablerets`, which are towns whose article is lowercase mid-sentence. So the
    span must contain no capitalised word anywhere.

    ADDRESS is deliberately not judged this way. `detect/addresses.py` builds its
    span from a postal code outwards and starts it at the street name, and a
    street type is lowercase in French and Italian - `rue`, `via`, `chemin` - so
    the one finding here assembled from structure rather than from a model's
    guess would be the one this rule threw away.

    The accepted cost, stated rather than hidden: a city written entirely in
    lowercase is dropped. That is the same trade the organisation arm already
    makes, and no document in the corpus writes a place name that way. A
    propagated copy is exempt for the reason given there - the evidence for a
    copy is its template, not its spelling.
    """
    if finding.entity is not EntityType.LOCATION or finding.is_propagated:
        return False
    words = [word for word in re.split(r"[\s\u00a0]+", finding.text.strip()) if word]
    if not words:
        return False
    return not any(word[:1].isupper() for word in words)


def drop_non_identifying(findings: Iterable[Finding]) -> Suppressing:
    """Drop findings whose *value* identifies nobody, wherever it appears.

    Safe to run before propagation as well as after: a country name is not
    wanted anywhere in the document, so removing it early only stops it from
    spreading itself across every heading.

    The three rules underneath are not all the same kind, which shows in how
    they treat a propagated copy. The country arm judges the **value** and
    applies to a copy exactly as to an original: ``Suisse`` narrows a population
    by millions whoever found it. The two lowercase arms judge a **claim** - the
    model called this word a company, this word a place - and a copy is not a
    claim, so they skip it. Getting that wrong left a confirmed organisation in
    a document with a clean verification in front of it; see
    :func:`_is_lowercase_common_noun`.
    """
    kept: list[Finding] = []
    dropped: list[Suppression] = []
    for finding in findings:
        if finding.entity not in _FREE_TEXT:
            kept.append(finding)
            continue
        if finding.entity in (EntityType.LOCATION, EntityType.ADDRESS) and _is_country(
            finding.text
        ):
            dropped.append(Suppression(NON_IDENTIFYING, finding))
            continue
        if _is_lowercase_common_noun(finding) or _is_lowercase_place(finding):
            dropped.append(Suppression(NON_IDENTIFYING, finding))
            continue
        kept.append(finding)
    return kept, dropped


def drop_jurisdiction_mentions(findings: Iterable[Finding], text: str) -> list[Finding]:
    """Drop findings whose *position* makes them a jurisdiction, not a place.

    Runs **after** propagation and never before, which is the opposite of what
    it looks like it should do and was measured the hard way. The same city is
    confidential in one sentence and not in the next, so unlike
    :func:`drop_non_identifying` this rule judges an occurrence rather than a
    value — and an occurrence the model found *only* in the governing-law clause
    is still the evidence that propagation needs to reach the same city in the
    party's address twenty lines up.

    Filtering first cost three covered entities on the corpus to save seventy-two
    over-redacted characters: ``Basel``, ``Geneve`` and ``Milano`` each appear in
    a jurisdiction clause and again as somebody's location, and killing the
    clause mention took the template with it. Filtering last removes the clause
    mention and keeps the address.
    """
    kept: list[Finding] = []
    dropped: list[Suppression] = []
    for finding in findings:
        if _in_jurisdiction_clause(finding, text):
            dropped.append(Suppression(JURISDICTION, finding))
        else:
            kept.append(finding)
    return kept, dropped


def country_names() -> Sequence[str]:
    """The suppression list, for tests and for the report's caveats."""
    return sorted(_COUNTRY_NAMES)

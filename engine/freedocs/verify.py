"""Stage 6: prove the scrub actually worked.

Every other stage is a claim; this one is the check. The scrubbed bytes are
re-opened with the same handler, re-flattened — hidden parts included — and
searched for the values that were supposed to be gone. A leak is a hard failure,
not a warning: a file that is *almost* clean is more dangerous than one that
obviously is not, because it gets sent.

This is also why the allocator's mapping is not needed here. Verification works
from the finding text captured during detection, which the caller holds for the
duration of the run and discards with everything else.

The reverse direction has its own check in ``restore.py``, and it is not this one
run backwards. It asks two questions rather than one - is the placeholder gone,
*and* did the value arrive - because a handler that silently drops a replacement
satisfies the first and fails the second, and only the pair catches it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .core.findings import EntityType, Finding
from .core.stream import TextStream
from .formats.base import FormatHandler, Region

#: Values shorter than this are not searched for. A two-character original would
#: match somewhere in almost any document and every run would "leak".
MIN_CANARY_LENGTH = 4


@dataclass(frozen=True)
class Leak:
    """A value that was detected as confidential and is still in the output.

    ``text`` is kept because the in-process caller sometimes needs it, but
    :meth:`describe` deliberately does not render it. That message travels: to
    the CLI's stderr, which a user may redirect to a file, and through the RPC
    layer into an app that may log it. Putting the surviving confidential value
    into an error about confidential values surviving would be its own leak, so
    the description names the type, the detector and the count and leaves the
    reader to look at their own document.
    """

    entity: str
    text: str
    detector: str
    occurrences: int
    #: How many occurrences of this value the caller kept on purpose. Reported so
    #: the message cannot be read as "the override did not work": with an
    #: allowance in play the failure is the *excess*, not the presence.
    allowed: int = 0
    #: Where one occurrence of this value was found in the *source* extraction,
    #: in code points. A position, not a value: it lets a caller that already
    #: holds the preview findings say which value this is without the error
    #: having to carry it. -1 when built without a finding.
    start: int = -1
    end: int = -1

    def describe(self) -> str:
        if self.allowed:
            return (
                f"a {self.entity} value found by {self.detector} appears "
                f"{self.occurrences}x in the output, and only {self.allowed} "
                f"occurrence(s) were kept on purpose"
            )
        return (
            f"a {self.entity} value found by {self.detector} still appears "
            f"{self.occurrences}x in the output"
        )


@dataclass(frozen=True)
class EmbeddedWord:
    """One longer word a removed value was left inside, and where it stands.

    **Carries document text**, so it travels down the local pipe to the window
    and never into the report: ``build_report`` reads ``Embedded.occurrences``
    and nothing here. ``word`` is the whole word as the output spells it, which
    is what lets a reader check ``facteurs`` without being told the value.
    """

    word: str
    region: Region
    occurrences: int


@dataclass(frozen=True)
class Embedded:
    """A removed one-word value that is still in the output inside longer words.

    Reported, never raised: see :func:`verify_output` for why this is the one
    kind of survivor that does not fail a scrub. :meth:`describe` is value-free
    for the reason :class:`Leak`'s is - this sentence reaches the report.
    """

    entity: str
    text: str
    detector: str
    occurrences: int
    #: The words themselves, for the window. Value-bearing: see `EmbeddedWord`.
    words: tuple[EmbeddedWord, ...] = ()

    def describe(self) -> str:
        return (
            f"a {self.entity} value found by {self.detector} was removed wherever it "
            f"stands as a word, and still appears {self.occurrences}x inside longer "
            f"words, where it was left; check those words if the value could be "
            f"part of a username, a file name or a code"
        )


@dataclass(frozen=True)
class VerifyResult:
    leaks: tuple[Leak, ...]
    checked_values: int
    skipped_short: int
    output_chars: int
    #: The text re-extracted from the output, kept so the optional review layer
    #: does not have to extract it again. For a scanned PDF that would mean a
    #: second OCR pass over every page, which is seconds per page for a result
    #: this function already has in hand.
    extracted: str = ""
    #: One-word values surviving only inside longer words. Not leaks; reported.
    embedded: tuple[Embedded, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.leaks

    def summary(self) -> str:
        if self.ok:
            line = (
                f"no leak: {self.checked_values} distinct values checked against "
                f"{self.output_chars} characters of output"
            )
            # Said on the same line, because "no leak" read alone is taken to
            # mean none of these strings is in the file - and inside a longer
            # word some are, left there on purpose and worth a look.
            inside = sum(item.occurrences for item in self.embedded)
            if inside:
                line += f"; {inside} occurrence(s) left inside longer words, see the warnings"
            return line
        return f"{len(self.leaks)} value(s) survived the scrub"


class LeakDetected(RuntimeError):
    """Raised when verification fails, carrying the offending values."""

    def __init__(self, result: VerifyResult) -> None:
        detail = "\n".join(f"  - {leak.describe()}" for leak in result.leaks)
        super().__init__(f"scrub verification failed:\n{detail}")
        self.result = result


def _distinct_values(findings: Sequence[Finding]) -> dict[tuple[str, str], Finding]:
    """Distinct values to look for, keyed by (entity, casefolded text)."""
    wanted: dict[tuple[str, str], Finding] = {}
    for finding in findings:
        wanted.setdefault((finding.entity.value, finding.text.casefold()), finding)
    return wanted


def verify_output(
    handler_cls: type[FormatHandler],
    output_path: Path,
    output_bytes: bytes,
    removed: Sequence[Finding],
    kept: Sequence[str] = (),
) -> VerifyResult:
    """Re-extract ``output_bytes`` and confirm none of ``removed`` survived.

    ``removed`` must contain only the findings that were actually rewritten.
    Passing report-only findings would guarantee a failure, since those are left
    in the document on purpose.

    ``kept`` is the text of the occurrences a caller explicitly exempted, and it
    exists because this check is value-based while an override is
    occurrence-based. Keeping *one* ``Zurigo`` and removing the next one leaves
    the string in the document, so a search for it finds a survivor and reports a
    leak that is really a decision. The allowance is a **count**, not an
    exemption: the value may appear as many times as were kept and no more, so a
    write-back that silently failed on the other occurrence is still caught.

    Nothing here infers an allowance. It is granted only by a caller naming the
    occurrence, which is the difference between a verified decision and a hole.

    **A one-word value inside a longer word is reported, not raised.** The search
    is a substring count, while propagation - the pass that reaches a value's
    other occurrences - matches whole words only. So on a real French document
    the model called ``Acteurs`` and ``Limité`` people, every standalone
    occurrence was removed, and the scrub then failed on ``facteurs`` and
    ``limitée``: eleven occurrences of ordinary words, nothing written, and the
    same thing on every ordinary file tried. Removing those would be wrong
    (``f[PERSON_1]``), and refusing the file left nothing to act on.

    The cost is stated, not hidden: a short name inside a username or a file
    name (``mrossi``) is now a warning rather than a refusal. A value of **more
    than one word** keeps the old rule, because a multi-word value inside a word
    is not a collision with the language - it is two words the extraction fused,
    which is how ``Malakoff Humanisconsulte`` hid a company name, and that is a
    leak. Whole-word occurrences use the boundary propagation uses: ``_`` is a
    separator, so ``2022_swica_resume`` is still a whole-word ``swica``.
    """
    allowance: Counter[str] = Counter(value.casefold() for value in kept)
    handler = handler_cls(output_path, output_bytes)
    # Read the output harder than the input was read. A format that skips work
    # for speed during extraction must not be allowed to skip it here: the
    # question has changed from "what is in this file" to "did anything survive".
    handler.harden_for_verification()
    stream = handler.extract()
    # What the stream holds plus what the handler does not extract at all
    # (`FormatHandler.verification_extras`): searched here, and nowhere else.
    searched = stream.text
    extras = handler.verification_extras(stream)
    if extras:
        searched = f"{stream.text}\n{extras}"
    haystack = searched.casefold()

    leaks: list[Leak] = []
    embedded: list[Embedded] = []
    checked = 0
    skipped = 0
    for (entity, needle), finding in _distinct_values(removed).items():
        if len(needle) < MIN_CANARY_LENGTH:
            skipped += 1
            continue
        checked += 1
        occurrences = haystack.count(needle)
        # One search, classified per occurrence: `inside` counts positions that
        # are themselves among the `occurrences` just counted, so the exemption
        # can never subtract something it did not look at.
        positions = _language_collisions(searched, haystack, needle, finding.entity)
        inside = len(positions)
        occurrences -= inside
        permitted = allowance.get(needle, 0)
        if occurrences > permitted:
            leaks.append(
                Leak(
                    entity=entity,
                    text=finding.text,
                    detector=finding.detector,
                    occurrences=occurrences,
                    allowed=permitted,
                    start=finding.span.start,
                    end=finding.span.end,
                )
            )
        if inside:
            embedded.append(
                Embedded(
                    entity=entity,
                    text=finding.text,
                    detector=finding.detector,
                    occurrences=inside,
                    words=_words_at(handler, stream, searched, positions, len(needle)),
                )
            )
    return VerifyResult(
        leaks=tuple(leaks),
        checked_values=checked,
        skipped_short=skipped,
        output_chars=len(stream.text),
        extracted=stream.text,
        embedded=tuple(embedded),
    )


#: The types a model nominates from prose, where a value can also be part of an
#: ordinary word. Everything else - an IBAN, an email, a national number - has a
#: shape, and that shape fused into longer text is still the identifier.
_PROSE_TYPES = frozenset({EntityType.PERSON, EntityType.ORGANISATION, EntityType.LOCATION})


def _words_at(
    handler: FormatHandler,
    stream: TextStream,
    searched: str,
    positions: Sequence[int],
    length: int,
) -> tuple[EmbeddedWord, ...]:
    """The whole word around each position, grouped by word and region.

    A position past the stream is in ``verification_extras`` - document
    properties - which has no anchors, so it is named as metadata.
    """
    counts: Counter[tuple[str, Region]] = Counter()
    spelling: dict[tuple[str, Region], str] = {}
    for start in positions:
        left, right = start, start + length
        while left > 0 and searched[left - 1].isalnum():
            left -= 1
        while right < len(searched) and searched[right].isalnum():
            right += 1
        word = searched[left:right]
        if start < len(stream.text):
            part = stream.part_at(start)
            region = handler.region_of(part) if part else Region("other")
        else:
            region = Region("metadata")
        key = (word.casefold(), region)
        spelling.setdefault(key, word)
        counts[key] += 1
    return tuple(
        EmbeddedWord(word=spelling[key], region=key[1], occurrences=count)
        for key, count in counts.items()
    )


def _language_collisions(text: str, haystack: str, needle: str, entity: EntityType) -> list[int]:
    """Where ``needle`` occurs in ``haystack`` as part of an ordinary word.

    Narrow by construction, because every occurrence counted here is one that
    does not fail the scrub:

    - only the prose types, and only a value made of letters alone - so no
      identifier, no multi-word value (fused text, the ``Humanisconsulte``
      case) and nothing with a digit or punctuation in it;
    - the occurrences are the ones ``str.count`` counted, found the same way, in
      the same casefolded text; when casefolding changed the text's length
      (``ß`` -> ``ss``) the positions no longer line up with the original's case
      and nothing is exempted;
    - an occurrence with no letter or digit either side is a whole word and is
      not counted; the boundary is propagation's, so ``_`` separates and
      ``2022_swica_resume`` holds a whole-word ``swica``;
    - every joint must read as one word: two lowercase letters, or a capital
      that starts the word followed by a lowercase one. A digit (``rossi1985``),
      lowercase into uppercase (``MarioRossi``) and all capitals
      (``MARIOROSSI``) are fusion and stay leaks.

    - the token holding the word must not be an address: an ``@``, a slash, a
      backslash, or a dot or colon between two characters anywhere in the
      surrounding run of non-space text refuses it. That is where a username
      identifies somebody - ``mrossi@acme.ch``, ``/home/mrossi``,
      ``C:\\Users\\mrossi`` - and no prose word the exemption exists for is
      written that way.

    What remains is ``facteurs``, ``personnel``, ``limitée``, ``Facteurs``. The
    stated cost is an all-lowercase username standing alone in prose, such as
    ``mrossi``.
    """
    if entity not in _PROSE_TYPES or not needle.isalpha():
        return []
    if len(haystack) != len(text):
        return []
    found: list[int] = []
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        joined_before = start > 0 and haystack[start - 1].isalnum()
        joined_after = end < len(haystack) and haystack[end].isalnum()
        if (
            (joined_before or joined_after)
            and (not joined_before or _one_word_before(text, start))
            and (not joined_after or _one_word_after(text, end))
            and not _inside_an_address(haystack, start, end)
        ):
            found.append(start)
        start = haystack.find(needle, end)
    return found


_ADDRESS_MARKS = frozenset("@/\\")
#: Address separators only between two characters: ``facteurs.`` and
#: ``Personnel:`` end a sentence or a heading, ``acme.ch`` and ``ftp:x`` do not.
_INNER_MARKS = frozenset(".:")


def _inside_an_address(text: str, start: int, end: int) -> bool:
    """The occurrence sits in an email, a URL or a path rather than in prose.

    Read over the whole run of non-space characters around it, because the
    mark that makes it an address is rarely next to the value: in
    ``mario.mrossi@acme.ch`` the ``@`` is after it, in a path the slash is
    before it. A dot or a colon counts only between two characters, so the
    full stop ending ``facteurs.`` does not make a sentence an address.
    """
    left = start
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    right = end
    while right < len(text) and not text[right].isspace():
        right += 1
    token = text[left:right].rstrip(".,;:!?)»\"'")
    if any(mark in token for mark in _ADDRESS_MARKS):
        return True
    return any(
        token[i] in _INNER_MARKS and token[i - 1].isalnum() and token[i + 1].isalnum()
        for i in range(1, len(token) - 1)
    )


def _one_word_before(text: str, start: int) -> bool:
    """The value continues a word on its left, and the joint reads as one word."""
    left, first = text[start - 1], text[start]
    if not (left.isalpha() and first.isalpha() and first.islower()):
        return False
    if left.islower():
        return True
    # A capital is allowed only as the word's own first letter: `Facteurs`.
    return left.isupper() and (start == 1 or not text[start - 2].isalnum())


def _one_word_after(text: str, end: int) -> bool:
    """The value continues into a word on its right, all lowercase at the joint."""
    last, right = text[end - 1], text[end]
    return last.isalpha() and right.isalpha() and last.islower() and right.islower()

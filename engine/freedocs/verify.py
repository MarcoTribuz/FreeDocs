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

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .core.findings import EntityType, Finding
from .formats.base import FormatHandler

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
            return (
                f"no leak: {self.checked_values} distinct values checked against "
                f"{self.output_chars} characters of output"
            )
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
    haystack = stream.text.casefold()

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
        # Never more than the substring count: the exemption may only subtract
        # what it positively classified, so a disagreement between the two
        # searches can make the check stricter and never looser.
        inside = min(_language_collisions(stream.text, finding), occurrences)
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
                )
            )
        if inside:
            embedded.append(
                Embedded(
                    entity=entity,
                    text=finding.text,
                    detector=finding.detector,
                    occurrences=inside,
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


def _language_collisions(text: str, finding: Finding) -> int:
    """Occurrences of the value that are part of an ordinary longer word.

    Narrow by construction, because every occurrence counted here is one that
    does not fail the scrub:

    - only the prose types, and only a value made of letters alone - so no
      identifier, no multi-word value (fused text, the ``Humanisconsulte``
      case) and nothing with a digit or punctuation in it;
    - an occurrence with no letter or digit either side is a whole word and is
      not counted; the boundary is propagation's, so ``_`` separates and
      ``2022_swica_resume`` holds a whole-word ``swica``;
    - a joint touching a digit (``rossi1985``) or a lowercase letter followed by
      an uppercase one (``MarioRossi``) is fusion, not language, and is not
      counted either.

    What remains is a value continuing into lowercase letters, or capitalised at
    the start of one: ``facteurs``, ``personnel``, ``limitée``, ``Facteurs``. The
    stated cost is an all-lowercase username such as ``mrossi``.
    """
    value = finding.text.strip()
    if finding.entity not in _PROSE_TYPES or not value.isalpha():
        return 0
    count = 0
    for match in re.finditer(re.escape(value), text, re.IGNORECASE):
        start, end = match.span()
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        joined_before = before.isalnum()
        joined_after = after.isalnum()
        if not (joined_before or joined_after):
            continue
        if joined_before and _fused(before, text[start]):
            continue
        if joined_after and _fused(text[end - 1], after):
            continue
        count += 1
    return count


def _fused(left: str, right: str) -> bool:
    """Whether two adjacent characters look like two tokens run together."""
    if left.isdigit() or right.isdigit():
        return True
    return left.islower() and right.isupper()

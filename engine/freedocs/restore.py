"""The reverse path: put the real values back into what the model returned.

Five stages, and only this module knows their order:

    router -> extract -> match -> write-back -> verify

It is the scrub pipeline with the substitution inverted, and almost all of it is
reuse. ``TextStream.plan_edits`` does not care which direction text is going, so
locating a placeholder and writing a value over it is the same mechanism that
located a value and wrote a placeholder over it. No format handler learns
anything, ``FormatHandler`` gains no method, and nothing here knows what a docx
or a page is.

Three things it is not, each stated because the alternative is a plausible
mistake:

- **The matcher is not a detector.** It produces no ``Finding``, enters no
  registry, resolves no overlaps by precedence, and does not live in ``detect/``.
  It is closer to ``core/overrides.py``: a mechanism acting on what a caller has
  already decided. A ``PLACEHOLDER_SHAPE`` regex filed under ``detect/`` would
  eventually be given a confidence and a precedence, and then it is a detector
  nobody measured.
- **It runs no model.** No NER, no threshold, no country selection. So a build
  without the ``ner`` extra restores exactly as well as one with it, and there is
  no accuracy here to benchmark.
- **It does not call ``scrub_hidden()``.** There is nothing to strip, and the
  returned document's metadata belongs to whoever produced it. This is why
  restore does not reuse ``Scrubber.read``, which calls it — and why it must not
  be routed through ``rpc.Session.extraction``, whose cache holds extractions
  taken *with* hidden content already deleted.

One deliberate asymmetry with the scrub, at the end of this module: a restore
that did not finish still writes its output.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .core.findings import Span
from .core.mapping import KeyMap, MapEntry
from .core.stream import Edit
from .formats.base import FormatHandler
from .formats.router import handler_for
from .pipeline import ProgressFn, StageEvent

#: The stages, in the order this module runs them. Four of the five names are the
#: scrub's, so a consumer that translates stage names by key gains exactly one
#: entry. Published only through the events a run emits, never as a list a caller
#: can draw a stepper from — the same reason ``capabilities`` publishes no stage
#: list for the scrub.
RESTORE_STAGES = ("router", "extract", "match", "write-back", "verify")

#: A token shaped like one of ours. Used only to *report* what the map does not
#: know: a stem the model translated (``[PERSONA_1]`` out of an English scrub), a
#: number it invented, a placeholder it wrapped in markdown. Never substituted.
#: Guessing which map entry a mangled token meant is how somebody else's value
#: ends up in the document, and that is a worse outcome than a visible
#: placeholder.
PLACEHOLDER_SHAPE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")


@dataclass(frozen=True)
class Restored:
    """One placeholder that was found and replaced."""

    placeholder: str
    entity: str
    #: How many times it was found in the returned document.
    occurrences: int
    #: How many times the scrub replaced it in the source. A difference is not a
    #: failure — a model that summarised the document legitimately kept fewer —
    #: but it is the number that explains a surprising restore.
    expected: int


@dataclass(frozen=True)
class Unrestored:
    """Something the restore could not finish, named without its value.

    ``describe()`` renders the placeholder and never the original, for the reason
    ``Leak.describe()`` renders neither: this text travels to stderr, into a JSON
    report and through the RPC layer, and a message about a value that failed to
    be written must not carry the value.
    """

    placeholder: str
    entity: str
    #: ``"placeholder-survived"`` — the token is still in the output, so the edit
    #: did not land. ``"value-missing"`` — the token is gone but the value never
    #: arrived, which is what a silently dropped replacement looks like.
    kind: str

    def describe(self) -> str:
        if self.kind == "value-missing":
            return (
                f"{self.placeholder} was removed from the output but its {self.entity} "
                "value did not arrive - the replacement was dropped rather than written"
            )
        return f"{self.placeholder} is still in the output; its {self.entity} value was not written"


@dataclass
class RestoreResult:
    source: Path
    format_name: str
    output: bytes
    restored: tuple[Restored, ...]
    #: In the map, absent from the returned document. Usually the model dropped
    #: that part of the text; reported because "restored" and "was not there" look
    #: identical in the output, which is the same reason
    #: ``Override.unmatched`` exists.
    unused: tuple[str, ...]
    #: Placeholder-shaped tokens the map does not know. Safe to print: these are
    #: labels, not values.
    unknown: tuple[str, ...]
    problems: tuple[Unrestored, ...]
    #: Compromises the handler had to make, read from the *live* handler after
    #: write-back. A handler goes on warning while writing — a placeholder shrunk
    #: to fit, a re-serialised embedded workbook — and restore is where that
    #: matters most, since a real value is almost always longer than the token it
    #: replaces.
    warnings: list[str] = field(default_factory=list)
    output_chars: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        values = sum(entry.occurrences for entry in self.restored)
        if self.ok:
            return (
                f"restored: {values} occurrence(s) of {len(self.restored)} value(s) "
                f"against {self.output_chars} characters of output"
            )
        return f"{len(self.problems)} value(s) did not make it back"


class RestoreIncomplete(RuntimeError):
    """Raised only where a caller asked for strictness, carrying the result.

    Unlike :class:`~freedocs.verify.LeakDetected` this does *not* mean nothing
    was written. See :meth:`Restorer.restore`.
    """

    def __init__(self, result: RestoreResult) -> None:
        detail = "\n".join(f"  - {problem.describe()}" for problem in result.problems)
        super().__init__(f"restore did not finish:\n{detail}")
        self.result = result


@dataclass
class Restorer:
    """Puts one key map's values back into whatever comes back from the model."""

    key_map: KeyMap
    #: Where to report stage progress. None means nobody is listening, which is
    #: the CLI and every test.
    progress: ProgressFn | None = None

    def _announce(
        self,
        stage: str,
        *,
        done: int | None = None,
        of: int | None = None,
        detail: str = "",
    ) -> None:
        if self.progress is None:
            return
        self.progress(
            StageEvent(
                stage=stage,
                index=RESTORE_STAGES.index(stage) + 1,
                count=len(RESTORE_STAGES),
                done=done,
                of=of,
                detail=detail,
            )
        )

    def restore(self, path: Path) -> RestoreResult:
        """Read ``path``, write the values back, and check both directions.

        **The output is returned even when the result is incomplete, and that is
        deliberately the opposite of a scrub.** A scrub that leaks must write
        nothing, because a nearly-clean file is more dangerous than an obviously
        dirty one: it gets sent. A restore that left one ``[IBAN_1]`` behind has
        produced a document that is still the caller's best artifact, and whose
        defect is visible in it. So the bytes come back, every problem is
        reported, and the caller exits non-zero. Do not "fix" this into
        consistency with stage 6.
        """
        self._announce("router")
        handler = handler_for(path)

        self._announce("extract")
        handler.set_progress(
            lambda done, of, detail: self._announce("extract", done=done, of=of, detail=detail)
        )
        try:
            stream = handler.extract()
        finally:
            # The handler outlives this call - write-back goes through it - and a
            # callback left behind would report extraction progress from a later
            # stage.
            handler.set_progress(None)

        edits, restored, unused = self._match(stream.text)
        unknown = _unknown_tokens(stream.text, self.key_map)

        self._announce("write-back")
        output = handler.write_back(stream.plan_edits(edits))

        self._announce("verify")
        problems, output_chars = _verify_restore(handler, output, restored, self.key_map)

        return RestoreResult(
            source=handler.path,
            format_name=handler.name,
            output=output,
            restored=restored,
            unused=unused,
            unknown=unknown,
            problems=problems,
            # From the live handler, not from a snapshot taken at extraction: the
            # warnings that say a value did not fit are emitted during write-back.
            warnings=[*handler.warnings, *self.key_map.warnings()],
            output_chars=output_chars,
        )

    def _match(self, text: str) -> tuple[list[Edit], tuple[Restored, ...], tuple[str, ...]]:
        """Locate every literal placeholder the map knows. Stage three.

        Literal only. No case folding, no tolerance for spaces inside the
        brackets, no unwrapping of markdown. Every near miss is reported as
        unknown instead, because a fuzzy match writes a real confidential value
        into a position the caller never saw.

        ``[PERSON_1]`` cannot be confused with ``[PERSON_11]``: the closing
        bracket ends the token, so no map placeholder is a prefix of another and
        no longest-match ordering is needed. That is the one place the brackets
        earn their keep, and ``test_restore.py`` pins it.
        """
        entries = self.key_map.entries
        if not entries:
            # `done`/`of` only where a stage has a real unit. Zero entries is not a
            # unit of nothing, it is no unit - and `0 of 0` renders as a bar stuck
            # at empty rather than as a stage with nothing to do.
            self._announce("match")
            return [], (), ()
        claimed: list[tuple[int, int]] = []
        edits: list[Edit] = []
        restored: list[Restored] = []
        unused: list[str] = []

        for index, entry in enumerate(entries):
            self._announce("match", done=index, of=len(entries))
            spans = _occurrences(text, entry.placeholder, claimed)
            if not spans:
                unused.append(entry.placeholder)
                continue
            for start, end in spans:
                edits.append(Edit(span=Span(start=start, end=end), replacement=entry.value))
            restored.append(
                Restored(
                    placeholder=entry.placeholder,
                    entity=entry.entity.value,
                    occurrences=len(spans),
                    expected=entry.occurrences,
                )
            )
        self._announce("match", done=len(entries), of=len(entries))
        return edits, tuple(restored), tuple(unused)


def _occurrences(text: str, needle: str, claimed: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Every occurrence of ``needle`` that no earlier entry already covers.

    Overlap is impossible for well-formed placeholders, so this guard is against
    a hand-edited key file rather than against our own output. Claiming
    first-come-first-served and skipping the rest is what keeps
    ``plan_edits`` from raising on an overlap the caller cannot act on.
    """
    found: list[tuple[int, int]] = []
    at = text.find(needle)
    while at != -1:
        end = at + len(needle)
        if not any(start < end and at < stop for start, stop in claimed):
            found.append((at, end))
            claimed.append((at, end))
        at = text.find(needle, end)
    return found


def _unknown_tokens(text: str, key_map: KeyMap) -> tuple[str, ...]:
    """Placeholder-shaped tokens the map does not know, deduplicated and sorted.

    This is the honest half of a literal-only match. Without it a translated stem
    or an invented number leaves the document silently, and the caller reads a
    clean report over a document with ``[PERSONA_1]`` still in it.
    """
    known = set(key_map.by_placeholder())
    seen = {match.group(0) for match in PLACEHOLDER_SHAPE.finditer(text)}
    return tuple(sorted(seen - known))


def _verify_restore(
    handler: FormatHandler,
    output: bytes,
    restored: Sequence[Restored],
    key_map: KeyMap,
) -> tuple[tuple[Unrestored, ...], int]:
    """Stage five, and it checks **both** directions.

    Placeholder absent *and* value present. The second half is not symmetry for
    its own sake: ``PdfTextHandler`` replaces text by stamping a redaction
    annotation, and PyMuPDF silently drops a replacement that does not fit its
    rectangle. A real value is almost always longer than the token it replaces,
    so on a PDF the common failure is the token being removed and the value never
    arriving — which a one-directional check reads as success. This is the same
    class of hole ``harden_for_verification()`` was written to close, and it is
    the load-bearing part of this module.

    Read as hard as the scrub reads its own output, for the same reason: the
    question has changed from "what is in this file" to "did the edit land".
    """
    reread = type(handler)(handler.path, output)
    reread.harden_for_verification()
    text = reread.extract().text
    haystack = text.casefold()
    by_placeholder = key_map.by_placeholder()

    problems: list[Unrestored] = []
    for entry in restored:
        mapping: MapEntry | None = by_placeholder.get(entry.placeholder)
        if mapping is None:  # pragma: no cover - restored is built from the map
            continue
        if entry.placeholder in text:
            problems.append(
                Unrestored(
                    placeholder=entry.placeholder,
                    entity=entry.entity,
                    kind="placeholder-survived",
                )
            )
        elif mapping.value.casefold() not in haystack:
            problems.append(
                Unrestored(
                    placeholder=entry.placeholder,
                    entity=entry.entity,
                    kind="value-missing",
                )
            )
    return tuple(problems), len(text)

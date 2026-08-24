"""What a person decided after reading the preview.

Detection is a measurement and it is never going to be complete: the corpus says
99.6% of what it should remove, which means a real document sometimes carries a
name no layer nominated, and sometimes flags a place that is nobody's address.
Both are fixable in one place — by the person looking at the preview — and
neither is fixable by another rule.

This module is that channel, and it is deliberately not a detector. It produces
nothing on its own, it cannot run without a caller supplying the decision, and it
holds no opinion about what confidential means. That opinion is the one thing the
window is not allowed to have; see the note in ``CLAUDE.md`` on why the app holds
no rules.

Two asymmetries are worth stating, because they are the design:

**A keep is addressed by span, a removal by value.** The window shows one row per
occurrence, so "keep *this* one" is a range the caller already has — and it has to
be a range, since the same city is confidential in an address and not in a
jurisdiction clause. A removal has no row to point at, and no coordinate the
caller could have obtained without the document text, which the preview does not
send. So a removal names a string and this module finds every occurrence of it.
That also matches what the caller means: a name the detectors missed once was
probably missed everywhere.

**A stale keep is a leak and a stale removal is not.** A range whose text has
changed is pointing at something the caller never saw. If that is honoured, a
confidential value survives because of a decision made about a different value —
so :meth:`Override.apply` raises rather than guessing. A removal that matches
nothing merely removes nothing, and is reported instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .findings import EntityType, Finding, Layer, Span

#: Marks a finding that exists because somebody said so, in the report and in
#: ``inspect`` output. Distinguishable from a detector name on sight, because
#: "who claimed this" is the first question asked of a finding nobody expected.
DETECTOR = "human"


class StaleOverride(ValueError):
    """A kept span no longer covers the text the caller saw.

    Raised rather than ignored. The alternative is honouring a decision about
    text that is no longer there, which keeps whatever moved into that range —
    and the caller believes they exempted something harmless. A file edited
    between the preview and the scrub is the ordinary way to reach this.
    """


@dataclass(frozen=True)
class KeptSpan:
    """One occurrence the caller does not want removed.

    ``text`` is not decoration. It is what makes the span checkable: offsets come
    from a previous extraction of the same file, and nothing guarantees the file
    is unchanged since.
    """

    start: int
    end: int
    text: str
    #: Which document this decision is about. ``None`` means every document in the
    #: request, which is almost never what a span means: offsets belong to one
    #: extraction, so an unscoped span applied to the second file of a batch is
    #: stale by construction and would be refused. Kept as an option only because
    #: a single-file caller has nothing to scope to.
    path: str | None = None

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)


@dataclass(frozen=True)
class RemovedValue:
    """A literal string the caller wants gone wherever it appears.

    ``entity`` decides the placeholder and the report line. It defaults to
    :attr:`EntityType.OTHER` because a caller who has not said what a value *is*
    has still said it must go, and inventing a category for them would put a
    guess in the output where a placeholder belongs.
    """

    value: str
    entity: EntityType = EntityType.OTHER
    #: Which document this decision is about, or ``None`` for all of them. Unlike
    #: a span, a value is meaningful across a batch — one list of names over a
    #: folder of contracts — so both readings are useful here.
    path: str | None = None


@dataclass(frozen=True)
class Override:
    """Per-occurrence decisions layered over whatever the detectors returned."""

    keep: tuple[KeptSpan, ...] = field(default_factory=tuple)
    remove: tuple[RemovedValue, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.keep or self.remove)

    def for_path(self, path: str) -> Override:
        """The subset of these decisions that applies to one document.

        A batch is scrubbed with one set of parameters, and a kept span is an
        offset into one particular extraction. Without this, the second file of a
        batch is checked against the first file's spans and fails as stale — which
        is the check working, on a question nobody asked.
        """
        return Override(
            keep=tuple(k for k in self.keep if k.path in (None, path)),
            remove=tuple(r for r in self.remove if r.path in (None, path)),
        )

    def apply(self, text: str, findings: Iterable[Finding]) -> list[Finding]:
        """Return ``findings`` with the caller's decisions applied.

        Order matters and is not arbitrary. Removals are located first, then the
        detected findings are filtered, so that a kept span can exempt an
        occurrence the caller *also* asked to remove by value — the narrower
        instruction wins, which is the only reading under which both controls do
        what their labels say.
        """
        self._check(text)
        kept_spans = [kept.span for kept in self.keep]
        # Applied to the caller's own additions as well, not only to what the
        # detectors returned. "Remove this value" and "keep this occurrence" is a
        # coherent pair of instructions — remove the company name everywhere
        # except in the letterhead — and honouring only the broader one would make
        # the keep silently inert on exactly the span it names.
        added = [
            new
            for new in self._added(text)
            if not any(new.span.overlaps(span) for span in kept_spans)
        ]

        surviving: list[Finding] = []
        for finding in findings:
            if any(finding.span.overlaps(span) for span in kept_spans):
                continue
            # A human removal and a detector claim on the same characters would be
            # two edits on one range, which `plan_edits` refuses. The human wins:
            # see LAYER_PRECEDENCE. Dropped here rather than left to
            # `resolve_overlaps`, because this runs after the registry has already
            # resolved and nothing would resolve it again.
            if any(finding.span.overlaps(new.span) for new in added):
                continue
            surviving.append(finding)

        return sorted(surviving + added, key=lambda f: (f.span.start, f.span.end))

    def unmatched(self, text: str) -> list[str]:
        """Values that appear nowhere in ``text``.

        Reported, never raised. A caller pasting a value that is not in this
        document is doing something ordinary — scrubbing a batch with one list of
        names — and failing the file would be wrong. Saying nothing would not:
        "it was removed" and "it was not there" look identical in the output.
        """
        return [item.value for item in self.remove if item.value and item.value not in text]

    def _check(self, text: str) -> None:
        for kept in self.keep:
            if kept.start < 0 or kept.end > len(text) or kept.start >= kept.end:
                raise StaleOverride(
                    f"kept span [{kept.start}, {kept.end}) is outside a document of "
                    f"{len(text)} characters"
                )
            actual = text[kept.start : kept.end]
            if actual != kept.text:
                # Both halves are quoted, and the old justification for that was
                # only half true. `kept.text` is the caller's own and came from
                # this channel, so naming it reveals nothing new. `actual` is a
                # slice of the document *as it is now*, which the caller has by
                # definition not seen - that is the whole reason this check
                # fired. It is quoted anyway, and the reason is the channel
                # rather than the value: this travels the local pipe, which
                # already carries matched text and, on request, the entire
                # extracted document. What it must never do is reach a report or
                # the traceback sink, and `rpc.scrub` catches it into a per-file
                # failure for exactly that.
                raise StaleOverride(
                    f"kept span [{kept.start}, {kept.end}) covers {actual!r}, "
                    f"but the caller saw {kept.text!r}; re-inspect the file"
                )

    def _added(self, text: str) -> Iterable[Finding]:
        """One finding per occurrence of each requested value.

        Occurrences are found by plain substring search, not the word-bounded
        match ``propagate`` uses. The difference is deliberate: propagation is an
        inference about a value a detector found, and has to be conservative,
        while this is an instruction. A caller who asks for ``Acme`` inside
        ``Acmegraph`` gets it, and the preview they are about to re-read shows
        exactly that.
        """
        claimed: list[Span] = []
        for item in self.remove:
            if not item.value:
                continue
            start = text.find(item.value)
            while start != -1:
                span = Span(start, start + len(item.value))
                # Two requested values can nest ("Acme" inside "Acme Corp"). The
                # first one wins rather than producing overlapping edits; which
                # one that is follows the caller's own ordering.
                if not any(span.overlaps(other) for other in claimed):
                    claimed.append(span)
                    yield Finding(
                        span=span,
                        entity=item.entity,
                        text=item.value,
                        layer=Layer.HUMAN,
                        detector=DETECTOR,
                        confidence=1.0,
                    )
                start = text.find(item.value, start + 1)


def parse_override(keep: Sequence[dict] | None, remove: Sequence[dict] | None) -> Override:
    """Build an :class:`Override` from decoded JSON, rejecting what it cannot read.

    Lives here rather than in ``rpc`` so that the CLI and the pipe agree on what a
    decision is. An unknown entity name is an error and not a fallback to
    ``OTHER``: a caller who names a type this build does not have is working from
    a different contract, and quietly downgrading them would put an unexpected
    placeholder in the document.
    """
    kept: list[KeptSpan] = []
    for item in keep or []:
        try:
            kept.append(
                KeptSpan(
                    start=int(item["start"]),
                    end=int(item["end"]),
                    text=str(item["text"]),
                    path=_optional_path(item),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "each kept span needs integer 'start' and 'end' and the 'text' it covers"
            ) from exc

    removals: list[RemovedValue] = []
    for item in remove or []:
        if isinstance(item, str):
            removals.append(RemovedValue(value=item))
            continue
        try:
            value = str(item["value"])
        except (KeyError, TypeError) as exc:
            raise ValueError("each removal needs a 'value'") from exc
        where = _optional_path(item)
        name = item.get("entity")
        if name is None:
            removals.append(RemovedValue(value=value, path=where))
            continue
        try:
            removals.append(
                RemovedValue(value=value, entity=EntityType(str(name).upper()), path=where)
            )
        except ValueError as exc:
            raise ValueError(f"unknown entity type {name!r}") from exc

    return Override(keep=tuple(kept), remove=tuple(removals))


def _optional_path(item: dict) -> str | None:
    where = item.get("path")
    return None if where is None else str(where)

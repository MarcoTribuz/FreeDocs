"""The bridge between "text a model can read" and "bytes in the original file".

A detector needs one flat, continuous string: ``"Mario Rossi"`` must look like
``"Mario Rossi"`` even when Word stored it as three separate runs. A writer needs
the opposite: it must put characters back into those exact three runs, or the
formatting is lost.

:class:`TextStream` holds both views at once. Extraction appends anchored chunks;
each :class:`Anchor` remembers where its characters came from. Detection runs on
``stream.text``. Write-back calls :meth:`TextStream.plan_edits`, which translates
stream-coordinate edits into per-anchor edits with local offsets.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any

from .findings import Span


@dataclass(frozen=True)
class Anchor:
    """Points from a range of the flat stream back into the source document.

    ``locator`` is opaque to the core and interpreted only by the format handler
    that created it: a run index for OOXML, a text span for PDF, a bounding box
    for OCR, a byte offset for plain text.
    """

    part: str
    locator: Any
    start: int
    end: int

    def __len__(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class AnchorEdit:
    """An edit expressed in the coordinates of a single anchor.

    ``local_start``/``local_end`` are offsets *within* the anchor's own text, so a
    handler can splice without knowing anything about the rest of the stream.
    """

    anchor: Anchor
    local_start: int
    local_end: int
    replacement: str

    @property
    def part(self) -> str:
        return self.anchor.part


@dataclass(frozen=True)
class Edit:
    """A requested replacement, in stream coordinates."""

    span: Span
    replacement: str


@dataclass(frozen=True)
class PartSegment:
    """A contiguous stretch of the flat stream that came from one part.

    Consecutive anchors naming the same part are one segment, so a caller
    rendering the text can put a page or sheet heading in front of each without
    knowing how many runs, cells or spans it was assembled from.
    """

    part: str
    start: int
    end: int


class TextStreamBuilder:
    """Accumulates anchored chunks into a :class:`TextStream`."""

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._anchors: list[Anchor] = []
        self._length = 0

    def add(self, text: str, *, part: str, locator: Any) -> Anchor | None:
        """Append text that lives somewhere in the source and may be edited.

        Empty text produces no anchor: an anchor with nothing in it could never
        be the target of an edit, and would only complicate the lookup.
        """
        if not text:
            return None
        anchor = Anchor(
            part=part, locator=locator, start=self._length, end=self._length + len(text)
        )
        self._chunks.append(text)
        self._anchors.append(anchor)
        self._length = anchor.end
        return anchor

    def add_filler(self, text: str = "\n") -> None:
        """Append separator text with no source location.

        Used between paragraphs, cells and slides so the detector sees boundaries
        instead of words fused across structural gaps. Filler is never edited,
        because there is nowhere in the source file to write it back to.
        """
        if not text:
            return
        self._chunks.append(text)
        self._length += len(text)

    def build(self) -> TextStream:
        return TextStream(text="".join(self._chunks), anchors=tuple(self._anchors))


@dataclass(frozen=True)
class TextStream:
    """Flat text plus the anchors that map it back to the source document."""

    text: str
    anchors: tuple[Anchor, ...]
    #: Cached anchor start offsets, for binary search during resolution.
    _starts: list[int] = field(init=False, repr=False, compare=False, default_factory=list)

    def __post_init__(self) -> None:
        starts = [a.start for a in self.anchors]
        if starts != sorted(starts):
            raise ValueError("anchors must be in stream order")
        object.__setattr__(self, "_starts", starts)

    def __len__(self) -> int:
        return len(self.text)

    def slice(self, span: Span) -> str:
        return self.text[span.start : span.end]

    def resolve(self, span: Span) -> list[tuple[Anchor, int, int]]:
        """Return ``(anchor, local_start, local_end)`` for every anchor the span touches.

        Filler regions produce no entry, so a span straddling a paragraph break
        resolves to the anchors on either side of it.
        """
        if len(span) == 0:
            return []
        # Start from the last anchor beginning at or before the span, since that
        # one may still overlap; everything earlier cannot.
        idx = max(0, bisect.bisect_right(self._starts, span.start) - 1)
        hits: list[tuple[Anchor, int, int]] = []
        for anchor in self.anchors[idx:]:
            if anchor.start >= span.end:
                break
            overlap_start = max(anchor.start, span.start)
            overlap_end = min(anchor.end, span.end)
            if overlap_start < overlap_end:
                hits.append((anchor, overlap_start - anchor.start, overlap_end - anchor.start))
        return hits

    def part_at(self, offset: int) -> str:
        """Which part of the source an offset came from, or ``""`` for filler.

        A binary search rather than a scan, because the caller is a loop over
        findings: the previous implementation walked every anchor once per
        finding, which on a 200-page PDF is tens of thousands of anchors times
        hundreds of findings. ``_starts`` is already cached for :meth:`resolve`.
        """
        if not self.anchors:
            return ""
        idx = bisect.bisect_right(self._starts, offset) - 1
        if idx < 0:
            return ""
        anchor = self.anchors[idx]
        return anchor.part if anchor.start <= offset < anchor.end else ""

    def part_segments(self) -> tuple[PartSegment, ...]:
        """Coalesce the anchors into one range per run of the same part.

        Filler between two anchors of the same part falls *inside* the segment,
        because it is the separator this stream inserted rather than a gap in the
        source. Filler between two different parts falls between segments and is
        left unassigned: it belongs to neither, and claiming it for one would put
        a page's trailing newline under the next page's heading.
        """
        segments: list[PartSegment] = []
        for anchor in self.anchors:
            if segments and segments[-1].part == anchor.part:
                last = segments[-1]
                segments[-1] = PartSegment(part=last.part, start=last.start, end=anchor.end)
            else:
                segments.append(PartSegment(part=anchor.part, start=anchor.start, end=anchor.end))
        return tuple(segments)

    def plan_edits(self, edits: list[Edit]) -> list[AnchorEdit]:
        """Translate stream-coordinate edits into per-anchor edits.

        When an edit spans several anchors the whole replacement lands in the
        first one and the rest only lose their covered characters. That is what
        keeps run-level formatting intact: surviving runs keep their own
        properties and no new run has to be invented.

        Raises:
            ValueError: if two edits overlap, or if an edit covers only filler
                text and so has nowhere in the source to be written.
        """
        ordered = sorted(edits, key=lambda e: (e.span.start, e.span.end))
        for index in range(1, len(ordered)):
            previous, current = ordered[index - 1], ordered[index]
            if previous.span.overlaps(current.span):
                raise ValueError(
                    f"overlapping edits: {previous.span} and {current.span}; "
                    "resolve conflicts in the detector registry first"
                )

        planned: list[AnchorEdit] = []
        for edit in ordered:
            hits = self.resolve(edit.span)
            if not hits:
                raise ValueError(
                    f"edit at {edit.span} resolves to no anchor - the text it covers "
                    "is separator-only and does not exist in the source document"
                )
            for position, (anchor, local_start, local_end) in enumerate(hits):
                planned.append(
                    AnchorEdit(
                        anchor=anchor,
                        local_start=local_start,
                        local_end=local_end,
                        replacement=edit.replacement if position == 0 else "",
                    )
                )
        return planned


def apply_anchor_edits(original: str, edits: list[AnchorEdit]) -> str:
    """Apply edits belonging to one anchor to that anchor's own text.

    Shared by every format handler, so the splice arithmetic exists in one place.
    """
    ordered = sorted(edits, key=lambda e: e.local_start)
    out: list[str] = []
    cursor = 0
    for edit in ordered:
        if edit.local_start < cursor:
            raise ValueError(f"overlapping edits within one anchor at offset {edit.local_start}")
        out.append(original[cursor : edit.local_start])
        out.append(edit.replacement)
        cursor = edit.local_end
    out.append(original[cursor:])
    return "".join(out)


def group_by_anchor(edits: list[AnchorEdit]) -> dict[int, list[AnchorEdit]]:
    """Group planned edits by anchor identity.

    Keyed by ``id(anchor)`` because ``locator`` may be an unhashable structure.
    """
    grouped: dict[int, list[AnchorEdit]] = {}
    for edit in edits:
        grouped.setdefault(id(edit.anchor), []).append(edit)
    return grouped

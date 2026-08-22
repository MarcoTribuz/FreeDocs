"""The anchor/offset machinery, which everything else depends on being right."""

from __future__ import annotations

import pytest

from freedocs.core.findings import Span
from freedocs.core.stream import (
    Edit,
    TextStreamBuilder,
    apply_anchor_edits,
    group_by_anchor,
)


def build(*chunks: str, filler: str = "") -> object:
    builder = TextStreamBuilder()
    for index, chunk in enumerate(chunks):
        builder.add(chunk, part="p", locator=index)
        if filler:
            builder.add_filler(filler)
    return builder.build()


def test_flat_text_joins_chunks_without_gaps():
    stream = build("Mario Ros", "si", " lavora a Lugano")
    assert stream.text == "Mario Rossi lavora a Lugano"


def test_empty_chunk_creates_no_anchor():
    stream = build("a", "", "b")
    assert len(stream.anchors) == 2


def test_resolve_maps_a_span_inside_one_anchor():
    stream = build("Mario Rossi")
    hits = stream.resolve(Span(6, 11))
    assert len(hits) == 1
    anchor, local_start, local_end = hits[0]
    assert (local_start, local_end) == (6, 11)
    assert anchor.locator == 0


def test_resolve_spans_three_anchors():
    """The case that breaks naive OOXML tools: one name split across runs."""
    stream = build("Mario ", "Ros", "si")
    hits = stream.resolve(Span(0, 11))
    assert [(a.locator, s, e) for a, s, e in hits] == [(0, 0, 6), (1, 0, 3), (2, 0, 2)]


def test_resolve_skips_filler_but_reaches_anchors_on_both_sides():
    stream = build("riga uno", "riga due", filler="\n")
    # "uno\nriga" straddles the newline that belongs to no anchor.
    hits = stream.resolve(Span(5, 13))
    assert [(a.locator, s, e) for a, s, e in hits] == [(0, 5, 8), (1, 0, 4)]


def test_resolve_empty_span_returns_nothing():
    stream = build("abc")
    assert stream.resolve(Span(1, 1)) == []


def test_plan_edits_puts_replacement_in_first_anchor_only():
    """Replacement lands once; later anchors only lose their covered text.

    This is what preserves run formatting: no run is invented or merged.
    """
    stream = build("Mario ", "Ros", "si")
    planned = stream.plan_edits([Edit(span=Span(0, 11), replacement="[PERSONA_1]")])
    assert [(e.anchor.locator, e.local_start, e.local_end, e.replacement) for e in planned] == [
        (0, 0, 6, "[PERSONA_1]"),
        (1, 0, 3, ""),
        (2, 0, 2, ""),
    ]


def test_plan_edits_rejects_overlapping_edits():
    stream = build("abcdefgh")
    with pytest.raises(ValueError, match="overlapping edits"):
        stream.plan_edits(
            [
                Edit(span=Span(0, 4), replacement="X"),
                Edit(span=Span(3, 6), replacement="Y"),
            ]
        )


def test_plan_edits_rejects_an_edit_covering_only_filler():
    builder = TextStreamBuilder()
    builder.add("abc", part="p", locator=0)
    builder.add_filler("\n\n")
    builder.add("def", part="p", locator=1)
    stream = builder.build()
    with pytest.raises(ValueError, match="resolves to no anchor"):
        stream.plan_edits([Edit(span=Span(3, 5), replacement="X")])


def test_plan_edits_is_order_independent():
    stream = build("abcdefghij")
    forward = stream.plan_edits(
        [Edit(span=Span(0, 2), replacement="A"), Edit(span=Span(5, 7), replacement="B")]
    )
    reverse = stream.plan_edits(
        [Edit(span=Span(5, 7), replacement="B"), Edit(span=Span(0, 2), replacement="A")]
    )
    assert forward == reverse


def test_anchors_must_be_ordered():
    stream = build("abc", "def")
    assert [a.start for a in stream.anchors] == [0, 3]


def test_apply_anchor_edits_splices_in_offset_order():
    stream = build("mario rossi vive a lugano")
    planned = stream.plan_edits(
        [
            Edit(span=Span(0, 11), replacement="[PERSONA_1]"),
            Edit(span=Span(19, 25), replacement="[LUOGO_1]"),
        ]
    )
    grouped = group_by_anchor(planned)
    (edits,) = grouped.values()
    assert apply_anchor_edits(stream.text, edits) == "[PERSONA_1] vive a [LUOGO_1]"


def test_apply_anchor_edits_with_no_edits_is_identity():
    assert apply_anchor_edits("unchanged", []) == "unchanged"


def test_part_at_finds_the_part_an_offset_belongs_to():
    builder = TextStreamBuilder()
    builder.add("Mario", part="page:1", locator=0)
    builder.add_filler("\n")
    builder.add("Rossi", part="page:2", locator=1)
    stream = builder.build()

    assert stream.part_at(0) == "page:1"
    assert stream.part_at(4) == "page:1"
    # The filler between two parts belongs to neither.
    assert stream.part_at(5) == ""
    assert stream.part_at(6) == "page:2"
    # Past the end is not an error: an offset nobody anchored has no part.
    assert stream.part_at(999) == ""


def test_part_segments_coalesce_one_part_into_one_range():
    """Three runs of one page are one heading, not three."""
    builder = TextStreamBuilder()
    builder.add("Mario", part="page:1", locator=0)
    builder.add(" ", part="page:1", locator=1)
    builder.add("Rossi", part="page:1", locator=2)
    segments = builder.build().part_segments()

    assert len(segments) == 1
    assert (segments[0].part, segments[0].start, segments[0].end) == ("page:1", 0, 11)


def test_a_segment_boundary_falls_between_parts_and_not_inside_one():
    """The newline separating two pages is claimed by neither of them.

    Claiming it for the earlier page would put a trailing blank line inside it;
    claiming it for the later one would put it above that page's heading.
    """
    builder = TextStreamBuilder()
    builder.add("uno", part="page:1", locator=0)
    builder.add_filler("\n")
    builder.add("due", part="page:2", locator=1)
    first, second = builder.build().part_segments()

    assert (first.start, first.end) == (0, 3)
    assert (second.start, second.end) == (4, 7)
    assert first.end < second.start

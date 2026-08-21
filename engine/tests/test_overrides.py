"""The human override loop, leak side first.

The dangerous half of this feature is ``keep``: every other control in the engine
can only cause a value to be removed, and this one causes a value to stay. So the
first tests here are about what a keep must *not* be able to do — silently widen
past the occurrence the caller pointed at, survive the file changing underneath
it, or slip past stage 6.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.core.overrides import (
    KeptSpan,
    Override,
    RemovedValue,
    StaleOverride,
    parse_override,
)

TEXT = "Il cliente Mario Rossi ha sede a Zurigo. Il fornitore e a Zurigo pure."
FIRST = TEXT.index("Zurigo")
SECOND = TEXT.index("Zurigo", FIRST + 1)


def finding(value: str, start: int, entity: EntityType = EntityType.LOCATION) -> Finding:
    return Finding(
        span=Span(start, start + len(value)),
        entity=entity,
        text=value,
        layer=Layer.NER,
        detector="gliner2:location",
        confidence=1.0,
    )


class TestStaleSpans:
    """A decision about text that has changed is refused, never reinterpreted."""

    def test_a_span_whose_text_moved_is_refused(self):
        override = Override(keep=(KeptSpan(FIRST, FIRST + 6, "Milano"),))
        with pytest.raises(StaleOverride, match="re-inspect"):
            override.apply(TEXT, [])

    def test_a_span_past_the_end_of_the_document_is_refused(self):
        override = Override(keep=(KeptSpan(5000, 5006, "Zurigo"),))
        with pytest.raises(StaleOverride):
            override.apply(TEXT, [])

    def test_an_inverted_span_is_refused(self):
        override = Override(keep=(KeptSpan(20, 10, "Zurigo"),))
        with pytest.raises(StaleOverride):
            override.apply(TEXT, [])

    def test_the_message_says_which_decision_went_stale(self):
        """A caller cannot fix this without being told which one it was."""
        override = Override(keep=(KeptSpan(FIRST, FIRST + 6, "Milano"),))
        with pytest.raises(StaleOverride) as raised:
            override.apply(TEXT, [])
        assert "Milano" in str(raised.value)
        assert str(FIRST) in str(raised.value)


class TestKeep:
    def test_only_the_named_occurrence_is_kept(self):
        """The whole reason a keep is a span and not a value.

        The same city is confidential in the party's address and not in "the
        courts of Zurich" — see ``detect/suppress.py``. A keep that spread to
        every occurrence of the string would be a leak in the first sentence.
        """
        override = Override(keep=(KeptSpan(FIRST, FIRST + 6, "Zurigo"),))
        kept = override.apply(TEXT, [finding("Zurigo", FIRST), finding("Zurigo", SECOND)])
        assert [f.span.start for f in kept] == [SECOND]

    def test_a_keep_covering_part_of_a_finding_still_exempts_it(self):
        """Half an edit is not a thing. Overlap is the test, not containment."""
        override = Override(keep=(KeptSpan(FIRST, FIRST + 3, "Zur"),))
        assert override.apply(TEXT, [finding("Zurigo", FIRST)]) == []

    def test_a_keep_touching_nothing_changes_nothing(self):
        override = Override(keep=(KeptSpan(0, 2, "Il"),))
        found = [finding("Zurigo", FIRST)]
        assert override.apply(TEXT, found) == found


class TestRemove:
    def test_every_occurrence_of_a_requested_value_is_found(self):
        override = Override(remove=(RemovedValue("Zurigo", EntityType.LOCATION),))
        added = override.apply(TEXT, [])
        assert [f.span.start for f in added] == [FIRST, SECOND]
        assert all(f.layer is Layer.HUMAN for f in added)
        assert all(f.detector == "human" for f in added)

    def test_an_unnamed_type_becomes_other_rather_than_a_guess(self):
        added = Override(remove=(RemovedValue("Mario Rossi"),)).apply(TEXT, [])
        assert [f.entity for f in added] == [EntityType.OTHER]

    def test_a_human_removal_displaces_a_detector_claim_on_the_same_text(self):
        """Two edits on one range is what ``plan_edits`` refuses. The human wins."""
        override = Override(remove=(RemovedValue("sede a Zurigo", EntityType.OTHER),))
        result = override.apply(TEXT, [finding("Zurigo", FIRST)])
        assert [(f.text, f.layer) for f in result] == [("sede a Zurigo", Layer.HUMAN)]

    def test_two_requested_values_never_overlap_each_other(self):
        override = Override(
            remove=(RemovedValue("Mario Rossi"), RemovedValue("Rossi")),
        )
        result = override.apply(TEXT, [])
        assert [f.text for f in result] == ["Mario Rossi"]

    def test_a_value_that_is_not_there_is_reported_not_raised(self):
        override = Override(remove=(RemovedValue("Cognome Assente"),))
        assert override.unmatched(TEXT) == ["Cognome Assente"]
        assert override.apply(TEXT, []) == []

    def test_a_value_that_is_there_is_not_reported(self):
        assert Override(remove=(RemovedValue("Zurigo"),)).unmatched(TEXT) == []


class TestKeepBeatsRemove:
    def test_a_kept_span_exempts_an_occurrence_the_caller_also_asked_to_remove(self):
        """The narrower instruction wins, or neither control means what it says."""
        override = Override(
            keep=(KeptSpan(FIRST, FIRST + 6, "Zurigo"),),
            remove=(RemovedValue("Zurigo", EntityType.LOCATION),),
        )
        result = override.apply(TEXT, [])
        assert [f.span.start for f in result] == [SECOND]


class TestPrecedence:
    def test_the_human_outranks_every_detector(self):
        from freedocs.core.findings import LAYER_PRECEDENCE

        assert LAYER_PRECEDENCE[Layer.HUMAN] > max(
            LAYER_PRECEDENCE[layer] for layer in Layer if layer is not Layer.HUMAN
        )


class TestParsing:
    def test_a_span_is_read_from_json_shaped_input(self):
        override = parse_override(
            [{"start": FIRST, "end": FIRST + 6, "text": "Zurigo"}],
            [{"value": "Acme", "entity": "organisation"}],
        )
        assert override.keep == (KeptSpan(FIRST, FIRST + 6, "Zurigo"),)
        assert override.remove == (RemovedValue("Acme", EntityType.ORGANISATION),)

    def test_a_bare_string_is_a_removal_with_no_type(self):
        assert parse_override(None, ["Acme"]).remove == (RemovedValue("Acme"),)

    def test_an_unknown_entity_type_is_an_error_not_a_downgrade(self):
        """Quietly using OTHER would put an unexpected placeholder in the output."""
        with pytest.raises(ValueError, match="unknown entity type"):
            parse_override(None, [{"value": "Acme", "entity": "NOT_A_TYPE"}])

    def test_a_span_missing_its_text_is_an_error(self):
        with pytest.raises(ValueError, match="the 'text' it covers"):
            parse_override([{"start": 0, "end": 6}], None)

    def test_a_removal_missing_its_value_is_an_error(self):
        with pytest.raises(ValueError, match="needs a 'value'"):
            parse_override(None, [{"entity": "PERSON"}])

    def test_nothing_in_gives_an_empty_override(self):
        override = parse_override(None, None)
        assert not override
        assert override.apply(TEXT, []) == []


class TestVerificationAllowance:
    """Stage 6 is value-based and an override is occurrence-based.

    Keeping one ``Zurigo`` and removing the next leaves the string in the
    document, so a search for it finds a survivor. The allowance exists for that,
    and it is a **count**: the value may appear as many times as were kept and no
    more, so a write-back that quietly failed on the other occurrence is still a
    hard failure. That distinction is the whole safety argument for the feature.
    """

    def _verify(self, output: str, removed_value: str, kept: tuple[str, ...]):
        from freedocs.formats.plaintext import PlainTextHandler
        from freedocs.verify import verify_output

        return verify_output(
            PlainTextHandler,
            Path("out.txt"),
            output.encode("utf-8"),
            [finding(removed_value, 0)],
            kept=kept,
        )

    def test_a_kept_occurrence_does_not_read_as_a_leak(self):
        result = self._verify("Sede a Zurigo. Ufficio a [LOCATION_1].", "Zurigo", ("Zurigo",))
        assert result.ok, result.summary()

    def test_one_more_than_was_kept_is_still_a_leak(self):
        """The allowance is a count. A failed write-back must not hide behind it."""
        result = self._verify("Sede a Zurigo. Ufficio a Zurigo.", "Zurigo", ("Zurigo",))
        assert not result.ok
        assert result.leaks[0].occurrences == 2
        assert result.leaks[0].allowed == 1

    def test_with_no_allowance_any_survivor_is_a_leak(self):
        result = self._verify("Sede a Zurigo.", "Zurigo", ())
        assert not result.ok

    def test_the_message_says_the_failure_is_the_excess(self):
        """Otherwise it reads as "the override did not work"."""
        result = self._verify("Zurigo e Zurigo.", "Zurigo", ("Zurigo",))
        described = result.leaks[0].describe()
        assert "kept on purpose" in described
        # And still value-free: this message reaches stderr and the RPC layer.
        assert "Zurigo" not in described


class TestScoping:
    """A batch is one request; a span belongs to one document."""

    def test_a_span_scoped_to_another_file_is_not_applied(self):
        override = Override(keep=(KeptSpan(FIRST, FIRST + 6, "Zurigo", path="/a.txt"),))
        found = [finding("Zurigo", FIRST)]
        # Without scoping this span would be checked against /b.txt and refused as
        # stale, which is the check answering a question nobody asked.
        assert override.for_path("/b.txt").apply(TEXT, found) == found
        assert override.for_path("/a.txt").apply(TEXT, found) == []

    def test_an_unscoped_decision_applies_everywhere(self):
        override = Override(remove=(RemovedValue("Zurigo"),))
        assert len(override.for_path("/anything.txt").remove) == 1

    def test_a_value_can_be_scoped_to_one_file_too(self):
        override = Override(remove=(RemovedValue("Zurigo", path="/a.txt"),))
        assert override.for_path("/b.txt").remove == ()
        assert override.for_path("/a.txt").remove != ()

    def test_a_path_is_read_from_json(self):
        override = parse_override(
            [{"start": 0, "end": 2, "text": "Il", "path": "/a.txt"}],
            [{"value": "Acme", "path": "/a.txt"}],
        )
        assert override.keep[0].path == "/a.txt"
        assert override.remove[0].path == "/a.txt"

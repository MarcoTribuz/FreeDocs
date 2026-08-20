"""Policy decisions and the keyless allocator that makes the scrub irreversible."""

from __future__ import annotations

import pytest

from freedocs.core.findings import EntityType, Finding, Layer, Span
from freedocs.core.policy import Action, Policy, SurrogateAllocator


def finding(entity: EntityType, text: str, confidence: float = 1.0) -> Finding:
    return Finding(
        span=Span(0, len(text)),
        entity=entity,
        text=text,
        layer=Layer.VALIDATOR,
        detector="test",
        confidence=confidence,
    )


def test_same_value_always_gets_the_same_placeholder():
    """Stability within a document: otherwise the text reads as two people."""
    allocator = SurrogateAllocator()
    first = allocator.placeholder_for(EntityType.PERSON, "Mario Rossi")
    second = allocator.placeholder_for(EntityType.PERSON, "Mario Rossi")
    assert first == second == "[PERSONA_1]"


def test_placeholders_ignore_case_and_extra_whitespace():
    allocator = SurrogateAllocator()
    assert allocator.placeholder_for(EntityType.PERSON, "Mario Rossi") == allocator.placeholder_for(
        EntityType.PERSON, "MARIO  ROSSI"
    )


def test_distinct_values_get_distinct_placeholders():
    allocator = SurrogateAllocator()
    assert allocator.placeholder_for(EntityType.PERSON, "Mario Rossi") == "[PERSONA_1]"
    assert allocator.placeholder_for(EntityType.PERSON, "Anna Bianchi") == "[PERSONA_2]"


def test_counters_are_independent_per_entity():
    allocator = SurrogateAllocator()
    assert allocator.placeholder_for(EntityType.PERSON, "Mario") == "[PERSONA_1]"
    assert allocator.placeholder_for(EntityType.IBAN, "CH93...") == "[IBAN_1]"


def test_close_destroys_the_mapping():
    """The whole basis of irreversibility: no key survives the run."""
    allocator = SurrogateAllocator()
    allocator.placeholder_for(EntityType.PERSON, "Mario Rossi")
    assert allocator.distinct_values == 1
    allocator.close()
    assert allocator.distinct_values == 0
    with pytest.raises(RuntimeError, match="closed"):
        allocator.placeholder_for(EntityType.PERSON, "Mario Rossi")


def test_context_manager_closes_on_exit():
    with SurrogateAllocator() as allocator:
        allocator.placeholder_for(EntityType.PERSON, "Mario Rossi")
    assert allocator.distinct_values == 0


def test_low_confidence_findings_are_kept():
    policy = Policy(min_confidence=0.8)
    assert policy.action_for(finding(EntityType.IBAN, "x", confidence=0.5)) is Action.KEEP


def test_quasi_identifiers_are_reported_not_removed():
    """Removing a date silently would hide the residual risk rather than show it."""
    policy = Policy()
    assert policy.action_for(finding(EntityType.DATE, "01.03.2024")) is Action.REPORT
    assert policy.action_for(finding(EntityType.JOB_TITLE, "CFO")) is Action.REPORT


def test_overrides_beat_the_default():
    policy = Policy(overrides={EntityType.URL: Action.KEEP})
    assert policy.action_for(finding(EntityType.URL, "https://x.test")) is Action.KEEP
    assert policy.action_for(finding(EntityType.EMAIL, "a@b.test")) is Action.REDACT

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
    assert first == second == "[PERSON_1]"


def test_placeholders_ignore_case_and_extra_whitespace():
    allocator = SurrogateAllocator()
    assert allocator.placeholder_for(EntityType.PERSON, "Mario Rossi") == allocator.placeholder_for(
        EntityType.PERSON, "MARIO  ROSSI"
    )


def test_distinct_values_get_distinct_placeholders():
    allocator = SurrogateAllocator()
    assert allocator.placeholder_for(EntityType.PERSON, "Mario Rossi") == "[PERSON_1]"
    assert allocator.placeholder_for(EntityType.PERSON, "Anna Bianchi") == "[PERSON_2]"


def test_counters_are_independent_per_entity():
    allocator = SurrogateAllocator()
    assert allocator.placeholder_for(EntityType.PERSON, "Mario") == "[PERSON_1]"
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


# -- placeholder language ------------------------------------------------------


def test_the_default_placeholder_language_is_english():
    """The reader of a scrubbed document is usually a language model.

    English is also the only choice that does not name one audience while the
    tool covers thirteen countries: [CF_1] in a German contract is a label from
    the wrong country, and [PERSONA_1] in an English one reads as a name.
    """
    from freedocs.core.policy import DEFAULT_LOCALE, SurrogateAllocator

    assert DEFAULT_LOCALE == "en"
    with SurrogateAllocator() as allocator:
        assert allocator.placeholder_for(EntityType.PERSON, "Mario Rossi") == "[PERSON_1]"


@pytest.mark.parametrize(
    ("locale", "expected"),
    [("en", "[PERSON_1]"), ("it", "[PERSONA_1]"), ("de", "[PERSON_1]"), ("fr", "[PERSONNE_1]")],
)
def test_each_locale_has_its_own_stems(locale: str, expected: str):
    from freedocs.core.policy import SurrogateAllocator, placeholder_labels

    with SurrogateAllocator(placeholder_labels(locale)) as allocator:
        assert allocator.placeholder_for(EntityType.PERSON, "Mario Rossi") == expected


def test_a_partial_locale_falls_back_to_english():
    """Only what is worth translating is translated.

    The country-issued types are not translated in any locale: one stem stands
    for twelve countries' worth of numbers and every national name for it would
    be wrong on eleven of them.
    """
    from freedocs.core.policy import PLACEHOLDER_LOCALES, placeholder_labels

    for locale in PLACEHOLDER_LOCALES:
        table = placeholder_labels(locale)
        assert set(table) == set(EntityType), f"{locale} leaves a type without a stem"
        assert table[EntityType.TAX_ID] == "TAX_ID"
        assert table[EntityType.EMAIL] == "EMAIL"


def test_an_unknown_locale_is_refused():
    from freedocs.core.policy import placeholder_labels

    with pytest.raises(ValueError, match="unknown placeholder locale"):
        placeholder_labels("zz")


def test_the_locale_reaches_the_allocator_through_the_policy(tmp_path):
    """An option nobody can set from outside is not an option."""
    from freedocs.pipeline import Scrubber, build_registry

    source = tmp_path / "nota.txt"
    source.write_text("Codice fiscale: RSSMRA85T10A562S\n", encoding="utf-8")
    for locale, stem in (("en", "TAX_ID"), ("it", "TAX_ID")):
        scrubber = Scrubber(
            policy=Policy(placeholder_locale=locale),
            registry=build_registry("l1"),
            strict=False,
        )
        result = scrubber.scrub_file(source)
        assert f"[{stem}_1]" in result.output.decode("utf-8")

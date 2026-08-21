"""What was removed, and what the tool is not claiming.

The report deliberately does not contain the original values. Writing them to a
JSON file next to the scrubbed document would undo the whole exercise: it would
be a re-identification key on disk. Findings are reported by type, count and
position, never by content.
"""

from __future__ import annotations

from typing import Any

from .core.policy import Action
from .pipeline import ScrubResult

#: Stated in every report. Users who believe a tool is perfect stop checking, and
#: this one has a known, bounded scope.
#:
#: The measured figures come from ``freedocs benchmark`` over the labelled corpus
#: in ``corpus/``: 378 gold entities across four languages, 342 of them types the
#: policy removes. Quoting a number the tool can reproduce on demand is the point;
#: quoting a number nobody measured is how a caveat becomes marketing.
#:
#: The figure went *down* when the corpus grew from 103 entities to 378, which is
#: the corpus doing its job rather than a regression. Update it from a benchmark
#: run, never by rounding up.
CAVEATS = [
    "Direct identifiers are removed; re-identification from combinations of "
    "remaining details (role, dates, locations) is still possible.",
    "Detection is not exhaustive. On the project's own labelled corpus the full "
    "layer stack covers 97% of the confidential entities it removes, which still "
    "means some are missed, and a real document is harder than a test one.",
    "Place names are the weakest category, especially where a place is also "
    "somebody's surname in the same document.",
    "Review the output before sending it anywhere.",
]


def build_report(result: ScrubResult) -> dict[str, Any]:
    """A JSON-serialisable summary containing no confidential values."""
    by_entity: dict[str, dict[str, int]] = {}
    for decision in result.decisions:
        bucket = by_entity.setdefault(
            decision.finding.entity.value, {"removed": 0, "reported": 0, "kept": 0}
        )
        if decision.action in {Action.REDACT, Action.SURROGATE}:
            bucket["removed"] += 1
        elif decision.action is Action.REPORT:
            bucket["reported"] += 1
        else:
            bucket["kept"] += 1

    return {
        "source": result.source.name,
        "format": result.format_name,
        "source_characters": result.source_chars,
        "entities": dict(sorted(by_entity.items())),
        "totals": {
            "removed": len(result.removed),
            "reported_only": len(result.reported),
        },
        "hidden_content_removed": [
            {"part": item.part, "kind": item.kind, "detail": item.detail}
            for item in result.hidden_removed
        ],
        "warnings": list(result.warnings),
        # The review quotes the *scrubbed* text, so its quotes are not
        # confidential values — they are what survived redaction, which is the
        # whole point of showing them. Absent entirely when no review was asked
        # for, so a reader cannot mistake "not run" for "nothing found".
        "review": _review_section(result),
        "verification": {
            "passed": result.verify.ok,
            "values_checked": result.verify.checked_values,
            "values_too_short_to_check": result.verify.skipped_short,
            "leaks": [
                {
                    "entity": leak.entity,
                    "detector": leak.detector,
                    "occurrences": leak.occurrences,
                }
                for leak in result.verify.leaks
            ],
        },
        "caveats": CAVEATS,
    }


def _review_section(result: ScrubResult) -> dict[str, Any] | None:
    review = result.review
    if review is None:
        return None
    return {
        "model": review.model,
        "ran": review.ran,
        "unavailable": review.unavailable,
        "partial": review.truncated,
        "concerns": [
            {"kind": concern.kind, "quote": concern.quote, "why": concern.why}
            for concern in review.concerns
        ],
    }


def format_console(result: ScrubResult) -> str:
    """Short human summary for the CLI."""
    lines = [f"{result.source.name}  [{result.format_name}]"]
    counts: dict[str, int] = {}
    for finding in result.removed:
        counts[finding.entity.value] = counts.get(finding.entity.value, 0) + 1
    if counts:
        lines.append("  removed:")
        lines.extend(f"    {entity:<22} {count}" for entity, count in sorted(counts.items()))
    else:
        lines.append("  removed: nothing matched")

    if result.reported:
        lines.append(f"  flagged for review: {len(result.reported)}")
    if result.hidden_removed:
        lines.append("  hidden content removed:")
        lines.extend(
            f"    {item.part:<12} {item.kind:<26} {item.detail}" for item in result.hidden_removed
        )

    lines.extend(f"  warning: {message}" for message in result.warnings)
    lines.append(f"  verify: {result.verify.summary()}")

    if result.review is not None:
        lines.append(f"  review: {result.review.summary()}")
        # Printed in full rather than counted: a quasi-identifier is only
        # actionable if you can see which words it is.
        lines.extend(f"    {concern.describe()}" for concern in result.review.concerns)
    return "\n".join(lines)

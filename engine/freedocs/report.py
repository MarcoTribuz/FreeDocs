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
CAVEATS = [
    "Direct identifiers are removed; re-identification from combinations of "
    "remaining details (role, dates, locations) is still possible.",
    "Detection in this build is checksum-based only: structured identifiers are "
    "found reliably, names and addresses are not detected at all.",
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
    return "\n".join(lines)

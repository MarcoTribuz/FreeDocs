"""What was removed, and what the tool is not claiming.

The report deliberately does not contain the original values. Findings are
reported by type, count and position, never by content, and that is unchanged by
the existence of a key file: the two are different artifacts with different
rules. A key file is encrypted, is written only where a caller named a path and a
passphrase, and is the one thing that can undo a scrub. A report is plaintext, is
written wherever ``--report`` points, and must stay safe to attach to a ticket.
Putting the values in it would make every report a re-identification key, so it
notes only *that* a key file exists - never where it is, because a report that
travels should not carry a pointer to the key.

The restore side is reported by the same rule: :func:`build_restore_report`
carries placeholders, entity names and counts. A placeholder is a label the
scrubbed document already published; the value behind it never appears here.
"""

from __future__ import annotations

from typing import Any

from .core.policy import Action
from .pipeline import ScrubResult
from .restore import RestoreResult

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
    "layer stack covers 99.6% of the confidential entities it removes, which "
    "still means some are missed, and a real document is harder than a test one.",
    "Place names are the weakest category, and both remaining misses are the "
    "same case: a place that is also somebody's surname in the same document, "
    "where the name was found and the place was not. No pattern settles that.",
    # Said plainly because it is the one category where a *removal* would be the
    # error. Nationality, religion and political affiliation are GDPR Article 9
    # special categories, and this tool neither removes nor reports them.
    "Nationality, religion and political affiliation are not detected. Asking "
    "the model for them was measured: it returns the adjective in 'Swiss "
    "francs' and 'the German account' rather than a person's nationality, and "
    "asking cost two entities elsewhere. So a document disclosing one keeps it.",
    # Stated because the reader of the output can see these survive and would
    # otherwise read a deliberate decision as a miss - which is the more
    # dangerous of the two misreadings, since it invites patching around a rule
    # that is doing its job.
    "Two kinds of place are kept on purpose: a bare country name, which narrows "
    "a population by tens of millions and identifies nobody, and a city named "
    "in a governing-law, jurisdiction or arbitration clause, where removing it "
    "would change what the sentence means. The same city is still removed "
    "wherever it is somebody's address.",
    "Identifiers are checksum-confirmed for twelve countries: Switzerland, "
    "Italy, Germany, Austria, France, Belgium, Spain, Portugal, the "
    "Netherlands, Poland, Sweden and the United Kingdom. Elsewhere - the "
    "United States included, whose social security and employer numbers carry "
    "no check digit - they are found by the model or not at all.",
    "Review the output before sending it anywhere.",
]

#: Appended only to a report for a run that wrote a key file. Its own constant so
#: the ordinary report is unchanged byte for byte: a caveat about a key file on a
#: run that has none is a sentence that trains the reader to skip caveats.
KEY_FILE_CAVEAT = (
    "A key file was written for this document. It is encrypted, and it is the "
    "one thing that can put the removed values back - so it is as confidential "
    "as the original document, and it must never travel with the scrubbed copy."
)


def build_report(result: ScrubResult, *, key_file: bool = False) -> dict[str, Any]:
    """A JSON-serialisable summary containing no confidential values.

    ``key_file`` says a key file was written for this document. A boolean and not
    a path: this file may be attached to a ticket, and where the key lives is the
    one thing about it worth not writing down here.
    """
    by_entity: dict[str, dict[str, int]] = {}
    # Which countries an entity type turned up for. One type now stands for many
    # countries, so "3 tax numbers removed" no longer tells the reader whether
    # the German ones were seen. Country codes are metadata about the document,
    # not values out of it, so they belong here alongside the counts.
    countries: dict[str, set[str]] = {}
    for decision in result.decisions:
        finding = decision.finding
        bucket = by_entity.setdefault(
            finding.entity.value, {"removed": 0, "reported": 0, "kept": 0}
        )
        if finding.country:
            countries.setdefault(finding.entity.value, set()).add(finding.country)
        if decision.action in {Action.REDACT, Action.SURROGATE}:
            bucket["removed"] += 1
        elif decision.action is Action.REPORT:
            bucket["reported"] += 1
        else:
            bucket["kept"] += 1
    for entity, seen in countries.items():
        by_entity[entity]["countries"] = sorted(seen)  # type: ignore[assignment]

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
        # A fact about the run, so it belongs beside the other run facts rather
        # than only in the prose below.
        "key_file_written": key_file,
        "caveats": [*CAVEATS, KEY_FILE_CAVEAT] if key_file else CAVEATS,
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


#: What a restore does not do, stated in its own report for the reason
#: :data:`CAVEATS` exists: the failures of this direction are quiet too, and the
#: first three are the expectations most likely to be wrong.
RESTORE_CAVEATS = [
    "Restore puts values back. It cannot bring back content that was *removed*: "
    "thumbnails, metadata, custom XML stores, hidden slides and macro projects "
    "were deleted rather than replaced, so there is no placeholder to undo.",
    "One placeholder stood for one value. Where the same value appeared with "
    "different case or spacing, the first spelling seen in the source document is "
    "what comes back.",
    "Placeholders are matched literally. A stem the model translated, a number it "
    "invented or a token it reformatted is reported and left alone - guessing "
    "which value a damaged token meant would write somebody else's data into the "
    "document.",
    "No detector runs, so a confidential value the model introduced on its own is "
    "not found here. Scrub the result again if that is a risk.",
    "Review the output before sending it anywhere.",
]


def build_restore_report(result: RestoreResult) -> dict[str, Any]:
    """A JSON-serialisable summary of one restore, carrying no original values.

    Placeholders and entity names only. A placeholder is a label the scrubbed
    document already published to whoever read it, so printing one discloses
    nothing the recipient did not have; the value behind it is exactly what this
    file must not hold.
    """
    return {
        "source": result.source.name,
        "format": result.format_name,
        "output_characters": result.output_chars,
        "restored": [
            {
                "placeholder": entry.placeholder,
                "entity": entry.entity,
                "occurrences": entry.occurrences,
                # What the scrub replaced. Reported beside the count actually
                # found so a shortfall reads as "the model dropped text" rather
                # than as a restore that half worked.
                "expected": entry.expected,
            }
            for entry in result.restored
        ],
        "totals": {
            "values_restored": len(result.restored),
            "occurrences_restored": sum(entry.occurrences for entry in result.restored),
            "values_not_present": len(result.unused),
            "unknown_placeholders": len(result.unknown),
        },
        "not_present": list(result.unused),
        "unknown_placeholders": list(result.unknown),
        "warnings": list(result.warnings),
        "verification": {
            "passed": result.ok,
            "problems": [
                {
                    "placeholder": problem.placeholder,
                    "entity": problem.entity,
                    "kind": problem.kind,
                }
                for problem in result.problems
            ],
        },
        "caveats": RESTORE_CAVEATS,
    }


def format_restore_console(result: RestoreResult) -> str:
    """Short human summary, shaped like :func:`format_console`.

    Same shape on purpose: the two directions of one tool should not read as two
    tools.
    """
    lines = [f"{result.source.name}  [{result.format_name}]"]
    if result.restored:
        lines.append("  restored:")
        counts: dict[str, int] = {}
        for entry in result.restored:
            counts[entry.entity] = counts.get(entry.entity, 0) + entry.occurrences
        lines.extend(f"    {entity:<22} {count}" for entity, count in sorted(counts.items()))
    else:
        lines.append("  restored: no placeholder from this key file was found")

    # Printed in full rather than counted, both of them: a placeholder is only
    # actionable if you can see which one it is.
    if result.unused:
        lines.append(f"  not in this document: {', '.join(result.unused)}")
    if result.unknown:
        lines.append(
            f"  placeholder-shaped and unknown to this key file: {', '.join(result.unknown)}"
        )

    lines.extend(f"  warning: {message}" for message in result.warnings)
    lines.append(f"  verify: {result.summary()}")
    lines.extend(f"    {problem.describe()}" for problem in result.problems)
    return "\n".join(lines)

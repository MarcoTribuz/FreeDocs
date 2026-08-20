"""Stage 6: prove the scrub actually worked.

Every other stage is a claim; this one is the check. The scrubbed bytes are
re-opened with the same handler, re-flattened — hidden parts included — and
searched for the values that were supposed to be gone. A leak is a hard failure,
not a warning: a file that is *almost* clean is more dangerous than one that
obviously is not, because it gets sent.

This is also why the allocator's mapping is not needed here. Verification works
from the finding text captured during detection, which the caller holds for the
duration of the run and discards with everything else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .core.findings import Finding
from .formats.base import FormatHandler

#: Values shorter than this are not searched for. A two-character original would
#: match somewhere in almost any document and every run would "leak".
MIN_CANARY_LENGTH = 4


@dataclass(frozen=True)
class Leak:
    """A value that was detected as confidential and is still in the output."""

    entity: str
    text: str
    detector: str
    occurrences: int

    def describe(self) -> str:
        return (
            f"{self.entity} value {self.text!r} (found by {self.detector}) still "
            f"appears {self.occurrences}x in the output"
        )


@dataclass(frozen=True)
class VerifyResult:
    leaks: tuple[Leak, ...]
    checked_values: int
    skipped_short: int
    output_chars: int

    @property
    def ok(self) -> bool:
        return not self.leaks

    def summary(self) -> str:
        if self.ok:
            return (
                f"no leak: {self.checked_values} distinct values checked against "
                f"{self.output_chars} characters of output"
            )
        return f"{len(self.leaks)} value(s) survived the scrub"


class LeakDetected(RuntimeError):
    """Raised when verification fails, carrying the offending values."""

    def __init__(self, result: VerifyResult) -> None:
        detail = "\n".join(f"  - {leak.describe()}" for leak in result.leaks)
        super().__init__(f"scrub verification failed:\n{detail}")
        self.result = result


def _distinct_values(findings: Sequence[Finding]) -> dict[tuple[str, str], Finding]:
    """Distinct values to look for, keyed by (entity, casefolded text)."""
    wanted: dict[tuple[str, str], Finding] = {}
    for finding in findings:
        wanted.setdefault((finding.entity.value, finding.text.casefold()), finding)
    return wanted


def verify_output(
    handler_cls: type[FormatHandler],
    output_path: Path,
    output_bytes: bytes,
    removed: Sequence[Finding],
) -> VerifyResult:
    """Re-extract ``output_bytes`` and confirm none of ``removed`` survived.

    ``removed`` must contain only the findings that were actually rewritten.
    Passing report-only findings would guarantee a failure, since those are left
    in the document on purpose.
    """
    handler = handler_cls(output_path, output_bytes)
    # Read the output harder than the input was read. A format that skips work
    # for speed during extraction must not be allowed to skip it here: the
    # question has changed from "what is in this file" to "did anything survive".
    handler.harden_for_verification()
    stream = handler.extract()
    haystack = stream.text.casefold()

    leaks: list[Leak] = []
    checked = 0
    skipped = 0
    for (entity, needle), finding in _distinct_values(removed).items():
        if len(needle) < MIN_CANARY_LENGTH:
            skipped += 1
            continue
        checked += 1
        occurrences = haystack.count(needle)
        if occurrences:
            leaks.append(
                Leak(
                    entity=entity,
                    text=finding.text,
                    detector=finding.detector,
                    occurrences=occurrences,
                )
            )
    return VerifyResult(
        leaks=tuple(leaks),
        checked_values=checked,
        skipped_short=skipped,
        output_chars=len(stream.text),
    )

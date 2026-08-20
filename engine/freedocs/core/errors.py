"""Errors shared across layers.

:class:`MissingDependency` lives here rather than in each module that raises it.
Optional extras mean several modules can raise it, and a caller catching one
module's private copy would let the others through — the CLI would report
"unsupported format" for what is really an uninstalled package.
"""

from __future__ import annotations


class MissingDependency(RuntimeError):
    """An optional dependency a requested feature needs is not installed.

    Raised rather than warned. A silently skipped detector means confidential
    data passes through undetected, which is the one failure mode this tool
    exists to prevent.
    """

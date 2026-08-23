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


class ModelNotFound(RuntimeError):
    """``FREEDOCS_NER_MODEL`` names something that is not a model directory.

    Raised rather than falling back to the pinned repository id. A filesystem
    path handed to ``hf_hub_download`` is resolved as a *repository* id, so a
    typo in a portable build's model path surfaces as a 404 about a repository
    nobody named — and on a machine that does have a network, as a silent 1.2 GB
    download that defeats the point of bundling the weights.
    """

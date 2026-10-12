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


class ModelDownloadFailed(RuntimeError):
    """Fetching the NER weights did not finish.

    Its own type because the window answers it differently from every other
    failure: nothing the user owns was touched, the partial download is kept for
    the next attempt, and the right control is "try again", not "pick another
    file". The message is about the network or the disk, never a document, so it
    carries no value by construction.
    """


class OutputRefused(OSError):
    """An output path is not something this engine will write to.

    Here rather than in ``core/outputs.py`` for that module's own reason: both
    adapters catch it, and a caller catching one module's private copy is how the
    CLI came to report "unsupported format" for an uninstalled package.

    The case it exists for is a symbolic link where an output file belongs, which
    ``write_bytes`` would have followed. Refused rather than followed, and named
    so the caller can say which file rather than printing a traceback.
    """


class InputTooLarge(RuntimeError):
    """A document is larger, or expands larger, than this build will read.

    A refusal rather than a crash, and never a partial read: the alternative to
    naming the limit is exhausting the process, and the engine is single-threaded
    with no cancel, so that is the whole session rather than one file. The
    ceilings themselves live in ``core/limits.py``, which is the only module that
    answers "how big may a thing be".
    """


class MalformedDocument(RuntimeError):
    """A parser refused the file, and the caller is told so in those terms.

    MuPDF and ``zipfile`` both raise their own exceptions on a document built to
    break them - `RuntimeError: code=7: Invalid number of pages`,
    `BadZipFile: Bad CRC-32 for ...` - and those escaped untranslated. From the
    CLI that is a traceback; over the pipe ``rpc.handle`` renders an unexpected
    exception as ``f"{type(exc).__name__}: {exc}"``, so the caller was handed a
    sentence about somebody else's internals. The library being right about the
    file is not the same as the caller being told about it.
    """

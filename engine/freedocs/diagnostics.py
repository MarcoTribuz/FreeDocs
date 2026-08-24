"""One place that answers "why did that not work".

Every fact here is already available somewhere: ``capabilities`` reports the OCR
halves, ``build_registry`` reports a missing NER layer in its notes, and an
absent extra announces itself as a :class:`MissingDependency` at the moment a
file fails. What was missing is a way to ask *before* a file fails, from the
terminal, without reading a JSON response written for the window.

So this module consolidates and never re-decides. ``ocr_unavailable_reason()``
stays the single authority on whether a scan is readable, and the registry stays
the single authority on which layers exist — a second opinion here would be a
second answer that can disagree with the first, which is the bug the OCR
capability already shipped once.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

#: Declared floor in ``pyproject.toml``. CI runs this version and 3.12, so
#: 3.11+ syntax is a build break rather than a style choice.
MINIMUM_PYTHON = (3, 10)


def engine_version() -> str:
    """What this build calls itself. One answer for the terminal and the window.

    There were two mechanisms. The CLI asked ``importlib.metadata`` and fell back
    to ``"unknown"``; the RPC layer read ``__version__``. Those disagree exactly
    where it matters: a PyInstaller one-dir bundle does not reliably carry the
    dist-info, so ``freedocs doctor`` could report ``"unknown"`` while the window
    was told ``"0.1.0"`` by the same executable.

    Installed metadata is still preferred - it is what an editable or a wheel
    install actually resolved to - but the fallback is the packaged constant
    rather than a shrug, so the answer is always a version.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("freedocs")
    except PackageNotFoundError:  # a source tree, or a bundle without dist-info
        from . import __version__

        return __version__


@dataclass(frozen=True)
class Check:
    """One question, its answer, and what to do when the answer is bad.

    ``required`` separates "this build is broken" from "this build cannot do
    everything". Both are worth printing; only the first is worth failing on by
    default, because a machine with no Tesseract is a normal machine and a
    doctor that reports it as an error trains people to ignore the doctor.
    """

    name: str
    ok: bool
    detail: str
    #: What to run, when there is something to run. None when the answer is
    #: "install a system package" or when the check passed.
    fix: str | None = None
    required: bool = True

    @property
    def degraded(self) -> bool:
        return not self.ok and not self.required


def _module_present(module: str) -> bool:
    """Is the module importable without importing it?

    ``find_spec`` rather than ``import``: importing the NER extra pulls in torch,
    which costs seconds and prints warnings, and a health check that is slow and
    noisy gets run once.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _python_check() -> Check:
    current = sys.version_info[:3]
    floor = ".".join(str(part) for part in MINIMUM_PYTHON)
    running = ".".join(str(part) for part in current)
    ok = current[:2] >= MINIMUM_PYTHON
    return Check(
        name="Python",
        ok=ok,
        detail=f"{running} on {platform.system()} {platform.machine()}"
        if ok
        else f"{running}, below the declared floor of {floor}",
        fix=None if ok else f"install Python {floor} or newer",
    )


def _frozen() -> bool:
    """Is this a PyInstaller bundle rather than a checkout?

    Asked because it changes what advice is honest, not what is true. Every fix
    below that names ``uv sync`` is an instruction to a developer standing in
    ``engine/``; inside a packaged app there is no virtualenv to sync, no
    ``pyproject.toml`` to read it from, and the user cannot act on it at all.
    """
    return bool(getattr(sys, "frozen", False))


def _sync_fix(extra: str) -> str | None:
    """``uv sync --extra <extra>``, or None where that would be nonsense.

    None rather than a bundle-specific rewrite. What a user of a packaged build
    should do about a missing extra depends on which build they have — a portable
    zip is re-downloaded, an installer is reinstalled — and the engine does not
    know which one it is inside. A missing fix renders as no advice; an invented
    one renders as advice that fails.
    """
    return None if _frozen() else f"uv sync --extra {extra}"


def _extra_check(name: str, module: str, extra: str, *, purpose: str) -> Check:
    present = _module_present(module)
    return Check(
        name=name,
        ok=present,
        detail=f"{module} available" if present else f"{module} missing, so {purpose}",
        fix=None if present else _sync_fix(extra),
        required=False,
    )


def _weights() -> tuple[bool, str, str | None]:
    """Whether the weights are usable, how to say where they are, and any fix.

    Two shapes, and the difference is worth reporting rather than flattening. An
    installed build downloads on first use, so "not here yet" is normal and
    nothing to report. A build that was handed a directory has weights that can
    be *incomplete* — an unzip that ran out of disk, a stick pulled mid-write —
    and that must surface here rather than as a document failing deep inside
    ``from_pretrained``.

    Sizes only, never hashes and never a load: a doctor that read 1.2 GB, or that
    triggered the download it is reporting on, is a diagnostic nobody runs twice.
    """
    from .core.model_manifest import verify
    from .detect.backends.gliner_backend import DEFAULT_MODEL, MODEL_ENV

    configured = os.environ.get(MODEL_ENV)
    if not configured:
        return True, "weights are fetched to the Hugging Face cache on first use", None

    directory = Path(configured).expanduser()
    problems = verify(directory, repo=DEFAULT_MODEL)
    if not problems:
        return True, f"weights bundled in {directory}", None
    # The first problem only. They cascade from one cause — a truncated copy
    # reports every file after the truncation — and a doctor line that scrolls is
    # a doctor line nobody reads to the end of.
    return (
        False,
        f"the bundled model in {directory} is unusable: {problems[0]}",
        "replace the model directory; this copy is incomplete",
    )


def _ner_check() -> Check:
    """The layer and the weights' *presence* — never the weights themselves.

    Deliberately does not load the model. The 1.2 GB download happens on first
    use and a doctor that triggered it would turn a diagnostic into a long
    surprise; ``freedocs benchmark`` is the command that proves the model works,
    because it proves it by measuring it.
    """
    if not (_module_present("gliner2") and _module_present("torch")):
        return Check(
            name="NER layer",
            ok=False,
            detail="gliner2 or torch missing, so names, organisations, locations, "
            "addresses and job titles are NOT detected",
            fix=_sync_fix("ner"),
            required=False,
        )
    usable, where, fix = _weights()
    return Check(
        name="NER layer",
        ok=usable,
        detail=f"gliner2 and torch available; {where}",
        fix=fix,
        required=False,
    )


def _ocr_check() -> Check:
    from .formats.pdf import ocr_unavailable_reason, tessdata_path, tesseract_binary

    reason = ocr_unavailable_reason()
    if reason is None:
        return Check(
            name="OCR",
            ok=True,
            detail=f"tesseract at {tesseract_binary()}, language data in {tessdata_path()}",
            required=False,
        )
    # The two halves install by different routes, so naming which one is missing
    # is the whole value of the check: pip cannot install the binary and a
    # package manager will not put the .traineddata where a bundle looks.
    fix = (
        # Both routes, because a packaged build has no package manager. The
        # binary cannot be bundled — PyMuPDF shells out to it — so a portable
        # copy's only way to OCR is a binary the user supplies. The override is
        # named first now that the usual install locations are searched: reaching
        # this branch means the binary is either absent or somewhere unusual, and
        # "install it" is the wrong advice for the second case.
        "install Tesseract with your package manager, or point FREEDOCS_TESSERACT"
        " at an existing one"
        if tesseract_binary() is None
        else "point FREEDOCS_TESSDATA at a directory of .traineddata files"
    )
    return Check(
        name="OCR",
        ok=False,
        detail=f"{reason}, so a scanned PDF is refused rather than silently returned",
        fix=fix,
        required=False,
    )


def _review_check(host: str) -> Check:
    from .detect.llm_review import RemoteHostRefused, available_models

    try:
        models = available_models(host)
    except RemoteHostRefused as exc:
        # Refused is loud and absent is quiet, and that distinction belongs here
        # too: a non-loopback host is a decision the caller made, not a machine
        # that happens to be off.
        return Check(name="LLM review", ok=False, detail=str(exc), required=False)
    if models:
        return Check(
            name="LLM review",
            ok=True,
            detail=f"{host} has {len(models)} model(s): {', '.join(sorted(models)[:4])}",
            required=False,
        )
    return Check(
        name="LLM review",
        ok=False,
        detail=f"nothing answered at {host}, so the optional review pass would be skipped",
        fix="start Ollama, or pass --review-host",
        required=False,
    )


def _mapping_check() -> Check:
    """Whether this build can write and read a key file.

    Asked of ``mapping_unavailable_reason()`` rather than answered here, which is
    this module's whole rule: it consolidates and never re-decides. A second
    opinion about the cipher's presence is a second answer that can disagree with
    the one ``capabilities`` published and the one ``--map`` will raise.

    Degraded rather than required, and the detail says why that is the safe
    direction: a build without it scrubs exactly as well and stays irreversible,
    which is the engine's default anyway.
    """
    from .core.mapping import mapping_unavailable_reason

    reason = mapping_unavailable_reason()
    if reason is None:
        return Check(
            name="Key file",
            ok=True,
            detail="cryptography available, so --map and restore can run",
            required=False,
        )
    return Check(
        name="Key file",
        ok=False,
        detail=reason,
        fix=_sync_fix("restore"),
        required=False,
    )


def _layers_check() -> Check:
    """What a scrub would actually run, asked of the registry itself."""
    from .pipeline import default_registry

    registry = default_registry()
    names = [type(detector).__name__ for detector in registry.detectors]
    return Check(
        name="Detection layers",
        ok=bool(names),
        detail=", ".join(names) if names else "no detector could be assembled",
        fix=None if names else "uv sync --extra ner",
    )


def run_checks(review_host: str) -> list[Check]:
    """Every check, in the order a reader wants them: floor first, extras after."""
    return [
        _python_check(),
        _extra_check(
            "PDF support",
            "pymupdf",
            "pdf",
            purpose="PDF files are refused",
        ),
        _extra_check(
            "Office support",
            "lxml",
            "ooxml",
            purpose="docx, xlsx and pptx files are refused",
        ),
        _ner_check(),
        _ocr_check(),
        _mapping_check(),
        _layers_check(),
        _review_check(review_host),
    ]

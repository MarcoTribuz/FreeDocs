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
from collections.abc import Mapping
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


def _engine_check() -> Check:
    """Which engine is answering, and whether it is withholding advice.

    ``ok=True`` and ``required=False`` whichever way it comes out, like
    :func:`_sandbox_check`: a build is not a fault. It is here so an absence
    cannot be read as presence. Every fix below that names a virtualenv
    *disappears* inside a packaged build rather than being rewritten
    (:func:`_sync_fix`), and until this existed that absence looked exactly like a
    check with nothing to suggest.

    **Names no path and no build date, deliberately.** A build date is a property
    of the file that was launched, and only the process that launched it knows
    which file that is: in a checkout the app spawns ``freedocs-rpc`` while
    ``sys.executable`` is the interpreter, so an engine-side modification time
    would be the mtime of Python. The launcher owns the identity of the thing it
    launched and reports it separately - the same split :func:`_sync_fix` already
    makes, one fact over.

    It also must not claim a build is *out of date*. There is no reference point
    to compare against, and acquiring one would mean the network call this tool
    refuses to make. It states which engine answered; the reader draws the
    conclusion.
    """
    version = engine_version()
    if _frozen():
        detail = (
            f"freedocs {version}, packaged - so a fix naming a virtualenv is "
            "omitted below rather than invented"
        )
    else:
        detail = f"freedocs {version}, running from a source tree"
    return Check(name="Engine build", ok=True, detail=detail, required=False)


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


def _weights(*, hashes: bool = False) -> tuple[bool, str, str | None]:
    """Whether the weights are usable, how to say where they are, and any fix.

    Two shapes, and the difference is worth reporting rather than flattening. An
    installed build downloads on first use, so "not here yet" is normal and
    nothing to report. A build that was handed a directory has weights that can
    be *incomplete* — an unzip that ran out of disk, a stick pulled mid-write —
    and that must surface here rather than as a document failing deep inside
    ``from_pretrained``.

    Sizes by default, never a load: a doctor that triggered the download it is
    reporting on is a diagnostic nobody runs twice. ``hashes`` asks the expensive
    question - 0.7 seconds on the real payload - and it is the only one that sees
    bytes changed without the length changing, which is the failure that loads
    perfectly and detects less. Off by default and on when asked, because the
    common case is a person checking whether the build works.
    """
    from .core.model_manifest import verify
    from .detect.backends.gliner_backend import DEFAULT_MODEL, MODEL_ENV, cached_snapshot

    configured = os.environ.get(MODEL_ENV)
    if not configured:
        # Not a failure either way, and said differently because the two states
        # behave differently: a cached copy loads with no network, an absent one
        # is a 1.2 GB download the next time anything asks for the model.
        if cached_snapshot() is not None:
            return True, "weights in the Hugging Face cache, loaded without the network", None
        return True, "weights not downloaded yet; fetched (about 1.2 GB) on first use", None

    directory = Path(configured).expanduser()
    problems = verify(directory, repo=DEFAULT_MODEL, hashes=hashes)
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


def _ner_check(*, hashes: bool = False) -> Check:
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
    usable, where, fix = _weights(hashes=hashes)
    return Check(
        name="NER layer",
        ok=usable,
        detail=f"gliner2 and torch available; {where}",
        fix=fix,
        required=False,
    )


#: The one install line that cannot name the language data, because the package
#: it installs takes no language choice. Languages on Windows are the bundle's
#: job: the spec ships ``engine/models/tessdata`` beside the executable, and
#: ``tessdata_path()`` prefers that copy to the system's. So this line is honest
#: exactly where that copy is present, which every installer built by ``app.yml``
#: is (``packaging/tessdata.py`` runs first). A Windows installer also carries
#: the binary, so this line is for a checkout or a portable copy.
_WINGET_COMMAND = "winget install --exact --id UB-Mannheim.TesseractOCR"

#: Commands exempt from naming the language data, each with the reason above.
_LANGUAGES_FROM_THE_BUNDLE = frozenset({_WINGET_COMMAND})


def _winget(environ: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Where winget is, as a ``_PACKAGE_MANAGERS`` entry, or nothing.

    winget is an App Installer alias inside the user's own profile, so it can
    only be located from ``LOCALAPPDATA`` - there is no fixed path to list the
    way ``/opt/homebrew/bin/brew`` is listed.
    """
    local = environ.get("LOCALAPPDATA")
    if not local:
        return ()
    return ((os.path.join(local, "Microsoft", "WindowsApps", "winget.exe"), _WINGET_COMMAND),)


#: Where each platform's package manager lives, and the one line that installs
#: Tesseract with it.
#:
#: Absolute paths, for exactly the reason ``_SYSTEM_BINARIES`` in ``formats/pdf``
#: holds absolute paths: a macOS ``.app`` opened from Finder inherits launchd's
#: environment, so ``PATH`` is ``/usr/bin:/bin:/usr/sbin:/sbin`` and
#: ``shutil.which("brew")`` fails on a machine that has Homebrew. Detecting the
#: manager is the whole point - naming apt on a Fedora machine is advice that
#: fails, which is what :func:`_sync_fix` returns None to avoid.
#:
#: **Every command names the language data**, and that is not tidiness.
#: ``brew install tesseract`` ships ``eng`` and ``osd`` only, while
#: ``DEFAULT_OCR_LANGUAGE`` asks for nine - and ``tessdata_path()`` counts a
#: directory that holds *any* ``.traineddata``, so an English-only install makes
#: ``ocr_available`` true and an Italian scan then reads badly. A value OCR
#: misreads fails its checksum, is never detected, and survives. Shortening one of
#: these lines is a quiet leak, not a shorter line.
_PACKAGE_MANAGERS: tuple[tuple[str, str], ...] = (
    ("/opt/homebrew/bin/brew", "brew install tesseract tesseract-lang"),
    ("/usr/local/bin/brew", "brew install tesseract tesseract-lang"),
    ("/opt/local/bin/port", "sudo port install tesseract tesseract-ita tesseract-deu"),
    (
        "/usr/bin/apt",
        "sudo apt install tesseract-ocr tesseract-ocr-ita tesseract-ocr-deu"
        " tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-nld tesseract-ocr-por"
        " tesseract-ocr-pol tesseract-ocr-swe",
    ),
    (
        "/usr/bin/dnf",
        "sudo dnf install tesseract tesseract-langpack-ita tesseract-langpack-deu"
        " tesseract-langpack-fra tesseract-langpack-spa tesseract-langpack-nld"
        " tesseract-langpack-por tesseract-langpack-pol tesseract-langpack-swe",
    ),
    ("/usr/bin/pacman", "sudo pacman -S tesseract tesseract-data-ita tesseract-data-deu"),
    # Windows: see `_winget`. The one entry that installs the binary only.
    *_winget(os.environ),
)


def _present(path: Path) -> bool:
    """Is a package manager installed here, asked so Windows can answer.

    ``winget.exe`` is an App Execution Alias - a reparse point that ``stat``
    cannot always follow - so ``is_file()`` may be false for a winget that runs.
    ``lexists`` asks whether the entry is there without following it. Kept to
    Windows because on POSIX a dangling Homebrew symlink is exactly the leftover
    whose command would fail.
    """
    if path.is_file():
        return True
    return os.name == "nt" and os.path.lexists(path)


def _install_command() -> str | None:
    """The one line that installs Tesseract on *this* machine, or None.

    Detected, never guessed, for the reason :func:`_sync_fix` exists - advice the
    engine cannot know is right is worse than no advice.

    But note where the two differ, because it is the whole justification for this
    not being suppressed in a frozen build. ``_sync_fix`` returns None when frozen
    because what a packaged user should do about a missing *extra* depends on
    which build shape they have, and the engine cannot see that. A *platform* it
    can see - :func:`_python_check` already prints it - and a system package
    installs the same way whatever build asked for it. So this is honest exactly
    where ``uv sync`` is not.

    The engine runs one of these lines in exactly one case, Homebrew, and only
    when a person asks: see :func:`install_plan` and :func:`run_install`.
    """
    plan = install_plan()
    return plan.command if plan else None


#: Package managers that install without elevation, and therefore the only ones
#: the engine will run - see M17 in ``docs/security-review.md``. Homebrew installs
#: as the user into a prefix the user owns. MacPorts, apt, dnf and pacman need
#: ``sudo``, and winget installs the UB Mannheim package machine-wide behind a UAC
#: prompt: teaching people to elevate for a document anonymiser is a net negative
#: even when it works, and Windows installers carry Tesseract anyway.
_UNATTENDED = frozenset({"/opt/homebrew/bin/brew", "/usr/local/bin/brew"})


@dataclass(frozen=True)
class InstallPlan:
    """How Tesseract gets onto this machine: a line to show, and maybe one to run.

    ``argv`` is None where the engine will not run the command itself, and it is
    built here from the table and nothing else: a caller can ask for the install,
    never choose what is executed.
    """

    command: str
    argv: tuple[str, ...] | None


def install_plan() -> InstallPlan | None:
    """The install for the package manager this machine has, or None.

    For Homebrew the language data is asked for only when the directory OCR would
    use lacks some of the nine: every installer now carries them in its sidecar,
    and ``tesseract-lang`` is over a gigabyte of languages nobody asked for. The
    shown line and the run line are the same words, so what the window displays
    is exactly what executes.
    """
    from .formats.pdf import missing_languages

    for manager, command in _PACKAGE_MANAGERS:
        if not _present(Path(manager)):
            continue
        if manager not in _UNATTENDED:
            return InstallPlan(command, None)
        packages = ("tesseract", "tesseract-lang") if missing_languages() else ("tesseract",)
        argv = (manager, "install", *packages)
        return InstallPlan(" ".join(("brew", *argv[1:])), argv)
    return None


#: Under the ten minutes the shell waits for any answer (`REQUEST_TIMEOUT` in
#: ``engine.rs``), so a stuck install ends as this engine's reported failure and
#: not as the window's timeout with the process still running behind it.
INSTALL_TIMEOUT_SECONDS = 540

#: How much of the installer's output a failure carries. The end is where both
#: Homebrew and a network error say what went wrong.
_FAILURE_TAIL_LINES = 12


def run_install(plan: InstallPlan) -> str | None:
    """Run ``plan.argv``; None on success, else the end of what it printed.

    A separate process, so ``core/egress.py`` neither blocks nor sees it - which is
    the reason this is reachable only from a person's explicit request and only
    for :data:`_UNATTENDED`. ``NONINTERACTIVE`` keeps Homebrew from waiting on a
    prompt nobody can see; nothing else in the environment changes.

    The failure text is the installer's own English, quoted by the window and
    never written to a report: it can name paths under the user's home, which is
    fine down the local pipe and nowhere else.
    """
    import subprocess

    if plan.argv is None:
        raise ValueError("this install is shown, never run")
    # No `FREEDOCS_*` variable reaches the installer. M10 was a passphrase
    # inherited by every process the engine spawned; the CLI pops its own, but a
    # sidecar launched with one set would hand it to Homebrew - and every script
    # Homebrew runs - which has no business holding it.
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("FREEDOCS_")
    }
    environment.update(NONINTERACTIVE="1", HOMEBREW_NO_ENV_HINTS="1")
    try:
        result = subprocess.run(
            plan.argv,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"{plan.command} did not finish within {INSTALL_TIMEOUT_SECONDS} seconds"
    except OSError as exc:
        return f"{plan.command} could not be started: {exc.strerror or exc}"
    if result.returncode == 0:
        return None
    output = (result.stderr or result.stdout or "").strip().splitlines()
    tail = "\n".join(output[-_FAILURE_TAIL_LINES:])
    return f"{plan.command} exited with status {result.returncode}" + (f":\n{tail}" if tail else "")


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
    if tesseract_binary() is None:
        # The command for the manager this machine actually has, when it has one.
        # Falling back to the generic sentence rather than naming a manager that
        # is not installed: both routes are still named there, because outside
        # the Windows installers the binary is not bundled - PyMuPDF shells out to
        # a platform package - so a portable copy's only way to OCR is a binary
        # the user supplies. The override is named first
        # now that the usual install locations are searched: reaching this branch
        # means the binary is either absent or somewhere unusual, and "install it"
        # is the wrong advice for the second case.
        fix = _install_command() or (
            "install Tesseract with your package manager, or point FREEDOCS_TESSERACT"
            " at an existing one"
        )
    else:
        fix = "point FREEDOCS_TESSDATA at a directory of .traineddata files"
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
    """What a scrub would actually run, asked of the registry itself.

    The fix goes through :func:`_sync_fix` like every other one. It used to be a
    literal ``"uv sync --extra ner"``, which is the one advice in this module a
    packaged user cannot act on: there is no virtualenv in a bundle to sync and no
    ``pyproject.toml`` to read the extra from. Being the only check that skipped
    the helper is exactly how it stayed wrong while the module around it was
    fixed.
    """
    from .pipeline import default_registry

    registry = default_registry()
    names = [type(detector).__name__ for detector in registry.detectors]
    return Check(
        name="Detection layers",
        ok=bool(names),
        detail=", ".join(names) if names else "no detector could be assembled",
        fix=None if names else _sync_fix("ner"),
    )


def _sandbox_check() -> Check:
    """What this process gives up, and what it does not.

    ``required=False`` and ``ok=True`` whichever way it comes out, because none
    of it is a fault: a build with no filesystem confinement is every build
    there has ever been, and reporting that as an error would train people to
    ignore the doctor - the reasoning `Check` itself carries about Tesseract.

    It is here at all so the absence cannot be read as presence. "Nothing leaves
    the machine" is the first line of the threat model, and a reader deserves to
    see which half of that is a property of the code and which half the process
    now refuses to do.
    """
    from .core.sandbox import describe

    return Check(name="Process hardening", ok=True, detail=describe(), required=False)


def run_checks(review_host: str, *, hashes: bool = False) -> list[Check]:
    """Every check, in the order a reader wants them: identity, floor, extras.

    ``hashes`` is threaded through rather than decided here: only the weights
    check has an expensive question to ask, and whether to pay for it belongs to
    whoever ran the doctor.
    """
    return [
        # Identity first: a reader wants to know which engine answered before
        # reading its answers, and a stale sidecar is not a failing check - it is
        # the wrong engine answering correctly.
        _engine_check(),
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
        _ner_check(hashes=hashes),
        _ocr_check(),
        _mapping_check(),
        _layers_check(),
        _review_check(review_host),
        _sandbox_check(),
    ]

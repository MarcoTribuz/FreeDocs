"""The contract between the desktop app and the engine.

Newline-delimited JSON over stdin and stdout. One object per line, requests
carrying an ``id``, responses echoing it, and progress arriving as notifications
with no ``id`` at all. That shape was chosen because a Tauri sidecar hands back
stdout line by line, so the transport needs no framing of its own and the whole
protocol can be exercised from a shell.

**This is a pipe, not a service.** It reads and writes files named by whoever is
on the other end, so it must only ever be spawned as a child process by the app
that already has the user's permission to open those files. It must never be
bound to a socket.

**The channel carries confidential values, and the disk must not.** A useful
preview has to show the user which of their own text is about to be removed, so
``inspect`` returns the matched text. That is fine down a local pipe to an app
the user is looking at; it is not fine in a log file. Anything written to disk —
the JSON report in particular — carries counts and positions only.

The same rule, one step further out: with ``include_text`` the whole extracted
document comes down this channel, which is a superset of the matched values — it
contains the confidential text *no layer detected*. It is opt-in for that reason,
so a caller that renders no preview never receives a document, and it must never
reach a report, a warning or an error's ``data`` block.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TextIO

from .core.egress import block_external, blocked, unblock
from .core.errors import (
    InputTooLarge,
    MalformedDocument,
    MissingDependency,
    ModelDownloadFailed,
    ModelNotFound,
    OutputRefused,
)
from .core.findings import EntityType
from .core.limits import MAX_TERM_CHARS, MAX_TERMS, MAX_TEXT_CHARS
from .core.mapping import (
    MIN_PASSPHRASE,
    BadPassphrase,
    MalformedMap,
    key_map_from,
    map_path_for,
    mapping_unavailable_reason,
    read_key_map,
    refuse_inside,
    write_key_map,
)
from .core.outputs import private_directory, write_output, write_private
from .core.overrides import Override, StaleOverride, parse_override
from .core.policy import (
    DEFAULT_LOCALE,
    PLACEHOLDER_LOCALES,
    REPORT_ONLY,
    Action,
    Policy,
    SurrogateAllocator,
    placeholder_labels,
)
from .core.sandbox import describe as describe_sandbox
from .core.sandbox import harden
from .core.terms import (
    MIN_TERM_CHARS,
    TermList,
    TermListError,
    create_terms,
    open_terms,
    parse_terms,
    read_import,
    rekey_terms,
    save_terms,
    terms_unavailable_reason,
    with_terms,
    write_export,
)
from .detect.llm_review import (
    DEFAULT_HOST as REVIEW_HOST,
)
from .detect.llm_review import (
    MAX_REVIEW_CHARS,
    LlmReviewer,
    RemoteHostRefused,
    available_models,
)
from .detect.validators import SUPPORTED_COUNTRIES
from .diagnostics import _module_present, engine_version, run_checks
from .formats.base import FormatHandler
from .formats.pdf import (
    ScannedPdfNotSupported,
    adopt_tesseract,
    ocr_unavailable_reason,
    tesseract_binary,
)
from .formats.router import UnsupportedFormat
from .pipeline import (
    LAYER_SPEC_NOTES,
    LAYER_SPECS,
    Extraction,
    Scrubber,
    build_registry,
    country_coverage,
    default_registry,
)
from .report import (
    CAVEATS,
    RESTORE_CAVEATS,
    build_report,
    build_restore_report,
    suppressed_section,
)
from .restore import Restorer
from .text_mode import PASTED_NAME, TextMaps, UnknownHandle, decoded, handler_for_text
from .verify import LeakDetected

#: Application error codes. Distinct from JSON-RPC's own range so the app can
#: tell "you asked wrongly" from "this file cannot be processed", and render the
#: second as an explanation rather than a bug.
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
UNSUPPORTED_FORMAT = 1
NEEDS_OCR = 2
LEAK_DETECTED = 3
MISSING_DEPENDENCY = 4
#: A restore that wrote its file and did not finish. Deliberately the same number
#: as ``cli.EXIT_INCOMPLETE``, as 3 and 4 already match their exit codes, so one
#: failure has one number whichever front end reported it. Unlike LEAK_DETECTED
#: the output *was* written - see ``Restorer.restore``.
INCOMPLETE_RESTORE = 5
#: An output path this engine will not write to - a symbolic link where a file
#: belongs. Its own code rather than INVALID_REQUEST because the request was
#: well-formed and the filesystem was not, and rather than a silent follow
#: because following it writes the caller's document somewhere nobody chose.
OUTPUT_REFUSED = 6
#: The document is larger, or expands larger, than this build reads. Distinct
#: from UNSUPPORTED_FORMAT because the format is supported and the caller's move
#: is different: split the document, not install something.
INPUT_TOO_LARGE = 7
#: A parser refused the file. Also distinct from UNSUPPORTED_FORMAT, which would
#: read as "this build cannot open PDFs" about a PDF that is simply broken.
MALFORMED_DOCUMENT = 8
#: Fetching the model weights did not finish. Its own code because nothing the
#: user owns was involved and the move is "try again", which the window offers
#: on this code and no other.
MODEL_DOWNLOAD_FAILED = 9

#: How much flat text ``inspect`` will put on the wire when asked for a preview.
#:
#: Chosen rather than measured, unlike ``MAX_CHUNK_CHARS``: it covers a 250-page
#: PDF and a large spreadsheet whole, and past it the window is holding more text
#: than a person will scroll. Truncation is stated in the response — never
#: silent — and the finding list is never truncated with it, because a finding
#: hidden to make the numbers agree is the one failure this feature must not
#: introduce.
MAX_PREVIEW_CHARS = 500_000

#: How many extractions one session keeps.
#:
#: Four, so moving between the files of a small batch still hits, and no more: an
#: extraction holds the whole flat text and every anchor. The point is the
#: expensive half — every kept occurrence re-runs detection, and without this it
#: also re-OCRs every page of a scan for a file that has not changed.
MAX_CACHED_EXTRACTIONS = 4


class RpcError(Exception):
    """An error to report to the caller rather than a crash to propagate."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass
class Session:
    """One engine process, serving one app.

    Holds the detector registry so a model loaded for the first file is still
    loaded for the second. That is the whole reason the app talks to a long-lived
    process instead of shelling out per file: GLiNER2 takes seconds to load and
    milliseconds to run.
    """

    out: TextIO
    _registry: object | None = None
    _registry_spec: str | None = None
    #: Extractions kept for reuse, keyed on the file's identity *and* its
    #: modification time and size. Serving a cached extraction for a file that
    #: has changed would show a preview of a document that no longer exists.
    _extractions: dict[tuple[str, int, int], Extraction] = field(default_factory=dict)
    #: The id of the request being served, so a stage notification can say which
    #: one it belongs to. A caller with two requests in flight would otherwise
    #: have to guess, and the answer would be wrong exactly when it mattered.
    current: Any = None
    #: The one unlocked term list, and where it lives. Held for the life of the
    #: unlock rather than per request, as the model weights are: a passphrase
    #: asked on every document is how passphrases become "12345678". Released by
    #: ``terms_lock``, by ``forget`` with ``terms``, and by the process ending.
    _terms: TermList | None = None
    _terms_path: Path | None = None
    #: Mappings held for pasted text, under opaque handles, and only when the
    #: scrub asked. The one place this process keeps a re-identification key past
    #: the request that made it - bounded and released; see ``text_mode``.
    _text_maps: TextMaps = field(default_factory=TextMaps)

    # -- transport -------------------------------------------------------------

    def emit(self, payload: dict[str, Any]) -> None:
        json.dump(payload, self.out, ensure_ascii=False)
        self.out.write("\n")
        # Flushed per line: the app is reading incrementally and a buffered
        # progress notification is a progress bar that jumps at the end.
        self.out.flush()

    def notify(self, method: str, **params: Any) -> None:
        self.emit({"jsonrpc": "2.0", "method": method, "params": params})

    def stage_reporter(self, file: str) -> Callable[[Any], None]:
        """Turn the pipeline's stage events into notifications.

        The pipeline knows the stages and their order; this knows the wire. Note
        what is *not* forwarded: there is no percentage, because the engine cannot
        know one, and `done`/`of` are omitted rather than zeroed when a stage has
        no unit to count. A test forbids a `percent` key in any notification.
        """

        def report(event: Any) -> None:
            params: dict[str, Any] = {
                "id": self.current,
                "file": file,
                "stage": event.stage,
                "index": event.index,
                "count": event.count,
            }
            if event.done is not None:
                params["done"] = event.done
            if event.of is not None:
                params["of"] = event.of
            if event.detail:
                params["detail"] = event.detail
            self.notify("stage", **params)

        return report

    # -- state -----------------------------------------------------------------

    def registry(self, spec: str | None, countries: tuple[str, ...] | None = None) -> object:
        """One registry per configuration, kept for the life of the session.

        The key has to be the whole configuration, not just the spec string.
        Loading GLiNER2 takes seconds and running it takes milliseconds, so the
        cache is what makes one long-lived process worth having — but a key that
        ignored `countries` would answer the second request of a session with the
        first request's country selection and never say so.
        """
        key = (spec, countries)
        if self._registry is None or self._registry_spec != key:
            self._registry = (
                build_registry(spec, countries=countries) if spec else default_registry(countries)
            )
            self._registry_spec = key
        return self._registry

    def extraction(self, scrubber: Scrubber, path: Path) -> Extraction:
        """Read the file, or hand back the reading already taken.

        Every kept occurrence and every added value re-runs `inspect`, because
        propagation means one decision can change other findings and the caller
        is not allowed to guess the new answer. Extraction is the half of that
        which cannot change: for a scanned PDF it is seconds of OCR per click.

        A file whose size or modification time moved is a different file and is
        read again. That is the whole safety condition, and it is why the key is
        not just the path.
        """
        try:
            stat = path.stat()
            key: tuple[str, int, int] | None = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            # Unreadable stat is not a reason to refuse: the handler is about to
            # open the file and will say something better than we could. It is a
            # reason not to cache, since there is nothing to invalidate against.
            key = None

        if key is not None:
            cached = self._extractions.get(key)
            if cached is not None:
                return cached

        extraction = _read(scrubber, path)

        if key is not None:
            if len(self._extractions) >= MAX_CACHED_EXTRACTIONS:
                # Oldest first: dicts preserve insertion order, and the file being
                # reviewed right now is the one most recently inserted.
                self._extractions.pop(next(iter(self._extractions)))
            self._extractions[key] = extraction
        return extraction

    def forget(self, params: dict[str, Any]) -> dict[str, Any]:
        """Release cached readings, named or all of them.

        The cache holds the one thing this process keeps that is worse than a
        finding: ``Extraction.stream.text`` is a *superset* of what was detected,
        because it contains the confidential text no layer found. That is the
        whole reason ``include_text`` is opt-in and the whole reason the text
        must never reach a report.

        Keeping it is worth paying for while a document is being reviewed - every
        excused occurrence re-inspects, and without the cache that re-OCRs a scan
        - and worth nothing once it is not. Until this existed the only way to
        release it was to end the session, and ending the session costs a GLiNER2
        reload.

        A control, not a rule. Nothing here decides when a caller is finished
        with a document; it decides what happens when they say so. And forgetting
        something never read is not an error, because the caller that will use
        this calls it on every exit path, including the ones where nothing was
        ever inspected.
        """
        # The term list only when named. The window calls this with no
        # arguments every time it drops its documents - clearing a batch,
        # changing mode - and locking the list there too would ask for the
        # passphrase after every batch, which is the habit that makes weak ones.
        terms_locked = bool(params.get("terms")) and self._lock_terms()

        # Held text mappings only when named, like the list: `"all"` or a list
        # of handles. A request naming only these leaves the file cache alone -
        # dropping a paste is not dropping the documents on another screen.
        maps_released = 0
        if "text_maps" in params:
            try:
                maps_released = self._text_maps.release(params["text_maps"])
            except TypeError as exc:
                raise RpcError(INVALID_REQUEST, str(exc)) from exc
            if "paths" not in params:
                return {
                    "released": 0,
                    "terms_locked": terms_locked,
                    "text_maps_released": maps_released,
                }

        wanted = params.get("paths")
        if wanted is None:
            released = len(self._extractions)
            self._extractions.clear()
            return {
                "released": released,
                "terms_locked": terms_locked,
                "text_maps_released": maps_released,
            }

        names = {str(_as_path(value)) for value in wanted}
        keys = [key for key in self._extractions if key[0] in names]
        for key in keys:
            del self._extractions[key]
        return {
            "released": len(keys),
            "terms_locked": terms_locked,
            "text_maps_released": maps_released,
        }

    # -- the term list -----------------------------------------------------------
    #
    # Values travel this pipe in both directions, which is the channel that
    # already carries every matched value and, on request, the whole document.
    # What must not happen is a term or a passphrase inside an *error*: every
    # failure below comes from `core/terms.py` or `core/sealed.py`, which quote
    # line numbers and counts, and `_terms_errors` forwards those and nothing
    # composed near a value.

    def _lock_terms(self) -> bool:
        was = self._terms is not None
        self._terms = None
        self._terms_path = None
        return was

    def _unlocked(self) -> tuple[TermList, Path]:
        if self._terms is None or self._terms_path is None:
            raise RpcError(INVALID_REQUEST, "the term list is locked; unlock it first")
        return self._terms, self._terms_path

    def _hold(self, path: Path, terms: TermList) -> dict[str, Any]:
        self._terms, self._terms_path = terms, path
        return {"path": str(path), "count": len(terms)}

    def terms_create(self, params: dict[str, Any]) -> dict[str, Any]:
        """A new, empty list, unlocked. Refused over anything that exists."""
        path = _require_path(params, "path", must_exist=False)
        passphrase = _passphrase(params, "passphrase")
        with _terms_errors():
            return self._hold(path, create_terms(path, passphrase))

    def terms_unlock(self, params: dict[str, Any]) -> dict[str, Any]:
        """Decrypt a list into this session. Answers with its size, not its terms."""
        path = _require_path(params, "path")
        passphrase = _passphrase(params, "passphrase")
        with _terms_errors():
            return self._hold(path, open_terms(path, passphrase))

    def terms_lock(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"locked": True, "was_unlocked": self._lock_terms()}

    def terms_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """The unlocked list, or the entries matching ``query``."""
        terms, path = self._unlocked()
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise RpcError(INVALID_REQUEST, "'query' must be a string")
        shown = terms.search(query)
        return {
            "path": str(path),
            "count": len(terms),
            "terms": [{"value": term.value, "entity": term.entity.value} for term in shown],
        }

    def terms_update(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add and remove entries and save, in one request.

        One request so there is no unsaved state anywhere: the window never holds
        an edit the engine has not written, and a crash loses nothing that was
        acknowledged.

        **The list is re-read from disk with the passphrase given, not edited in
        memory.** That is the check that the passphrase is the list's own - a save
        under a mistyped one would re-key the client register to a passphrase
        nobody knows, and succeed - and it also means a second window that saved
        in between is merged into rather than overwritten.
        """
        _, path = self._unlocked()
        passphrase = _passphrase(params, "passphrase")
        with _terms_errors():
            add = parse_terms(_list_param(params, "add"))
            remove = [str(value) for value in _list_param(params, "remove")]
            current = open_terms(path, passphrase)
            current, removed = current.without(remove)
            current, added = current.with_added(add)
            save_terms(path, current, passphrase)
        return {**self._hold(path, current), "added": added, "removed": removed}

    def terms_import(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a plaintext or CSV list into the unlocked one, and save.

        The source is never deleted, and the response says it should be. Both
        halves are deliberate: a plaintext copy beside the encrypted list is the
        encryption defeated, and deleting a person's file is not this tool's
        call. ``delete_source`` is a flag so the window can say it in the
        reader's language; ``notice`` is the English sentence for everyone else.
        """
        _, path = self._unlocked()
        source = _require_path(params, "source")
        passphrase = _passphrase(params, "passphrase")
        with _terms_errors():
            incoming = read_import(source)
            current = open_terms(path, passphrase)
            current, added = current.with_added(incoming)
            save_terms(path, current, passphrase)
        return {
            **self._hold(path, current),
            "added": added,
            "skipped": len(incoming) - added,
            "delete_source": True,
            "notice": (
                f"{source.name} is not encrypted and still holds every entry; "
                "delete it now that the term list has them"
            ),
        }

    def terms_export(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write the unlocked list out in plaintext, owner only.

        The window confirms before it asks, and the response repeats the
        warning, because this is the one way the list leaves its encryption and
        the person should hear it at both ends.
        """
        terms, path = self._unlocked()
        output = _require_path(params, "output", must_exist=False)
        with _terms_errors():
            write_export(output, terms, refuse=[path])
        return {
            "output": str(output),
            "count": len(terms),
            "warning": (
                f"{output.name} is not encrypted; anyone who can read it can read "
                "every entry, so delete it when you are done with it"
            ),
        }

    def terms_rekey(self, params: dict[str, Any]) -> dict[str, Any]:
        """Change the unlocked list's passphrase. The old one must open it."""
        _, path = self._unlocked()
        old = _passphrase(params, "old")
        new = _passphrase(params, "new")
        with _terms_errors():
            return self._hold(path, rekey_terms(path, old, new))

    def _override_from(self, params: dict[str, Any]) -> Override:
        """The caller's decisions, plus the term list when ``use_terms`` asks.

        A locked list is a refusal, never a quiet skip. A scrub that ignored it
        would produce a document the person believes had the firm's names taken
        out, and the only sign otherwise would be those names in it.
        """
        override = _override_from(params)
        if not params.get("use_terms"):
            return override
        if self._terms is None:
            raise RpcError(
                INVALID_REQUEST,
                "use_terms was asked for and the term list is locked; unlock it, "
                "or scrub without it",
            )
        return with_terms(override, self._terms)

    # -- methods ---------------------------------------------------------------

    def capabilities(self) -> dict[str, Any]:
        """What this build can actually do.

        The app asks first and shows the answer, so a missing optional dependency
        becomes a visible limitation instead of a file that mysteriously fails.
        """
        registry = self.registry(None)
        return {
            "version": engine_version(),
            "formats": sorted(_supported_extensions()),
            "detector_specs": list(LAYER_SPECS),
            # Sent rather than duplicated in the window, for the same reason as
            # review_host: which countries this build covers is the engine's
            # answer, and two lists would be two answers that can disagree.
            "countries": list(SUPPORTED_COUNTRIES),
            # Which languages the placeholder stems come in, and which one is
            # used when nobody chooses. Sent, not hardcoded in the window: the
            # wording of a placeholder is a judgement and the app holds none.
            "placeholder_languages": list(PLACEHOLDER_LOCALES),
            "placeholder_language": DEFAULT_LOCALE,
            "layers": [type(detector).__name__ for detector in registry.detectors],
            "limitations": list(registry.notes),
            # Both halves, not just the language data. PyMuPDF shells out to
            # the Tesseract executable, and a packaged build ships the
            # `.traineddata` files but not the binary — so checking only the
            # data made this true everywhere and the window promised an OCR the
            # first scan could not deliver.
            "ocr_available": ocr_unavailable_reason() is None,
            "ocr_unavailable_reason": ocr_unavailable_reason(),
            # Whether this build can write and read a key file. Published for the
            # same reason as the OCR pair and answered by the same kind of single
            # authority: a window that offered the control and then failed on the
            # first attempt is the bug `ocr_unavailable_reason()` exists to
            # prevent, one feature over.
            "mapping_available": mapping_unavailable_reason() is None,
            "mapping_unavailable_reason": mapping_unavailable_reason(),
            # The passphrase floor, published for the same reason as the two
            # `max_characters` above: the window needs it to disable a button
            # before the request, and a copy of it in the window is a rule the
            # window is holding. It had one - raising the floor here left the
            # window still accepting eight characters, the engine refusing inside
            # the `scrub` request, and the failure landing after the scrubbed
            # copies were written.
            "passphrase_min_characters": MIN_PASSPHRASE,
            # The term list is sealed with the key file's cipher, so this is the
            # same answer under its own name: a window should not have to know
            # the two features share an extra to offer the right controls.
            "terms_available": terms_unavailable_reason() is None,
            "terms_unavailable_reason": terms_unavailable_reason(),
            "terms_max_entries": MAX_TERMS,
            "term_min_characters": MIN_TERM_CHARS,
            "term_max_characters": MAX_TERM_CHARS,
            # The longest paste `inspect_text` and `scrub_text` accept, so the
            # window can say so before sending two million characters down the
            # pipe to be refused.
            "text_max_characters": MAX_TEXT_CHARS,
            # Whether this process will refuse an outbound connection that is not
            # to this machine, and one sentence saying what else it gives up.
            # Published because "nothing leaves the machine" is the claim the
            # whole tool rests on, and a window that repeats it should be
            # repeating something it asked rather than something it assumes.
            "network_blocked": blocked(),
            "hardening": describe_sandbox(),
            # Whether the model travels with this build or is fetched on first
            # use. Sent because the window cannot work it out: it is a property
            # of how the app was packaged, and a portable copy that says
            # "downloading" once would be a portable copy nobody trusts offline
            # again. An enum, so the window translates it rather than quoting it.
            "model_source": _model_source_kind(),
            # Offered so the app can present a real choice instead of a free-text
            # box that 404s. Empty when Ollama is not running, which is the
            # honest answer to "what can I review with".
            "review_models": available_models(),
            # The default the app should prefill, sent rather than hardcoded there:
            # where Ollama lives is a judgement, and the app holds no judgements.
            "review_host": REVIEW_HOST,
            # How much of a document the reviewer reads. Sent because it is the
            # only thing that makes `review.partial` explicable: without it the
            # window can report "first part only" and not say what part.
            "review_max_characters": MAX_REVIEW_CHARS,
            "preview_max_characters": MAX_PREVIEW_CHARS,
            # A new field rather than richer `detector_specs` entries: changing
            # the element type of a published list is not an additive change.
            "detector_spec_notes": dict(LAYER_SPEC_NOTES),
            "caveats": list(CAVEATS),
            # A separate list, because a restore's limits are not a scrub's and a
            # merged one would show a reader of either screen four sentences that
            # do not apply.
            "restore_caveats": list(RESTORE_CAVEATS),
        }

    def doctor(self, params: dict[str, Any]) -> dict[str, Any]:
        """What this machine can actually do, and how to fix what it cannot.

        Every `Check` carries a `fix` written to be shown to a person, and until
        now the only person who could see one was in a terminal. Cheap to ask:
        the checks use ``find_spec`` and never import the model.

        The fixes are ``sys.frozen``-aware: a packaged build has no virtualenv to
        ``uv sync``, so those fixes become absent rather than being rewritten into
        advice the engine cannot know is right — a portable zip is replaced, an
        installer is reinstalled, and which one this is is not a fact in here.
        """
        checks = run_checks(
            str(params.get("review_host") or REVIEW_HOST),
            # Off unless asked. Reading 1.2 GB is the difference between a pane
            # that opens instantly and one that stalls, and the question it
            # answers - were these bytes altered without the length changing -
            # is one a person asks deliberately, not on every render.
            hashes=bool(params.get("hashes")),
        )
        return {
            "version": engine_version(),
            "ok": all(check.ok for check in checks if check.required),
            "checks": [
                {
                    "name": check.name,
                    "ok": check.ok,
                    "detail": check.detail,
                    "fix": check.fix,
                    "required": check.required,
                    # Computed here because the CLI computes it too, from the
                    # same property. A window deriving `not ok and not required`
                    # itself would be the window holding a rule.
                    "degraded": check.degraded,
                }
                for check in checks
            ],
        }

    def use_tesseract(self, params: dict[str, Any]) -> dict[str, Any]:
        """Take a Tesseract the caller chose, and answer with what is true now.

        A control, not a rule - the same shape as :meth:`forget`. Nothing here
        decides what counts as a Tesseract: :func:`adopt_tesseract` validates it
        with the same two checks that govern ``FREEDOCS_TESSERACT`` and
        ``_SYSTEM_BINARIES``, so a caller cannot be more permissive than the
        environment variable already is. There is no ``force`` or ``trust``
        parameter, because one would put the capability and the refusal back into
        the disagreement ``ocr_unavailable_reason`` is the single authority to
        prevent.

        **A refusal is a field, not an error.** Raising was the obvious shape and
        it is the wrong one: the window would render an error and then separately
        re-ask ``capabilities``, and those two answers could disagree. One payload
        carrying the refusal *and* the resulting state makes that impossible by
        construction - the two state fields below are the same two expressions
        ``capabilities`` publishes, read from the same process after the attempt.

        ``refused`` is an enum rather than a sentence so the window can translate
        it, per the rule that an enum is translated and an f-string is quoted. The
        two values are kept apart because the next move differs: pick another
        file, versus rename this one.

        ``accepted`` and ``ocr_available`` may honestly differ - an accepted
        binary with the language data still missing is the two halves, not a
        contradiction - and ``tesseract`` names what will be used *now*, which on
        a refusal is whatever was already answering. "I refused yours, and here is
        what I am using instead" is more useful than a bare no.

        Needs no cache invalidation. A document that required OCR was *refused*
        rather than cached, so nothing in ``_extractions`` was read without it,
        and clearing the cache here would discard extractions that cost nothing to
        keep.
        """
        # `must_exist=False`: a path that is gone and a path that is not runnable
        # are the same user mistake - picked the wrong file - so they share the
        # refusal channel. INVALID_REQUEST stays for a malformed request.
        candidate = _require_path(params, "path", must_exist=False)
        refused = adopt_tesseract(candidate)
        return {
            "accepted": refused is None,
            "refused": refused,
            "tesseract": tesseract_binary(),
            "ocr_available": ocr_unavailable_reason() is None,
            "ocr_unavailable_reason": ocr_unavailable_reason(),
        }

    def countries(self, params: dict[str, Any]) -> dict[str, Any]:
        """Which countries get what, and what narrowing to some of them costs."""
        selection = _countries_from(params)
        confidence = params.get("min_confidence")
        if confidence is None:
            confidence = 0.5
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise RpcError(INVALID_REQUEST, "'min_confidence' must be between 0 and 1")
        return country_coverage(selection, float(confidence))

    def review_models(self, params: dict[str, Any]) -> dict[str, Any]:
        """Which models one particular Ollama has pulled.

        Separate from :meth:`capabilities` because the host is a runtime choice.
        An Ollama on a non-default port used to leave the app showing an empty
        list with no way to correct it, which reads as "this build cannot review"
        when the truth is "look somewhere else".
        """
        host = str(params.get("host") or REVIEW_HOST)
        try:
            models = available_models(host, allow_remote=bool(params.get("allow_remote")))
        except RemoteHostRefused as exc:
            # The same treatment `scrub` gives it: the caller asked for something
            # this tool will not do until it is asked explicitly.
            raise RpcError(INVALID_REQUEST, str(exc)) from exc
        return {"host": host, "models": models}

    def model_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        """Whether the NER weights are on this machine, asked without fetching them.

        What the first-run screen is decided from, so it is the engine's answer
        and not the window's guess: ``source`` is how this build gets its model
        (the same enum ``capabilities`` sends), ``ner_available`` whether the
        layer is in the build at all, and ``present`` whether a document could be
        read by the model right now without a download. Costs no network call
        and loads nothing, because a question asked at every launch must not be
        the thing that makes a launch slow.
        """
        from .detect.backends.gliner_backend import cached_snapshot, model_source

        ner = _module_present("gliner2") and _module_present("torch")
        source = _model_source_kind()
        if source == "bundled":
            try:
                model_source()
                present = True
            except ModelNotFound:
                present = False
        else:
            present = cached_snapshot() is not None
        return {"source": source, "ner_available": ner, "present": ner and present}

    def model_fetch(self, _params: dict[str, Any]) -> dict[str, Any]:
        """Download the NER weights now, with progress, then load them.

        ``download`` notifications carry ``done`` and ``of`` in bytes - a real
        unit, so this is the one bar the window may fill in proportion; see
        ``StageEvent`` for why the pipeline's stages may not. The model is loaded
        before answering, so the first document after the screen does not pay
        the seconds a load takes, and the response arriving means the layer
        works rather than that some files exist.

        Refused for a bundled build: it carries its model, and a portable copy
        that reached for the network once is one nobody trusts offline again.
        """
        from .detect.backends.gliner_backend import fetch_model
        from .detect.ner import load_backend

        if _model_source_kind() != "hub":
            raise RpcError(INVALID_REQUEST, "this build carries its own model; nothing to fetch")
        request_id = self.current

        def report(done: int, of: int) -> None:
            self.notify("download", id=request_id, done=done, of=of)

        try:
            fetch_model(report)
            _ = load_backend("gliner2").model  # type: ignore[attr-defined]
        except MissingDependency as exc:
            raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc
        except ModelDownloadFailed as exc:
            raise RpcError(MODEL_DOWNLOAD_FAILED, str(exc)) from exc
        return {"present": True}

    def entities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Every entity type, whether it is removed, and what replaces it.

        The placeholder is composed by the same allocator that writes the
        document, so a preview of `[PERSONA_1]` cannot disagree with the
        `[PERSON_1]` the file ends up with. Before this the window could offer a
        locale and show only its ISO code, which tells the reader nothing about
        what the choice does.
        """
        locale = _locale_from(params or {})
        labels = placeholder_labels(locale)
        return {
            "placeholder_language": locale,
            "entities": [
                {
                    "name": entity.value,
                    "default_action": (
                        Action.REPORT.value if entity in REPORT_ONLY else Action.REDACT.value
                    ),
                    "report_only": entity in REPORT_ONLY,
                    "placeholder": SurrogateAllocator(labels).placeholder_for(entity, "example"),
                }
                for entity in EntityType
            ],
        }

    def inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        """What would be removed from one file, without writing anything.

        Runs the same read-and-detect the scrub runs, through `Scrubber`, rather
        than a second copy of those stages. The copy is how a preview comes to
        show findings the scrub that follows it does not agree with.
        """
        path = _require_path(params, "path")
        policy = _policy_from(params)
        scoped = self._override_from(params).for_path(str(path))
        scrubber = Scrubber(
            policy=policy,
            registry=self.registry(  # type: ignore[arg-type]
                params.get("detectors"), _countries_from(params)
            ),
            overrides=scoped,
            progress=self.stage_reporter(str(path)),
        )

        extraction = self.extraction(scrubber, path)
        inspection = _detect(scrubber, extraction)

        return _inspection_payload(
            str(path),
            extraction,
            inspection,
            policy,
            include_text=bool(params.get("include_text")),
        )

    def scrub(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write scrubbed copies, reporting progress per file."""
        paths = [_as_path(value) for value in params.get("paths") or []]
        if not paths:
            raise RpcError(INVALID_REQUEST, "'paths' must be a non-empty list")
        output_dir = _require_path(params, "output_dir", must_exist=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        # Resolved before the first file is read. A key file aimed at the output
        # directory, or one asked for with no passphrase, must stop the request
        # rather than interrupt it with scrubbed copies already on disk.
        map_target, passphrase = _map_from(params, output_dir)

        scrubber = Scrubber(
            policy=_policy_from(params),
            registry=self.registry(  # type: ignore[arg-type]
                params.get("detectors"), _countries_from(params)
            ),
            strict=not bool(params.get("allow_leaks")),
            reviewer=_reviewer_from(params),
        )
        override = self._override_from(params)

        results: list[dict[str, Any]] = []
        for index, path in enumerate(paths):
            self.notify("progress", file=str(path), index=index, total=len(paths))
            # Re-bound per file rather than once for the batch. A kept span is an
            # offset into one extraction, so carrying the whole set into every
            # file would fail the second one as stale - the check working on a
            # question nobody asked. See Override.for_path.
            results.append(
                self._scrub_one(
                    replace(
                        scrubber,
                        overrides=override.for_path(str(path)),
                        progress=self.stage_reporter(str(path)),
                    ),
                    path,
                    output_dir,
                    map_target=map_target,
                    passphrase=passphrase,
                    placeholder_language=_locale_from(params),
                )
            )
        return {"results": results}

    def _scrub_one(
        self,
        scrubber: Scrubber,
        path: Path,
        output_dir: Path,
        *,
        map_target: Path | None = None,
        passphrase: str = "",
        placeholder_language: str = DEFAULT_LOCALE,
    ) -> dict[str, Any]:
        """One file's outcome, as data rather than as an exception.

        A batch must not stop because its third file is a scan nobody can read,
        so every failure is reported in place and the run continues.
        """
        try:
            result = scrubber.scrub_file(path)
        except _SCRUB_REFUSALS as exc:
            return _scrub_refusal(path, exc)

        destination = output_dir / path.name
        try:
            # Left to the umask: this is the copy the caller sends on, and stage 6
            # has already searched it for every value that was meant to be gone.
            write_output(destination, result.output)
        except OutputRefused as exc:
            return _failure(path, OUTPUT_REFUSED, str(exc))

        key_file: str | None = None
        key_warnings: list[str] = []
        if map_target is not None:
            key_path = map_path_for(map_target, path)
            key_map = key_map_from(result, placeholder_language=placeholder_language)
            try:
                write_key_map(key_path, key_map, passphrase)
            except MissingDependency as exc:
                # The scrubbed copy is already on disk and is correct, so this is
                # reported against the file rather than raised for the batch - but
                # it is a failure: the caller asked to be able to undo this and
                # cannot.
                return _failure(path, MISSING_DEPENDENCY, str(exc))
            except ValueError as exc:
                # The passphrase rules. Value-free by construction in
                # core/mapping.py, which is what makes it safe to forward.
                return _failure(path, INVALID_REQUEST, str(exc))
            # The path, unlike in the JSON report: this response goes down a local
            # pipe to the process that chose the location, and a window that
            # cannot say where the key went is a window nobody can find it from.
            key_file = str(key_path)
            key_warnings = key_map.warnings()

        return {
            "path": str(path),
            "ok": True,
            "output": str(destination),
            "removed": len(result.removed),
            "flagged": len(result.reported),
            # The quoting form: this response goes down the local pipe, which
            # already carries matched text. The `report` below does not quote.
            "warnings": [*result.caller_warnings, *key_warnings],
            "hidden_removed": [
                {"part": item.part, "kind": item.kind, "detail": item.detail}
                for item in result.hidden_removed
            ],
            "review": _review_payload(result),
            # What was left in the output on purpose. The window needs it for
            # the same reason the report does: a clean verification now means
            # "nothing survived that was meant to go", and without this line a
            # reader takes it to mean the word is not in the document.
            "suppressed": suppressed_section(result.suppressed),
            "key_file": key_file,
            "report": build_report(result, key_file=key_file is not None),
        }

    def restore(self, params: dict[str, Any]) -> dict[str, Any]:
        """Put one document's values back from its key file.

        **One path, not a list.** A key file describes one document, so a batch
        here would either apply one map to several documents - which is what the
        per-document scoping in ``Override.for_path`` exists to prevent, one
        feature over - or need a map per path and stop being one request.

        The passphrase arrives over the pipe. That is the same channel that
        already carries the extracted document text, going to a child process the
        caller started; what matters is that no failure below puts it into a
        response, which is why every error here comes from ``core/mapping.py``
        rather than being composed near the value.
        """
        path = _require_path(params, "path")
        map_path = _require_path(params, "map")
        output_dir = _require_path(params, "output_dir", must_exist=False)
        passphrase = params.get("passphrase")
        if not isinstance(passphrase, str) or not passphrase:
            raise RpcError(INVALID_REQUEST, "'passphrase' must be a non-empty string")

        key_map = _open_key_map(map_path, passphrase)

        restorer = Restorer(key_map=key_map, progress=self.stage_reporter(str(path)))
        try:
            result = restorer.restore(path)
        except UnsupportedFormat as exc:
            raise RpcError(UNSUPPORTED_FORMAT, str(exc)) from exc
        except InputTooLarge as exc:
            raise RpcError(INPUT_TOO_LARGE, str(exc)) from exc
        except MalformedDocument as exc:
            raise RpcError(MALFORMED_DOCUMENT, str(exc)) from exc
        except ScannedPdfNotSupported as exc:
            raise RpcError(NEEDS_OCR, str(exc)) from exc
        except MissingDependency as exc:
            raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc

        # Owner only, directory included when this call creates it. What lands
        # here is the originals, reassembled - the key file's permissions were
        # careful and this was not.
        private_directory(output_dir)
        destination = output_dir / path.name
        # Written even when incomplete. The opposite of a leak: a scrub that
        # failed verification must write nothing because a nearly-clean document
        # gets sent, while a half-restored one is still the caller's best artifact
        # and its defect is visible in it. The response says so and the caller
        # decides.
        try:
            write_private(destination, result.output)
        except OutputRefused as exc:
            raise RpcError(OUTPUT_REFUSED, str(exc)) from exc
        return {
            "path": str(path),
            "output": str(destination),
            "format": result.format_name,
            **_restore_payload(result),
        }

    # -- pasted text -----------------------------------------------------------
    #
    # The plaintext handler over a string, handed to the same `Scrubber` and
    # `Restorer` a file goes through. Nothing is cached and nothing is written:
    # re-extracting a paste costs nothing, and a cache entry is text held
    # resident for no gain.

    def inspect_text(self, params: dict[str, Any]) -> dict[str, Any]:
        """`inspect` for a paste. The text is always returned: the caller sent it."""
        handler = _text_handler(params)
        policy = _policy_from(params)
        scrubber = Scrubber(
            policy=policy,
            registry=self.registry(  # type: ignore[arg-type]
                params.get("detectors"), _countries_from(params)
            ),
            overrides=self._override_from(params).for_path(PASTED_NAME),
            progress=self.stage_reporter(PASTED_NAME),
        )
        extraction = _read(scrubber, handler)
        inspection = _detect(scrubber, extraction)
        return _inspection_payload(PASTED_NAME, extraction, inspection, policy, include_text=True)

    def scrub_text(self, params: dict[str, Any]) -> dict[str, Any]:
        """Scrub a paste and return the scrubbed text. Nothing touches disk.

        The mapping goes one of three ways, and the caller picks per text:
        thrown away (the default, irreversible like every scrub), held under a
        handle with ``keep_map`` until forgotten, or sealed into a key file with
        ``map`` and ``map_passphrase``. Both at once is allowed and is two copies
        of the same key the caller asked for.

        A failure - a leak above all - comes back as `scrub`'s per-file failure
        shape with **no** ``text``: a nearly-clean paste gets sent exactly as a
        nearly-clean file does.
        """
        handler = _text_handler(params)
        map_target, passphrase = _map_from(params, None)
        placeholder_language = _locale_from(params)
        scrubber = Scrubber(
            policy=_policy_from(params),
            registry=self.registry(  # type: ignore[arg-type]
                params.get("detectors"), _countries_from(params)
            ),
            strict=not bool(params.get("allow_leaks")),
            reviewer=_reviewer_from(params),
            overrides=self._override_from(params).for_path(PASTED_NAME),
            progress=self.stage_reporter(PASTED_NAME),
        )
        pasted = Path(PASTED_NAME)
        try:
            result = scrubber.scrub(handler)
        except _SCRUB_REFUSALS as exc:
            return _scrub_refusal(pasted, exc)

        key_map = None
        if map_target is not None or params.get("keep_map"):
            key_map = key_map_from(result, placeholder_language=placeholder_language)

        key_file: str | None = None
        key_warnings: list[str] = []
        if map_target is not None and key_map is not None:
            key_path = map_path_for(map_target, pasted)
            try:
                write_key_map(key_path, key_map, passphrase)
            except MissingDependency as exc:
                return _failure(pasted, MISSING_DEPENDENCY, str(exc))
            except OutputRefused as exc:
                return _failure(pasted, OUTPUT_REFUSED, str(exc))
            except ValueError as exc:
                return _failure(pasted, INVALID_REQUEST, str(exc))
            key_file = str(key_path)
            key_warnings = key_map.warnings()

        handle: str | None = None
        if params.get("keep_map") and key_map is not None:
            handle = self._text_maps.hold(key_map)
            key_warnings = key_map.warnings()

        return {
            "path": PASTED_NAME,
            "ok": True,
            "text": decoded(handler, result.output),
            "removed": len(result.removed),
            "flagged": len(result.reported),
            "warnings": [*result.caller_warnings, *key_warnings],
            "review": _review_payload(result),
            "suppressed": suppressed_section(result.suppressed),
            "handle": handle,
            "key_file": key_file,
            # Returned, never saved. The caller may write it; the engine has no
            # reason to put a paste's report anywhere.
            "report": build_report(result, key_file=key_file is not None),
        }

    def restore_text(self, params: dict[str, Any]) -> dict[str, Any]:
        """Put the values back into a pasted reply, from a handle or a key file.

        A handle is not consumed: a second reply from the same model is normal
        use. One that is not held - forgotten, evicted, or from before a restart
        - is ``INVALID_REQUEST`` with a message naming no value.
        """
        handler = _text_handler(params)
        if "handle" in params:
            try:
                key_map = self._text_maps.get(params["handle"])
            except UnknownHandle as exc:
                raise RpcError(INVALID_REQUEST, str(exc)) from exc
        elif "map" in params:
            key_map = _open_key_map(_require_path(params, "map"), _passphrase(params, "passphrase"))
        else:
            raise RpcError(INVALID_REQUEST, "restore_text needs a 'handle' or a 'map'")

        restorer = Restorer(key_map=key_map, progress=self.stage_reporter(PASTED_NAME))
        result = restorer.restore(handler)
        return {
            "path": PASTED_NAME,
            "text": decoded(handler, result.output),
            **_restore_payload(result),
        }


# -- helpers ------------------------------------------------------------------


def _supported_extensions() -> set[str]:
    from .formats.router import HANDLERS

    return {extension for handler in HANDLERS for extension in handler.extensions}


def _model_source_kind() -> str:
    """``"bundled"`` or ``"hub"`` — never the path.

    A closed vocabulary, so the window translates it by key rather than quoting
    it, which is the rule for anything that came from an enum. The directory
    itself is deliberately not sent: it is a local filesystem path, it tells the
    window nothing it can act on, and ``doctor`` is where a path belongs.

    Reports what the loader *will* do, not what a previous run did. It asks the
    same function the backend asks, so the answer cannot drift from the
    behaviour — and it tolerates the refusal, because a misconfigured path must
    still let ``capabilities`` answer. A window that cannot ask what this build
    can do has no way to report that it is broken.
    """
    from .detect.backends.gliner_backend import DEFAULT_MODEL, model_source

    try:
        return "hub" if model_source() == DEFAULT_MODEL else "bundled"
    except ModelNotFound:
        return "bundled"


def _as_path(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise RpcError(INVALID_REQUEST, f"expected a path string, got {value!r}")
    return Path(value).expanduser()


def _require_path(params: dict[str, Any], key: str, *, must_exist: bool = True) -> Path:
    if key not in params:
        raise RpcError(INVALID_REQUEST, f"missing required parameter {key!r}")
    path = _as_path(params[key])
    if must_exist and not path.exists():
        raise RpcError(INVALID_REQUEST, f"{path} does not exist")
    return path


def _countries_from(params: dict[str, Any]) -> tuple[str, ...] | None:
    """None when the caller said nothing, which means every supported country.

    A present-but-empty list is refused rather than read as "none of them": over
    this pipe that is what a caller sends when its own state got lost, and the
    result would be a scrub with the whole checksum layer switched off and a file
    the user believes is clean.
    """
    raw = params.get("countries")
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
        raise RpcError(INVALID_REQUEST, "'countries' must be a list of country codes")
    names = tuple(name.strip().lower() for name in raw if name.strip())
    if not names:
        raise RpcError(INVALID_REQUEST, "'countries' was empty; omit it to use all of them")
    unknown = sorted(set(names) - set(SUPPORTED_COUNTRIES))
    if unknown:
        raise RpcError(INVALID_REQUEST, f"unknown country code(s): {', '.join(unknown)}")
    return names


def _policy_from(params: dict[str, Any]) -> Policy:
    overrides: dict[EntityType, Action] = {}
    for name in params.get("keep") or []:
        try:
            overrides[EntityType(str(name).upper())] = Action.KEEP
        except ValueError as exc:
            raise RpcError(INVALID_REQUEST, f"unknown entity type {name!r}") from exc
    minimum = params.get("min_confidence", 0.5)
    if not isinstance(minimum, (int, float)) or not 0.0 <= minimum <= 1.0:
        raise RpcError(INVALID_REQUEST, "'min_confidence' must be between 0 and 1")
    return Policy(
        overrides=overrides,
        min_confidence=float(minimum),
        placeholder_locale=_locale_from(params),
    )


def _locale_from(params: dict[str, Any]) -> str:
    """The placeholder locale, validated once for every method that takes one.

    Shared rather than copied: `entities` composes an example placeholder from
    the same locale a scrub would write, so an unknown locale has to be the same
    error in both places or the preview and the scrub disagree about what is
    valid.
    """
    locale = params.get("placeholder_language") or DEFAULT_LOCALE
    if locale not in PLACEHOLDER_LOCALES:
        raise RpcError(
            INVALID_REQUEST,
            f"unknown placeholder language {locale!r}; expected one of "
            f"{', '.join(PLACEHOLDER_LOCALES)}",
        )
    return str(locale)


def _map_from(params: dict[str, Any], output_dir: Path | None) -> tuple[Path | None, str]:
    """Where the key file goes and what opens it, or (None, "") for no key file.

    Validated here rather than at the moment of writing, so a request that cannot
    produce a key file is refused before any document is read. The two refusals
    are the ones a caller can act on:

    - a ``map`` with no ``map_passphrase``, because there is no unencrypted form
      of this file and quietly writing nothing would be worse than saying so;
    - a ``map`` inside ``output_dir``, which is the accident that actually
      happens - zipping the output folder and sending the scrubbed document along
      with the key to undo it. The rule itself lives in ``core/mapping.py`` so
      the CLI and this layer cannot disagree about it.
    """
    raw = params.get("map")
    if raw is None:
        return None, ""
    target = _as_path(raw)
    passphrase = params.get("map_passphrase")
    if not isinstance(passphrase, str) or not passphrase:
        raise RpcError(
            INVALID_REQUEST,
            "'map' asks for a key file, so 'map_passphrase' is required: there is "
            "no unencrypted form of it",
        )
    # A paste has no output directory, so there is nothing to land inside.
    if output_dir is not None and not bool(params.get("map_in_output_dir")):
        complaint = refuse_inside(target, output_dir)
        if complaint:
            raise RpcError(INVALID_REQUEST, complaint)
    return target, passphrase


def _override_from(params: dict[str, Any]) -> Override:
    """Per-occurrence decisions off the wire.

    Separate from ``_policy_from`` because the two ``keep`` controls are different
    things and collapsing them would be a bug: ``keep`` names entity *types* to
    leave alone everywhere, ``keep_spans`` names single occurrences. One control
    for both would make "this Zurich is fine" mean "no location is confidential".
    """
    try:
        return parse_override(params.get("keep_spans"), params.get("remove"))
    except ValueError as exc:
        raise RpcError(INVALID_REQUEST, str(exc)) from exc


def _passphrase(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise RpcError(INVALID_REQUEST, f"{key!r} must be a non-empty string")
    return value


def _list_param(params: dict[str, Any], key: str) -> list[Any]:
    value = params.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise RpcError(INVALID_REQUEST, f"{key!r} must be a list")
    return value


@contextlib.contextmanager
def _terms_errors() -> Iterator[None]:
    """The term list's failures as codes. Every message is value-free at source."""
    try:
        yield
    except MissingDependency as exc:
        raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc
    except InputTooLarge as exc:
        raise RpcError(INPUT_TOO_LARGE, str(exc)) from exc
    except OutputRefused as exc:
        raise RpcError(OUTPUT_REFUSED, str(exc)) from exc
    except (BadPassphrase, TermListError, ValueError) as exc:
        # ValueError covers the passphrase floor, which `core/sealed.py` raises
        # without quoting what it refused.
        raise RpcError(INVALID_REQUEST, str(exc)) from exc


def _reviewer_from(params: dict[str, Any]) -> LlmReviewer | None:
    """Build the optional reviewer, or None when nobody asked for one."""
    model = params.get("review")
    if not model:
        return None
    try:
        return LlmReviewer(
            model=str(model),
            host=str(params.get("review_host") or REVIEW_HOST),
            allow_remote=bool(params.get("review_remote")),
        )
    except RemoteHostRefused as exc:
        # A request error, not a failure of the file: the caller asked for
        # something this tool will not do without saying so explicitly.
        raise RpcError(INVALID_REQUEST, str(exc)) from exc


def _review_payload(result: Any) -> dict[str, Any] | None:
    """The review as data, or None when there was none.

    The quotes are from the *scrubbed* text, so they are not confidential values:
    they are what survived, which is exactly what the user needs to see.
    """
    review = result.review
    if review is None:
        return None
    return {
        "model": review.model,
        "ran": review.ran,
        "unavailable": review.unavailable,
        "partial": review.truncated,
        "summary": review.summary(),
        "concerns": [
            {"kind": concern.kind, "quote": concern.quote, "why": concern.why}
            for concern in review.concerns
        ],
    }


def _read(scrubber: Scrubber, path: Path | FormatHandler) -> Extraction:
    """Route and extract, with the engine's refusals mapped to codes.

    The path goes in rather than a handler: routing is the first stage, and a
    caller that opened the file itself would be doing the router's work while the
    run reported a stage it never ran.
    """
    try:
        return scrubber.read(path)
    except UnsupportedFormat as exc:
        raise RpcError(UNSUPPORTED_FORMAT, str(exc)) from exc
    except InputTooLarge as exc:
        raise RpcError(INPUT_TOO_LARGE, str(exc)) from exc
    except MalformedDocument as exc:
        raise RpcError(MALFORMED_DOCUMENT, str(exc)) from exc
    except ScannedPdfNotSupported as exc:
        raise RpcError(NEEDS_OCR, str(exc)) from exc
    except MissingDependency as exc:
        raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc


def _detect(scrubber: Scrubber, extraction: Extraction) -> Any:
    """Stage three with the engine's refusals mapped to codes, for both inspects."""
    try:
        return scrubber.detect_in(extraction)
    except StaleOverride as exc:
        # A decision pointing at text that has since changed is refused, never
        # applied to whatever moved into that range. See overrides.py.
        raise RpcError(INVALID_REQUEST, str(exc)) from exc
    except (MissingDependency, ModelNotFound) as exc:
        # A detector backend loads its model on first use, so a missing one
        # surfaces here rather than at construction. Without this the app was
        # told "internal error" for what is really "a component is missing".
        #
        # ModelNotFound rides along because it is the same answer to the
        # user: FREEDOCS_NER_MODEL naming an incomplete directory is a
        # portable build missing its weights, not an engine fault, and it
        # reached no mapping at all before - so the window reported a
        # misconfigured bundle as an internal error.
        raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc


def _text_handler(params: dict[str, Any]) -> Any:
    """The handler over a paste, with its refusals mapped to codes."""
    try:
        return handler_for_text(params.get("text"))
    except TypeError as exc:
        raise RpcError(INVALID_REQUEST, str(exc)) from exc
    except InputTooLarge as exc:
        raise RpcError(INPUT_TOO_LARGE, str(exc)) from exc


def _open_key_map(map_path: Path, passphrase: str) -> Any:
    """Read a key file, with the reasons it will not open mapped to codes."""
    try:
        return read_key_map(map_path, passphrase)
    except MissingDependency as exc:
        raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc
    except (BadPassphrase, MalformedMap) as exc:
        raise RpcError(INVALID_REQUEST, str(exc)) from exc


def _restore_payload(result: Any) -> dict[str, Any]:
    """What a restore did, for a file and for a paste alike. No path, no output."""
    return {
        "ok": result.ok,
        "restored": [
            {
                "placeholder": entry.placeholder,
                "entity": entry.entity,
                "occurrences": entry.occurrences,
                "expected": entry.expected,
            }
            for entry in result.restored
        ],
        "not_present": list(result.unused),
        "unknown_placeholders": list(result.unknown),
        "warnings": list(result.warnings),
        "problems": [
            {
                "placeholder": problem.placeholder,
                "entity": problem.entity,
                "kind": problem.kind,
            }
            for problem in result.problems
        ],
        "report": build_restore_report(result),
    }


def _preview(stream: Any) -> dict[str, Any]:
    """The extracted text, and which part each region of it came from.

    One blob rather than a window around each finding. The findings' offsets are
    offsets into this text, and ``keep_spans`` sends those same offsets back, so a
    window would introduce a second coordinate system and a second place doing the
    arithmetic — the class of bug ``core/stream.py`` exists to prevent. It is also
    what the screen needs: the sentence *around* a value is what tells a reader
    whether a city is a party's address or a jurisdiction clause.

    ``text_end`` and ``text_truncated`` are both sent although either implies the
    other. The banner needs the boolean and the highlighter needs the offset, and
    making the caller derive one from the other is making it hold a rule about
    this cap.
    """
    text = stream.text
    end = min(len(text), MAX_PREVIEW_CHARS)
    return {
        "text": text[:end],
        "text_end": end,
        "text_truncated": end < len(text),
        # Clipped to what was actually sent, so the index never points past the
        # end of the string it indexes.
        "parts": [
            {"part": segment.part, "start": segment.start, "end": min(segment.end, end)}
            for segment in stream.part_segments()
            if segment.start < end
        ],
    }


def _inspection_payload(
    label: str,
    extraction: Extraction,
    inspection: Any,
    policy: Policy,
    *,
    include_text: bool,
) -> dict[str, Any]:
    """One inspection as the wire carries it, for a file and for a paste alike.

    One builder, because two would be how a pasted text comes to be previewed
    differently from the same words in a file.
    """
    stream = inspection.stream
    payload: dict[str, Any] = {
        "path": label,
        "format": extraction.format_name,
        "characters": len(stream.text),
        # The registry's notes belong here too. A preview taken with the
        # checksum layer narrowed to two countries looks exactly like a
        # preview taken with all thirteen, and the difference is the whole
        # point of the option.
        "warnings": inspection.warnings,
        # Occurrences the detection layer will deliberately leave behind, so
        # the preview can say why a value it shows as confidential is still
        # visible three lines further down.
        "suppressed": suppressed_section(inspection.suppressed),
        # What would be dropped that is not text. `freedocs inspect` has
        # named the thumbnail, the comments and the tracked changes since
        # `15ee0e1`; this payload did not, so the window's preview was silent
        # about the leak users do not expect and learned of it only after a
        # scrub. The same read produced both - `Scrubber.read` already calls
        # `scrub_hidden` - so this was a missing field rather than missing
        # work. `detail` is a description and never a value, which is what
        # makes it safe to render on a screen and, one channel over, safe to
        # write to a report.
        "hidden": [
            {"part": item.part, "kind": item.kind, "detail": item.detail}
            for item in extraction.hidden
        ],
        "findings": [
            {
                "start": finding.span.start,
                "end": finding.span.end,
                "entity": finding.entity.value,
                "action": policy.action_for(finding).value,
                "confidence": round(finding.confidence, 3),
                "detector": finding.detector,
                # Which layer claimed it: L1 a checksum, L2 the model, H the
                # caller. The most useful thing on a row a person is judging,
                # and computed here rather than guessed from the detector
                # string — which is what the window was reduced to doing.
                "layer": finding.layer.value,
                # Reaches the report and never the placeholder. Without it a
                # narrowed country selection is unverifiable from the preview.
                "country": finding.country,
                "part": stream.part_at(finding.span.start),
                # The value itself: a preview that cannot show what is about
                # to be removed is not a preview. See the module docstring on
                # why this is safe down this channel and nowhere else.
                "text": finding.text,
            }
            for finding in inspection.findings
        ],
    }
    if inspection.terms is not None:
        payload["terms"] = {
            "loaded": inspection.terms.loaded,
            "matched": inspection.terms.matched,
        }
    if include_text:
        payload.update(_preview(stream))
    return payload


#: What one document's scrub can fail with, reported in place so a batch goes on.
_SCRUB_REFUSALS = (
    StaleOverride,
    UnsupportedFormat,
    InputTooLarge,
    MalformedDocument,
    ScannedPdfNotSupported,
    MissingDependency,
    ModelNotFound,
    LeakDetected,
)


def _scrub_refusal(path: Path, exc: Exception) -> dict[str, Any]:
    """One scrub failure as data rather than as an exception.

    Shared by a file's scrub and a paste's, so the leak shape - value-free, and
    carrying no output - is one definition.
    """
    if isinstance(exc, StaleOverride):
        # In place rather than raised, like every other per-file failure: a
        # batch must not stop because one file moved under a decision.
        return _failure(path, INVALID_REQUEST, str(exc))
    if isinstance(exc, UnsupportedFormat):
        return _failure(path, UNSUPPORTED_FORMAT, str(exc))
    if isinstance(exc, InputTooLarge):
        return _failure(path, INPUT_TOO_LARGE, str(exc))
    if isinstance(exc, MalformedDocument):
        return _failure(path, MALFORMED_DOCUMENT, str(exc))
    if isinstance(exc, ScannedPdfNotSupported):
        return _failure(path, NEEDS_OCR, str(exc))
    if isinstance(exc, (MissingDependency, ModelNotFound)):
        # ModelNotFound is a broken bundle rather than an absent extra, but
        # it is the same code and the same sentence to whoever reads it.
        return _failure(path, MISSING_DEPENDENCY, str(exc))
    if isinstance(exc, LeakDetected):
        # Nothing is written. The message is composed here rather than taken
        # from the exception: this response may be logged by the app, and an
        # error about confidential values surviving must not carry them.
        # Leak.describe() is value-free too, but not relying on that is
        # cheaper than depending on it staying that way.
        return _failure(
            path,
            LEAK_DETECTED,
            f"verification found {len(exc.result.leaks)} value(s) still present "
            "in the scrubbed output, so nothing was written",
            data={
                "leaks": len(exc.result.leaks),
                "entities": sorted({leak.entity for leak in exc.result.leaks}),
                # Per leak as well as in total. All three fields are
                # value-free - the entity, which layer nominated it and how
                # many times it survived - and without them the window can
                # only say "4 value(s)", which is where every diagnosis of
                # this error has had to start from scratch.
                "detail": [
                    {
                        "entity": leak.entity,
                        "detector": leak.detector,
                        "occurrences": leak.occurrences,
                        "allowed": leak.allowed,
                    }
                    for leak in exc.result.leaks
                ],
            },
        )
    raise exc  # pragma: no cover - _SCRUB_REFUSALS lists every branch above


def _failure(path: Path, code: int, message: str, data: Any = None) -> dict[str, Any]:
    return {
        "path": str(path),
        "ok": False,
        "error": {"code": code, "message": message, "data": data},
    }


# -- dispatch -----------------------------------------------------------------


def _handlers(session: Session) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    return {
        "capabilities": lambda _params: session.capabilities(),
        "entities": session.entities,
        "doctor": session.doctor,
        "countries": session.countries,
        "review_models": session.review_models,
        "model_status": session.model_status,
        "model_fetch": session.model_fetch,
        "inspect": session.inspect,
        "scrub": session.scrub,
        "restore": session.restore,
        "forget": session.forget,
        "use_tesseract": session.use_tesseract,
        "terms_create": session.terms_create,
        "terms_unlock": session.terms_unlock,
        "terms_lock": session.terms_lock,
        "terms_list": session.terms_list,
        "terms_update": session.terms_update,
        "terms_import": session.terms_import,
        "terms_export": session.terms_export,
        "terms_rekey": session.terms_rekey,
        "inspect_text": session.inspect_text,
        "scrub_text": session.scrub_text,
        "restore_text": session.restore_text,
    }


def handle(session: Session, line: str) -> dict[str, Any] | None:
    """Process one request line, returning the response, or None for junk."""
    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": INVALID_REQUEST, "message": f"malformed JSON: {exc}"},
        }
    if not isinstance(request, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": INVALID_REQUEST, "message": "a request must be an object"},
        }

    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _error_response(request_id, INVALID_REQUEST, "'params' must be an object")

    handlers = _handlers(session)
    if method not in handlers:
        return _error_response(request_id, METHOD_NOT_FOUND, f"unknown method {method!r}")

    session.current = request_id
    try:
        result = handlers[method](params)
    except RpcError as exc:
        return _error_response(request_id, exc.code, str(exc), exc.data)
    except Exception as exc:
        # A crash in one request must not take down a session the app is relying
        # on. The caller gets an error it can render; where the *traceback* goes
        # depends on who is watching, which is what `_report_crash` decides.
        _report_crash()
        return _error_response(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
    finally:
        session.current = None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


#: Restores the full traceback in a packaged build, for a user who has been asked
#: for one. Not a debug mode in any wider sense - it changes this and nothing else.
DEBUG_VARIABLE = "FREEDOCS_DEBUG"


def _report_crash() -> None:
    """Print the traceback where a person can see it, and nowhere else.

    **stderr is not a private channel for a packaged app.** `engine.rs` inherits
    it deliberately, so a Python traceback reaches the terminal a developer is
    watching - and in a bundled `.app` there is no terminal. The parent is
    launchd, and everything written there goes to the operating system's unified
    log, on disk, readable by anyone who can read this machine's logs. An
    exception's own message is part of a traceback, and a parser's message can
    quote the document it was reading. That made this a disk channel nobody had
    audited, in a tool whose central rule is that values may reach the pipe and
    must not reach the disk.

    So a frozen build prints the exception's *type* and how to ask for more. The
    caller loses nothing either way: the full message travels the response, which
    is local, and `Session` is the only reader.
    """
    if not getattr(sys, "frozen", False) or os.environ.get(DEBUG_VARIABLE):
        traceback.print_exc(file=sys.stderr)
        return
    kind = type(sys.exc_info()[1]).__name__
    print(
        f"engine: {kind} while handling a request; set {DEBUG_VARIABLE}=1 for the traceback",
        file=sys.stderr,
    )


def _error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Read requests until stdin closes. One line in, one line out.

    The other of the two places that own the process, so the other place the
    hardening is applied - and undone on the way out for the same reason
    ``cli.main`` does it: `tests/test_rpc.py` calls this directly.
    """
    harden()
    block_external()
    try:
        return _serve(stdin, stdout)
    finally:
        unblock()


def _serve(stdin: TextIO | None, stdout: TextIO | None) -> int:
    source: Iterator[str] = iter(stdin or sys.stdin)
    session = Session(out=stdout or sys.stdout)
    session.notify("ready", **session.capabilities())
    for line in source:
        line = line.strip()
        if not line:
            continue
        response = handle(session, line)
        if response is not None:
            session.emit(response)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve())

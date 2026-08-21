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
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from .core.errors import MissingDependency
from .core.findings import EntityType
from .core.policy import REPORT_ONLY, Action, Policy
from .detect.llm_review import (
    DEFAULT_HOST as REVIEW_HOST,
)
from .detect.llm_review import (
    LlmReviewer,
    RemoteHostRefused,
    available_models,
)
from .formats.pdf import ScannedPdfNotSupported, tessdata_path
from .formats.router import UnsupportedFormat, handler_for
from .pipeline import LAYER_SPECS, Scrubber, build_registry, default_registry
from .report import CAVEATS, build_report
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

    # -- transport -------------------------------------------------------------

    def emit(self, payload: dict[str, Any]) -> None:
        json.dump(payload, self.out, ensure_ascii=False)
        self.out.write("\n")
        # Flushed per line: the app is reading incrementally and a buffered
        # progress notification is a progress bar that jumps at the end.
        self.out.flush()

    def notify(self, method: str, **params: Any) -> None:
        self.emit({"jsonrpc": "2.0", "method": method, "params": params})

    # -- state -----------------------------------------------------------------

    def registry(self, spec: str | None) -> object:
        if self._registry is None or self._registry_spec != spec:
            self._registry = build_registry(spec) if spec else default_registry()
            self._registry_spec = spec
        return self._registry

    # -- methods ---------------------------------------------------------------

    def capabilities(self) -> dict[str, Any]:
        """What this build can actually do.

        The app asks first and shows the answer, so a missing optional dependency
        becomes a visible limitation instead of a file that mysteriously fails.
        """
        registry = self.registry(None)
        return {
            "version": _version(),
            "formats": sorted(_supported_extensions()),
            "detector_specs": list(LAYER_SPECS),
            "layers": [type(detector).__name__ for detector in registry.detectors],
            "limitations": list(registry.notes),
            "ocr_available": tessdata_path() is not None,
            # Offered so the app can present a real choice instead of a free-text
            # box that 404s. Empty when Ollama is not running, which is the
            # honest answer to "what can I review with".
            "review_models": available_models(),
            # The default the app should prefill, sent rather than hardcoded there:
            # where Ollama lives is a judgement, and the app holds no judgements.
            "review_host": REVIEW_HOST,
            "caveats": list(CAVEATS),
        }

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

    def entities(self) -> dict[str, Any]:
        """Every entity type, and whether it is removed or only flagged."""
        return {
            "entities": [
                {
                    "name": entity.value,
                    "default_action": (
                        Action.REPORT.value if entity in REPORT_ONLY else Action.REDACT.value
                    ),
                    "report_only": entity in REPORT_ONLY,
                }
                for entity in EntityType
            ]
        }

    def inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        """What would be removed from one file, without writing anything."""
        path = _require_path(params, "path")
        policy = _policy_from(params)
        registry = self.registry(params.get("detectors"))

        handler = _open(path)
        stream = _extract(handler, path)
        try:
            findings = registry.detect(stream.text)  # type: ignore[attr-defined]
        except MissingDependency as exc:
            # A detector backend loads its model on first use, so a missing one
            # surfaces here rather than at construction. Without this the app was
            # told "internal error" for what is really "a component is missing".
            raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc

        return {
            "path": str(path),
            "format": handler.name,
            "characters": len(stream.text),
            "warnings": list(handler.warnings),
            "findings": [
                {
                    "start": finding.span.start,
                    "end": finding.span.end,
                    "entity": finding.entity.value,
                    "action": policy.action_for(finding).value,
                    "confidence": round(finding.confidence, 3),
                    "detector": finding.detector,
                    "part": _part_of(stream, finding.span.start),
                    # The value itself: a preview that cannot show what is about
                    # to be removed is not a preview. See the module docstring on
                    # why this is safe down this channel and nowhere else.
                    "text": finding.text,
                }
                for finding in findings
            ],
        }

    def scrub(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write scrubbed copies, reporting progress per file."""
        paths = [_as_path(value) for value in params.get("paths") or []]
        if not paths:
            raise RpcError(INVALID_REQUEST, "'paths' must be a non-empty list")
        output_dir = _require_path(params, "output_dir", must_exist=False)
        output_dir.mkdir(parents=True, exist_ok=True)

        scrubber = Scrubber(
            policy=_policy_from(params),
            registry=self.registry(params.get("detectors")),  # type: ignore[arg-type]
            strict=not bool(params.get("allow_leaks")),
            reviewer=_reviewer_from(params),
        )

        results: list[dict[str, Any]] = []
        for index, path in enumerate(paths):
            self.notify("progress", file=str(path), index=index, total=len(paths))
            results.append(self._scrub_one(scrubber, path, output_dir))
        return {"results": results}

    def _scrub_one(self, scrubber: Scrubber, path: Path, output_dir: Path) -> dict[str, Any]:
        """One file's outcome, as data rather than as an exception.

        A batch must not stop because its third file is a scan nobody can read,
        so every failure is reported in place and the run continues.
        """
        try:
            result = scrubber.scrub_file(path)
        except UnsupportedFormat as exc:
            return _failure(path, UNSUPPORTED_FORMAT, str(exc))
        except ScannedPdfNotSupported as exc:
            return _failure(path, NEEDS_OCR, str(exc))
        except MissingDependency as exc:
            return _failure(path, MISSING_DEPENDENCY, str(exc))
        except LeakDetected as exc:
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
                },
            )

        destination = output_dir / path.name
        destination.write_bytes(result.output)
        return {
            "path": str(path),
            "ok": True,
            "output": str(destination),
            "removed": len(result.removed),
            "flagged": len(result.reported),
            "warnings": list(result.warnings),
            "hidden_removed": [
                {"part": item.part, "kind": item.kind, "detail": item.detail}
                for item in result.hidden_removed
            ],
            "review": _review_payload(result),
            "report": build_report(result),
        }


# -- helpers ------------------------------------------------------------------


def _version() -> str:
    from . import __version__

    return __version__


def _supported_extensions() -> set[str]:
    from .formats.router import HANDLERS

    return {extension for handler in HANDLERS for extension in handler.extensions}


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
    return Policy(overrides=overrides, min_confidence=float(minimum))


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


def _open(path: Path) -> Any:
    try:
        return handler_for(path)
    except UnsupportedFormat as exc:
        raise RpcError(UNSUPPORTED_FORMAT, str(exc)) from exc
    except MissingDependency as exc:
        raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc


def _extract(handler: Any, path: Path) -> Any:
    try:
        handler.scrub_hidden()
        return handler.extract()
    except ScannedPdfNotSupported as exc:
        raise RpcError(NEEDS_OCR, str(exc)) from exc
    except MissingDependency as exc:
        raise RpcError(MISSING_DEPENDENCY, str(exc)) from exc


def _part_of(stream: Any, offset: int) -> str:
    """Which page, sheet or part an offset falls in, for the preview."""
    for anchor in stream.anchors:
        if anchor.start <= offset < anchor.end:
            return anchor.part
    return ""


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
        "entities": lambda _params: session.entities(),
        "review_models": session.review_models,
        "inspect": session.inspect,
        "scrub": session.scrub,
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

    try:
        result = handlers[method](params)
    except RpcError as exc:
        return _error_response(request_id, exc.code, str(exc), exc.data)
    except Exception as exc:
        # A crash in one request must not take down a session the app is relying
        # on. The traceback goes to stderr, which the app can surface as a bug
        # report; the caller gets an error it can render.
        traceback.print_exc(file=sys.stderr)
        return _error_response(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Read requests until stdin closes. One line in, one line out."""
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

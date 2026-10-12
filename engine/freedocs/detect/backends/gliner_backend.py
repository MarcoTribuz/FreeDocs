"""GLiNER2 backend.

``fastino/gliner2-privacy-filter-PII-multi`` sits on an ``mdeberta-v3-base``
encoder, so one model covers Italian, German, French and English without being
told which it is looking at. That matters more than it sounds: the alternative
family needs the document's language named up front, and a scrubber that has to
guess the language before it can find names has an extra way to fail silently.

The model is asked for entities at a low threshold and the real filtering happens
in :class:`~freedocs.detect.ner.NerDetector`. One tuning knob, in one place,
measurable with ``freedocs benchmark``.
"""

from __future__ import annotations

import contextlib
import io
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ...core.egress import permitted
from ...core.errors import MissingDependency, ModelDownloadFailed, ModelNotFound
from ...core.model_manifest import MANIFEST_NAME, REQUIRED_FILES, verify
from ..ner import RawEntity

#: 1244 MB, fetched to the Hugging Face cache once: by the app's first-run screen
#: through :func:`fetch_model`, or on first use from the CLI. After that it is
#: loaded from the cache as a directory. Pinned by name so an upgrade is a deliberate,
#: re-benchmarked change. A portable build carries the weights instead and names
#: the directory in ``FREEDOCS_NER_MODEL``; see :func:`model_source`.
DEFAULT_MODEL = "fastino/gliner2-privacy-filter-PII-multi"

#: Set by the app when it finds a model beside the executable. The engine never
#: works out on its own that it is portable — it is told, and only ever with a
#: path that exists, which is the same rule ``_tessdata_candidates`` follows.
MODEL_ENV = "FREEDOCS_NER_MODEL"

#: What ``GLiNER2.from_pretrained`` opens first, so what makes a directory a
#: model rather than a directory.
_MODEL_MARKER = "config.json"

#: Requested in the model's own vocabulary; mapped to EntityType afterwards.
#: Phrases rather than bare tokens ("phone number", not "phone") because the
#: model is prompted with these strings and reads them as descriptions.
DEFAULT_LABELS: tuple[str, ...] = (
    "person",
    "organization",
    "location",
    "address",
    "email",
    "phone number",
    "iban",
    "credit card number",
    "date of birth",
    "job title",
    # Asked for because the United States has no checksummed identifier this tool
    # can validate: `stdnum.us.ssn` accepts 89% of random values of the right
    # shape and `us.ein` 83%, because neither number has a check digit. An L1
    # rule there would be a tightened regex pretending to be a validator, which
    # is what this layer exists not to be. A model reading the surrounding words
    # is the honest place for an identifier only context can distinguish.
    "social security number",
    "tax identification number",
    "national identification number",
)

#: Deliberately below any useful operating point: recall here, filtering later.
MODEL_THRESHOLD = 0.2


def model_source() -> str:
    """The local directory to load from, or the repository id to download.

    ``GLiNER2.from_pretrained`` takes either — its ``download_or_local`` branches
    on ``os.path.isdir`` — which is what lets a portable build ship a flat
    directory of weights and need no Hugging Face cache, no redirected ``HF_HOME``
    and, because nothing is fetched, no writable state anywhere.

    Resolved per call rather than read at import. ``load_backend`` is ``@cache``d,
    so a module-level ``os.environ`` read would be taken once, by whichever caller
    happened to be first, and would be invisible to a test that sets the variable
    afterwards — the same trap ``DEFAULT_LABELS`` has.

    Raises rather than falling back when the variable names something unusable:
    see :class:`~freedocs.core.errors.ModelNotFound`.
    """
    configured = os.environ.get(MODEL_ENV)
    if not configured:
        return DEFAULT_MODEL
    directory = Path(configured).expanduser()
    if not (directory / _MODEL_MARKER).is_file():
        # Not `!r`: `repr` of a Windows path doubles every backslash, so the
        # message a user is meant to act on arrives full of `\\\\`.
        raise ModelNotFound(
            f"{MODEL_ENV} names {directory}, which holds no {_MODEL_MARKER}; "
            "a bundled model directory is incomplete or the path is wrong"
        )
    return str(directory)


def verify_bundled(model_id: str) -> None:
    """Refuse a bundled payload that is not the one the build recorded.

    **Hashes, not sizes, and that is the whole point.** A truncated copy fails
    deep inside ``from_pretrained`` and looks broken, which is bad but loud. A
    payload whose bytes changed while its length did not loads perfectly and
    detects *less* — and silently detecting less is this tool's defining failure,
    the thing every other guard in the codebase exists to prevent. Only a hash
    sees it. Measured on the real 1.2 GB payload: 0.7 seconds, once, beside a
    model load that already takes several.

    Here rather than in :func:`model_source` on purpose. That function answers
    "where are the weights" and is called every time a backend is constructed,
    which is once per ``Scrubber``; this answers "are they the right weights" and
    belongs beside the single load it protects.

    Two things are deliberately *not* refused. A repository id is not a directory
    and the hub checks its own blobs, so the installer route is untouched. And a
    directory carrying no manifest is left alone: ``FREEDOCS_NER_MODEL`` is also
    the hook a developer uses to point at a checkout, and a manifest is what a
    *built* payload carries — its absence means nobody claimed anything about
    this copy, not that the copy is damaged.
    """
    directory = Path(model_id)
    if not (directory / MANIFEST_NAME).is_file():
        return
    problems = verify(directory, repo=DEFAULT_MODEL, hashes=True)
    if problems:
        raise ModelNotFound(
            f"the bundled model at {directory} is not what this build recorded: "
            + "; ".join(problems)
            + ". Replace the copy rather than trusting it: a payload that loads "
            "and is not the one measured detects less, silently."
        )


def cached_snapshot() -> Path | None:
    """The local snapshot of :data:`DEFAULT_MODEL` holding every file, or None.

    Asked of ``huggingface_hub``'s own cache index, so it costs no network call
    and honours ``HF_HOME`` the way the download did. ``None`` means at least
    one file the loader opens is not on this machine, which is the state the
    first-run screen exists for.

    It is also what :meth:`GlinerBackend._load` loads from, and that is the
    other half of the reason it exists. Handing ``from_pretrained`` the
    repository id makes ``huggingface_hub`` ask the hub whether its cached copy
    is current on *every* load, so an installer build reached the network every
    time the app started, not once. A directory is read as a directory. After
    the first download the weights in use are the ones on disk, and the model
    only changes when somebody fetches it on purpose - which is also what
    "pinned so an upgrade is a deliberate, re-benchmarked change" should have
    meant all along.
    """
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return None
    found: list[Path] = []
    for name in REQUIRED_FILES:
        hit = try_to_load_from_cache(DEFAULT_MODEL, name)
        # A string is a path; None is "never seen" and a sentinel object is
        # "the hub said this file does not exist". Neither is a model.
        if not isinstance(hit, str):
            return None
        found.append(Path(hit))
    # `config.json` sits at the root of the snapshot, so its directory is the
    # directory `from_pretrained` expects.
    return found[0].parent


#: How often a download may report, at most. `hf_hub_download` advances its bar
#: per network chunk, which over a fast line is hundreds of lines a second down a
#: pipe the window reads one at a time.
_REPORT_INTERVAL = 0.25

#: ``(done, of)`` in bytes across every file being fetched.
DownloadReport = Callable[[int, int], None]


def fetch_model(report: DownloadReport) -> Path:
    """Download whatever of :data:`DEFAULT_MODEL` is missing, and say how far it got.

    The second call in this process allowed to reach the network, and the same
    act as the first: before this existed the weights were fetched inside the
    first ``inspect``, so a new user's first document sat still for minutes with
    nothing to say why. Here the fetch is its own request, the window asks for it
    with the user's consent, and the progress is in **bytes**, which is a real
    unit - the one place a bar may honestly fill in proportion.

    Sizes are asked of the hub before anything is fetched so ``of`` is the whole
    download from the first report rather than a total that grows file by file.
    A file already in the cache is skipped, and ``hf_hub_download`` resumes a
    file it left ``.incomplete``, so an interrupted first run restarts where it
    stopped rather than at zero. Every failure becomes
    :class:`~freedocs.core.errors.ModelDownloadFailed`, because "the network went
    away" must not reach the window as a traceback about ``httpx``.
    """
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
        from huggingface_hub.utils import tqdm as hub_tqdm
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise MissingDependency(
            "huggingface_hub is required to fetch the model; install the 'ner' extra"
        ) from exc

    lock = threading.Lock()
    state = {"base": 0, "file": 0, "total": 0, "last": 0.0}

    def emit(*, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - state["last"] < _REPORT_INTERVAL:
            return
        state["last"] = now
        report(min(state["base"] + state["file"], state["total"]), state["total"])

    class _Progress(hub_tqdm):  # type: ignore[misc, valid-type]
        """A bar that counts for the window and draws nothing.

        Its own counter rather than ``self.n``: the hub disables its bars when
        ``HF_HUB_DISABLE_PROGRESS_BARS`` is set, and a disabled tqdm stops
        counting. The output goes to a buffer because stderr is the terminal a
        developer reads tracebacks in. Locked because the Xet transfer reports
        from its own threads.
        """

        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["file"] = io.StringIO()
            super().__init__(*args, **kwargs)
            with lock:
                state["file"] = int(kwargs.get("initial") or 0)  # type: ignore[call-overload]
                emit()

        def update(self, n: float | None = 1) -> bool | None:
            with lock:
                state["file"] = max(0, state["file"] + int(n or 0))
                emit()
            return super().update(n)

    try:
        with permitted("downloading the NER model"):
            missing = [name for name in REQUIRED_FILES if not isinstance(_cached(name), str)]
            sizes = {
                name: int(get_hf_file_metadata(hf_hub_url(DEFAULT_MODEL, name)).size or 0)
                for name in missing
            }
            state["total"] = sum(sizes.values())
            emit(force=True)
            for name in missing:
                hf_hub_download(DEFAULT_MODEL, name, tqdm_class=_Progress)
                with lock:
                    state["base"] += sizes[name]
                    state["file"] = 0
                    emit(force=True)
    except MissingDependency:
        raise
    except Exception as exc:
        raise ModelDownloadFailed(
            f"the model download did not finish ({type(exc).__name__}: {exc}); "
            "what was already downloaded is kept and the next attempt continues from it"
        ) from exc

    snapshot = cached_snapshot()
    if snapshot is None:
        raise ModelDownloadFailed(
            "the model download finished but the cache does not hold every file the "
            "loader needs; try again"
        )
    return snapshot


def _cached(name: str) -> object:
    from huggingface_hub import try_to_load_from_cache

    return try_to_load_from_cache(DEFAULT_MODEL, name)


@dataclass
class GlinerBackend:
    name: str = "gliner2"
    #: A factory, not a constant: the answer depends on the environment the
    #: sidecar was started with, and a default evaluated at class-definition time
    #: would freeze whatever was set when the module was first imported.
    model_id: str = field(default_factory=model_source)
    requested_labels: tuple[str, ...] = DEFAULT_LABELS
    threshold: float = MODEL_THRESHOLD
    _model: object | None = field(default=None, init=False, repr=False)

    def labels(self) -> Sequence[str]:
        return self.requested_labels

    @property
    def model(self) -> object:
        if self._model is None:
            self._model = self._load()
        return self._model

    def _load(self) -> object:
        try:
            from gliner2 import GLiNER2
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise MissingDependency(
                "gliner2 is required for the GLiNER2 backend; install the 'ner' extra"
            ) from exc
        # The library prints a configuration banner to stdout on load, which would
        # land in the middle of CLI output and, worse, in piped JSON.
        #
        # And this is the single call in the whole process that legitimately
        # reaches the network: an installer build fetches the weights on first
        # use, and `huggingface_hub` confirms a cached copy is current unless
        # `HF_HUB_OFFLINE` says otherwise. It lifts the egress block by name
        # rather than the block keeping a list of hosts it trusts - what makes
        # this acceptable is which call it is, not where it goes.
        # Before the load, not after: the point is to refuse the payload rather
        # than to notice afterwards that the answers were wrong.
        verify_bundled(self.model_id)
        source = self.model_id
        if source == DEFAULT_MODEL:
            # A complete local copy is loaded as a directory, which asks the hub
            # nothing; see `cached_snapshot`. Only a missing one falls through to
            # the repository id and its download.
            snapshot = cached_snapshot()
            if snapshot is not None:
                source = str(snapshot)
        with contextlib.redirect_stdout(io.StringIO()), permitted("loading the NER model"):
            return GLiNER2.from_pretrained(source, map_location="cpu")

    def predict(self, text: str) -> Sequence[RawEntity]:
        result = self.model.extract_entities(  # type: ignore[attr-defined]
            text,
            list(self.requested_labels),
            threshold=self.threshold,
            include_confidence=True,
            include_spans=True,
        )
        out: list[RawEntity] = []
        for label, hits in (result or {}).get("entities", {}).items():
            for hit in hits:
                # include_spans=True is what makes this backend usable at all;
                # without offsets there is no way back to a run or a rectangle.
                if "start" not in hit or "end" not in hit:
                    continue
                out.append(
                    RawEntity(
                        start=int(hit["start"]),
                        end=int(hit["end"]),
                        label=label,
                        score=float(hit.get("confidence", 1.0)),
                    )
                )
        return out

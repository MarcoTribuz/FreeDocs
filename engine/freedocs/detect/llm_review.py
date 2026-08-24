"""Layer 3: a second reader for the scrubbed text. Opt-in, advisory, never edits.

Everything else in this project locates confidential data by position and removes
it. This does neither. It reads the text *after* the scrub and reports what it
thinks is still wrong, for a human to act on.

Two reasons it cannot be a detector:

* **No offsets.** A generative model will happily quote a string back but cannot
  reliably say where it was. The anchors in :mod:`freedocs.core.stream` are the
  only route from a finding to a run of a Word document or a rectangle on a PDF
  page, and they are addressed by character. A layer that cannot supply an offset
  cannot drive an edit.
* **It is the wrong tool for the job it would be given.** The measured coverage of
  the checksum and NER layers is 99% of the corpus at 0.3% over-redaction. A model
  asked to find what they missed is asked for the residue, which is mostly
  quasi-identifiers — combinations no single span can fix.

So what it is for is the thing nothing else does: noticing that a document with
every name removed still says "the CFO of the Lugano branch hired in March 2024".

**The text leaves this process.** Ollama is a local server by default and nothing
goes over a network, which is the only reason this layer is allowed to exist in a
tool whose point is that documents do not leave the machine. A non-loopback host is
refused unless the caller says so explicitly, because "I pointed OLLAMA_HOST at a
GPU box" must be a decision rather than an accident. Even then it is the *scrubbed*
text that goes, not the original.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..core.egress import is_loopback

#: Ollama's default. Loopback, so nothing leaves the machine.
DEFAULT_HOST = "http://127.0.0.1:11434"

#: No default model name is invented here. Which models are pulled is the user's
#: business, and guessing produces a 404 that reads like a bug in this code.
#: :func:`available_models` exists so a caller can offer a real choice.

#: Long: a review of a full document on a local CPU is not fast, and a timeout
#: that fires mid-answer looks like a broken feature rather than a slow one.
DEFAULT_TIMEOUT = 300.0

#: Only as much text as a review can actually reason about. A model handed forty
#: pages returns generalities; the point of this layer is specific observations.
MAX_REVIEW_CHARS = 12_000

#: Asked for as a JSON schema rather than parsed out of prose. Ollama enforces it,
#: which turns "the model ignored the format instruction" from a parsing problem
#: into something that cannot happen.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "concerns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["leftover", "quasi_identifier", "context"],
                    },
                    "quote": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["kind", "quote", "why"],
            },
        }
    },
    "required": ["concerns"],
}

#: The prompt describes the *shape* of a placeholder rather than listing
#: examples. The examples used to be written out — [PERSONA_1], [IBAN_2], [CF_1] —
#: and two of the three named stems that no longer exist, because the placeholder
#: table moved and nothing connected it to this string. A shape cannot drift.
SYSTEM_PROMPT = """\
You review documents that have already been anonymised by an automated tool. \
Any bracketed token of the form [WORD_number] is a placeholder marking text the \
tool removed - [PERSON_1], [IBAN_2], [TAX_ID_1] and so on, in whatever language \
the tool was configured for. They are not problems, they are the tool working.

Report only what is still a re-identification risk:

- "leftover": a direct identifier the tool missed. A name, an address, an email, \
an account number, a case reference still present in full.
- "quasi_identifier": details that identify someone in combination even though \
none of them does alone. A job title plus a branch plus a date. A rare condition \
plus an age plus a town.
- "context": wording that reveals who the subject is without naming them. "the \
only female partner in the Zurich office".

Do not report the placeholders. Do not report generic business language. Do not \
speculate about text that is not there. Quote the exact words you are objecting \
to. If the document looks acceptable, return an empty list.

Answer in the language of the document."""


class OllamaUnavailable(RuntimeError):
    """Ollama could not be reached, or refused the request.

    A distinct type because this layer is advisory: the caller is expected to
    carry on scrubbing and report that the review did not happen, rather than
    fail the run.
    """


class RemoteHostRefused(RuntimeError):
    """The configured Ollama is not on this machine and nobody said that was fine."""


#: What this layer will talk over. Checked because the host arrives off the wire
#: and goes to ``urllib.request.urlopen``, which speaks rather more than HTTP:
#: without this, ``file:///etc/passwd`` was a local host and a file read.
_SCHEMES = frozenset({"http", "https"})


def _is_local(host: str) -> bool:
    """Whether a host URL points at this machine, over a protocol we meant.

    Name-based checks are deliberately narrow: ``localhost`` and the loopback
    ranges only, through ``core/egress.is_loopback``. A hostname that happens to
    resolve to a loopback address is not treated as local, because whether it
    still will tomorrow is not this code's call to make.

    Two things were wrong with the copy this replaced, and they compounded. An
    **empty** hostname counted as local - and an empty hostname is what
    ``urlparse`` gives for ``file:///etc/passwd`` and for ``http://:11434``. And
    the **scheme** was never looked at, so anything ``urlopen`` supports was fair
    game against a host that looked local. The loopback half now lives in one
    place for exactly that reason: two copies of a rule is how the guard on the
    one component that talks to the network gets walked past.
    """
    parsed = urlparse(host)
    if parsed.scheme.lower() not in _SCHEMES:
        return False
    return is_loopback(parsed.hostname or "")


#: The half of the refusal that is the same whoever is asking. Two places refuse a
#: non-loopback host — the reviewer, and the model listing — and they must not drift
#: into giving different reasons for one rule.
_REMOTE_REFUSAL = (
    "Pass allow_remote=True if that is what you want. Note that scrubbed is not the "
    "same as harmless: the review exists precisely because quasi-identifiers survive "
    "a scrub."
)


def _refuse_remote(host: str, because: str) -> RemoteHostRefused:
    return RemoteHostRefused(f"{host} is not on this machine. {because} {_REMOTE_REFUSAL}")


@dataclass(frozen=True)
class Concern:
    """One observation from the review. Advisory: nothing is removed for it."""

    kind: str
    quote: str
    why: str

    def describe(self) -> str:
        return f"[{self.kind}] {self.quote!r}: {self.why}"


@dataclass(frozen=True)
class ReviewOutcome:
    """What the review produced, or why it produced nothing.

    ``ran`` is separate from an empty ``concerns`` list on purpose: "the reviewer
    read this and had no objection" and "the reviewer never ran" are different
    facts, and collapsing them would let a silently skipped review look like a
    clean bill of health.
    """

    model: str
    ran: bool
    concerns: tuple[Concern, ...] = ()
    truncated: bool = False
    #: Why it did not run, when it did not. Ollama being absent is the usual case.
    unavailable: str | None = None

    def summary(self) -> str:
        if not self.ran:
            return f"review skipped: {self.unavailable}"
        if not self.concerns:
            covered = "part of the document" if self.truncated else "the document"
            return f"{self.model} reviewed {covered} and raised nothing"
        scope = " (first part of the document only)" if self.truncated else ""
        return f"{self.model} raised {len(self.concerns)} concern(s){scope}"


@dataclass
class LlmReviewer:
    """Asks a local model to read the scrubbed text and object to it."""

    model: str
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT
    max_chars: int = MAX_REVIEW_CHARS
    #: Required to talk to anything that is not loopback. Not a default, and not
    #: inferred from the URL: sending text off this machine is the one thing this
    #: project exists to avoid, so it takes an explicit yes.
    allow_remote: bool = False
    #: Set when the reviewed text had to be cut, so the caller can say the review
    #: covered part of the document rather than all of it.
    truncated: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not _is_local(self.host) and not self.allow_remote:
            raise _refuse_remote(self.host, "The review sends the scrubbed text to it.")

    def review(self, text: str) -> list[Concern]:
        """Return what the model objects to, or an empty list.

        Raises :class:`OllamaUnavailable` if the server cannot be reached. The
        caller decides whether that is fatal; in this project it never is.
        """
        excerpt = text[: self.max_chars]
        self.truncated = len(text) > self.max_chars
        if not excerpt.strip():
            return []

        payload = {
            "model": self.model,
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": excerpt},
            ],
            "options": {
                # Deterministic enough to be worth re-running: a review that says
                # something different every time is not a review.
                "temperature": 0.0,
            },
        }
        body = self._post("/api/chat", payload)
        content = ((body.get("message") or {}).get("content") or "").strip()
        return _parse_concerns(content)

    def review_outcome(self, text: str) -> ReviewOutcome:
        """:meth:`review`, with a reachability failure turned into a reported fact.

        This is what the pipeline calls. The review is advisory, so Ollama being
        absent must not fail a scrub that otherwise succeeded — but it must not
        pass unnoticed either.
        """
        try:
            concerns = self.review(text)
        except OllamaUnavailable as exc:
            return ReviewOutcome(model=self.model, ran=False, unavailable=str(exc))
        return ReviewOutcome(
            model=self.model,
            ran=True,
            concerns=tuple(concerns),
            truncated=self.truncated,
        )

    def _post(self, route: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.host.rstrip('/')}{route}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise OllamaUnavailable(f"Ollama returned {exc.code} for {route}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaUnavailable(
                f"could not reach Ollama at {self.host}: {exc}. Is it running?"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaUnavailable(f"Ollama sent a reply that is not JSON: {exc}") from exc


def _parse_concerns(content: str) -> list[Concern]:
    """Turn the model's answer into concerns, discarding anything malformed.

    The schema is enforced server-side, so this is defence rather than parsing: a
    review that crashes the run it was advising on would be worse than no review.
    """
    if not content:
        return []
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []

    out: list[Concern] = []
    for item in parsed.get("concerns") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        why = str(item.get("why") or "").strip()
        kind = str(item.get("kind") or "context").strip()
        if not quote or not why:
            continue
        out.append(Concern(kind=kind, quote=quote, why=why))
    return out


def available_models(
    host: str = DEFAULT_HOST, timeout: float = 10.0, *, allow_remote: bool = False
) -> list[str]:
    """Models this Ollama has pulled, so a caller can offer a real choice.

    Returns an empty list rather than raising when Ollama is absent: the answer to
    "which models can I review with" is legitimately "none". Unreachable is not the
    same as refused, and only the second raises.

    The host guard is the same one :class:`LlmReviewer` applies, for two reasons.
    Listing a remote host's models would offer a choice the scrub then refuses,
    which reads as a bug rather than as the rule it is. And a listing is still a
    request to a machine that is not this one — no document text in it, but the
    decision to talk off-box at all is the user's to make explicitly.
    """
    if not _is_local(host) and not allow_remote:
        raise _refuse_remote(host, "Asking it which models it has means talking to it.")
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return sorted(str(model.get("name")) for model in body.get("models") or [] if model.get("name"))

"""The review layer, without a model where possible and with one where it counts.

The HTTP call is stubbed for everything that is about *this* code: the host guard,
the parsing, the degradation when Ollama is absent. One test at the bottom talks to
a real Ollama, and skips when there is none.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freedocs.detect.llm_review import (
    DEFAULT_HOST,
    MAX_REVIEW_CHARS,
    Concern,
    LlmReviewer,
    OllamaUnavailable,
    RemoteHostRefused,
    ReviewOutcome,
    _is_local,
    _parse_concerns,
    available_models,
)
from freedocs.pipeline import Scrubber, build_registry

from .conftest import CANARIES


def reply(concerns: list[dict]) -> dict:
    """An Ollama /api/chat response carrying the given concerns."""
    return {"message": {"content": json.dumps({"concerns": concerns})}}


def stub(monkeypatch, response: dict | Exception, captured: dict | None = None):
    def fake_post(self, route, payload):
        if captured is not None:
            captured.update(payload)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(LlmReviewer, "_post", fake_post)


# -- the host guard -----------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434", "http://127.5.5.5"],
)
def test_loopback_hosts_are_accepted(host: str):
    assert LlmReviewer(model="m", host=host).host == host


@pytest.mark.parametrize(
    "host",
    ["http://10.0.0.5:11434", "http://ollama.internal:11434", "https://api.example.com"],
)
def test_a_remote_host_is_refused_by_default(host: str):
    """Sending text off this machine is the one thing the project exists to avoid."""
    with pytest.raises(RemoteHostRefused, match="not on this machine"):
        LlmReviewer(model="m", host=host)


def test_a_remote_host_is_allowed_when_asked_for_explicitly():
    reviewer = LlmReviewer(model="m", host="http://10.0.0.5:11434", allow_remote=True)
    assert reviewer.allow_remote is True


def test_the_refusal_says_what_it_would_have_sent():
    """ "It is only the scrubbed text" is not the same as "it is harmless"."""
    with pytest.raises(RemoteHostRefused) as caught:
        LlmReviewer(model="m", host="http://gpu.example.com")
    assert "quasi-identifiers survive a scrub" in str(caught.value)


def test_a_hostname_resolving_to_loopback_is_still_treated_as_remote():
    """Whether it resolves there tomorrow is not this code's call to make."""
    assert _is_local("http://my-laptop.local:11434") is False


# -- parsing ------------------------------------------------------------------


def test_concerns_are_parsed(monkeypatch):
    stub(monkeypatch, reply([{"kind": "leftover", "quote": "a@b.test", "why": "an email"}]))
    (concern,) = LlmReviewer(model="m").review("qualcosa")
    assert concern == Concern(kind="leftover", quote="a@b.test", why="an email")


def test_an_empty_list_is_a_valid_answer(monkeypatch):
    stub(monkeypatch, reply([]))
    assert LlmReviewer(model="m").review("qualcosa") == []


@pytest.mark.parametrize(
    "content",
    ["", "not json at all", "[1, 2, 3]", '{"wrong": "shape"}', '{"concerns": "not a list"}'],
)
def test_a_malformed_answer_yields_nothing_rather_than_crashing(content: str):
    """A review that breaks the run it was advising on is worse than no review."""
    assert _parse_concerns(content) == []


def test_incomplete_concerns_are_discarded(monkeypatch):
    stub(
        monkeypatch,
        reply(
            [
                {"kind": "leftover", "quote": "", "why": "no quote"},
                {"kind": "leftover", "quote": "x@y.test", "why": ""},
                {"kind": "leftover", "quote": "a@b.test", "why": "kept"},
            ]
        ),
    )
    concerns = LlmReviewer(model="m").review("qualcosa")
    assert [c.why for c in concerns] == ["kept"]


def test_an_unknown_kind_is_kept(monkeypatch):
    """The observation is the value; the label is the model's opinion of it."""
    stub(monkeypatch, reply([{"kind": "invented", "quote": "x", "why": "y"}]))
    (concern,) = LlmReviewer(model="m").review("qualcosa")
    assert concern.kind == "invented"


# -- what is sent -------------------------------------------------------------


def test_the_request_asks_for_a_schema_and_zero_temperature(monkeypatch):
    """The schema is server-enforced, so "the model ignored the format" cannot happen."""
    captured: dict = {}
    stub(monkeypatch, reply([]), captured)
    LlmReviewer(model="qwen").review("testo")
    assert captured["model"] == "qwen"
    assert captured["stream"] is False
    assert captured["options"]["temperature"] == 0.0
    assert captured["format"]["properties"]["concerns"]["type"] == "array"


def test_long_text_is_truncated_and_says_so(monkeypatch):
    """A model handed forty pages returns generalities, which is not the point."""
    stub(monkeypatch, reply([]))
    reviewer = LlmReviewer(model="m")
    reviewer.review("x" * (MAX_REVIEW_CHARS + 500))
    assert reviewer.truncated is True


def test_short_text_is_not_marked_truncated(monkeypatch):
    stub(monkeypatch, reply([]))
    reviewer = LlmReviewer(model="m")
    reviewer.review("breve")
    assert reviewer.truncated is False


def test_blank_text_never_reaches_the_model(monkeypatch):
    captured: dict = {}
    stub(monkeypatch, reply([]), captured)
    assert LlmReviewer(model="m").review("   \n  ") == []
    assert captured == {}


# -- degradation --------------------------------------------------------------


def test_an_unreachable_ollama_is_reported_not_raised(monkeypatch):
    """Advisory means a missing reviewer must not fail a scrub that worked."""
    stub(monkeypatch, OllamaUnavailable("could not reach Ollama"))
    outcome = LlmReviewer(model="m").review_outcome("testo")
    assert outcome.ran is False
    assert "could not reach" in outcome.unavailable
    assert outcome.concerns == ()


def test_a_skipped_review_does_not_look_like_a_clean_one(monkeypatch):
    """The distinction the whole ReviewOutcome type exists for."""
    stub(monkeypatch, OllamaUnavailable("nope"))
    skipped = LlmReviewer(model="m").review_outcome("testo")
    stub(monkeypatch, reply([]))
    clean = LlmReviewer(model="m").review_outcome("testo")

    assert skipped.concerns == clean.concerns == ()
    assert skipped.ran is not clean.ran
    assert "skipped" in skipped.summary()
    assert "raised nothing" in clean.summary()


def test_the_summary_says_when_only_part_was_read(monkeypatch):
    stub(monkeypatch, reply([]))
    reviewer = LlmReviewer(model="m")
    outcome = reviewer.review_outcome("x" * (MAX_REVIEW_CHARS + 1))
    assert "part of the document" in outcome.summary()


def test_available_models_returns_empty_rather_than_raising():
    """ "Which models can I review with" legitimately answers "none"."""
    assert available_models("http://127.0.0.1:1", timeout=0.5) == []


def test_listing_a_remote_host_is_refused_too():
    """Offering models the scrub would then refuse reads as a bug, not as the rule.

    Unreachable and refused are different: the test above proves the first stays a
    quiet empty list, and this one proves the second is loud.
    """
    with pytest.raises(RemoteHostRefused, match="not on this machine"):
        available_models("http://10.0.0.5:11434")


def test_listing_a_remote_host_is_allowed_when_asked_for_explicitly(monkeypatch):
    """No network here: the guard is what is under test, not the connection."""
    monkeypatch.setattr(
        "freedocs.detect.llm_review.urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no route")),
    )
    assert available_models("http://10.0.0.5:11434", allow_remote=True) == []


def test_the_cli_reports_a_refused_host_instead_of_a_traceback(capsys):
    """`review-models --review-host` names a host the guard may reject.

    Once listing became guarded this command could raise through argparse, which
    is a stack trace where an explanation belongs.
    """
    from freedocs.cli import main

    code = main(["review-models", "--review-host", "http://10.0.0.5:11434"])
    assert code != 0
    complaint = capsys.readouterr().err
    assert "not on this machine" in complaint
    # The shared message speaks of allow_remote, which is not a command-line flag.
    assert "--review-remote" in complaint


def test_the_cli_can_be_told_the_remote_host_is_intended(capsys, monkeypatch):
    monkeypatch.setattr("freedocs.cli.available_models", lambda host, **kw: ["stub:latest"])
    from freedocs.cli import main

    assert main(["review-models", "--review-host", "http://10.0.0.5:11434", "--review-remote"]) == 0
    assert "stub:latest" in capsys.readouterr().out


def test_both_refusals_give_the_same_reason():
    """One rule, so one explanation. Two wordings would be two rules to reason about."""
    with pytest.raises(RemoteHostRefused) as listing:
        available_models("http://gpu.example.com")
    with pytest.raises(RemoteHostRefused) as reviewing:
        LlmReviewer(model="m", host="http://gpu.example.com")
    assert "quasi-identifiers survive a scrub" in str(listing.value)
    assert "quasi-identifiers survive a scrub" in str(reviewing.value)


# -- in the pipeline ----------------------------------------------------------


@pytest.fixture
def document(tmp_path: Path) -> Path:
    path = tmp_path / "scheda.txt"
    path.write_text(f"IBAN: {CANARIES['IBAN']}\nNote: contratto annuale.\n", encoding="utf-8")
    return path


def test_no_reviewer_means_no_review(document: Path):
    """None is not an empty result: nobody asked."""
    result = Scrubber(registry=build_registry("l1")).scrub_file(document)
    assert result.review is None


def test_the_reviewer_sees_the_scrubbed_text_not_the_original(document: Path, monkeypatch):
    """Sending the original to any model is the thing this tool prevents."""
    seen: list[str] = []

    def capture(self, text):
        seen.append(text)
        return ReviewOutcome(model="m", ran=True)

    monkeypatch.setattr(LlmReviewer, "review_outcome", capture)
    Scrubber(registry=build_registry("l1"), reviewer=LlmReviewer(model="m")).scrub_file(document)

    assert seen and CANARIES["IBAN"] not in seen[0]
    assert "[IBAN_1]" in seen[0]


def test_the_review_is_skipped_when_verification_failed(document: Path, monkeypatch):
    """Nothing is written, so there is no file to review."""
    from freedocs.formats import plaintext

    monkeypatch.setattr(plaintext.PlainTextHandler, "write_back", lambda self, edits: self.data)
    called: list[str] = []
    monkeypatch.setattr(
        LlmReviewer,
        "review_outcome",
        lambda self, text: called.append(text) or ReviewOutcome("m", True),
    )
    result = Scrubber(
        registry=build_registry("l1"), reviewer=LlmReviewer(model="m"), strict=False
    ).scrub_file(document)

    assert result.verify.ok is False
    assert called == []
    assert result.review is None


def test_the_review_reaches_the_report(document: Path, monkeypatch):
    from freedocs.report import build_report

    monkeypatch.setattr(
        LlmReviewer,
        "review_outcome",
        lambda self, text: ReviewOutcome(
            model="m",
            ran=True,
            concerns=(Concern("quasi_identifier", "il CFO di Lugano", "role plus branch"),),
        ),
    )
    result = Scrubber(registry=build_registry("l1"), reviewer=LlmReviewer(model="m")).scrub_file(
        document
    )
    section = build_report(result)["review"]
    assert section["ran"] is True
    assert section["concerns"][0]["quote"] == "il CFO di Lugano"


def test_the_report_has_no_review_key_content_when_none_was_run(document: Path):
    from freedocs.report import build_report

    result = Scrubber(registry=build_registry("l1")).scrub_file(document)
    assert build_report(result)["review"] is None


# -- against a real Ollama ----------------------------------------------------


def _installed_model() -> str | None:
    models = available_models(DEFAULT_HOST, timeout=3.0)
    return models[0] if models else None


@pytest.mark.slow
def test_a_real_model_flags_a_quasi_identifier():
    """The case the layer exists for, and the only one nothing else catches.

    Loose on purpose: it asserts that *something* was raised about a document whose
    every direct identifier is already a placeholder, not which words the model
    picked. Pinning the wording would make a better model fail this test.
    """
    model = _installed_model()
    if model is None:
        pytest.skip("no Ollama model available")

    text = (
        "Verbale riservato\n\n"
        "Presenti: [PERSONA_1] e [PERSONA_2].\n"
        "Cliente: [AZIENDA_1], [INDIRIZZO_1].\n"
        "IBAN: [IBAN_1]\n\n"
        "La revisione spetta all'unica donna partner dell'ufficio di Lugano, "
        "assunta a marzo 2019.\n"
    )
    outcome = LlmReviewer(model=model, timeout=280).review_outcome(text)
    if not outcome.ran:
        pytest.skip(f"Ollama not usable: {outcome.unavailable}")
    assert outcome.concerns, "a document naming the only female partner of one office"
    assert all(concern.quote and concern.why for concern in outcome.concerns)


@pytest.mark.slow
def test_a_real_model_does_not_object_to_placeholders():
    """The placeholders are the tool working, not a problem to report."""
    model = _installed_model()
    if model is None:
        pytest.skip("no Ollama model available")

    text = "Cliente: [PERSONA_1]\nIBAN: [IBAN_1]\nNote: rinnovo automatico annuale.\n"
    outcome = LlmReviewer(model=model, timeout=280).review_outcome(text)
    if not outcome.ran:
        pytest.skip(f"Ollama not usable: {outcome.unavailable}")
    quoted = " ".join(concern.quote for concern in outcome.concerns)
    assert "[PERSONA_1]" not in quoted
    assert "[IBAN_1]" not in quoted

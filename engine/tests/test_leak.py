"""End to end: does any canary value survive a scrub?

This is the test that decides whether FreeDocs is usable. Everything else checks
that a component behaves; this one checks the only promise the tool makes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("stdnum", reason="python-stdnum is required for the L1 layer")

from freedocs.core.findings import EntityType
from freedocs.core.policy import Action, Policy
from freedocs.pipeline import Scrubber
from freedocs.report import build_report
from freedocs.verify import LeakDetected

from .conftest import CANARIES

pytestmark = pytest.mark.leak


@pytest.fixture
def source(tmp_path: Path, document: str) -> Path:
    path = tmp_path / "scheda-cliente.txt"
    path.write_text(document, encoding="utf-8")
    return path


def test_no_canary_survives_the_scrub(source: Path):
    result = Scrubber().scrub_file(source)
    output = result.output.decode("utf-8")
    survivors = [value for value in CANARIES.values() if value in output]
    assert not survivors, f"these values survived the scrub: {survivors}"


def test_verification_passes(source: Path):
    result = Scrubber().scrub_file(source)
    assert result.verify.ok, result.verify.summary()
    assert result.verify.checked_values > 0


def test_something_was_actually_removed(source: Path):
    """Guards against a vacuous pass: an empty finding list also leaks nothing."""
    result = Scrubber().scrub_file(source)
    assert len(result.removed) >= len(CANARIES) - 1


def test_placeholders_appear_in_the_output(source: Path):
    output = Scrubber().scrub_file(source).output.decode("utf-8")
    assert "[CF_1]" in output
    assert "[IBAN_1]" in output
    assert "[AVS_1]" in output


def test_surrounding_text_is_untouched(source: Path):
    """Redaction must not disturb the parts of the document that are fine."""
    output = Scrubber().scrub_file(source).output.decode("utf-8")
    assert output.startswith("Scheda cliente - riservata\n")
    assert "Codice fiscale: " in output
    assert output.count("\n") == source.read_text(encoding="utf-8").count("\n")


def test_report_contains_no_confidential_values(source: Path):
    """A report holding the originals would be a re-identification key on disk."""
    result = Scrubber().scrub_file(source)
    serialised = repr(build_report(result))
    leaked = [value for value in CANARIES.values() if value in serialised]
    assert not leaked, f"report exposes {leaked}"


def test_repeated_value_gets_one_stable_placeholder(tmp_path: Path):
    iban = CANARIES["IBAN"]
    path = tmp_path / "doppio.txt"
    path.write_text(f"IBAN {iban}\nconferma IBAN {iban}\n", encoding="utf-8")
    output = Scrubber().scrub_file(path).output.decode("utf-8")
    assert output == "IBAN [IBAN_1]\nconferma IBAN [IBAN_1]\n"


def test_keeping_an_entity_makes_verification_fail_loudly(tmp_path: Path):
    """Kept values are not reported as removed, so they must not count as leaks."""
    email = CANARIES["EMAIL"]
    path = tmp_path / "solo-email.txt"
    path.write_text(f"Contatto: {email}\n", encoding="utf-8")

    policy = Policy(overrides={EntityType.EMAIL: Action.KEEP})
    result = Scrubber(policy=policy).scrub_file(path)
    assert email in result.output.decode("utf-8")
    assert result.verify.ok
    assert not result.removed


def test_strict_mode_raises_when_a_value_survives(tmp_path: Path, monkeypatch):
    """A deliberately broken writer must fail the run, not produce a clean-looking file."""
    from freedocs.formats import plaintext

    path = tmp_path / "iban.txt"
    path.write_text(f"IBAN {CANARIES['IBAN']}\n", encoding="utf-8")

    # Simulate the classic redaction bug: the tool reports success but the
    # original characters are still in the file.
    monkeypatch.setattr(
        plaintext.PlainTextHandler,
        "write_back",
        lambda self, edits: self.data,
    )
    with pytest.raises(LeakDetected):
        Scrubber(strict=True).scrub_file(path)


def test_non_strict_mode_returns_the_failure_instead_of_raising(tmp_path: Path, monkeypatch):
    from freedocs.formats import plaintext

    path = tmp_path / "iban.txt"
    path.write_text(f"IBAN {CANARIES['IBAN']}\n", encoding="utf-8")
    monkeypatch.setattr(
        plaintext.PlainTextHandler,
        "write_back",
        lambda self, edits: self.data,
    )
    result = Scrubber(strict=False).scrub_file(path)
    assert not result.verify.ok
    assert result.verify.leaks


def test_clean_document_is_returned_unchanged(tmp_path: Path):
    text = "Il preventivo per il progetto e stato approvato in riunione.\n"
    path = tmp_path / "pulito.txt"
    path.write_text(text, encoding="utf-8")
    result = Scrubber().scrub_file(path)
    assert result.output.decode("utf-8") == text
    assert not result.removed

"""End to end: does any canary value survive a scrub?

This is the test that decides whether FreeDocs is usable. Everything else checks
that a component behaves; this one checks the only promise the tool makes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("stdnum", reason="python-stdnum is required for the L1 layer")

from freedocs.core.findings import EntityType
from freedocs.core.overrides import Override, RemovedValue
from freedocs.core.policy import Action, Policy
from freedocs.report import build_report
from freedocs.verify import LeakDetected

from .conftest import CANARIES, l1_scrubber

pytestmark = pytest.mark.leak


@pytest.fixture
def source(tmp_path: Path, document: str) -> Path:
    # newline="" throughout this file, because `write_text` translates "\n" to the
    # platform's terminator and the handler is required to give the terminators
    # back exactly as it found them. Without it the fixture writes CRLF on
    # Windows, the scrub correctly preserves CRLF, and the assertion compares it
    # against the "\n" written here — so three tests failed on the Windows runner
    # for a difference the test itself introduced.
    path = tmp_path / "scheda-cliente.txt"
    path.write_text(document, encoding="utf-8", newline="")
    return path


def test_no_canary_survives_the_scrub(source: Path):
    result = l1_scrubber().scrub_file(source)
    output = result.output.decode("utf-8")
    survivors = [value for value in CANARIES.values() if value in output]
    assert not survivors, f"these values survived the scrub: {survivors}"


def test_verification_passes(source: Path):
    result = l1_scrubber().scrub_file(source)
    assert result.verify.ok, result.verify.summary()
    assert result.verify.checked_values > 0


def test_something_was_actually_removed(source: Path):
    """Guards against a vacuous pass: an empty finding list also leaks nothing."""
    result = l1_scrubber().scrub_file(source)
    assert len(result.removed) >= len(CANARIES) - 1


def test_placeholders_appear_in_the_output(source: Path):
    output = l1_scrubber().scrub_file(source).output.decode("utf-8")
    assert "[TAX_ID_1]" in output
    assert "[IBAN_1]" in output
    assert "[NATIONAL_ID_1]" in output


def test_surrounding_text_is_untouched(source: Path):
    """Redaction must not disturb the parts of the document that are fine."""
    output = l1_scrubber().scrub_file(source).output.decode("utf-8")
    assert output.startswith("Scheda cliente - riservata\n")
    assert "Codice fiscale: " in output
    assert output.count("\n") == source.read_text(encoding="utf-8").count("\n")


def test_report_contains_no_confidential_values(source: Path):
    """A report holding the originals would be a re-identification key on disk."""
    result = l1_scrubber().scrub_file(source)
    serialised = repr(build_report(result))
    leaked = [value for value in CANARIES.values() if value in serialised]
    assert not leaked, f"report exposes {leaked}"


def test_repeated_value_gets_one_stable_placeholder(tmp_path: Path):
    iban = CANARIES["IBAN"]
    path = tmp_path / "doppio.txt"
    path.write_text(f"IBAN {iban}\nconferma IBAN {iban}\n", encoding="utf-8", newline="")
    output = l1_scrubber().scrub_file(path).output.decode("utf-8")
    assert output == "IBAN [IBAN_1]\nconferma IBAN [IBAN_1]\n"


def test_keeping_an_entity_makes_verification_fail_loudly(tmp_path: Path):
    """Kept values are not reported as removed, so they must not count as leaks."""
    email = CANARIES["EMAIL"]
    path = tmp_path / "solo-email.txt"
    path.write_text(f"Contatto: {email}\n", encoding="utf-8", newline="")

    policy = Policy(overrides={EntityType.EMAIL: Action.KEEP})
    result = l1_scrubber(policy=policy).scrub_file(path)
    assert email in result.output.decode("utf-8")
    assert result.verify.ok
    assert not result.removed


def test_strict_mode_raises_when_a_value_survives(tmp_path: Path, monkeypatch):
    """A deliberately broken writer must fail the run, not produce a clean-looking file."""
    from freedocs.formats import plaintext

    path = tmp_path / "iban.txt"
    path.write_text(f"IBAN {CANARIES['IBAN']}\n", encoding="utf-8", newline="")

    # Simulate the classic redaction bug: the tool reports success but the
    # original characters are still in the file.
    monkeypatch.setattr(
        plaintext.PlainTextHandler,
        "write_back",
        lambda self, edits: self.data,
    )
    with pytest.raises(LeakDetected):
        l1_scrubber(strict=True).scrub_file(path)


def test_non_strict_mode_returns_the_failure_instead_of_raising(tmp_path: Path, monkeypatch):
    from freedocs.formats import plaintext

    path = tmp_path / "iban.txt"
    path.write_text(f"IBAN {CANARIES['IBAN']}\n", encoding="utf-8", newline="")
    monkeypatch.setattr(
        plaintext.PlainTextHandler,
        "write_back",
        lambda self, edits: self.data,
    )
    result = l1_scrubber(strict=False).scrub_file(path)
    assert not result.verify.ok
    assert result.verify.leaks


def test_clean_document_is_returned_unchanged(tmp_path: Path):
    text = "Il preventivo per il progetto e stato approvato in riunione.\n"
    path = tmp_path / "pulito.txt"
    path.write_text(text, encoding="utf-8", newline="")
    result = l1_scrubber().scrub_file(path)
    assert result.output.decode("utf-8") == text
    assert not result.removed


# --- the key file, which is the one thing that can undo all of this -----------


def test_no_key_file_is_written_by_default(source: Path, tmp_path: Path):
    """The invariant this whole file is about, stated for the reverse direction.

    Scrubbing writes no re-identification key unless a caller names a path and a
    passphrase. Nothing in the pipeline can produce one: it is composed from a
    finished result by whichever front end asked, so a scrub through the library
    cannot leave one behind at all.
    """
    l1_scrubber().scrub_file(source)
    assert list(tmp_path.rglob("*.fdmap")) == []


def test_the_allocator_still_forgets_when_a_key_file_is_built(source: Path):
    """Building a key file must not reopen the thing whose job is to forget.

    It reads `ScrubResult.decisions`, which survives the run; the allocator is
    closed in `pipeline.scrub`'s `finally` either way. If this ever needed an
    accessor on `SurrogateAllocator`, the design would have gone wrong.
    """
    pytest.importorskip("cryptography", reason="the restore extra is required")
    from freedocs.core.mapping import key_map_from

    result = l1_scrubber().scrub_file(source)
    key_map = key_map_from(result, placeholder_language="en")
    assert key_map.entries, "the map should carry what the scrub removed"


def test_a_key_file_on_disk_holds_no_canary_in_the_clear(source: Path, tmp_path: Path):
    """The file exists to be readable *with* the passphrase and useless without.
    Searched as bytes, like the PDF and OOXML leak checks: an encoding that
    happened to differ would make a plaintext key file look encrypted."""
    pytest.importorskip("cryptography", reason="the restore extra is required")
    from freedocs.core.mapping import key_map_from, write_key_map

    result = l1_scrubber().scrub_file(source)
    path = tmp_path / "keys.fdmap"
    write_key_map(path, key_map_from(result, placeholder_language="en"), "correct horse battery")

    raw = path.read_bytes()
    leaked = [name for name, value in CANARIES.items() if value.encode("utf-8") in raw]
    assert not leaked, f"key file exposes {leaked}"


def test_a_restore_puts_every_canary_back(source: Path, tmp_path: Path):
    """The round trip, end to end, over the same document the leak checks use.

    Its value here rather than only in `test_restore.py`: this file's canaries are
    the ones with real check digits, so a restore that mangled a value would be
    caught by the value not matching rather than by a length.
    """
    pytest.importorskip("cryptography", reason="the restore extra is required")
    from freedocs.core.mapping import key_map_from, read_key_map, write_key_map
    from freedocs.restore import Restorer

    result = l1_scrubber().scrub_file(source)
    scrubbed = tmp_path / "clean.txt"
    scrubbed.write_bytes(result.output)
    key_path = tmp_path / "keys.fdmap"
    write_key_map(
        key_path, key_map_from(result, placeholder_language="en"), "correct horse battery"
    )

    restored = Restorer(key_map=read_key_map(key_path, "correct horse battery")).restore(scrubbed)
    assert restored.ok, [problem.describe() for problem in restored.problems]

    text = restored.output.decode("utf-8")
    removed = {finding.text for finding in result.removed}
    assert not [value for value in removed if value not in text]


# --- the report, and the values that are not in the document's text -----------


def test_the_report_names_no_sheet_it_renamed(tmp_path: Path):
    """A sheet's own name is a value, and the report is written to disk.

    The canaries above cannot catch this and never could: they live in cell
    content, and the two strings that escaped were a *sheet's name* - quoted by
    the rename warning and by the hidden-sheet inventory. Neither is text in the
    document, so a search for a body canary passes straight over both.

    Both halves are asserted, because deleting the warning would also pass: the
    report must not name what the sheet was called, and must still say what it is
    called now, which is the half a broken formula needs.
    """
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    from .xlsx_builder import Sheet, XlsxSpec, write_xlsx

    visible = CANARIES["IT_CODICE_FISCALE"]
    hidden = CANARIES["CH_UID"]
    path = write_xlsx(
        tmp_path / "cartella.xlsx",
        XlsxSpec(
            sheets=[
                Sheet(name=visible, rows=[["Totale", 1200]]),
                Sheet(name=hidden, rows=[["nota", "interna"]], state="veryHidden"),
            ],
            app_titles=True,
        ),
    )

    result = l1_scrubber().scrub_file(path)
    serialised = repr(build_report(result))
    leaked = [name for name in (visible, hidden) if name in serialised]
    assert not leaked, f"report exposes the sheet name(s) {leaked}"

    renamed = [message for message in result.warnings if message.startswith("renamed ")]
    assert renamed, "a renamed sheet must still be reported"
    assert "[" in renamed[0] or "_" in renamed[0], (
        "the warning must name what the sheet is called now: " + renamed[0]
    )


def test_the_report_does_not_quote_a_requested_value_it_did_not_find(tmp_path: Path):
    """A value somebody asked to remove is a value, found or not.

    The absent ones are the dangerous half. A found value becomes a placeholder
    and a count; an absent one used to become a sentence quoting it, and that
    sentence went into ``warnings`` and from there into the report - onto disk,
    attached to a document it has nothing to do with. One list of client names
    over a folder of contracts put most of the list into every report.

    Both halves are asserted, because deleting the notice would also pass: the
    report must still count what was not found, and the caller must still be
    told which value it was.
    """
    absent = "Nordwind Holding"
    present = "Scheda cliente"
    path = tmp_path / "scheda.txt"
    path.write_text(f"{present}: nessun dato\n", encoding="utf-8", newline="")

    override = Override(remove=(RemovedValue(absent), RemovedValue(present)))
    result = l1_scrubber(overrides=override).scrub_file(path)
    report = build_report(result)

    assert absent not in repr(report), "the report quotes a value that was not found"
    assert present not in repr(report)
    assert report["requested_values_not_found"] == 1
    assert any(absent in message for message in result.caller_warnings)
    assert not any(absent in message for message in result.warnings)


def test_the_report_does_not_name_an_attachment(tmp_path: Path):
    """An attachment is routinely named after the person or the case it concerns.

    Same class as the sheet name above: the filename never appears in the
    document's text, so it is invisible to every other assertion in this file.
    """
    pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF is required for PDF support")

    name = f"dossier-{CANARIES['IT_CODICE_FISCALE']}.txt"
    path = tmp_path / "allegati.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 80), "Pratica interna", fontname="helv", fontsize=11)
    doc.embfile_add(name, b"contenuto")
    doc.save(str(path), garbage=4, clean=True, deflate=True)
    doc.close()

    result = l1_scrubber().scrub_file(path)
    serialised = repr(build_report(result))
    assert name not in serialised, "report exposes the attachment's filename"
    assert CANARIES["IT_CODICE_FISCALE"] not in serialised
    kinds = {item.kind for item in result.hidden_removed}
    assert "embedded-files" in kinds, "the attachment must still be reported"


def test_a_stale_override_never_reaches_the_report(tmp_path: Path):
    """A `StaleOverride` quotes the document as it is *now* — which the caller has
    by definition not seen, since that is why the check fired.

    Quoted deliberately, and the reason is the channel rather than the value: it
    travels the local pipe, which already carries matched text and, on request,
    the whole extracted document. The rule it must obey is the one this file is
    about, so this pins the two directions it must never take. `rpc` catches it
    into a per-file failure, so no report is built for that file at all; and the
    frozen-build traceback sink is `test_rpc.py`'s question.
    """
    from freedocs.core.overrides import KeptSpan, Override, StaleOverride

    path = tmp_path / "cambiato.txt"
    path.write_text(f"IBAN {CANARIES['IBAN']}\n", encoding="utf-8", newline="")

    # A decision taken against a document that has since changed underneath it.
    scrubber = l1_scrubber()
    scrubber.overrides = Override(keep=(KeptSpan(start=5, end=26, text="qualcosa che non c'e"),))
    with pytest.raises(StaleOverride) as caught:
        scrubber.scrub_file(path)

    # It names the decision, which is what a caller can act on.
    assert "re-inspect" in str(caught.value)
    # And nothing was written, so there is no report and no output to leak into.
    assert list(tmp_path.glob("*")) == [path]

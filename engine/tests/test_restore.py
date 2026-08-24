"""The reverse path: does the value come back, and is the failure visible?

Two questions, and the second matters more. A restore that quietly does nothing
produces a document full of placeholders that a person then sends to a client, so
every test that asserts a successful round trip has a sibling asserting the
report says what did not happen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("stdnum", reason="python-stdnum is required for the L1 layer")

from freedocs.core.findings import EntityType
from freedocs.core.mapping import KeyMap, MapEntry, key_map_from
from freedocs.report import build_restore_report
from freedocs.restore import PLACEHOLDER_SHAPE, RESTORE_STAGES, Restorer

from .conftest import CANARIES, l1_scrubber


def _map(*entries: tuple[str, str, EntityType]) -> KeyMap:
    return KeyMap(
        document="doc.txt",
        format_name="plaintext",
        output_sha256="",
        placeholder_language="en",
        entries=tuple(
            MapEntry(
                placeholder=placeholder,
                value=value,
                entity=entity,
                country=None,
                occurrences=1,
                variants=1,
            )
            for placeholder, value, entity in entries
        ),
    )


def _restore(key_map: KeyMap, source: Path):
    return Restorer(key_map=key_map).restore(source)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    # newline="" for the reason test_leak.py gives: write_text would translate
    # "\n" to CRLF on Windows and the comparison would fail on a difference the
    # test introduced.
    path.write_text(text, encoding="utf-8", newline="")
    return path


# -- the plain round trip ------------------------------------------------------


def test_a_scrub_and_a_restore_return_the_document(tmp_path: Path, document: str):
    """The one test the feature exists for."""
    source = _write(tmp_path, "scheda.txt", document)
    result = l1_scrubber().scrub_file(source)
    key_map = key_map_from(result, placeholder_language="en")

    scrubbed = _write(tmp_path, "clean.txt", result.output.decode("utf-8"))
    restored = Restorer(key_map=key_map).restore(scrubbed)

    assert restored.ok, [problem.describe() for problem in restored.problems]
    assert restored.output.decode("utf-8") == document
    assert restored.unused == ()
    assert restored.unknown == ()


def test_every_canary_comes_back(tmp_path: Path, document: str):
    source = _write(tmp_path, "scheda.txt", document)
    result = l1_scrubber().scrub_file(source)
    scrubbed = _write(tmp_path, "clean.txt", result.output.decode("utf-8"))

    text = (
        Restorer(key_map=key_map_from(result, placeholder_language="en"))
        .restore(scrubbed)
        .output.decode("utf-8")
    )
    removed = {finding.text for finding in result.removed}
    missing = [value for value in removed if value not in text]
    assert not missing


def test_every_occurrence_is_restored(tmp_path: Path):
    """One placeholder, three occurrences: the count in the report is the count in
    the returned document, not the count the scrub replaced."""
    key_map = _map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON))
    source = _write(tmp_path, "in.txt", "[PERSON_1] a, [PERSON_1] b, [PERSON_1] c.\n")

    result = Restorer(key_map=key_map).restore(source)
    assert result.output.decode("utf-8").count("Mario Rossi") == 3
    (entry,) = result.restored
    assert entry.occurrences == 3
    assert entry.expected == 1


# -- what the closing bracket buys ---------------------------------------------


def test_a_single_digit_placeholder_is_not_confused_with_a_two_digit_one(tmp_path: Path):
    """`[PERSON_1]` cannot prefix-match `[PERSON_11]`, because the bracket ends the
    token. That is the one place the brackets earn their keep, and it is why no
    longest-match ordering is needed."""
    key_map = _map(
        ("[PERSON_1]", "Uno", EntityType.PERSON),
        ("[PERSON_11]", "Undici", EntityType.PERSON),
    )
    source = _write(tmp_path, "in.txt", "[PERSON_11] then [PERSON_1].\n")

    text = Restorer(key_map=key_map).restore(source).output.decode("utf-8")
    assert text == "Undici then Uno.\n"


# -- what the model did to the placeholders ------------------------------------


def test_a_translated_stem_is_reported_and_left_alone(tmp_path: Path):
    """`[PERSONA_1]` out of an English scrub is the model translating a token.
    Guessing which entry it meant would write a real value into a position nobody
    chose, so it is reported instead."""
    key_map = _map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON))
    source = _write(tmp_path, "in.txt", "[PERSON_1] and [PERSONA_1].\n")

    result = Restorer(key_map=key_map).restore(source)
    assert result.unknown == ("[PERSONA_1]",)
    assert "[PERSONA_1]" in result.output.decode("utf-8")
    assert "Mario Rossi and [PERSONA_1]" in result.output.decode("utf-8")


def test_an_invented_placeholder_is_reported(tmp_path: Path):
    key_map = _map(("[IBAN_1]", CANARIES["IBAN"], EntityType.IBAN))
    source = _write(tmp_path, "in.txt", "[IBAN_1] and [IBAN_9].\n")

    result = Restorer(key_map=key_map).restore(source)
    assert result.unknown == ("[IBAN_9]",)


@pytest.mark.parametrize(
    "token",
    ["[ PERSON_1 ]", "[person_1]", "**[PERSON_1]**"],
)
def test_a_reformatted_token_is_not_matched_loosely(tmp_path: Path, token: str):
    """Literal only. A tolerant match is how somebody else's value lands in the
    document, and the visible placeholder is the better failure."""
    key_map = _map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON))
    source = _write(tmp_path, "in.txt", f"only {token} here.\n")

    result = Restorer(key_map=key_map).restore(source)
    text = result.output.decode("utf-8")
    if token == "**[PERSON_1]**":
        # The token itself is intact; only its markdown wrapper is new, so this
        # one *is* a literal match and must be restored.
        assert "Mario Rossi" in text
    else:
        assert "Mario Rossi" not in text
        assert result.unused == ("[PERSON_1]",)


def test_a_placeholder_the_model_dropped_is_reported_not_silent(tmp_path: Path):
    """ "Restored" and "was not there" look identical in the output, which is the
    same reason `Override.unmatched` exists."""
    key_map = _map(
        ("[PERSON_1]", "Mario Rossi", EntityType.PERSON),
        ("[EMAIL_1]", CANARIES["EMAIL"], EntityType.EMAIL),
    )
    source = _write(tmp_path, "in.txt", "only [PERSON_1] survived the summary.\n")

    result = Restorer(key_map=key_map).restore(source)
    assert result.unused == ("[EMAIL_1]",)
    assert result.ok, "a value the model dropped is not a restore failure"


def test_the_shape_pattern_only_matches_our_own_shape():
    assert PLACEHOLDER_SHAPE.findall("[PERSON_1] [A_2] [X9_10]") == [
        "[PERSON_1]",
        "[A_2]",
        "[X9_10]",
    ]
    # Not ours: lowercase, no number, a nested bracket, a bare word in brackets.
    assert PLACEHOLDER_SHAPE.findall("[person_1] [PERSON] [see 1] [PERSON_]") == []


# -- nothing is invented -------------------------------------------------------


def test_an_empty_map_changes_nothing(tmp_path: Path):
    source = _write(tmp_path, "in.txt", "[PERSON_1] stays exactly where it is.\n")
    result = Restorer(key_map=_map()).restore(source)
    assert result.output.decode("utf-8") == "[PERSON_1] stays exactly where it is.\n"
    assert result.restored == ()
    assert result.unknown == ("[PERSON_1]",)


def test_hidden_content_is_not_stripped_from_the_returned_document(tmp_path: Path):
    """`scrub_hidden()` is deliberately not called. The returned document's
    metadata belongs to whoever produced it, and deleting it would be this tool
    editing a file it was asked to fill in."""
    lxml = pytest.importorskip("lxml", reason="the ooxml extra is required")
    assert lxml
    from .docx_builder import DocxSpec, all_part_text, write_docx

    source = write_docx(
        tmp_path / "in.docx",
        DocxSpec(paragraphs=[["[PERSON_1] signs."]], creator="Somebody Else"),
    )
    result = _restore(_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)), source)
    assert "Somebody Else" in all_part_text(result.output)


# -- per format ----------------------------------------------------------------


def test_docx_round_trip(tmp_path: Path):
    pytest.importorskip("lxml", reason="the ooxml extra is required")
    from .docx_builder import DocxSpec, all_part_text, write_docx

    source = write_docx(
        tmp_path / "in.docx",
        # Split across runs on purpose: a value that arrives longer than the token
        # it replaces must still land in the first anchor and leave the others'
        # formatting alone.
        DocxSpec(paragraphs=[["Cliente ", "[PERSON_1]", ", conto ", "[IBAN_1]", "."]]),
    )
    key_map = _map(
        ("[PERSON_1]", "Mario Rossi", EntityType.PERSON),
        ("[IBAN_1]", CANARIES["IBAN"], EntityType.IBAN),
    )
    result = Restorer(key_map=key_map).restore(source)

    assert result.ok, [problem.describe() for problem in result.problems]
    text = all_part_text(result.output)
    assert "Mario Rossi" in text
    assert CANARIES["IBAN"] in text
    assert "[PERSON_1]" not in text


def test_a_placeholder_split_across_runs_is_restored(tmp_path: Path):
    """The model rewrote a paragraph and Word split the token across two runs.
    `plan_edits` puts the whole replacement in the first anchor and clears the
    rest, which is the same mechanism the scrub relies on."""
    pytest.importorskip("lxml", reason="the ooxml extra is required")
    from .docx_builder import DocxSpec, all_part_text, write_docx

    source = write_docx(
        tmp_path / "in.docx", DocxSpec(paragraphs=[["Cliente [PERS", "ON_1] firma."]])
    )
    result = _restore(_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)), source)

    assert "Mario Rossi" in all_part_text(result.output)
    assert result.ok


def test_xlsx_round_trip(tmp_path: Path):
    pytest.importorskip("lxml", reason="the ooxml extra is required")
    from .xlsx_builder import Sheet, XlsxSpec, part_text, write_xlsx

    source = write_xlsx(
        tmp_path / "in.xlsx",
        XlsxSpec(sheets=[Sheet(name="Clienti", rows=[["Nome", "[PERSON_1]"]])]),
    )
    result = _restore(_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)), source)

    assert result.ok, [problem.describe() for problem in result.problems]
    assert "Mario Rossi" in part_text(result.output, "xl/sharedStrings.xml")


def test_a_placeholder_split_by_a_cell_boundary_is_reported(tmp_path: Path):
    """Two cells joined by a tab put a separator inside the token, so no literal
    match exists. Reported as absent rather than guessed at."""
    pytest.importorskip("lxml", reason="the ooxml extra is required")
    from .xlsx_builder import Sheet, XlsxSpec, write_xlsx

    source = write_xlsx(
        tmp_path / "in.xlsx",
        XlsxSpec(sheets=[Sheet(name="Clienti", rows=[["[PERSON", "_1]"]])]),
    )
    result = _restore(_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)), source)

    assert result.unused == ("[PERSON_1]",)
    assert result.restored == ()


# -- the check that runs both directions ---------------------------------------


def test_verification_reports_a_value_that_never_arrived(tmp_path: Path, monkeypatch):
    """The load-bearing half. A handler that drops a replacement removes the
    placeholder and writes nothing, which a one-directional check reads as
    success - and that is exactly what PyMuPDF does when a value does not fit."""
    from freedocs.formats import plaintext

    source = _write(tmp_path, "in.txt", "cliente [PERSON_1].\n")

    def drop_everything(self, edits):
        return b"cliente .\n"

    monkeypatch.setattr(plaintext.PlainTextHandler, "write_back", drop_everything)
    result = _restore(_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)), source)

    assert not result.ok
    (problem,) = result.problems
    assert problem.kind == "value-missing"
    assert problem.placeholder == "[PERSON_1]"


def test_verification_reports_a_placeholder_that_survived(tmp_path: Path, monkeypatch):
    from freedocs.formats import plaintext

    source = _write(tmp_path, "in.txt", "cliente [PERSON_1].\n")

    def change_nothing(self, edits):
        return b"cliente [PERSON_1].\n"

    monkeypatch.setattr(plaintext.PlainTextHandler, "write_back", change_nothing)
    result = _restore(_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)), source)

    assert not result.ok
    (problem,) = result.problems
    assert problem.kind == "placeholder-survived"


def test_a_problem_is_described_without_its_value(tmp_path: Path, monkeypatch):
    """The message travels to stderr, into a report and through the RPC layer, so
    it names the placeholder and never the original."""
    from freedocs.formats import plaintext

    source = _write(tmp_path, "in.txt", "conto [IBAN_1].\n")

    def drop_everything(self, edits):
        return b"conto .\n"

    monkeypatch.setattr(plaintext.PlainTextHandler, "write_back", drop_everything)
    result = _restore(_map(("[IBAN_1]", CANARIES["IBAN"], EntityType.IBAN)), source)

    (problem,) = result.problems
    assert CANARIES["IBAN"] not in problem.describe()
    assert "[IBAN_1]" in problem.describe()


def test_the_output_is_written_even_when_incomplete(tmp_path: Path, monkeypatch):
    """The deliberate asymmetry with stage 6. A scrub that leaks writes nothing;
    a half-restored document is still the caller's best artifact and its defect is
    visible in it."""
    from freedocs.formats import plaintext

    source = _write(tmp_path, "in.txt", "cliente [PERSON_1].\n")
    monkeypatch.setattr(
        plaintext.PlainTextHandler, "write_back", lambda self, edits: b"cliente [PERSON_1].\n"
    )
    result = _restore(_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)), source)

    assert not result.ok
    assert result.output, "an incomplete restore still returns its bytes"


# -- progress and reporting ----------------------------------------------------


def test_the_stages_are_announced_in_order_and_claim_no_percentage(tmp_path: Path):
    seen = []
    source = _write(tmp_path, "in.txt", "cliente [PERSON_1].\n")
    Restorer(
        key_map=_map(("[PERSON_1]", "Mario Rossi", EntityType.PERSON)),
        progress=seen.append,
    ).restore(source)

    names = [event.stage for event in seen]
    assert names[0] == "router"
    assert names[-1] == "verify"
    assert set(names) <= set(RESTORE_STAGES)
    assert all(event.count == len(RESTORE_STAGES) for event in seen)
    assert not any(hasattr(event, "percent") for event in seen)


def test_the_match_stage_counts_entries_because_it_can(tmp_path: Path):
    """`done`/`of` only where a stage has a real unit. Matching has one - map
    entries - and the other four do not, so they leave it None."""
    seen = []
    source = _write(tmp_path, "in.txt", "cliente [PERSON_1].\n")
    Restorer(
        key_map=_map(
            ("[PERSON_1]", "Mario Rossi", EntityType.PERSON),
            ("[EMAIL_1]", CANARIES["EMAIL"], EntityType.EMAIL),
        ),
        progress=seen.append,
    ).restore(source)

    matches = [event for event in seen if event.stage == "match"]
    assert matches and all(event.of == 2 for event in matches)
    assert matches[-1].done == 2


def test_the_restore_report_carries_no_values(tmp_path: Path, document: str):
    """The mirror of `test_report_contains_no_confidential_values`. A placeholder
    is a label the scrubbed document already published; the value behind it is
    what this file must never hold."""
    source = _write(tmp_path, "scheda.txt", document)
    result = l1_scrubber().scrub_file(source)
    scrubbed = _write(tmp_path, "clean.txt", result.output.decode("utf-8"))
    restored = Restorer(key_map=key_map_from(result, placeholder_language="en")).restore(scrubbed)

    serialised = repr(build_restore_report(restored))
    leaked = [name for name, value in CANARIES.items() if value in serialised]
    assert not leaked, f"restore report exposes {leaked}"


def test_the_lossy_round_trip_is_stated_in_the_warnings(tmp_path: Path):
    key_map = KeyMap(
        document="doc.txt",
        format_name="plaintext",
        output_sha256="",
        placeholder_language="en",
        entries=(
            MapEntry(
                placeholder="[PERSON_1]",
                value="Mario Rossi",
                entity=EntityType.PERSON,
                country=None,
                occurrences=2,
                variants=2,
            ),
        ),
    )
    source = _write(tmp_path, "in.txt", "[PERSON_1] and [PERSON_1].\n")
    result = Restorer(key_map=key_map).restore(source)
    assert any("more than one" in message for message in result.warnings)

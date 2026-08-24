"""The GUI contract, exercised without a GUI.

Every one of these runs the real dispatch over real files, because the protocol
is the only thing the desktop app can see. A shape change here is a broken app,
and the app cannot be unit-tested nearly as cheaply as this can.
"""

from __future__ import annotations

import io
import json
import os
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from freedocs.core.findings import EntityType
from freedocs.rpc import (
    INVALID_REQUEST,
    LEAK_DETECTED,
    METHOD_NOT_FOUND,
    MISSING_DEPENDENCY,
    NEEDS_OCR,
    UNSUPPORTED_FORMAT,
    RpcError,
    Session,
    handle,
    serve,
)

from .conftest import CANARIES


@pytest.fixture
def session() -> Session:
    return Session(out=io.StringIO())


@pytest.fixture
def document(tmp_path: Path) -> Path:
    path = tmp_path / "scheda.txt"
    path.write_text(
        "Scheda cliente\n"
        f"Codice fiscale: {CANARIES['IT_CODICE_FISCALE']}\n"
        f"IBAN: {CANARIES['IBAN']}\n"
        "Ordine 90210 del 03.03.2024\n",
        encoding="utf-8",
    )
    return path


def call(session: Session, method: str, **params) -> dict:
    """Send one request, pinned to the checksum layer unless told otherwise.

    These tests are about the protocol, not about detection quality: the shape of
    a response is what the desktop app depends on. Letting them load the NER model
    tripled the whole suite's runtime for no extra coverage, since the benchmark
    already measures what the model finds.
    """
    params.setdefault("detectors", "l1")
    request = {"jsonrpc": "2.0", "id": 7, "method": method, "params": params}
    response = handle(session, json.dumps(request))
    assert response is not None
    assert response["id"] == 7
    return response


def result_of(session: Session, method: str, **params) -> dict:
    response = call(session, method, **params)
    assert "error" not in response, response["error"]
    return response["result"]


def error_of(session: Session, method: str, **params) -> dict:
    response = call(session, method, **params)
    assert "result" not in response
    return response["error"]


# -- framing ------------------------------------------------------------------


def test_malformed_json_is_answered_not_crashed(session: Session):
    response = handle(session, "{not json")
    assert response["error"]["code"] == INVALID_REQUEST


def test_a_non_object_request_is_rejected(session: Session):
    assert handle(session, "[1, 2, 3]")["error"]["code"] == INVALID_REQUEST


def test_an_unknown_method_is_rejected(session: Session):
    assert error_of(session, "sudo")["code"] == METHOD_NOT_FOUND


def test_non_object_params_are_rejected(session: Session):
    response = handle(
        session, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "inspect", "params": [1]})
    )
    assert response["error"]["code"] == INVALID_REQUEST


def test_one_response_per_line(document: Path):
    """The transport is newline-delimited; an embedded newline breaks framing."""
    out = io.StringIO()
    requests = "\n".join(
        json.dumps({"jsonrpc": "2.0", "id": index, "method": "entities"}) for index in range(3)
    )
    serve(stdin=io.StringIO(requests), stdout=out)
    lines = [line for line in out.getvalue().splitlines() if line]
    # One "ready" notification plus one response each.
    assert len(lines) == 4
    for line in lines:
        json.loads(line)


def test_blank_lines_are_ignored(session: Session):
    out = io.StringIO()
    serve(stdin=io.StringIO('\n\n{"jsonrpc":"2.0","id":1,"method":"entities"}\n\n'), stdout=out)
    responses = [json.loads(line) for line in out.getvalue().splitlines() if line]
    assert sum(1 for item in responses if item.get("id") == 1) == 1


def test_the_session_announces_itself_on_startup():
    """The app renders capabilities before the user picks a file."""
    out = io.StringIO()
    serve(stdin=io.StringIO(""), stdout=out)
    first = json.loads(out.getvalue().splitlines()[0])
    assert first["method"] == "ready"
    assert "formats" in first["params"]


# -- capabilities -------------------------------------------------------------


def test_capabilities_lists_the_formats_actually_registered(session: Session):
    capabilities = result_of(session, "capabilities")
    assert ".pdf" in capabilities["formats"]
    assert ".docx" in capabilities["formats"]
    assert ".xlsx" in capabilities["formats"]
    assert ".pptx" in capabilities["formats"]


def test_capabilities_states_its_limitations(session: Session):
    """A missing optional dependency must be visible, not discovered later."""
    capabilities = result_of(session, "capabilities")
    assert isinstance(capabilities["limitations"], list)
    assert capabilities["caveats"], "the app must be able to show the caveats"
    assert isinstance(capabilities["ocr_available"], bool)


def test_capabilities_says_whether_the_model_travels_with_the_build(session: Session):
    """An enum, so the window translates it rather than quoting it.

    The window cannot work this out: whether the weights are bundled or fetched
    is a property of how the app was packaged. And it is not the path — a local
    filesystem path tells the window nothing it can act on, and `doctor` is where
    a path belongs.
    """
    assert result_of(session, "capabilities")["model_source"] == "hub"


def test_capabilities_reports_a_bundled_model_as_bundled(session: Session, monkeypatch, tmp_path):
    from .test_portable import write_payload

    monkeypatch.setenv("FREEDOCS_NER_MODEL", str(write_payload(tmp_path / "ner-model")))
    assert result_of(session, "capabilities")["model_source"] == "bundled"


def test_a_misconfigured_model_still_lets_capabilities_answer(
    session: Session, monkeypatch, tmp_path
):
    """A window that cannot ask what this build can do cannot report it is broken.

    So the refusal is tolerated here and raised where it matters, at load. The
    answer stays "bundled" rather than falling back to "hub", because a caller
    that was handed a path is not going to download.
    """
    empty = tmp_path / "not-a-model"
    empty.mkdir()
    monkeypatch.setenv("FREEDOCS_NER_MODEL", str(empty))
    assert result_of(session, "capabilities")["model_source"] == "bundled"


def test_capabilities_names_the_host_it_would_review_against(session: Session):
    """The app prefills from this rather than keeping its own copy of the address."""
    capabilities = result_of(session, "capabilities")
    assert capabilities["review_host"].startswith("http://127.0.0.1")
    assert isinstance(capabilities["review_models"], list)


# -- review_models ------------------------------------------------------------


def test_review_models_answers_for_the_host_it_was_given(session: Session):
    """Empty is a real answer; the point is that it says which host it means.

    Deliberately a port nothing listens on: this is about the response shape and
    about unreachable not being an error, so it must not depend on whether the
    machine running the suite happens to have Ollama.
    """
    found = result_of(session, "review_models", host="http://127.0.0.1:1")
    assert found["host"] == "http://127.0.0.1:1"
    assert found["models"] == []


def test_review_models_falls_back_to_the_default_host(session: Session):
    found = result_of(session, "review_models")
    assert found["host"].startswith("http://127.0.0.1")


def test_review_models_refuses_a_host_off_this_machine(session: Session):
    """Listing a host the scrub would then refuse reads as a bug, not as the rule."""
    error = error_of(session, "review_models", host="http://ollama.example.com:11434")
    assert error["code"] == INVALID_REQUEST
    assert "not on this machine" in error["message"]


def test_the_refusal_explains_itself_where_the_host_was_typed(session: Session):
    error = error_of(session, "review_models", host="http://10.0.0.5:11434")
    assert "quasi-identifiers survive a scrub" in error["message"]


def test_review_models_passes_an_explicit_remote_opt_in_through(session: Session, monkeypatch):
    """The pipe allows it explicitly. The window has no control for it by design.

    Stubbed rather than dialled: a real connection to an off-machine address sits
    on the timeout for ten seconds, and what is being checked here is that the
    flag reaches the guard, not that the internet works.
    """
    seen: dict = {}

    def fake_models(host, timeout=10.0, *, allow_remote=False):
        seen.update(host=host, allow_remote=allow_remote)
        return ["stub:latest"]

    monkeypatch.setattr("freedocs.rpc.available_models", fake_models)
    found = result_of(session, "review_models", host="http://10.0.0.5:11434", allow_remote=True)
    assert seen == {"host": "http://10.0.0.5:11434", "allow_remote": True}
    assert found["models"] == ["stub:latest"]


def test_entities_marks_the_report_only_ones(session: Session):
    entities = result_of(session, "entities")["entities"]
    by_name = {item["name"]: item for item in entities}
    assert by_name[EntityType.DATE.value]["report_only"] is True
    assert by_name[EntityType.IBAN.value]["report_only"] is False


# -- inspect ------------------------------------------------------------------


def test_inspect_reports_findings_with_positions(session: Session, document: Path):
    found = result_of(session, "inspect", path=str(document))
    assert found["format"] == "plaintext"
    entities = {item["entity"] for item in found["findings"]}
    assert EntityType.TAX_ID.value in entities
    for item in found["findings"]:
        assert item["end"] > item["start"]


def test_inspect_includes_the_value_so_a_preview_can_show_it(session: Session, document: Path):
    """A preview that cannot show what is about to be removed is not a preview."""
    found = result_of(session, "inspect", path=str(document))
    texts = {item["text"] for item in found["findings"]}
    assert CANARIES["IT_CODICE_FISCALE"] in texts


def test_inspect_reports_the_action_the_policy_would_take(session: Session, document: Path):
    found = result_of(session, "inspect", path=str(document))
    actions = {item["entity"]: item["action"] for item in found["findings"]}
    assert actions[EntityType.IBAN.value] == "redact"


def test_keep_changes_the_reported_action(session: Session, document: Path):
    found = result_of(session, "inspect", path=str(document), keep=["IBAN"])
    actions = {item["entity"]: item["action"] for item in found["findings"]}
    assert actions[EntityType.IBAN.value] == "keep"


def test_inspect_writes_nothing(session: Session, document: Path, tmp_path: Path):
    before = sorted(p.name for p in tmp_path.iterdir())
    result_of(session, "inspect", path=str(document))
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_a_missing_file_is_a_request_error(session: Session, tmp_path: Path):
    assert error_of(session, "inspect", path=str(tmp_path / "assente.txt"))["code"] == (
        INVALID_REQUEST
    )


def test_a_missing_parameter_is_a_request_error(session: Session):
    assert error_of(session, "inspect")["code"] == INVALID_REQUEST


def test_an_unknown_entity_name_is_a_request_error(session: Session, document: Path):
    assert error_of(session, "inspect", path=str(document), keep=["TELEPATHY"])["code"] == (
        INVALID_REQUEST
    )


@pytest.mark.parametrize("value", [-0.5, 1.5, "high", None])
def test_an_out_of_range_confidence_is_rejected(session: Session, document: Path, value):
    assert error_of(session, "inspect", path=str(document), min_confidence=value)["code"] == (
        INVALID_REQUEST
    )


def test_an_unsupported_format_reports_its_own_code(session: Session, tmp_path: Path):
    path = tmp_path / "archivio.zip"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    assert error_of(session, "inspect", path=str(path))["code"] == UNSUPPORTED_FORMAT


def test_a_scan_without_ocr_reports_its_own_code(session: Session, tmp_path: Path, monkeypatch):
    """The app should say "install OCR", not "something went wrong"."""
    pymupdf = pytest.importorskip("pymupdf")
    from freedocs.formats import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "tessdata_path", lambda: None)
    doc = pymupdf.open()
    page = doc.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(pymupdf.Rect(50, 50, 250, 150), pixmap=pixmap)
    path = tmp_path / "scansione.pdf"
    doc.save(str(path))
    doc.close()

    assert error_of(session, "inspect", path=str(path))["code"] == NEEDS_OCR


# -- scrub --------------------------------------------------------------------


def test_scrub_writes_the_file_and_reports_where(session: Session, document: Path, tmp_path: Path):
    output = tmp_path / "out"
    results = result_of(session, "scrub", paths=[str(document)], output_dir=str(output))["results"]
    assert len(results) == 1
    assert results[0]["ok"] is True
    written = Path(results[0]["output"])
    assert written.exists()
    assert CANARIES["IT_CODICE_FISCALE"] not in written.read_text(encoding="utf-8")


def test_scrub_creates_the_output_directory(session: Session, document: Path, tmp_path: Path):
    output = tmp_path / "nuova" / "cartella"
    result_of(session, "scrub", paths=[str(document)], output_dir=str(output))
    assert output.is_dir()


def test_scrub_emits_progress_per_file(document: Path, tmp_path: Path):
    out = io.StringIO()
    session = Session(out=out)
    result_of(
        session,
        "scrub",
        paths=[str(document), str(document)],
        output_dir=str(tmp_path / "out"),
    )
    progress = [
        json.loads(line)
        for line in out.getvalue().splitlines()
        if line and json.loads(line).get("method") == "progress"
    ]
    assert [item["params"]["index"] for item in progress] == [0, 1]
    assert all(item["params"]["total"] == 2 for item in progress)


def test_the_report_carries_no_confidential_values(
    session: Session, document: Path, tmp_path: Path
):
    """The report is the part that reaches disk, so it holds counts only."""
    results = result_of(session, "scrub", paths=[str(document)], output_dir=str(tmp_path / "out"))[
        "results"
    ]
    serialised = json.dumps(results[0]["report"])
    for value in (CANARIES["IT_CODICE_FISCALE"], CANARIES["IBAN"]):
        assert value not in serialised


def test_one_bad_file_does_not_abandon_the_batch(session: Session, document: Path, tmp_path: Path):
    """A batch that stops at its third file has wasted the first two."""
    broken = tmp_path / "archivio.zip"
    broken.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    results = result_of(
        session,
        "scrub",
        paths=[str(broken), str(document)],
        output_dir=str(tmp_path / "out"),
    )["results"]
    assert [item["ok"] for item in results] == [False, True]
    assert results[0]["error"]["code"] == UNSUPPORTED_FORMAT


def test_a_leak_is_reported_as_a_failure_without_the_values(
    session: Session, document: Path, tmp_path: Path, monkeypatch
):
    """Nothing is written, and the count goes out without the text."""
    from freedocs.formats import plaintext

    monkeypatch.setattr(plaintext.PlainTextHandler, "write_back", lambda self, edits: self.data)
    output = tmp_path / "out"
    results = result_of(session, "scrub", paths=[str(document)], output_dir=str(output))["results"]
    assert results[0]["ok"] is False
    assert results[0]["error"]["code"] == LEAK_DETECTED
    assert results[0]["error"]["data"]["leaks"] > 0
    assert CANARIES["IBAN"] not in json.dumps(results[0])
    assert not (output / document.name).exists()


def test_scrub_surfaces_hidden_content_removals(session: Session, tmp_path: Path):
    """The user should see what was taken out that they never saw in the first place."""
    pytest.importorskip("lxml")
    from .docx_builder import DocxSpec, write_docx

    path = write_docx(
        tmp_path / "scheda.docx",
        DocxSpec(paragraphs=[[f"IBAN: {CANARIES['IBAN']}"]], comment="nota interna"),
    )
    results = result_of(session, "scrub", paths=[str(path)], output_dir=str(tmp_path / "out"))[
        "results"
    ]
    kinds = {item["kind"] for item in results[0]["hidden_removed"]}
    assert "comments" in kinds
    assert "metadata" in kinds


def test_an_empty_path_list_is_a_request_error(session: Session, tmp_path: Path):
    assert error_of(session, "scrub", paths=[], output_dir=str(tmp_path))["code"] == (
        INVALID_REQUEST
    )


def test_a_non_string_path_is_a_request_error(session: Session, tmp_path: Path):
    assert error_of(session, "scrub", paths=[42], output_dir=str(tmp_path))["code"] == (
        INVALID_REQUEST
    )


# -- session state ------------------------------------------------------------


def test_the_registry_is_reused_across_requests(session: Session, document: Path):
    """The reason the app talks to a process rather than shelling out per file.

    Loading GLiNER2 takes seconds and running it takes milliseconds, so a process
    that rebuilt the registry per request would spend its life loading a model.
    """
    result_of(session, "inspect", path=str(document))
    first = session._registry
    result_of(session, "inspect", path=str(document))
    assert session._registry is first


def test_changing_the_detector_spec_rebuilds_the_registry(session: Session):
    """The spec is part of the cache key, not just the countries.

    Asked of ``registry`` directly, and with the *default* spec as the second
    value, for one reason each. An explicit ``detectors="ner"`` is a request this
    build cannot answer without the model, so the earlier version of this test
    could only pass on a machine carrying 1.2 GB of weights — and CI deliberately
    installs no ``ner`` extra, so it failed there every time. The default spec
    degrades to L1 with a note when the extra is absent (see
    ``pipeline.default_registry``) and is therefore answerable either way.

    And building a registry is free while predicting is not: the backend loads
    its model on first use, so going through ``inspect`` would pay for a model
    load to test a dictionary lookup.
    """
    first = session.registry("l1")
    assert session.registry(None) is not first
    # And back again: one slot keyed on the spec, not a one-way flag.
    assert session.registry("l1") is not first


@pytest.mark.slow
def test_the_default_stack_is_what_an_app_gets_when_it_asks_for_nothing(
    session: Session, document: Path
):
    """One test does exercise the real default, so the wiring cannot rot."""
    pytest.importorskip("gliner2", reason="the 'ner' extra is required")
    request = {"jsonrpc": "2.0", "id": 1, "method": "inspect", "params": {"path": str(document)}}
    response = handle(session, json.dumps(request))
    assert "error" not in response, response.get("error")
    layers = result_of(session, "capabilities")["layers"]
    assert "NerDetector" in layers


def test_a_backend_that_cannot_load_reports_a_missing_component(
    session: Session, document: Path, monkeypatch
):
    """Detector backends load their model on first use, not at construction.

    So a missing one surfaces during detection, after the request has been
    accepted. Before this was mapped, the app was told "internal error" for what
    is really "a component is missing" — and a packaged build with the model stack
    left out of the bundle failed exactly this way.
    """
    from freedocs.core.errors import MissingDependency
    from freedocs.detect import registry as registry_module

    def refuse(self, text):
        raise MissingDependency("gliner2 is required for the GLiNER2 backend")

    monkeypatch.setattr(registry_module.DetectorRegistry, "detect", refuse)
    assert error_of(session, "inspect", path=str(document))["code"] == MISSING_DEPENDENCY


# -- country selection ---------------------------------------------------------


def test_capabilities_names_the_countries(session):
    """Sent rather than duplicated in the window, like review_host."""
    caps = session.capabilities()
    assert "ch" in caps["countries"] and "de" in caps["countries"]
    assert caps["countries"] == sorted(caps["countries"])


def test_narrowing_the_countries_changes_what_inspect_finds(session, tmp_path):
    path = tmp_path / "misto.txt"
    path.write_text(
        "Numero AVS: 756.1234.5678.97\nSteuerliche Identifikationsnummer: 36574261809\n",
        encoding="utf-8",
    )
    everything = session.inspect({"path": str(path), "detectors": "l1"})
    swiss_only = session.inspect({"path": str(path), "detectors": "l1", "countries": ["ch"]})
    assert {f["entity"] for f in everything["findings"]} >= {"NATIONAL_ID", "TAX_ID"}
    assert {f["entity"] for f in swiss_only["findings"]} == {"NATIONAL_ID"}


def test_a_narrowed_inspection_says_so(session, tmp_path):
    """A preview taken with two countries looks like one taken with thirteen.

    The difference is the whole point of the option, so the registry note has to
    reach this response the way it already reaches a scrub's warnings.
    """
    path = tmp_path / "vuoto.txt"
    path.write_text("niente di interessante\n", encoding="utf-8")
    narrowed = session.inspect({"path": str(path), "detectors": "l1", "countries": ["ch"]})
    assert any("only being looked for" in warning for warning in narrowed["warnings"])
    everything = session.inspect({"path": str(path), "detectors": "l1"})
    assert not any("only being looked for" in warning for warning in everything["warnings"])


def test_an_empty_country_list_is_refused(session, tmp_path):
    """Over a pipe that is what a caller sends when its own state got lost.

    Read as "no countries" it would scrub with the checksum layer switched off
    and hand back a file the user believes is clean.
    """
    path = tmp_path / "x.txt"
    path.write_text("x\n", encoding="utf-8")
    with pytest.raises(RpcError) as caught:
        session.inspect({"path": str(path), "detectors": "l1", "countries": []})
    assert "omit it" in str(caught.value)


def test_an_unknown_country_is_refused(session, tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("x\n", encoding="utf-8")
    with pytest.raises(RpcError) as caught:
        session.inspect({"path": str(path), "detectors": "l1", "countries": ["zz"]})
    assert "zz" in str(caught.value)


def test_the_registry_cache_is_keyed_on_the_countries_too(session, tmp_path):
    """Otherwise the second request of a session answers with the first's choice.

    The cache exists because loading GLiNER2 takes seconds; a key that ignored
    this option would silently reuse a narrowed registry for a full request.
    """
    path = tmp_path / "avs.txt"
    path.write_text("Numero AVS: 756.1234.5678.97\n", encoding="utf-8")
    narrowed = session.inspect({"path": str(path), "detectors": "l1", "countries": ["it"]})
    assert not narrowed["findings"]
    again = session.inspect({"path": str(path), "detectors": "l1", "countries": ["ch"]})
    assert [f["entity"] for f in again["findings"]] == ["NATIONAL_ID"]


# --- the human override loop -------------------------------------------------
#
# The window sends two new things: occurrences to leave alone, and values to
# remove that no detector nominated. Both are exercised here rather than in the
# app, for the reason at the top of this file.


def _span_of(found: dict, entity: str) -> dict:
    item = next(f for f in found["findings"] if f["entity"] == entity)
    return {"start": item["start"], "end": item["end"], "text": item["text"]}


def test_a_kept_span_disappears_from_the_preview(session: Session, document: Path):
    """The loop is preview, adjust, preview. A decision the preview ignores is a bug."""
    before = result_of(session, "inspect", path=str(document))
    kept = _span_of(before, EntityType.IBAN.value)
    after = result_of(session, "inspect", path=str(document), keep_spans=[kept])
    assert EntityType.IBAN.value in {f["entity"] for f in before["findings"]}
    assert EntityType.IBAN.value not in {f["entity"] for f in after["findings"]}


def test_a_requested_value_appears_in_the_preview_as_human(session: Session, document: Path):
    found = result_of(session, "inspect", path=str(document), remove=[{"value": "Scheda cliente"}])
    added = [f for f in found["findings"] if f["detector"] == "human"]
    assert [f["text"] for f in added] == ["Scheda cliente"]
    assert added[0]["entity"] == EntityType.OTHER.value


def test_a_requested_value_that_is_absent_is_reported_as_a_warning(
    session: Session, document: Path
):
    """ "Removed" and "was not there" look identical in the output."""
    found = result_of(session, "inspect", path=str(document), remove=["Cognome Assente"])
    assert any("Cognome Assente" in warning for warning in found["warnings"])


def test_a_stale_kept_span_is_refused_rather_than_reinterpreted(session: Session, document: Path):
    """Honouring it would keep whatever moved into that range."""
    response = call(
        session,
        "inspect",
        path=str(document),
        keep_spans=[{"start": 0, "end": 6, "text": "Milano"}],
    )
    assert response["error"]["code"] == INVALID_REQUEST
    assert "re-inspect" in response["error"]["message"]


def test_an_unknown_entity_on_a_removal_is_refused(session: Session, document: Path):
    response = call(
        session, "inspect", path=str(document), remove=[{"value": "x", "entity": "NOPE"}]
    )
    assert response["error"]["code"] == INVALID_REQUEST


def test_the_two_keep_controls_are_not_the_same_control(session: Session, document: Path):
    """``keep`` names types, ``keep_spans`` names occurrences.

    One control for both would make "this IBAN is fine" mean "no IBAN in any file
    is confidential", which is the opposite of a per-occurrence decision.
    """
    by_type = result_of(session, "inspect", path=str(document), keep=[EntityType.IBAN.value])
    actions = {f["entity"]: f["action"] for f in by_type["findings"]}
    # Still reported, but the action is now keep - the finding does not vanish.
    assert actions[EntityType.IBAN.value] == "keep"

    before = result_of(session, "inspect", path=str(document))
    by_span = result_of(
        session, "inspect", path=str(document), keep_spans=[_span_of(before, EntityType.IBAN.value)]
    )
    assert EntityType.IBAN.value not in {f["entity"] for f in by_span["findings"]}


def test_a_scrub_honours_both_halves_and_still_verifies(
    session: Session, document: Path, tmp_path: Path
):
    before = result_of(session, "inspect", path=str(document))
    kept = _span_of(before, EntityType.IBAN.value)
    out = tmp_path / "out"
    result = result_of(
        session,
        "scrub",
        paths=[str(document)],
        output_dir=str(out),
        keep_spans=[kept],
        remove=[{"value": "Scheda cliente", "entity": "OTHER"}],
    )
    one = result["results"][0]
    assert one["ok"], one
    written = Path(one["output"]).read_text(encoding="utf-8")
    # Kept on purpose, so it is still there; and stage 6 was told, so it passed.
    assert kept["text"] in written
    assert "Scheda cliente" not in written
    assert "[REDACTED_1]" in written


# -- the preview text ---------------------------------------------------------


def test_inspect_does_not_send_the_document_text_unless_asked(session: Session, document: Path):
    """The flat text is a superset of the findings: it holds what nothing caught."""
    result = result_of(session, "inspect", path=str(document))
    assert "text" not in result
    assert "parts" not in result


def test_the_preview_text_is_the_text_the_offsets_point_into(session: Session, document: Path):
    """The load-bearing test: one coordinate system, pinned.

    Every finding's span is an offset into the text this response carries, and
    ``keep_spans`` sends those same offsets back. If the two ever disagree, a
    caller excusing one occurrence names a range nobody saw — and the engine
    would either refuse it as stale or keep whatever moved into it.
    """
    result = result_of(session, "inspect", path=str(document), include_text=True)
    assert result["findings"], "the fixture is meant to contain findings"
    for finding in result["findings"]:
        assert result["text"][finding["start"] : finding["end"]] == finding["text"]


def test_the_preview_names_which_part_each_region_came_from(session: Session, tmp_path: Path):
    """Two sheets, two ranges, in stream order and not overlapping."""
    pytest.importorskip("lxml")
    from .xlsx_builder import Sheet, XlsxSpec, write_xlsx

    path = write_xlsx(
        tmp_path / "clienti.xlsx",
        XlsxSpec(
            sheets=[
                Sheet(name="Clienti", rows=[["IBAN", CANARIES["IBAN"]]]),
                Sheet(name="Note", rows=[["Codice", CANARIES["IT_CODICE_FISCALE"]]]),
            ]
        ),
    )
    parts = result_of(session, "inspect", path=str(path), include_text=True)["parts"]
    assert len(parts) >= 2
    assert [part["start"] for part in parts] == sorted(part["start"] for part in parts)
    for earlier, later in pairwise(parts):
        assert earlier["end"] <= later["start"]


def test_a_long_document_is_truncated_and_says_so(session: Session, tmp_path: Path, monkeypatch):
    """Stated, never silent — and `characters` still reports the whole file."""
    from freedocs import rpc

    monkeypatch.setattr(rpc, "MAX_PREVIEW_CHARS", 40)
    path = tmp_path / "lungo.txt"
    path.write_text("Scheda cliente. " * 40, encoding="utf-8")

    result = result_of(session, "inspect", path=str(path), include_text=True)
    assert len(result["text"]) == 40
    assert result["text_end"] == 40
    assert result["text_truncated"] is True
    assert result["characters"] > 40
    # The index must not point past the string it indexes.
    assert all(part["end"] <= 40 for part in result["parts"])


def test_a_finding_past_the_truncation_point_is_still_reported(
    session: Session, tmp_path: Path, monkeypatch
):
    """Truncating the findings to match the text would hide one."""
    from freedocs import rpc

    monkeypatch.setattr(rpc, "MAX_PREVIEW_CHARS", 10)
    path = tmp_path / "tardivo.txt"
    path.write_text(
        f"Premessa lunga senza nulla di riservato.\nIBAN: {CANARIES['IBAN']}\n",
        encoding="utf-8",
    )

    result = result_of(session, "inspect", path=str(path), include_text=True)
    assert result["text_truncated"] is True
    found = [finding for finding in result["findings"] if finding["text"] == CANARIES["IBAN"]]
    assert found, "a finding beyond the preview window must still be reported"
    assert found[0]["start"] > result["text_end"]


def test_the_scrub_report_never_carries_the_preview_text(
    session: Session, document: Path, tmp_path: Path
):
    """The preview goes down the pipe; the report goes to disk.

    Checked with a phrase that is not a finding, so this fails if the whole
    extracted text ever reaches the report — which the value-free assertion above
    would not catch, since it only looks for the values a detector claimed.
    """
    results = result_of(
        session,
        "scrub",
        paths=[str(document)],
        output_dir=str(tmp_path / "out"),
        include_text=True,
    )["results"]
    assert "Scheda cliente" not in json.dumps(results[0]["report"])


# -- the extraction cache -----------------------------------------------------


def test_the_extraction_is_reused_across_inspections(session: Session, document: Path, monkeypatch):
    """Every kept occurrence re-inspects; re-reading a scan means re-OCRing it."""
    from freedocs.pipeline import Scrubber

    reads = []
    original = Scrubber.read

    def counting(self, source, *args, **kwargs):
        reads.append(source)
        return original(self, source, *args, **kwargs)

    monkeypatch.setattr(Scrubber, "read", counting)
    result_of(session, "inspect", path=str(document))
    result_of(session, "inspect", path=str(document))
    assert len(reads) == 1


def test_a_changed_file_is_read_again(session: Session, document: Path):
    """A cache that serves old text shows a preview of a document that is gone."""
    first = result_of(session, "inspect", path=str(document))
    document.write_text(
        f"Scheda cliente\nIBAN: {CANARIES['IBAN']}\nNuova riga aggiunta\n", encoding="utf-8"
    )
    second = result_of(session, "inspect", path=str(document))
    assert second["characters"] != first["characters"]


# -- what the window could not ask before -------------------------------------


def test_inspect_says_which_layer_claimed_each_finding(session: Session, document: Path):
    """A checksum, a model, or the caller. The window was reduced to guessing."""
    result = result_of(session, "inspect", path=str(document), remove=["Scheda cliente"])
    layers = {finding["text"]: finding["layer"] for finding in result["findings"]}
    assert layers[CANARIES["IT_CODICE_FISCALE"]] == "L1"
    assert layers["Scheda cliente"] == "H"


def test_inspect_names_the_country_of_a_country_issued_identifier(session: Session, document: Path):
    """One global algorithm settles an IBAN; a tax number belongs to somebody."""
    findings = result_of(session, "inspect", path=str(document))["findings"]
    by_text = {finding["text"]: finding["country"] for finding in findings}
    assert by_text[CANARIES["IT_CODICE_FISCALE"]] == "it"
    assert by_text[CANARIES["IBAN"]] is None


def test_capabilities_says_how_much_text_the_reviewer_reads(session: Session):
    """Without this, "first part of the document only" names no part."""
    capabilities = result_of(session, "capabilities")
    assert capabilities["review_max_characters"] > 0
    assert capabilities["preview_max_characters"] > 0


def test_every_detector_spec_is_explained(session: Session):
    """A fourth spec must not ship as an opaque string in a menu."""
    from freedocs.pipeline import LAYER_SPECS

    capabilities = result_of(session, "capabilities")
    assert set(capabilities["detector_spec_notes"]) == set(LAYER_SPECS)
    assert set(capabilities["detector_specs"]) == set(LAYER_SPECS)


def test_entities_shows_the_placeholder_a_locale_would_write(session: Session):
    """Composed by the allocator that writes the file, so it cannot disagree."""
    english = {
        item["name"]: item["placeholder"] for item in result_of(session, "entities")["entities"]
    }
    italian = {
        item["name"]: item["placeholder"]
        for item in result_of(session, "entities", placeholder_language="it")["entities"]
    }
    assert english["PERSON"] == "[PERSON_1]"
    assert italian["PERSON"] == "[PERSONA_1]"
    # The country-issued types are deliberately not translated: one stem stands
    # for twelve countries and a national name for it would be wrong on eleven.
    assert italian["TAX_ID"] == "[TAX_ID_1]"


def test_an_unknown_placeholder_language_is_a_request_error(session: Session):
    assert error_of(session, "entities", placeholder_language="xx")["code"] == INVALID_REQUEST


def test_doctor_reports_a_fix_for_every_failing_check(session: Session):
    """`Check.fix` was written to be shown to a person and never could be."""
    report = result_of(session, "doctor", review_host="http://127.0.0.1:1")
    assert report["checks"], "a machine always has something to report"
    names = {check["name"] for check in report["checks"]}
    assert "OCR" in names
    for check in report["checks"]:
        assert check["degraded"] == (not check["ok"] and not check["required"])
        if not check["ok"]:
            # Either something to run, or a sentence saying what to install. What
            # it must never be is a bare failure with no next step.
            assert check["fix"] or check["detail"]


def test_countries_says_which_ones_are_checksum_confirmed(session: Session):
    """An undifferentiated list lets a reader believe a US SSN is confirmed."""
    coverage = result_of(session, "countries")
    by_code = {country["code"]: country for country in coverage["countries"]}
    assert by_code["ch"]["checksum_confirmed"] is True
    assert by_code["us"]["checksum_confirmed"] is False
    assert by_code["us"]["detail"]
    assert by_code["us"]["entities"] == []


def test_countries_explains_what_a_narrowed_selection_costs(session: Session):
    coverage = result_of(session, "countries", countries=["ch", "it"])
    assert coverage["selected"] == ["ch", "it"]
    assert "de" in coverage["excluded"]
    assert "NOT being detected" in coverage["note"]


def test_countries_publishes_the_confidence_table(session: Session):
    """Asserted against the constants, so the table cannot drift from them."""
    from freedocs.detect.validators import MEDIUM_CHECK, STRONG_CHECK, WEAK_CHECK

    levels = {
        level["name"]: level["value"]
        for level in result_of(session, "countries")["confidence_levels"]
    }
    assert levels == {"strong": STRONG_CHECK, "medium": MEDIUM_CHECK, "weak": WEAK_CHECK}


def test_a_raised_threshold_marks_the_rules_it_switches_off(session: Session):
    """A threshold slider with nothing to see is a mystery control."""
    low = result_of(session, "countries", min_confidence=0.4)
    high = result_of(session, "countries", min_confidence=0.6)

    def inert(coverage):
        return {
            rule["name"]
            for country in coverage["countries"]
            for rule in country["rules"]
            if rule["inert_without_context"]
        }

    assert inert(low) == set()
    assert inert(high), "raising the threshold has to silence the weak rules"


def test_the_countries_command_and_the_rpc_answer_agree(session: Session):
    """The CLI prints from the same function, so there is one answer."""
    from freedocs.pipeline import country_coverage

    assert result_of(session, "countries")["countries"] == country_coverage()["countries"]


# -- stage progress -----------------------------------------------------------


def stages_of(out: io.StringIO) -> list[dict]:
    return [
        json.loads(line)["params"]
        for line in out.getvalue().splitlines()
        if line and json.loads(line).get("method") == "stage"
    ]


def run(requests: list[dict]) -> io.StringIO:
    out = io.StringIO()
    serve(
        stdin=io.StringIO("\n".join(json.dumps(request) for request in requests)),
        stdout=out,
    )
    return out


def test_inspect_announces_its_stages(document: Path):
    """Three, because an inspection stops after detection.

    Reporting six and finishing at three would be a bar that stops halfway and
    calls itself done.
    """
    out = run(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "inspect",
                "params": {"path": str(document), "detectors": "l1"},
            }
        ]
    )
    stages = stages_of(out)
    assert [item["stage"] for item in stages] == ["router", "extract", "detect"]
    assert all(item["count"] == 3 for item in stages)
    assert [item["index"] for item in stages] == [1, 2, 3]
    assert all(item["id"] == 1 for item in stages)


def test_a_scrub_announces_every_stage_in_order(document: Path, tmp_path: Path):
    out = run(
        [
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "scrub",
                "params": {
                    "paths": [str(document)],
                    "output_dir": str(tmp_path / "out"),
                    "detectors": "l1",
                },
            }
        ]
    )
    assert [item["stage"] for item in stages_of(out)] == [
        "router",
        "extract",
        "detect",
        "policy",
        "write-back",
        "verify",
    ]


def test_the_review_stage_is_only_counted_when_a_review_was_asked_for(
    document: Path, tmp_path: Path, monkeypatch
):
    """A stepper drawn from a constant would show a step this run never runs."""
    import freedocs.rpc as rpc_module

    class FakeReviewer:
        model = "stub"

        def review_outcome(self, _text):
            from freedocs.detect.llm_review import ReviewOutcome

            return ReviewOutcome(model="stub", ran=True)

    monkeypatch.setattr(rpc_module, "_reviewer_from", lambda _params: FakeReviewer())
    out = run(
        [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "scrub",
                "params": {
                    "paths": [str(document)],
                    "output_dir": str(tmp_path / "out"),
                    "detectors": "l1",
                },
            }
        ]
    )
    stages = stages_of(out)
    assert all(item["count"] == 7 for item in stages)
    assert stages[-1]["stage"] == "review"


def test_no_stage_notification_claims_a_percentage(document: Path, tmp_path: Path):
    """The guard on the thing that must not be faked.

    How long detection takes next to extraction on an unseen document is not a
    fact the engine has, so there is no honest overall fraction and there must be
    no field that looks like one.
    """
    out = run(
        [
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "scrub",
                "params": {
                    "paths": [str(document)],
                    "output_dir": str(tmp_path / "out"),
                    "detectors": "l1",
                },
            }
        ]
    )
    for line in out.getvalue().splitlines():
        if line:
            assert "percent" not in line


def test_a_pdf_reports_the_page_it_is_on(session: Session, tmp_path: Path):
    """Pages are the real unit of the stage that can take minutes."""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "tre.pdf"
    document = pymupdf.open()
    for number in range(3):
        page = document.new_page()
        page.insert_text((72, 72), f"Pagina {number + 1}")
    document.save(path)
    document.close()

    out = run(
        [
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "inspect",
                "params": {"path": str(path), "detectors": "l1"},
            }
        ]
    )
    counted = [item for item in stages_of(out) if item.get("of")]
    assert counted, "a PDF has pages to count"
    assert counted[-1]["done"] == 3
    assert all(item["of"] == 3 for item in counted)


def test_the_stage_names_are_a_closed_vocabulary():
    """The window translates these by key, so a rename is a visible change.

    Not a style test: a stage whose name the catalogues have never heard of
    renders as its wire string in the middle of a translated sentence.
    """
    from freedocs.pipeline import INSPECT_STAGES, REVIEW_STAGE, STAGES
    from freedocs.restore import RESTORE_STAGES

    assert STAGES == ("router", "extract", "detect", "policy", "write-back", "verify")
    assert REVIEW_STAGE == "review"
    assert set(INSPECT_STAGES) <= set(STAGES)
    assert RESTORE_STAGES == ("router", "extract", "match", "write-back", "verify")
    # The reverse path adds exactly one word to the vocabulary the catalogues have
    # to carry. Pinned, because a second one arriving unnoticed is a wire string
    # rendered raw in the middle of a translated sentence.
    assert set(RESTORE_STAGES) - set(STAGES) == {"match"}


# --- the key file and the reverse path ---------------------------------------
#
# The protocol is all the window can see, so these assert response shape and the
# two refusals a caller can act on. The cipher itself is `test_mapping.py`'s.

PASSPHRASE = "correct horse battery staple"


def test_capabilities_publishes_whether_a_key_file_is_possible(session: Session):
    """So the window can disable the control instead of offering it and failing -
    which is the bug `ocr_unavailable_reason()` exists to prevent, one feature
    over."""
    caps = result_of(session, "capabilities")
    assert isinstance(caps["mapping_available"], bool)
    assert caps["mapping_available"] == (caps["mapping_unavailable_reason"] is None)
    # A separate list from `caveats`: a restore's limits are not a scrub's, and one
    # merged list would show a reader of either screen sentences that do not apply.
    assert caps["restore_caveats"] and caps["restore_caveats"] != caps["caveats"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful here")
def test_the_restored_document_is_owner_only_over_the_pipe_too(
    session: Session, document: Path, tmp_path: Path
):
    """The pipe's half of the rule `core/outputs.py` holds.

    Asserted on both adapters deliberately: they are two adapters over one
    engine, and `15ee0e1` was an entire commit about the same thing being missing
    on the untested side.
    """
    out_dir, keys, back = tmp_path / "out", tmp_path / "keys", tmp_path / "back"
    result_of(
        session,
        "scrub",
        paths=[str(document)],
        output_dir=str(out_dir),
        map=str(keys),
        map_passphrase=PASSPHRASE,
    )
    restored = result_of(
        session,
        "restore",
        path=str(out_dir / document.name),
        map=str(keys / (document.stem + ".fdmap")),
        passphrase=PASSPHRASE,
        output_dir=str(back),
    )
    assert Path(restored["output"]).stat().st_mode & 0o777 == 0o600
    assert back.stat().st_mode & 0o777 == 0o700


def test_capabilities_publishes_the_passphrase_floor(session: Session):
    """The window held this as its own constant, which is the one rule it had.

    Raise the floor in `core/mapping.py` and the window went on accepting eight
    characters: the engine refused inside the `scrub` request and the failure
    landed after the scrubbed copies were written. Asserted against the module's
    own constant rather than against 8, so the two cannot drift apart in the way
    this test exists to stop.
    """
    from freedocs.core.mapping import MIN_PASSPHRASE

    caps = result_of(session, "capabilities")
    assert caps["passphrase_min_characters"] == MIN_PASSPHRASE


def test_a_packaged_build_keeps_its_tracebacks_off_the_system_log(
    session: Session, monkeypatch, capsys
):
    """stderr is not a private channel for a packaged app.

    `engine.rs` inherits it deliberately so a Python traceback reaches the
    terminal a developer is watching. In a bundled `.app` there is no terminal:
    the parent is launchd, and everything written there goes to the operating
    system's unified log, on disk, for anyone who can read the machine's logs.
    An exception's own message is part of a traceback, and a parser's message can
    quote the document it was reading - so this was a disk channel nobody had
    audited, in a tool whose central rule is that values reach the pipe and never
    the disk.

    The caller loses nothing: the full message still travels the response, which
    is local.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    # A handler made to fail unexpectedly, because the sink is what is under test
    # and not which bug reaches it. The message carries a name, which is what a
    # parser quoting the document it was reading would look like.
    monkeypatch.setattr(
        Session,
        "inspect",
        lambda self, params: (_ for _ in ()).throw(RuntimeError("while reading Mario Rossi")),
    )
    error = error_of(session, "inspect", path="/tmp/whatever.txt")
    captured = capsys.readouterr()

    assert "Traceback" not in captured.err, captured.err
    assert "Mario Rossi" not in captured.err, captured.err
    assert "FREEDOCS_DEBUG" in captured.err
    # And the response still says what happened, because it is not a disk channel.
    assert error["message"]


def test_a_development_build_still_prints_the_whole_thing(session: Session, capsys, monkeypatch):
    """The other half, and the reason the sink exists at all: a developer watching
    a terminal is exactly who a traceback is for."""
    assert not getattr(sys, "frozen", False), "this test is about an unfrozen build"
    monkeypatch.setattr(
        Session,
        "inspect",
        lambda self, params: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    error_of(session, "inspect", path="/tmp/whatever.txt")
    assert "Traceback" in capsys.readouterr().err


def test_inspect_reports_the_hidden_content_the_terminal_reports(session: Session, tmp_path: Path):
    """`freedocs inspect` names the thumbnail, the comments and the tracked
    changes; `rpc.inspect` did not, so the window's preview was silent about
    exactly the leak users do not expect and learned of it only after a scrub.

    Both halves are the same read: `Scrubber.read` already calls `scrub_hidden`,
    so this was a field missing from a payload rather than work not done. The
    detail is safe to send because it is a description and never a value - which
    is `HiddenItem`'s own rule, and which is what makes rendering it in a preview
    reasonable at all.
    """
    pytest.importorskip("lxml", reason="lxml is required for OOXML support")
    from .docx_builder import DocxSpec, write_docx

    # The default spec already carries metadata a scrub drops - a creator, a
    # template path, a company - which is exactly the class of thing a preview
    # was staying silent about.
    path = write_docx(tmp_path / "con-nascosti.docx", DocxSpec(paragraphs=[["Ciao"]]))
    payload = result_of(session, "inspect", path=str(path))

    kinds = {item["kind"] for item in payload["hidden"]}
    assert kinds, "the preview must say what would be dropped"
    assert all(isinstance(item["detail"], str) for item in payload["hidden"])


def test_forget_releases_the_extracted_text_a_session_is_holding(session: Session, document: Path):
    """The one thing this process keeps in memory that is worse than a finding.

    `Extraction.stream.text` is a *superset* of what was detected: it contains
    the confidential text no layer found. It is cached so that excusing one
    occurrence does not re-OCR a scan, which is worth it while a document is
    being reviewed and worth nothing once it is not - and until now the only way
    to release it was to end the session.

    Counted rather than searched, because the point is the release and not the
    representation: a test that grepped the process's memory would be testing
    CPython.
    """
    result_of(session, "inspect", path=str(document), include_text=True)
    assert session._extractions, "the reading should be cached while it is useful"

    released = result_of(session, "forget")
    assert released["released"] == 1
    assert not session._extractions


def test_forget_can_name_one_document(session: Session, document: Path, tmp_path: Path):
    """A batch is several documents and leaving one of them is not leaving all
    of them, so the caller says which."""
    other = tmp_path / "altro.txt"
    other.write_text("Nessun dato qui.\n", encoding="utf-8")
    result_of(session, "inspect", path=str(document))
    result_of(session, "inspect", path=str(other))
    assert len(session._extractions) == 2

    assert result_of(session, "forget", paths=[str(other)])["released"] == 1
    assert len(session._extractions) == 1


def test_forgetting_something_never_read_is_not_an_error(session: Session, tmp_path: Path):
    """The window calls this on every exit path, including the ones where nothing
    was ever inspected. A refusal there would make a tidy-up into a failure."""
    assert result_of(session, "forget", paths=[str(tmp_path / "mai-visto.txt")])["released"] == 0


def test_capabilities_says_whether_the_network_is_blocked(session: Session):
    """ "Nothing leaves the machine" is the claim the whole tool rests on, so the
    window should be repeating something it asked rather than something it
    assumes. Both fields, because one of them is the honest half: `hardening`
    names what is *not* enforced as well as what is."""
    caps = result_of(session, "capabilities")
    assert isinstance(caps["network_blocked"], bool)
    assert "Not enforced" in caps["hardening"]


def test_doctor_reports_the_hardening_without_calling_it_a_fault(session: Session):
    """A build with no filesystem confinement is every build there has ever been.
    Reporting that as an error is how people learn to ignore the doctor."""
    checks = result_of(session, "doctor")["checks"]
    hardening = [check for check in checks if check["name"] == "Process hardening"]
    assert hardening, [check["name"] for check in checks]
    assert hardening[0]["ok"] is True
    assert hardening[0]["required"] is False


def test_scrub_without_map_reports_no_key_file(session: Session, document: Path, tmp_path: Path):
    result = result_of(session, "scrub", paths=[str(document)], output_dir=str(tmp_path / "out"))[
        "results"
    ][0]
    assert result["key_file"] is None
    assert result["report"]["key_file_written"] is False
    assert list(tmp_path.rglob("*.fdmap")) == []


def test_a_map_without_a_passphrase_is_refused(session: Session, document: Path, tmp_path: Path):
    """There is no unencrypted form of this file, so quietly writing nothing would
    be worse than saying so."""
    error = error_of(
        session,
        "scrub",
        paths=[str(document)],
        output_dir=str(tmp_path / "out"),
        map=str(tmp_path / "keys"),
    )
    assert error["code"] == INVALID_REQUEST


def test_a_map_inside_the_output_directory_is_refused(
    session: Session, document: Path, tmp_path: Path
):
    out_dir = tmp_path / "out"
    error = error_of(
        session,
        "scrub",
        paths=[str(document)],
        output_dir=str(out_dir),
        map=str(out_dir / "keys"),
        map_passphrase=PASSPHRASE,
    )
    assert error["code"] == INVALID_REQUEST
    # Refused before anything was read, so there is nothing to undo by hand.
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def _scrub_with_key(session: Session, document: Path, tmp_path: Path) -> dict:
    pytest.importorskip("cryptography", reason="the restore extra is required")
    return result_of(
        session,
        "scrub",
        paths=[str(document)],
        output_dir=str(tmp_path / "out"),
        map=str(tmp_path / "keys"),
        map_passphrase=PASSPHRASE,
    )["results"][0]


def test_scrub_says_where_the_key_file_went(session: Session, document: Path, tmp_path: Path):
    """The path, unlike in the JSON report: this response goes down a local pipe to
    the process that chose the location, and a window that cannot say where the key
    is is a window nobody can find it from."""
    result = _scrub_with_key(session, document, tmp_path)
    assert Path(result["key_file"]).is_file()
    assert result["report"]["key_file_written"] is True
    # The report on disk says a key exists and deliberately not where.
    assert "key_file" not in str(result["report"]).replace("key_file_written", "")


def test_restore_returns_the_document(session: Session, document: Path, tmp_path: Path):
    scrubbed = _scrub_with_key(session, document, tmp_path)
    returned = tmp_path / "returned.txt"
    returned.write_text(
        Path(scrubbed["output"]).read_text(encoding="utf-8") + "\nplus [PERSONA_1].\n",
        encoding="utf-8",
    )

    result = result_of(
        session,
        "restore",
        path=str(returned),
        map=scrubbed["key_file"],
        passphrase=PASSPHRASE,
        output_dir=str(tmp_path / "back"),
    )
    assert result["ok"] is True
    assert result["format"] == "plaintext"
    assert {entry["placeholder"] for entry in result["restored"]}
    # The token the model translated is reported and left alone.
    assert result["unknown_placeholders"] == ["[PERSONA_1]"]
    assert CANARIES["IBAN"] in Path(result["output"]).read_text(encoding="utf-8")


def test_the_restore_report_carries_no_confidential_values(
    session: Session, document: Path, tmp_path: Path
):
    scrubbed = _scrub_with_key(session, document, tmp_path)
    result = result_of(
        session,
        "restore",
        path=str(scrubbed["output"]),
        map=scrubbed["key_file"],
        passphrase=PASSPHRASE,
        output_dir=str(tmp_path / "back"),
    )
    serialised = json.dumps(result["report"])
    assert CANARIES["IT_CODICE_FISCALE"] not in serialised
    assert CANARIES["IBAN"] not in serialised


def test_a_wrong_passphrase_leaks_neither_it_nor_a_value(
    session: Session, document: Path, tmp_path: Path
):
    """`handle` renders an unexpected exception as its own message straight into a
    response, so this is the test that keeps `core/mapping.py` honest."""
    scrubbed = _scrub_with_key(session, document, tmp_path)
    response = handle(
        session,
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "restore",
                "params": {
                    "path": scrubbed["output"],
                    "map": scrubbed["key_file"],
                    "passphrase": "not the passphrase at all",
                    "output_dir": str(tmp_path / "back"),
                },
            }
        ),
    )
    blob = json.dumps(response)
    assert response["error"]["code"] == INVALID_REQUEST
    assert "not the passphrase at all" not in blob
    assert CANARIES["IBAN"] not in blob
    assert not (tmp_path / "back" / "scheda.txt").exists()


def test_restore_needs_a_passphrase(session: Session, tmp_path: Path):
    target = tmp_path / "in.txt"
    target.write_text("[PERSON_1]\n", encoding="utf-8")
    error = error_of(
        session,
        "restore",
        path=str(target),
        map=str(target),
        output_dir=str(tmp_path / "back"),
    )
    assert error["code"] == INVALID_REQUEST


def test_restore_announces_its_stages(document: Path, tmp_path: Path):
    """One request, and the notifications a stepper would be drawn from."""
    pytest.importorskip("cryptography", reason="the restore extra is required")
    out = run(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "scrub",
                "params": {
                    "paths": [str(document)],
                    "output_dir": str(tmp_path / "out"),
                    "detectors": "l1",
                    "map": str(tmp_path / "keys"),
                    "map_passphrase": PASSPHRASE,
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "restore",
                "params": {
                    "path": str(tmp_path / "out" / "scheda.txt"),
                    "map": str(tmp_path / "keys" / "scheda.fdmap"),
                    "passphrase": PASSPHRASE,
                    "output_dir": str(tmp_path / "back"),
                },
            },
        ]
    )
    stages = [
        json.loads(line)["params"]
        for line in out.getvalue().splitlines()
        if line and json.loads(line).get("method") == "stage"
    ]
    restore_stages = [item["stage"] for item in stages if item["count"] == 5]
    assert restore_stages[0] == "router"
    assert restore_stages[-1] == "verify"
    assert "match" in restore_stages
    # Same guard as the scrub's: there is no honest overall fraction here either.
    assert not any("percent" in item for item in stages)

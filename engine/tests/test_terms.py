"""The term list: the firm's client register, encrypted, and only ever a removal.

Three failures matter more than the rest. A term readable in the file without
the passphrase. A term or the passphrase inside an error message, which
`rpc.handle` renders into a response. And a save interrupted halfway, which
loses a list that is its own source.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("cryptography", reason="the restore extra is required for a term list")
pytest.importorskip("stdnum", reason="python-stdnum is required for the L1 layer")

from freedocs.core import limits, outputs
from freedocs.core.errors import InputTooLarge
from freedocs.core.findings import EntityType
from freedocs.core.mapping import BadPassphrase
from freedocs.core.overrides import DETECTOR, TERMS_DETECTOR, Override, RemovedValue
from freedocs.core.terms import (
    MIN_TERM_CHARS,
    Term,
    TermList,
    TermListError,
    check_term,
    create_terms,
    export_text,
    open_terms,
    parse_terms,
    read_import,
    rekey_terms,
    save_terms,
    with_terms,
    write_export,
)

PASSPHRASE = "correct horse battery staple"
SECRET_TERM = "Nordwind Holding"


def _list(*values: str) -> TermList:
    return TermList(tuple(Term(value) for value in values))


# -- the file ---------------------------------------------------------------------


def test_create_then_open(tmp_path: Path):
    path = tmp_path / "firm.fdterms"
    assert len(create_terms(path, PASSPHRASE)) == 0
    assert len(open_terms(path, PASSPHRASE)) == 0


def test_a_round_trip_keeps_values_and_entities(tmp_path: Path):
    path = tmp_path / "firm.fdterms"
    terms = TermList((Term(SECRET_TERM, EntityType.ORGANISATION), Term("Giulia Verdi")))
    save_terms(path, terms, PASSPHRASE)
    assert open_terms(path, PASSPHRASE) == terms


def test_no_term_is_readable_in_the_file(tmp_path: Path):
    path = tmp_path / "firm.fdterms"
    save_terms(path, _list(SECRET_TERM, "Progetto Aurora"), PASSPHRASE)
    raw = path.read_bytes()
    assert SECRET_TERM.encode() not in raw
    assert b"Aurora" not in raw


def test_create_refuses_to_replace_a_list(tmp_path: Path):
    """Creating over an existing list would replace the register with nothing."""
    path = tmp_path / "firm.fdterms"
    save_terms(path, _list(SECRET_TERM), PASSPHRASE)
    with pytest.raises(TermListError, match="already exists"):
        create_terms(path, PASSPHRASE)
    assert open_terms(path, PASSPHRASE) == _list(SECRET_TERM)


def test_the_file_is_owner_only(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("mode bits are not enforced on Windows")
    path = tmp_path / "firm.fdterms"
    save_terms(path, _list(SECRET_TERM), PASSPHRASE)
    assert path.stat().st_mode & 0o777 == 0o600


def test_a_wrong_passphrase_quotes_neither_it_nor_a_term(tmp_path: Path):
    path = tmp_path / "firm.fdterms"
    save_terms(path, _list(SECRET_TERM), PASSPHRASE)
    with pytest.raises(BadPassphrase) as caught:
        open_terms(path, "not the passphrase at all")
    message = str(caught.value)
    assert "not the passphrase at all" not in message
    assert SECRET_TERM not in message


def test_a_short_passphrase_is_refused_before_anything_is_written(tmp_path: Path):
    path = tmp_path / "firm.fdterms"
    with pytest.raises(ValueError, match="at least") as caught:
        create_terms(path, "tiny!")
    assert "tiny!" not in str(caught.value)
    assert not path.exists()


def test_an_interrupted_save_leaves_the_previous_list(tmp_path: Path, monkeypatch):
    """The list is edited in place and is its own source.

    `os.replace` failing is the moment after the new copy is complete and before
    it takes the old one's name - the last point a crash can land. The old list
    must still open, and the half-step must not leave a second copy beside it.
    """
    path = tmp_path / "firm.fdterms"
    save_terms(path, _list(SECRET_TERM), PASSPHRASE)

    def fail(*args, **kwargs):
        raise OSError("disk pulled")

    monkeypatch.setattr(outputs.os, "replace", fail)
    with pytest.raises(OSError):
        save_terms(path, _list(SECRET_TERM, "Progetto Aurora"), PASSPHRASE)
    monkeypatch.undo()

    assert open_terms(path, PASSPHRASE) == _list(SECRET_TERM)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["firm.fdterms"]


def test_a_symlink_where_the_list_belongs_is_not_followed(tmp_path: Path):
    """The atomic writer goes through the same `O_NOFOLLOW` open as every output,
    and the rename replaces the link itself rather than what it points at."""
    if os.name == "nt":
        pytest.skip("symlinks need privileges on Windows")
    target = tmp_path / "elsewhere"
    target.write_text("do not touch", encoding="utf-8")
    path = tmp_path / "firm.fdterms"
    path.symlink_to(target)
    save_terms(path, _list(SECRET_TERM), PASSPHRASE)
    assert target.read_text(encoding="utf-8") == "do not touch"
    assert not path.is_symlink()


def test_rekey_needs_the_old_passphrase_and_then_only_the_new_opens(tmp_path: Path):
    path = tmp_path / "firm.fdterms"
    save_terms(path, _list(SECRET_TERM), PASSPHRASE)
    with pytest.raises(BadPassphrase):
        rekey_terms(path, "wrong passphrase!", "a brand new passphrase")
    rekey_terms(path, PASSPHRASE, "a brand new passphrase")
    with pytest.raises(BadPassphrase):
        open_terms(path, PASSPHRASE)
    assert open_terms(path, "a brand new passphrase") == _list(SECRET_TERM)


def test_too_many_entries_is_a_size_refusal(monkeypatch):
    monkeypatch.setattr(limits, "MAX_TERMS", 3)
    with pytest.raises(InputTooLarge, match="up to 3"):
        _list("aa", "bb").with_added([Term("cc"), Term("dd")])


def test_a_sealed_file_too_large_is_refused_before_it_is_read(tmp_path: Path):
    path = tmp_path / "huge.fdterms"
    path.write_bytes(b"{" + b" " * (limits.MAX_TERMS_BYTES + 1))
    with pytest.raises(TermListError, match="bytes"):
        open_terms(path, PASSPHRASE)


# -- entries ------------------------------------------------------------------------


def test_an_entry_is_trimmed():
    assert check_term(Term("  Acme Corp \t")).value == "Acme Corp"


@pytest.mark.parametrize("value", ["", "a", "x" * (limits.MAX_TERM_CHARS + 1), "two\nlines"])
def test_an_entry_that_cannot_be_matched_sensibly_is_refused(value: str):
    with pytest.raises(TermListError) as caught:
        check_term(Term(value))
    if len(value) >= MIN_TERM_CHARS:
        assert value not in str(caught.value)


def test_a_duplicate_is_skipped_and_its_first_entity_stays():
    terms = TermList((Term(SECRET_TERM, EntityType.ORGANISATION),))
    grown, added = terms.with_added([Term(SECRET_TERM, EntityType.PERSON), Term("Giulia Verdi")])
    assert added == 1
    assert grown.terms[0].entity is EntityType.ORGANISATION


def test_removal_is_by_exact_value():
    terms, removed = _list(SECRET_TERM, "Nordwind").without(["Nordwind"])
    assert removed == 1
    assert terms == _list(SECRET_TERM)


def test_search_is_blind_to_case_and_accents():
    terms = _list("Société Générale SA", SECRET_TERM)
    assert [t.value for t in terms.search("societe")] == ["Société Générale SA"]
    assert len(terms.search(None)) == 2


def test_parse_terms_refuses_an_unknown_entity_without_quoting_it():
    with pytest.raises(TermListError, match="entry 1") as caught:
        parse_terms([{"value": SECRET_TERM, "entity": "CLIENT"}])
    assert SECRET_TERM not in str(caught.value)


# -- import and export --------------------------------------------------------------


def test_import_reads_comments_prefixes_and_blank_lines(tmp_path: Path):
    source = tmp_path / "clients.txt"
    source.write_text(
        "# the firm's clients\n\nPERSON\tGiulia Verdi\nNordwind Holding\n",
        encoding="utf-8",
    )
    assert read_import(source) == [
        Term("Giulia Verdi", EntityType.PERSON),
        Term(SECRET_TERM),
    ]
    assert source.exists(), "an import must never delete its source"


def test_an_unknown_prefix_names_the_line_and_not_the_value(tmp_path: Path):
    """What comes before a tab that is not an entity type is most likely half a
    value, so the message names where it is and nothing else."""
    source = tmp_path / "clients.txt"
    source.write_text(f"Giulia Verdi\nNordwind\tHolding {SECRET_TERM}\n", encoding="utf-8")
    with pytest.raises(TermListError, match="line 2") as caught:
        read_import(source)
    assert "Nordwind" not in str(caught.value)


def test_an_empty_entry_names_its_line(tmp_path: Path):
    source = tmp_path / "clients.txt"
    source.write_text("Giulia Verdi\nPERSON\t \n", encoding="utf-8")
    with pytest.raises(TermListError, match="line 2"):
        read_import(source)


def test_a_csv_takes_value_then_entity_and_skips_its_header(tmp_path: Path):
    source = tmp_path / "crm.csv"
    source.write_text(
        'value,entity\n"Nordwind Holding",organisation\nGiulia Verdi,\n', encoding="utf-8"
    )
    assert read_import(source) == [
        Term(SECRET_TERM, EntityType.ORGANISATION),
        Term("Giulia Verdi"),
    ]


def test_an_export_imports_back_unchanged(tmp_path: Path):
    terms = TermList((Term(SECRET_TERM, EntityType.ORGANISATION), Term("Giulia Verdi")))
    out = tmp_path / "export.txt"
    write_export(out, terms)
    assert "NOT encrypted" in out.read_text(encoding="utf-8")
    assert TermList(tuple(read_import(out))) == terms


def test_an_export_is_never_written_over_the_list(tmp_path: Path):
    """The one accident here that cannot be undone: the encrypted register
    replaced by its own plaintext."""
    path = tmp_path / "firm.fdterms"
    save_terms(path, _list(SECRET_TERM), PASSPHRASE)
    with pytest.raises(TermListError):
        write_export(path, _list(SECRET_TERM), refuse=[path])
    with pytest.raises(TermListError):
        write_export(tmp_path / "copy.fdterms", _list(SECRET_TERM))
    assert open_terms(path, PASSPHRASE) == _list(SECRET_TERM)


def test_the_export_is_owner_only(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("mode bits are not enforced on Windows")
    out = tmp_path / "export.txt"
    write_export(out, _list(SECRET_TERM))
    assert out.stat().st_mode & 0o777 == 0o600
    assert export_text(_list(SECRET_TERM)).endswith(f"OTHER\t{SECRET_TERM}\n")


# -- as an override -------------------------------------------------------------------


def test_the_list_is_merged_as_removals_marked_as_the_list():
    merged = with_terms(Override(remove=(RemovedValue("typed by hand"),)), _list(SECRET_TERM))
    assert {(r.value, r.detector) for r in merged.remove} == {
        (SECRET_TERM, TERMS_DETECTOR),
        ("typed by hand", DETECTOR),
    }


def test_an_absent_term_is_never_an_unmatched_value():
    """Nearly every entry of a register is absent from nearly every document.
    Quoting them would be the G0 leak made routine."""
    merged = with_terms(Override(remove=(RemovedValue("typed by hand"),)), _list(SECRET_TERM))
    assert merged.unmatched("an unrelated document") == ["typed by hand"]


def test_a_finding_from_the_list_says_so():
    text = f"Contratto con {SECRET_TERM}."
    findings = with_terms(Override(), _list(SECRET_TERM)).apply(text, [])
    assert [(f.text, f.detector, f.layer.value) for f in findings] == [
        (SECRET_TERM, TERMS_DETECTOR, "H")
    ]


def test_the_longer_of_two_nested_values_wins_whatever_the_order():
    """In list order `Acme` would claim its characters first and leave ` Corp`."""
    text = "Fattura Acme Corp n. 12"
    for terms in (_list("Acme", "Acme Corp"), _list("Acme Corp", "Acme")):
        findings = with_terms(Override(), terms).apply(text, [])
        assert [f.text for f in findings] == ["Acme Corp"]


def test_matched_counts_the_entries_that_removed_something():
    text = "Fattura Acme Corp n. 12"
    override = with_terms(Override(), _list("Acme", "Acme Corp", "Progetto Aurora"))
    use = override.terms_use(override.apply(text, []))
    assert (use.loaded, use.matched) == (3, 1)
    assert Override().terms_use([]) is None

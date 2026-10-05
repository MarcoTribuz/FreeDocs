"""The firm's term list: values removed on every scrub, encrypted at rest.

A client register, a list of matter numbers, the code names of projects that do
not exist yet. It is the persistent form of the window's "add a value" control,
and like that control it can only ever **remove**. There is no persistent half
of ``keep`` and there must not be one: a standing "never redact X" would be an
allowance applied to documents nobody has read yet, which is the dangerous half
of ``core/overrides.py`` with the preview taken away.

**Encrypted because the realistic exposure is a synchronised folder.** Owner-only
permissions were the first proposal, and they protect against another account on
the machine - which is not where a firm's files go. They go to OneDrive,
SharePoint, iCloud and Dropbox, and to backups on disks nobody encrypted, and a
plaintext client register there is on somebody else's servers whatever the mode
bits said. The key file had already been decided the same way.

What that buys, and what it does not, is ``docs/terms.md``'s table and nothing
here may claim more. In short: a file that leaves this machine is unreadable
without the passphrase; malware running as the user is not stopped, because it
can read the passphrase as it is typed or the unlocked list from the engine.

Three rules this module keeps:

- **No error quotes a term or the passphrase.** Line numbers, counts and file
  names only. ``rpc.handle`` renders an unexpected exception into a response,
  and a message about line 412 of an import must not be line 412.
- **A save is atomic.** The list is edited in place and is its own source, so
  ``outputs.replace_private`` writes a sibling and renames over the original.
- **The header says nothing.** No count, no name, no date: how many clients a
  firm has is itself confidential, and the envelope's own fields are all a
  reader without the passphrase gets.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import sealed
from .findings import EntityType
from .limits import (
    MAX_TERM_CHARS,
    MAX_TERMS,
    MAX_TERMS_BYTES,
    MAX_TERMS_IMPORT_BYTES,
    refuse_too_many_terms,
)
from .outputs import private_directory, replace_private, write_private
from .overrides import TERMS_DETECTOR, Override, RemovedValue
from .text import fold_diacritics

#: Bumped when the envelope or the payload changes shape. A reader meeting a
#: version it does not know refuses rather than guessing.
TERMS_VERSION = 1

#: Recognisable in a listing and easy to put in a ``.gitignore``, as ``.fdmap``.
TERMS_SUFFIX = ".fdterms"

#: A single character would be removed from every word that contains it. Two is
#: still aggressive - ``AG`` is a legal form - but it is a thing a person can
#: mean, and the preview shows what it did.
MIN_TERM_CHARS = 2

#: See ``save_terms``: what the size of a sealed list may say about it.
PAD_BLOCK = 4096

_HOLDS = "this file holds every value on the term list"


class TermListError(sealed.MalformedSealed):
    """The file is not a term list, or an entry cannot be one.

    Never carries a term. A line number, a count or a file name says where to
    look, and the person holding the list can look.
    """


@dataclass(frozen=True)
class Term:
    """One value to remove, and the placeholder family it goes under.

    ``OTHER`` by default for the reason ``RemovedValue`` gives: a firm that has
    not said what a string is has still said it must go.
    """

    value: str
    entity: EntityType = EntityType.OTHER


@dataclass(frozen=True)
class TermList:
    """The decrypted list. Held by the engine for the life of an unlock."""

    terms: tuple[Term, ...] = ()

    def __len__(self) -> int:
        return len(self.terms)

    def removals(self) -> tuple[RemovedValue, ...]:
        """The list as override removals, each marked as coming from the list."""
        return tuple(
            RemovedValue(value=term.value, entity=term.entity, detector=TERMS_DETECTOR)
            for term in self.terms
        )

    def search(self, query: str | None) -> list[Term]:
        """Entries containing ``query``, case- and accent-blind, in list order.

        Folded for the reason every other table match in this engine is: the
        person searching types ``Societe`` for ``Société``. Matching a document
        is literal; finding an entry to delete is not the same question.
        """
        if not query:
            return list(self.terms)
        needle = fold_diacritics(query)
        return [term for term in self.terms if needle in fold_diacritics(term.value)]

    def with_added(self, new: Iterable[Term]) -> tuple[TermList, int]:
        """The list with ``new`` appended, and how many were actually new.

        An exact duplicate is skipped rather than refused: importing the same
        CRM export twice is ordinary. The first entity given for a value stays,
        because silently re-filing a client under a different type is a change
        nobody asked for.
        """
        seen = {term.value for term in self.terms}
        added: list[Term] = []
        for term in new:
            checked = check_term(term)
            if checked.value in seen:
                continue
            seen.add(checked.value)
            added.append(checked)
        refuse_too_many_terms("the term list", len(self.terms) + len(added))
        return TermList((*self.terms, *added)), len(added)

    def without(self, values: Iterable[str]) -> tuple[TermList, int]:
        """The list with every entry whose value is in ``values`` removed."""
        gone = set(values)
        kept = tuple(term for term in self.terms if term.value not in gone)
        return TermList(kept), len(self.terms) - len(kept)


def with_terms(override: Override, terms: TermList | None) -> Override:
    """``override`` with the list's removals added. Nothing else changes.

    The caller's own kept spans still apply to the list's findings: "remove this
    client everywhere except in the letterhead I am looking at" is a coherent
    instruction, and the preview is where it was given.
    """
    if terms is None or not terms.terms:
        return override
    return Override(keep=override.keep, remove=(*terms.removals(), *override.remove))


def check_term(term: Term) -> Term:
    """One entry, trimmed and refused when it cannot be matched sensibly.

    Surrounding whitespace is dropped because matching is literal and a
    trailing space pasted from a spreadsheet would make a client unmatchable
    at the end of every sentence. A line break or another control character is
    refused: the list is exported one entry per line, and an entry that cannot
    survive its own export is an entry that disappears on the next import.
    """
    value = term.value.strip()
    if len(value) < MIN_TERM_CHARS:
        raise TermListError(
            f"an entry must be at least {MIN_TERM_CHARS} characters, since it is "
            "removed wherever it appears inside a word"
        )
    if len(value) > MAX_TERM_CHARS:
        raise TermListError(f"an entry must be at most {MAX_TERM_CHARS} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise TermListError("an entry may not contain a line break, a tab or a control character")
    return Term(value=value, entity=term.entity)


def terms_unavailable_reason() -> str | None:
    """Why this build cannot hold a term list, or None when it can.

    The cipher's answer, not a second one: the list is sealed with the same
    envelope as the key file, so the two capabilities are one fact.
    """
    return sealed.cipher_unavailable_reason()


def check_passphrase(passphrase: str) -> None:
    sealed.check_passphrase(passphrase, _HOLDS)


def create_terms(path: Path, passphrase: str) -> TermList:
    """A new, empty list at ``path``. Refused when anything is already there.

    Creating over an existing list would replace a client register with an
    empty one, and the old passphrase would not bring it back.
    """
    check_passphrase(passphrase)
    if path.exists() or path.is_symlink():
        raise TermListError(f"{path.name} already exists; open it, or choose another name")
    empty = TermList()
    save_terms(path, empty, passphrase)
    return empty


def save_terms(path: Path, terms: TermList, passphrase: str) -> None:
    """Seal and write atomically, owner only."""
    check_passphrase(passphrase)
    sealed.require_cipher()
    payload = json.dumps(
        {"terms": [{"value": term.value, "entity": term.entity.value} for term in terms.terms]},
        ensure_ascii=False,
    ).encode("utf-8")
    # Padded to a whole block with JSON whitespace, which the reader ignores.
    # The header says nothing about the size of the list, and without this the
    # ciphertext length would: AES-GCM is a stream mode, so the file grew by
    # exactly the bytes of every entry added. A block of 4 KiB is about a
    # hundred entries, which is the resolution a reader of the file is left with.
    payload += b" " * (-len(payload) % PAD_BLOCK)
    data = sealed.seal(
        version_field="freedocs_terms",
        version=TERMS_VERSION,
        header={},
        payload_field="terms",
        payload=payload,
        passphrase=passphrase,
    )
    private_directory(path.parent)
    replace_private(path, data)


def open_terms(path: Path, passphrase: str) -> TermList:
    """Decrypt and validate. Raises ``BadPassphrase`` or :class:`TermListError`."""
    payload, _envelope = sealed.open_sealed(
        path,
        passphrase,
        version_field="freedocs_terms",
        version=TERMS_VERSION,
        payload_field="terms",
        max_bytes=MAX_TERMS_BYTES,
        malformed=TermListError,
    )
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TermListError(f"{path.name} decrypted to something that is not a term list") from exc
    rows = decoded.get("terms") if isinstance(decoded, dict) else None
    if not isinstance(rows, list):
        raise TermListError(f"{path.name} decrypted without a 'terms' list")
    refuse_too_many_terms(path.name, len(rows))

    terms: list[Term] = []
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("value"), str):
            raise TermListError(f"{path.name} entry {number} has no value")
        try:
            entity = EntityType(str(row.get("entity", EntityType.OTHER.value)))
        except ValueError as exc:
            raise TermListError(f"{path.name} entry {number} names an unknown entity type") from exc
        try:
            terms.append(check_term(Term(value=row["value"], entity=entity)))
        except TermListError as exc:
            raise TermListError(f"{path.name} entry {number}: {exc}") from exc
    return TermList(tuple(terms))


def rekey_terms(path: Path, old: str, new: str) -> TermList:
    """Re-seal under a new passphrase. The old one must open the file first."""
    check_passphrase(new)
    terms = open_terms(path, old)
    save_terms(path, terms, new)
    return terms


def read_import(source: Path) -> list[Term]:
    """Entries from a plaintext or CSV file, for a one-way import.

    Plaintext is one value per line, ``#`` starting a comment, and an optional
    ``ENTITY<TAB>`` prefix - the shape :func:`export_text` writes, so an export
    imports back unchanged. A CSV (by suffix) takes the value from its first
    column and the entity from an optional second one, and skips a header row
    whose first cell is ``value``.

    Nothing here deletes ``source``. The caller is told to, because a plaintext
    copy of the list defeats the encryption; deleting a person's file is not
    this tool's decision.
    """
    try:
        size = source.stat().st_size
        if size > MAX_TERMS_IMPORT_BYTES:
            raise TermListError(
                f"{source.name} is {size} bytes; this build imports up to "
                f"{MAX_TERMS_IMPORT_BYTES} bytes"
            )
        raw = source.read_bytes()
    except OSError as exc:
        raise TermListError(f"cannot read {source.name}: {exc.strerror or 'unreadable'}") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TermListError(f"{source.name} is not UTF-8 text") from exc

    if source.suffix.lower() == ".csv":
        terms = _read_csv(source.name, text)
    else:
        terms = _read_lines(source.name, text)
    refuse_too_many_terms(source.name, len(terms))
    return terms


def _read_lines(name: str, text: str) -> list[Term]:
    terms: list[Term] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entity = EntityType.OTHER
        value = stripped
        # Split before stripping. `PERSON<TAB> ` stripped first reads as the
        # value `PERSON`, which is an entry nobody meant and one that removes a
        # word from every document.
        if "\t" in line:
            prefix, value = line.split("\t", 1)
            # Not quoted: when the prefix is not an entity type it is most
            # likely the first half of a value that contained a tab.
            entity = _entity_on_line(name, number, prefix)
        terms.append(_term_on_line(name, number, value, entity))
    return terms


def _read_csv(name: str, text: str) -> list[Term]:
    terms: list[Term] = []
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise TermListError(f"{name} is not a readable CSV file") from exc
    for number, row in enumerate(rows, start=1):
        if not row or not row[0].strip() or row[0].strip().startswith("#"):
            continue
        if number == 1 and row[0].strip().casefold() == "value":
            continue
        entity = EntityType.OTHER
        if len(row) > 1 and row[1].strip():
            entity = _entity_on_line(name, number, row[1])
        terms.append(_term_on_line(name, number, row[0], entity))
    return terms


def _entity_on_line(name: str, number: int, raw: str) -> EntityType:
    try:
        return EntityType(raw.strip().upper())
    except ValueError as exc:
        raise TermListError(
            f"{name} line {number}: what comes before the value is not an entity type"
        ) from exc


def _term_on_line(name: str, number: int, value: str, entity: EntityType) -> Term:
    try:
        return check_term(Term(value=value, entity=entity))
    except TermListError as exc:
        raise TermListError(f"{name} line {number}: {exc}") from exc


def export_text(terms: TermList) -> str:
    """The list in plaintext, one ``ENTITY<TAB>value`` per line.

    Always prefixed, ``OTHER`` included, so a value that happens to look like
    ``PERSON`` followed by a tab cannot be read back as something else.
    """
    header = (
        "# FreeDocs term list export. This file is NOT encrypted: anyone who can\n"
        "# read it can read every entry. Import it back and delete it.\n"
    )
    return header + "".join(f"{term.entity.value}\t{term.value}\n" for term in terms.terms)


def write_export(output: Path, terms: TermList, *, refuse: Sequence[Path] = ()) -> None:
    """Write the plaintext export, owner only, never over the list itself.

    ``refuse`` names the sealed file the export came from: an export written
    over it would replace the encrypted list with its own plaintext, which is
    the one accident in this feature that cannot be undone.
    """
    try:
        target = output.resolve()
        forbidden = {path.resolve() for path in refuse}
    except OSError:  # pragma: no cover - an unresolvable path fails at the write
        target, forbidden = output, set()
    if target in forbidden or output.suffix == TERMS_SUFFIX:
        raise TermListError(
            f"refusing to write a plaintext export to {output.name}; that is where "
            "an encrypted term list belongs"
        )
    private_directory(output.parent)
    write_private(output, export_text(terms).encode("utf-8"))


def parse_terms(items: Sequence[object] | None) -> list[Term]:
    """Entries from decoded JSON: a string, or ``{"value", "entity"?}``.

    The same contract as a removal in ``parse_override``, so the window builds
    one shape for both. An unknown entity is an error, not a quiet ``OTHER``.
    """
    terms: list[Term] = []
    for number, item in enumerate(items or [], start=1):
        if isinstance(item, str):
            terms.append(check_term(Term(value=item)))
            continue
        if not isinstance(item, dict) or not isinstance(item.get("value"), str):
            raise TermListError(f"entry {number} needs a 'value' string")
        entity = EntityType.OTHER
        if item.get("entity") is not None:
            try:
                entity = EntityType(str(item["entity"]).upper())
            except ValueError as exc:
                raise TermListError(f"entry {number} names an unknown entity type") from exc
        terms.append(check_term(Term(value=item["value"], entity=entity)))
    return terms


__all__ = [
    "MAX_TERMS",
    "MIN_TERM_CHARS",
    "TERMS_SUFFIX",
    "TERMS_VERSION",
    "Term",
    "TermList",
    "TermListError",
    "check_passphrase",
    "check_term",
    "create_terms",
    "export_text",
    "open_terms",
    "parse_terms",
    "read_import",
    "rekey_terms",
    "save_terms",
    "terms_unavailable_reason",
    "with_terms",
    "write_export",
]

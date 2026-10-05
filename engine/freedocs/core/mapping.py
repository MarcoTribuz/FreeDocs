"""The key file: placeholder back to original, encrypted, opt-in.

This is the one file FreeDocs writes that is as confidential as the document it
came from. Everything here follows from that.

The engine's default is unchanged and stays unchanged: a scrub destroys its
mapping in a ``finally`` block and nothing reaches disk. This module is reached
only when a caller names a path *and* supplies a passphrase, and it is what turns
that one run from anonymisation into pseudonymisation. Nothing in the scrub
pipeline imports it: the key file is composed from a finished
:class:`~freedocs.pipeline.ScrubResult` by the front end that asked for it, so
:class:`~freedocs.core.policy.SurrogateAllocator` still forgets on the same line
it always did.

Both the writer and the reader live here, for the reason
``core/model_manifest.py`` exists: a format whose two halves sit in different
modules is a format that gets half-changed. ``parse``-style validation of the
envelope is here too rather than in ``rpc.py``, the same call
``core/overrides.py`` makes — the CLI and the pipe must not be able to disagree
about what a key file is.

Three things this module refuses to do:

- **Put a passphrase or a value into an exception.** ``rpc.handle`` renders an
  unexpected exception as ``f"{type(exc).__name__}: {exc}"`` straight into a
  response, so a message that quoted either would be the leak this whole tool
  exists to prevent. Same discipline as ``Leak.describe()``.
- **Fall back to plaintext.** There is no unencrypted form of this file. A
  ``--map`` that quietly degraded when the extra was missing would write the key
  in the clear at exactly the moment nobody was watching.
- **Import ``cryptography`` at module scope.** It is an optional extra, so the
  import happens inside the two functions that need it and
  :func:`mapping_unavailable_reason` is the single authority on whether they can
  run — the lesson ``ocr_unavailable_reason()`` was written after.

The envelope itself - scrypt, AES-256-GCM, the header bound as associated data,
the work-factor band - lives in ``core/sealed.py``, because the term list is
sealed the same way and two copies of a cipher recipe are two places for a fix
to land in one of. What is left here is what a key file *says*.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import sealed
from .findings import EntityType
from .limits import MAX_MAP_BYTES
from .outputs import private_directory, write_private

# Re-exported: these were this module's names before the envelope moved, and
# the CLI, the pipe and the tests still ask for them here.
from .sealed import MIN_PASSPHRASE, BadPassphrase
from .sealed import aad as _aad
from .sealed import derive as _derive

__all__ = [
    "MAP_SUFFIX",
    "MAP_VERSION",
    "MAX_MAP_BYTES",
    "MIN_PASSPHRASE",
    "BadPassphrase",
    "KeyMap",
    "MalformedMap",
    "MapEntry",
    "_aad",
    "_derive",
    "check_passphrase",
    "key_map_from",
    "map_path_for",
    "mapping_unavailable_reason",
    "read_key_map",
    "refuse_inside",
    "write_key_map",
]

if TYPE_CHECKING:  # pragma: no cover - import cycle: pipeline imports core, not vice versa
    from ..pipeline import ScrubResult

#: Bumped when the envelope changes shape. A reader that meets a version it does
#: not know refuses rather than guessing: a mis-parsed key file would write the
#: wrong value into a document and look like it worked.
MAP_VERSION = 1

#: Distinct on purpose, and greppable. A key file must be recognisable at a
#: glance in a directory listing and easy to put in a ``.gitignore``.
MAP_SUFFIX = ".fdmap"


class MalformedMap(sealed.MalformedSealed):
    """The file is not a key file, or not one this build can read."""


@dataclass(frozen=True)
class MapEntry:
    """One placeholder and the value it stands for.

    ``variants`` is the count of distinct spellings that collapsed into this
    placeholder, and it is why it is here rather than derivable later.
    ``policy._normalise`` casefolds and collapses whitespace, so ``Mario Rossi``,
    ``MARIO ROSSI`` and ``Mario  Rossi`` share one placeholder and only one of
    them can be written back. Anything above 1 means the round trip is lossy for
    this entry, and the caller is told so instead of finding out by reading the
    restored document.
    """

    placeholder: str
    value: str
    entity: EntityType
    country: str | None
    #: How many times the value was replaced in the source document. Reported so
    #: a restore can say "the map expected three and the returned document had
    #: one", which is the difference between a model that dropped text and a
    #: restore that failed.
    occurrences: int
    variants: int


@dataclass(frozen=True)
class KeyMap:
    """Everything needed to undo one document's scrub, and nothing else.

    No offsets. They describe an extraction of a file that no longer exists, and
    a restore searches the returned text anyway — carrying them would be extra
    confidential detail in the one file that must carry as little as possible.
    """

    document: str
    format_name: str
    #: SHA-256 of the *scrubbed output* — the file the user actually sent.
    #: Audit metadata, and deliberately not enforced anywhere: a restore runs on
    #: what came back from the model, which never matches this. A check here
    #: could only ever fire wrongly, so the honest pairing question is "do this
    #: document's placeholders appear in this map", which the restore report
    #: answers.
    output_sha256: str
    #: Which locale wrote the stems. Metadata only: matching is on the literal
    #: placeholders this file carries, so ``PLACEHOLDER_LABELS`` gains no second
    #: reader and a restore cannot re-derive a stem and guess.
    placeholder_language: str
    entries: tuple[MapEntry, ...]

    def by_placeholder(self) -> dict[str, MapEntry]:
        return {entry.placeholder: entry for entry in self.entries}

    def warnings(self) -> list[str]:
        """What this key file cannot fully undo, stated when it is written.

        Said at write time as well as at restore time, because the person who
        chooses to keep a key file is the person who should know its limit.
        """
        lossy = [entry for entry in self.entries if entry.variants > 1]
        if not lossy:
            return []
        return [
            f"{len(lossy)} placeholder(s) stood for a value written more than one "
            "way (differing case or spacing); a restore writes the first spelling "
            "seen in the source document, not each original form"
        ]


def mapping_unavailable_reason() -> str | None:
    """Why this build cannot read or write a key file, or None when it can.

    Asked of ``sealed.cipher_unavailable_reason`` rather than answered here: the
    term list needs the same cipher, and two checks for one extra is the shape
    ``capabilities.ocr_available`` once had when it checked one half of a
    two-part requirement.
    """
    return sealed.cipher_unavailable_reason()


def key_map_from(result: ScrubResult, *, placeholder_language: str) -> KeyMap:
    """Build the key map from a finished scrub.

    Reads ``result.decisions``, which still carries both halves after
    ``allocator.close()`` has run: ``Decision.finding.text`` is the original and
    ``Decision.replacement`` is the placeholder. That is why this feature needs
    no change to :class:`SurrogateAllocator` and why the mapping's destruction in
    ``pipeline.scrub``'s ``finally`` is untouched.

    Only rewritten findings appear. ``REPORT_ONLY`` types are never replaced, so
    there is no placeholder to invert, and an entry for one would promise a
    restore something to do.

    The value kept is the **first in document order**. ``_decide`` walks findings
    in span order, so the first decision naming a placeholder is the first
    occurrence in the document, and ``setdefault`` on that is a definition rather
    than an accident.

    The gate is ``replacement is not None``, which is exactly the set
    ``pipeline._REWRITING_ACTIONS`` describes: a decision gets a placeholder if and
    only if the policy chose to rewrite it. Read from the decision rather than
    imported from there, so this module does not reach across for a private name
    and does not keep a second copy of the set either.
    """
    first: dict[str, MapEntry] = {}
    spellings: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for decision in result.decisions:
        if decision.replacement is None:
            continue
        placeholder = decision.replacement
        finding = decision.finding
        counts[placeholder] = counts.get(placeholder, 0) + 1
        spellings.setdefault(placeholder, set()).add(finding.text)
        first.setdefault(
            placeholder,
            MapEntry(
                placeholder=placeholder,
                value=finding.text,
                entity=finding.entity,
                country=finding.country,
                occurrences=0,
                variants=0,
            ),
        )

    entries = tuple(
        MapEntry(
            placeholder=entry.placeholder,
            value=entry.value,
            entity=entry.entity,
            country=entry.country,
            occurrences=counts[entry.placeholder],
            variants=len(spellings[entry.placeholder]),
        )
        for entry in first.values()
    )
    return KeyMap(
        document=result.source.name,
        format_name=result.format_name,
        output_sha256=hashlib.sha256(result.output).hexdigest(),
        placeholder_language=placeholder_language,
        entries=entries,
    )


def check_passphrase(passphrase: str) -> None:
    """Refuse a passphrase too short to be one. Raises without quoting it."""
    sealed.check_passphrase(passphrase, "this file holds every value the scrub removed")


def _header(key_map: KeyMap) -> dict[str, Any]:
    """What a key file adds to the envelope's cleartext header.

    Bound as associated data with the rest of it, so the ciphertext cannot be
    lifted onto a different header: swapping the document name fails decryption
    rather than producing a key file that describes the wrong document.

    It leaks the source filename and the output hash to anyone who can read the
    file. Stated rather than hidden — ``report.build_report`` already emits
    ``result.source.name``, and whoever holds this file holds every value in it,
    so a filename is not the secret being protected here.
    """
    return {
        "document": {
            "name": key_map.document,
            "format": key_map.format_name,
            "sha256": key_map.output_sha256,
        },
        "placeholder_language": key_map.placeholder_language,
    }


def write_key_map(path: Path, key_map: KeyMap, passphrase: str) -> None:
    """Encrypt and write, mode 0600.

    Restrictive permissions on an encrypted file are not redundant. They stop the
    accident that actually happens — another account on a shared machine, a
    backup agent, a directory served by something — and they cost one syscall.
    """
    check_passphrase(passphrase)
    payload = json.dumps(
        {
            "entries": [
                {
                    "placeholder": entry.placeholder,
                    "value": entry.value,
                    "entity": entry.entity.value,
                    "country": entry.country,
                    "occurrences": entry.occurrences,
                    "variants": entry.variants,
                }
                for entry in key_map.entries
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")
    data = sealed.seal(
        version_field="freedocs_map",
        version=MAP_VERSION,
        header=_header(key_map),
        payload_field="entries",
        payload=payload,
        passphrase=passphrase,
    )

    private_directory(path.parent)
    # Through `core/outputs.py` rather than a second `os.open` here. This
    # function's own comments are what that module was built from - the explicit
    # mode rather than a write-then-chmod, and the chmod anyway because O_CREAT
    # leaves an existing file's mode alone - and a restored document turned out to
    # need every one of them.
    write_private(path, data)


def read_key_map(path: Path, passphrase: str) -> KeyMap:
    """Decrypt and validate. Raises :class:`BadPassphrase` or :class:`MalformedMap`.

    Every failure here is reported without quoting the passphrase or any
    decrypted value, because this function's caller may be ``rpc.handle``, whose
    generic path puts an exception's own message straight into a response.
    """
    payload, envelope = sealed.open_sealed(
        path,
        passphrase,
        version_field="freedocs_map",
        version=MAP_VERSION,
        payload_field="entries",
        max_bytes=MAX_MAP_BYTES,
        malformed=MalformedMap,
        required_objects=("document",),
    )
    return _parse_payload(path.name, payload, envelope, envelope["document"])


def _parse_payload(
    name: str, payload: bytes, envelope: dict[str, Any], document: dict[str, Any]
) -> KeyMap:
    """Turn decrypted bytes into a :class:`KeyMap`, refusing anything odd.

    Validation after decryption is not paranoia about the cipher — the tag has
    already proved the bytes are ours. It is about a *future* build's file, and
    about the one thing worth refusing loudly: a duplicate placeholder, which
    would silently make one of two values unrestorable.
    """
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise MalformedMap(f"{name} decrypted to something that is not a key map") from exc
    rows = decoded.get("entries") if isinstance(decoded, dict) else None
    if not isinstance(rows, list):
        raise MalformedMap(f"{name} decrypted without an 'entries' list")

    entries: list[MapEntry] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise MalformedMap(f"{name} has an entry that is not an object")
        placeholder = row.get("placeholder")
        value = row.get("value")
        if not isinstance(placeholder, str) or not isinstance(value, str):
            raise MalformedMap(f"{name} has an entry without a placeholder and a value")
        if placeholder in seen:
            raise MalformedMap(
                f"{name} names {placeholder} twice; one of the two values could "
                "never be restored and this build will not guess which"
            )
        seen.add(placeholder)
        try:
            entity = EntityType(str(row.get("entity")))
        except ValueError as exc:
            raise MalformedMap(
                f"{name} names an unknown entity type {row.get('entity')!r}"
            ) from exc
        entries.append(
            MapEntry(
                placeholder=placeholder,
                value=value,
                entity=entity,
                country=row.get("country") if isinstance(row.get("country"), str) else None,
                occurrences=_count(row, "occurrences", 0, name),
                variants=_count(row, "variants", 1, name),
            )
        )

    language = envelope.get("placeholder_language")
    return KeyMap(
        document=str(document.get("name") or name),
        format_name=str(document.get("format") or "unknown"),
        output_sha256=str(document.get("sha256") or ""),
        placeholder_language=language if isinstance(language, str) else "en",
        entries=tuple(entries),
    )


def _count(row: dict[str, Any], field: str, default: int, name: str) -> int:
    """One entry's count, refused as a key-file problem rather than a traceback.

    ``int(row.get(field) or default)`` raised a bare ``ValueError`` on anything
    non-numeric, and ``rpc.handle`` renders an unexpected exception as
    ``f"{type(exc).__name__}: {exc}"`` - so the caller got a message about
    Python's integer parsing, in the one module whose every other failure names
    the file and nothing else.
    """
    raw = row.get(field)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise MalformedMap(f"{name} has an entry whose {field!r} is not a count")
    return raw


def map_path_for(target: Path, source: Path) -> Path:
    """Where one document's key file goes.

    A directory (or anything without our suffix) gets ``<stem>.fdmap`` inside it;
    a named file is taken as given. One file per document, never one per batch:
    a span is scoped per document everywhere else in this engine, and a combined
    file is one file that leaks three documents.
    """
    if target.suffix == MAP_SUFFIX and not target.is_dir():
        return target
    return target / (source.stem + MAP_SUFFIX)


def refuse_inside(target: Path, output_dir: Path) -> str | None:
    """A sentence when the key file would land in the output directory.

    The realistic accident is not theft. It is zipping the output folder and
    sending it, or having it inside a synced ``Documents``: the scrubbed document
    and the key to undo it, travelling together. Costs one comparison and
    addresses the failure that will actually happen.
    """
    try:
        resolved = target.resolve()
        out = output_dir.resolve()
    except OSError:  # pragma: no cover - an unresolvable path fails later anyway
        return None
    if resolved == out or out in resolved.parents:
        return (
            f"the key file would be written inside {output_dir}, next to the "
            "scrubbed document it undoes; put it elsewhere, or pass "
            "--map-in-output-dir to say you meant it"
        )
    return None

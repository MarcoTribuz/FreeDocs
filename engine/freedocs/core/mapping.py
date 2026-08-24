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
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import MissingDependency
from .findings import EntityType

if TYPE_CHECKING:  # pragma: no cover - import cycle: pipeline imports core, not vice versa
    from ..pipeline import ScrubResult

#: Bumped when the envelope changes shape. A reader that meets a version it does
#: not know refuses rather than guessing: a mis-parsed key file would write the
#: wrong value into a document and look like it worked.
MAP_VERSION = 1

#: Distinct on purpose, and greppable. A key file must be recognisable at a
#: glance in a directory listing and easy to put in a ``.gitignore``.
MAP_SUFFIX = ".fdmap"

#: Refused below this. The file's entire content is confidential, so a passphrase
#: that a wordlist reaches in seconds is not a passphrase. Hard failure rather
#: than a warning: a warning printed during a successful command is a warning
#: nobody reads.
MIN_PASSPHRASE = 8

#: scrypt cost. n=2**15 is roughly 100 ms and 32 MB on a laptop, which is the
#: right order for a key a human types once per document and wrong for anything
#: an attacker wants to try a billion of.
SCRYPT_N = 32768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2

SALT_BYTES = 16
#: AES-GCM's standard nonce length. Random per file, never reused: the key is
#: derived per file from a fresh salt, so even an identical passphrase and
#: identical contents produce a different ciphertext.
NONCE_BYTES = 12
KEY_BYTES = 32


class BadPassphrase(ValueError):
    """The passphrase does not open this file, or the file was altered.

    One error for both, deliberately. AES-GCM cannot tell a wrong key from
    tampered bytes and neither can a caller do anything different about them, so
    inventing two messages would be inventing a distinction. The message names
    neither the passphrase nor anything inside the file.
    """


class MalformedMap(ValueError):
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

    The single authority, and the reason there is one: ``capabilities`` publishes
    it, ``doctor`` renders it and both write and read raise from it, so the
    capability and the refusal cannot disagree. ``capabilities.ocr_available``
    once checked one half of a two-part requirement and made the window promise
    an OCR the first scan could not deliver; this is that bug's shape, prevented
    the same way.

    Uses ``find_spec`` rather than an import: this is called from
    ``capabilities``, on every session start, and importing a Rust extension to
    answer a question about its presence is work for nothing.
    """
    import importlib.util

    try:
        found = importlib.util.find_spec("cryptography") is not None
    except (ImportError, ValueError):
        found = False
    if found:
        return None
    return (
        "cryptography is not installed, so a key file can be neither written nor "
        "read; a scrub without one is unaffected and stays irreversible"
    )


def _require_cryptography() -> Any:
    reason = mapping_unavailable_reason()
    if reason is not None:
        raise MissingDependency(reason)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM


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
    """
    from ..pipeline import _REWRITING_ACTIONS

    first: dict[str, MapEntry] = {}
    spellings: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for decision in result.decisions:
        if decision.action not in _REWRITING_ACTIONS or decision.replacement is None:
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
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(
            f"the passphrase must be at least {MIN_PASSPHRASE} characters; this "
            "file holds every value the scrub removed"
        )


def _derive(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
        maxmem=SCRYPT_MAXMEM,
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise MalformedMap(f"{field!r} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise MalformedMap(f"{field!r} is not valid base64") from exc


def _header(key_map: KeyMap, salt: bytes, nonce: bytes) -> dict[str, Any]:
    """The cleartext half, which is also the AEAD associated data.

    Binding the header means the ciphertext cannot be lifted onto a different
    header: swapping the document name or the KDF parameters fails decryption
    rather than producing a key file that describes the wrong document.

    It leaks the source filename and the output hash to anyone who can read the
    file. Stated rather than hidden — ``report.build_report`` already emits
    ``result.source.name``, and whoever holds this file holds every value in it,
    so a filename is not the secret being protected here.
    """
    return {
        "freedocs_map": MAP_VERSION,
        "kdf": {
            "algorithm": "scrypt",
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
            "salt": _b64(salt),
        },
        "cipher": "AES-256-GCM",
        "nonce": _b64(nonce),
        "document": {
            "name": key_map.document,
            "format": key_map.format_name,
            "sha256": key_map.output_sha256,
        },
        "placeholder_language": key_map.placeholder_language,
    }


def _aad(header: dict[str, Any]) -> bytes:
    """Canonical bytes of the header, so writer and reader agree byte for byte."""
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_key_map(path: Path, key_map: KeyMap, passphrase: str) -> None:
    """Encrypt and write, mode 0600.

    Restrictive permissions on an encrypted file are not redundant. They stop the
    accident that actually happens — another account on a shared machine, a
    backup agent, a directory served by something — and they cost one syscall.
    """
    aesgcm = _require_cryptography()
    check_passphrase(passphrase)

    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    header = _header(key_map, salt, nonce)
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

    sealed = aesgcm(_derive(passphrase, salt)).encrypt(nonce, payload, _aad(header))
    envelope = {**header, "entries": _b64(sealed)}

    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened with an explicit mode rather than written and then chmod'ed: between
    # those two calls the key sits on disk world-readable.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(envelope, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    # An existing file keeps its old mode through O_CREAT, so this is the case
    # where writing over yesterday's key file would otherwise keep yesterday's
    # permissions.
    os.chmod(path, 0o600)


def read_key_map(path: Path, passphrase: str) -> KeyMap:
    """Decrypt and validate. Raises :class:`BadPassphrase` or :class:`MalformedMap`.

    Every failure here is reported without quoting the passphrase or any
    decrypted value, because this function's caller may be ``rpc.handle``, whose
    generic path puts an exception's own message straight into a response.
    """
    aesgcm = _require_cryptography()

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MalformedMap(f"cannot read {path.name}: {exc.strerror or 'unreadable'}") from exc
    try:
        envelope = json.loads(raw)
    except ValueError as exc:
        raise MalformedMap(f"{path.name} is not a key file: malformed JSON") from exc
    if not isinstance(envelope, dict):
        raise MalformedMap(f"{path.name} is not a key file: expected an object")

    version = envelope.get("freedocs_map")
    if version != MAP_VERSION:
        raise MalformedMap(
            f"{path.name} is a version {version!r} key file; this build reads version {MAP_VERSION}"
        )
    if envelope.get("cipher") != "AES-256-GCM":
        raise MalformedMap(f"{path.name} names an unknown cipher {envelope.get('cipher')!r}")

    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("algorithm") != "scrypt":
        raise MalformedMap(f"{path.name} names an unknown key derivation")
    document = envelope.get("document")
    if not isinstance(document, dict):
        raise MalformedMap(f"{path.name} is missing its 'document' header")

    salt = _unb64(kdf.get("salt"), "kdf.salt")
    nonce = _unb64(envelope.get("nonce"), "nonce")
    sealed = _unb64(envelope.get("entries"), "entries")

    # Rebuilt from the file's own header rather than from constants, so a key file
    # written with different scrypt parameters still opens. The AAD is then
    # whatever the file says, which is exactly what binds the two halves.
    header = {key: value for key, value in envelope.items() if key != "entries"}
    try:
        key = hashlib.scrypt(
            passphrase.encode("utf-8"),
            salt=salt,
            n=int(kdf.get("n", SCRYPT_N)),
            r=int(kdf.get("r", SCRYPT_R)),
            p=int(kdf.get("p", SCRYPT_P)),
            dklen=KEY_BYTES,
            maxmem=SCRYPT_MAXMEM,
        )
    except (TypeError, ValueError) as exc:
        raise MalformedMap(f"{path.name} has unusable key derivation parameters") from exc

    try:
        payload = aesgcm(key).decrypt(nonce, sealed, _aad(header))
    except Exception as exc:
        raise BadPassphrase(
            f"{path.name} did not open: the passphrase is wrong, or the file has "
            "been altered since it was written"
        ) from exc

    return _parse_payload(path.name, payload, envelope, document)


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
                occurrences=int(row.get("occurrences") or 0),
                variants=int(row.get("variants") or 1),
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

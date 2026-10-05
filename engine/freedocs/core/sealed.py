"""The encrypted envelope, shared by the key file and the term list.

Two files are sealed this way and both are as confidential as anything this tool
touches: the key file holds every value one scrub removed, and the term list is
the firm's client register. They were going to be two copies of one recipe - a
scrypt key from a passphrase, AES-256-GCM over the payload, the cleartext header
bound as associated data - and two copies of a cipher recipe are two places for
the next fix to land in only one of. So the recipe lives here and
``core/mapping.py`` and ``core/terms.py`` say only what goes inside.

**The key-file format did not move by one byte when this was extracted.**
``tests/fixtures/before-sealed.fdmap`` was written by the code this replaced,
with its randomness pinned, and ``test_sealed.py`` both opens it and writes the
same map again to compare the bytes. A key file somebody kept last month is a
file they will want to open next year.

**The two kinds refuse each other.** Each carries its own version field
(``freedocs_map``, ``freedocs_terms``), and a reader meeting the other one says
which file it was handed rather than reporting an unknown version. Nothing about
them is interchangeable anyway - the header is the AAD, so a key file's
ciphertext cannot be lifted under a term list's header - but "this is a key
file, not a term list" is the sentence a person who picked the wrong file needs.

The rules ``core/mapping.py`` grew stay in force here, because they are about
the envelope rather than the key file:

- **No exception quotes the passphrase or anything decrypted.** ``rpc.handle``
  renders an unexpected exception straight into a response.
- **The file's own work factor is bounded before any derivation runs**, because
  a reader derives from what the file declares.
- **``cryptography`` is imported inside the functions that need it**, and
  :func:`cipher_unavailable_reason` is the single authority on whether they can.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from .errors import MissingDependency

CIPHER = "AES-256-GCM"

#: Refused below this. Both files are entirely confidential, so a passphrase
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

#: The band a *file's own* KDF parameters must fall in, since a reader derives
#: the key from what the file declares rather than from the constants above.
#:
#: ``SCRYPT_MAXMEM`` already bounded two of the three by accident: scrypt's cost
#: is n*r*p and only n and r touch memory, so a raised n or r fails inside
#: ``hashlib.scrypt`` and becomes a clean refusal. Nothing bounded p at all, and a
#: file declaring ``p = 2**24`` grinds for hours - inside a single-threaded engine
#: with no cancel, which is the whole session, while the caller sees a timeout and
#: the process keeps burning a core. A key file is a thing people send each
#: other, so this is reachable exactly as the feature intends to be used.
#:
#: Read as a time budget, not a taste in parameters. The per-field ceilings are
#: generous enough that a future version could raise the defaults and a file
#: written by one would still open; the product is what actually bounds the wait,
#: and is deliberately checked separately so an absurd single value is named as
#: itself.
MAX_SCRYPT_N = 1 << 20
MAX_SCRYPT_R = 64
MAX_SCRYPT_P = 16
MAX_SCRYPT_WORK = 16 * SCRYPT_N * SCRYPT_R * SCRYPT_P

SALT_BYTES = 16
#: AES-GCM's standard nonce length. Random per write, never reused: the key is
#: derived per write from a fresh salt, so even an identical passphrase and
#: identical contents produce a different ciphertext.
NONCE_BYTES = 12
KEY_BYTES = 32

#: Every sealed kind this build knows, by the header field that names it. Read
#: only to say which file a reader was handed instead of the one it wanted.
KINDS = {"freedocs_map": "key file", "freedocs_terms": "term list"}


class BadPassphrase(ValueError):
    """The passphrase does not open this file, or the file was altered.

    One error for both, deliberately. AES-GCM cannot tell a wrong key from
    tampered bytes and neither can a caller do anything different about them, so
    inventing two messages would be inventing a distinction. The message names
    neither the passphrase nor anything inside the file.
    """


class MalformedSealed(ValueError):
    """The file is not the sealed kind asked for, or not one this build reads.

    Never raised as itself: each kind passes its own subclass, so a caller that
    catches ``MalformedMap`` is not handed a term-list problem and the reverse.
    """


def cipher_unavailable_reason() -> str | None:
    """Why this build cannot seal or open anything, or None when it can.

    The single authority, and the reason there is one: ``capabilities`` publishes
    it for both the key file and the term list, ``doctor`` renders it and every
    seal and open raises from it, so the capability and the refusal cannot
    disagree. ``capabilities.ocr_available`` once checked one half of a two-part
    requirement and made the window promise an OCR the first scan could not
    deliver; this is that bug's shape, prevented the same way.

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
        "cryptography is not installed, so neither a key file nor a term list can "
        "be written or read; a scrub without either is unaffected and stays "
        "irreversible"
    )


def require_cipher() -> Any:
    reason = cipher_unavailable_reason()
    if reason is not None:
        raise MissingDependency(reason)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM


def check_passphrase(passphrase: str, holds: str) -> None:
    """Refuse a passphrase too short to be one. Raises without quoting it.

    ``holds`` finishes the sentence with what the file protects, because the
    reason the floor exists is the thing the person is about to lock away.
    """
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f"the passphrase must be at least {MIN_PASSPHRASE} characters; {holds}")


def derive(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
        maxmem=SCRYPT_MAXMEM,
    )


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def unb64(value: object, field: str, malformed: type[MalformedSealed]) -> bytes:
    if not isinstance(value, str):
        raise malformed(f"{field!r} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise malformed(f"{field!r} is not valid base64") from exc


def aad(header: dict[str, Any]) -> bytes:
    """Canonical bytes of the header, so writer and reader agree byte for byte."""
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def work_factor(
    kdf: dict[str, Any], name: str, malformed: type[MalformedSealed]
) -> tuple[int, int, int]:
    """The file's own scrypt parameters, refused unless they are in the band.

    Refused *before* any derivation runs, which is the whole point: a ceiling
    enforced by ``hashlib.scrypt`` failing is a ceiling on memory, and the
    parameter that costs only time had none. Every rejection names the field and
    the band, because the caller's only useful move is to distrust the file.

    ``bool`` is excluded explicitly: ``isinstance(True, int)`` is true, so a
    ``"p": true`` would otherwise derive with p=1 and be treated as a valid file.
    A JSON float - ``1e9``, or 1.5 - is refused for what it is rather than
    silently truncated.
    """
    read: dict[str, int] = {}
    for field, default, ceiling in (
        ("n", SCRYPT_N, MAX_SCRYPT_N),
        ("r", SCRYPT_R, MAX_SCRYPT_R),
        ("p", SCRYPT_P, MAX_SCRYPT_P),
    ):
        raw = kdf.get(field, default)
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise malformed(f"{name} declares a scrypt {field} that is not a whole number")
        if not 1 <= raw <= ceiling:
            raise malformed(
                f"{name} declares scrypt {field}={raw}; this build reads 1 to {ceiling}"
            )
        read[field] = raw

    work = read["n"] * read["r"] * read["p"]
    if work > MAX_SCRYPT_WORK:
        raise malformed(
            f"{name} asks for {work // (SCRYPT_N * SCRYPT_R * SCRYPT_P)} times the key "
            "derivation work this build does; each parameter is in range but their "
            "product is not"
        )
    return read["n"], read["r"], read["p"]


def seal(
    *,
    version_field: str,
    version: int,
    header: dict[str, Any],
    payload_field: str,
    payload: bytes,
    passphrase: str,
) -> bytes:
    """The whole file, as bytes: cleartext header plus the sealed payload.

    ``header`` is what the kind adds to the envelope's own fields, and it is
    bound as associated data along with them - so swapping a document name or a
    KDF parameter fails decryption rather than producing a file that describes
    something else. Sorted keys and a trailing newline, because that is what the
    key file has always been and ``before-sealed.fdmap`` holds it to that.
    """
    aesgcm = require_cipher()
    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    full = {
        version_field: version,
        "kdf": {
            "algorithm": "scrypt",
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
            "salt": b64(salt),
        },
        "cipher": CIPHER,
        "nonce": b64(nonce),
        **header,
    }
    sealed = aesgcm(derive(passphrase, salt)).encrypt(nonce, payload, aad(full))
    envelope = {**full, payload_field: b64(sealed)}
    return (json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def open_sealed(
    path: Path,
    passphrase: str,
    *,
    version_field: str,
    version: int,
    payload_field: str,
    max_bytes: int,
    malformed: type[MalformedSealed],
    required_objects: tuple[str, ...] = (),
) -> tuple[bytes, dict[str, Any]]:
    """Decrypt one file. Returns the payload bytes and the cleartext envelope.

    Every structural check runs before the derivation, and ``required_objects``
    lets a kind demand its own header fields there too: a key file missing its
    ``document`` block is malformed, and checking that after decryption would
    report it as a wrong passphrase instead, since the header is the AAD.
    """
    aesgcm = require_cipher()
    kind = KINDS[version_field]

    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise malformed(
                f"{path.name} is {size} bytes; this build reads a {kind} of up to {max_bytes} bytes"
            )
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise malformed(f"cannot read {path.name}: {exc.strerror or 'unreadable'}") from exc
    except UnicodeDecodeError as exc:
        raise malformed(f"{path.name} is not a {kind}: not UTF-8 text") from exc
    try:
        envelope = json.loads(raw)
    except ValueError as exc:
        raise malformed(f"{path.name} is not a {kind}: malformed JSON") from exc
    if not isinstance(envelope, dict):
        raise malformed(f"{path.name} is not a {kind}: expected an object")

    if version_field not in envelope:
        for other_field, other_kind in KINDS.items():
            if other_field in envelope:
                raise malformed(f"{path.name} is a {other_kind}, not a {kind}")
    found = envelope.get(version_field)
    if found != version:
        raise malformed(
            f"{path.name} is a version {found!r} {kind}; this build reads version {version}"
        )
    if envelope.get("cipher") != CIPHER:
        raise malformed(f"{path.name} names an unknown cipher {envelope.get('cipher')!r}")

    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("algorithm") != "scrypt":
        raise malformed(f"{path.name} names an unknown key derivation")
    for field in required_objects:
        if not isinstance(envelope.get(field), dict):
            raise malformed(f"{path.name} is missing its {field!r} header")

    salt = unb64(kdf.get("salt"), "kdf.salt", malformed)
    nonce = unb64(envelope.get("nonce"), "nonce", malformed)
    sealed = unb64(envelope.get(payload_field), payload_field, malformed)

    # Rebuilt from the file's own header rather than from constants, so a file
    # written with different scrypt parameters still opens. The AAD is then
    # whatever the file says, which is exactly what binds the two halves.
    header = {key: value for key, value in envelope.items() if key != payload_field}
    n, r, p = work_factor(kdf, path.name, malformed)
    try:
        key = hashlib.scrypt(
            passphrase.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=KEY_BYTES,
            # Kept as a second, independent ceiling. The band above bounds the
            # wait; this bounds the allocation, and a power-of-two n inside the
            # band can still ask for more memory than this build will give it.
            maxmem=SCRYPT_MAXMEM,
        )
    except (TypeError, ValueError) as exc:
        raise malformed(f"{path.name} has unusable key derivation parameters") from exc

    try:
        payload = aesgcm(key).decrypt(nonce, sealed, aad(header))
    except Exception as exc:
        raise BadPassphrase(
            f"{path.name} did not open: the passphrase is wrong, or the file has "
            "been altered since it was written"
        ) from exc
    return payload, envelope

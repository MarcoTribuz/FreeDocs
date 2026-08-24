"""How this engine writes the files it produces.

One module because two adapters produce the same artifacts. ``cli.py`` and
``rpc.py`` each write a scrubbed document, a restored document and a JSON report,
and a permission rule with two implementations is two rules — the defect
``15ee0e1`` was an entire commit about, where five of seven fixes were the same
thing missing on the untested side.

Two questions, answered separately because they have different answers.

**Who may read it.** The key file was meticulously ``0o600`` while the restored
document — which is the *originals*, reassembled — went out at whatever the umask
said. So the rule is what the file contains, not which command produced it: a
file that could re-identify the document is owner-only, and a file this tool
exists to hand to somebody else is left to the umask. The scrubbed copy is the
second kind. Making it owner-only would be tightening the one artifact whose
purpose is to be sent, and stage 6 has already searched it for every value that
was supposed to be gone.

**What the path may be.** ``write_bytes`` after ``mkdir(exist_ok=True)`` follows
a symlink, so in a shared or predictable output directory a pre-planted link
redirects the write — to a dotfile, a key, a config. ``O_NOFOLLOW`` refuses it.
``O_EXCL`` was rejected: re-running a scrub into the same output directory is
ordinary use, and turning that into a refusal buys nothing the symlink guard does
not already buy.

**On Windows this module protects the path and not the mode.** ``O_NOFOLLOW``
does not exist there and ``os.open``'s mode argument controls only the read-only
attribute, so ``write_private`` is an ordinary write. Said rather than implied:
the platform half of this is unverified anyway — nothing in this project has ever
been launched on Windows, only built there.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import OutputRefused

#: Owner only. For anything from which the document could be reconstructed: the
#: key file, a restored document, and the report — which carries no values since
#: ``build_report`` was audited, but does carry where each one was and what the
#: source was called.
PRIVATE_MODE = 0o600

#: A directory created to hold one of the above. Only ever applied to a directory
#: this call creates: an existing one belongs to whoever made it, and quietly
#: narrowing a path the user already had is a surprise, not a hardening.
PRIVATE_DIR_MODE = 0o700

#: Absent on Windows, where it is simply not enforced. ``0`` rather than a raise:
#: the alternative is refusing to write at all on a platform this build supports.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def write_output(path: Path, data: bytes) -> None:
    """Write a file this tool hands over. Who may read it is the umask's call."""
    _write(path, data, mode=0o666)


def write_private(path: Path, data: bytes) -> None:
    """Write a file that could re-identify the document. Owner only."""
    _write(path, data, mode=PRIVATE_MODE)


def write_private_json(path: Path, payload: Any) -> None:
    """A report, as bytes rather than through ``write_text``.

    ``write_text`` translates ``"\\n"`` to the platform terminator, which is the
    class of difference that broke three tests on the Windows runner once. A
    report is read by a machine; encoding it here keeps it identical everywhere.
    """
    write_private(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def private_directory(path: Path) -> None:
    """Create a directory for private output, owner only when we create it."""
    existed = path.is_dir()
    path.mkdir(parents=True, exist_ok=True)
    if not existed and os.name != "nt":
        # `mkdir(mode=...)` is masked by the umask, so the mode is set rather
        # than requested. Same reason `write_key_map` chmods after O_CREAT.
        os.chmod(path, PRIVATE_DIR_MODE)


def _write(path: Path, data: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except OSError as exc:
        raise OutputRefused(
            f"cannot write {path.name}: {exc.strerror or 'the path is not a plain file'}; "
            "a symbolic link where an output file belongs is refused rather than followed"
        ) from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    if mode == PRIVATE_MODE and os.name != "nt":
        # O_CREAT leaves an existing file's mode alone, so writing over
        # yesterday's output would otherwise keep yesterday's permissions.
        os.chmod(path, mode)

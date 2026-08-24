"""Outbound sockets, off unless the destination is this machine.

"Nothing leaves the machine. No network call is part of a scrub." That is the
first line of SECURITY.md's threat model and it was true of the code as written -
nothing in the pipeline opens a socket - which is a different claim from being
enforced. The things most likely to break it are not in the pipeline at all: a
dependency checking for its own updates, a telemetry hook, a model loader
confirming a cached file is still current. ``huggingface_hub`` does exactly the
last one unless it is told not to, which is why ``HF_HUB_OFFLINE`` exists and why
only portable builds set it.

**What this is not.** It is not a defence against hostile code. A C extension can
open a socket without going anywhere near Python's, and MuPDF and libxml2 are C.
The threat this closes is the *accidental* call - a library deciding to phone
home while it holds a page of somebody's contract - and that one it closes
completely for anything written in Python.

**Why the refusal is a ``ConnectionRefusedError``.** A bespoke exception would
make a blocked machine behave differently from an air-gapped one, and an
air-gapped machine is a state this tool says it works on and its dependencies
already handle. Raising what the operating system would raise means the graceful
path a library already has is the path it takes. It is still identifiable, for
anyone who wants to tell the two apart.

**Installed by an entry point, never by an import.** ``cli.main`` and
``rpc.serve`` are the two places that own the process. Importing ``freedocs`` as
a library must not silently change what somebody else's sockets can do.

**One named exception.** Fetching the model weights is the single call in this
process that legitimately reaches the network, so ``gliner_backend._load`` lifts
the block around itself by name. The alternative - a list of destinations the
block trusts - would be a second copy of a rule, and the wrong one: what makes
that call acceptable is which call it is, not where it goes.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import socket
from collections.abc import Iterator

#: Set to opt out entirely. For a developer debugging a network problem, and for
#: the one build shape that has to fetch its model on first use with no other way
#: to say so.
ALLOW_VARIABLE = "FREEDOCS_ALLOW_NETWORK"

#: The one name the platform guarantees points at this machine. Every other name
#: is refused rather than resolved, for the reason the review layer's guard gives:
#: whether a hostname still points at loopback tomorrow is not this code's call.
LOOPBACK_NAMES = frozenset({"localhost"})


class EgressRefused(ConnectionRefusedError):
    """A connection to somewhere other than this machine, from a scrub.

    A ``ConnectionRefusedError`` on purpose - see the module docstring. The
    message names FreeDocs so nobody spends an afternoon looking for a firewall.
    """


_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_installed = False
_permitted_because: str | None = None


def is_loopback(host: str) -> bool:
    """Whether a host names this machine.

    The single answer to that question. ``detect/llm_review.py`` asked it too and
    had its own copy, which disagreed in a way that mattered: an empty hostname
    counted as local, and an empty hostname is what ``urlparse`` gives for
    ``file:///etc/passwd`` and for ``http://:11434``. Two copies of a rule is how
    a guard on the one component that talks to the network gets walked past.
    """
    name = host.strip().lower()
    if not name:
        return False
    if name in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def blocked() -> bool:
    """Whether an outbound connection would be refused right now."""
    return _installed and _permitted_because is None


def block_external() -> None:
    """Refuse outbound connections that are not to this machine.

    Idempotent: both entry points may call it, and a test may call either.
    Wrapping the wrapper would leave the original unreachable and ``unblock``
    unable to undo anything.
    """
    global _installed
    if _installed or os.environ.get(ALLOW_VARIABLE):
        return
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
    _installed = True


def unblock() -> None:
    """Put the original methods back. For tests, and for nothing else."""
    global _installed
    if not _installed:
        return
    socket.socket.connect = _original_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
    _installed = False


@contextlib.contextmanager
def permitted(reason: str) -> Iterator[None]:
    """Lift the block for one call that has a reason to reach the network.

    The reason is a string rather than a flag because it ends up in the refusal
    when something *else* connects during the window, and "the model was loading"
    is the difference between a diagnosis and a mystery.

    Not thread-safe, and does not need to be: the engine is one process serving
    one request at a time, which is stated in ``rpc.py`` and is the same reason a
    cancel button needs a reader thread it does not have.
    """
    global _permitted_because
    previous = _permitted_because
    _permitted_because = reason
    try:
        yield
    finally:
        _permitted_because = previous


def _check(address: object) -> None:
    if not blocked():
        return
    host = _host_of(address)
    if host is None or is_loopback(host):
        return
    raise EgressRefused(
        f"FreeDocs refused a connection to {host}: nothing about a scrub reaches "
        f"the network. Set {ALLOW_VARIABLE}=1 to allow it."
    )


def _host_of(address: object) -> str | None:
    """The host an address names, or None for a family this has no opinion on.

    ``AF_UNIX`` takes a path and never leaves the machine; ``AF_NETLINK`` and the
    rest are local by construction. Returning None for those is the difference
    between a guard and an obstacle.
    """
    if isinstance(address, tuple) and address and isinstance(address[0], str):
        return address[0]
    return None


def _guarded_connect(self: socket.socket, address: object) -> None:
    _check(address)
    return _original_connect(self, address)  # type: ignore[arg-type]


def _guarded_connect_ex(self: socket.socket, address: object) -> int:
    _check(address)
    return _original_connect_ex(self, address)  # type: ignore[arg-type]

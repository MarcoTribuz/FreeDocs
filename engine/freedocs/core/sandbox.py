"""What this process gives up before it reads a stranger's document.

Every input is hostile by definition and the parsers are C, so the honest
question is not whether one of them can be made to misbehave but what it reaches
if it does. This module holds what can be given up *portably and verifiably*, and
- just as importantly - states what cannot, because a security control nobody has
ever seen run is a claim rather than a control.

**Core dumps are turned off.** Cheap, portable across Unix, and load-bearing
since the reverse path landed: a dump of this process can contain the key file's
passphrase and every value the scrub removed. On macOS the soft limit is already
0, so this is a no-op there and matters on Linux, where it is commonly unlimited
and where a crash handler will happily write the file.

**There is no address-space ceiling, and that was measured rather than skipped.**
``RLIMIT_AS`` was the obvious second control. On macOS this process reserves
**425 GB** of address space before importing anything, which is ordinary
behaviour for the allocator and makes any ceiling either useless or fatal at
startup; torch adds to it. A limit that kills the engine on launch, or that has
to be set so high it bounds nothing, is worse than none - and the document limits
in ``core/limits.py`` already bound the allocation an input can actually drive.

**Filesystem confinement is absent, and it is a gap rather than a decision.**
Landlock on Linux, an AppContainer or job object on Windows, a signed hardened
runtime on macOS: each is real and each is unverifiable from here. This project
has never run on Linux or Windows - it builds there - and a Landlock ruleset that
is subtly wrong does not fail loudly, it stops the engine reading the document
the user chose. The macOS half is blocked further back: the hardened runtime is
applied by code signing, and signing is a paid certificate this project has
decided against. Said out loud in ``doctor`` rather than implied by silence.

The other half of the sandbox is real and lives next door: ``core/egress.py``
turns "no network call is part of a scrub" from a property of the code as written
into something the process refuses to do.
"""

from __future__ import annotations

import os
import sys

#: Set to skip the hardening. For a developer who wants a core file.
ALLOW_VARIABLE = "FREEDOCS_ALLOW_CORE_DUMPS"


def harden() -> None:
    """Give up what this process has no use for. Never raises.

    Called from the two entry points that own the process, for the same reason
    ``egress.block_external`` is: importing ``freedocs`` as a library must not
    silently change a caller's limits.

    Failures are ignored rather than reported. A platform that will not let this
    lower its own soft limit is a platform where the control is absent, which
    ``describe()`` already says, and refusing to scrub over it would be trading a
    working tool for a defence in depth.
    """
    if os.name == "nt" or os.environ.get(ALLOW_VARIABLE):
        return
    try:
        import resource

        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    except Exception:  # pragma: no cover - platform-dependent
        return


def core_dumps_disabled() -> bool:
    """Whether a crash could write this process's memory to disk."""
    if os.name == "nt":
        # Windows writes a crash dump on a policy this process does not set, so
        # the honest answer is "not by us" rather than True.
        return False
    try:
        import resource

        return resource.getrlimit(resource.RLIMIT_CORE)[0] == 0
    except Exception:  # pragma: no cover - platform-dependent
        return False


def describe() -> str:
    """One sentence for ``doctor``: what is enforced, and what is not.

    Both halves, always. A report that listed only what is on would let the
    absence of filesystem confinement read as its presence, which is the failure
    this whole module is written against.
    """
    from . import egress

    on = []
    if core_dumps_disabled():
        on.append("core dumps off")
    if egress.blocked():
        on.append("outbound network off except loopback")
    enforced = ", ".join(on) if on else "nothing"
    return (
        f"enforced: {enforced}. Not enforced: filesystem confinement "
        f"({_confinement_gap()}), and no address-space ceiling (measured as "
        "unusable: this process reserves hundreds of gigabytes of address space "
        "before it imports anything)."
    )


def _confinement_gap() -> str:
    if sys.platform == "darwin":
        return "the hardened runtime is applied by code signing, which this project does not do"
    if sys.platform.startswith("linux"):
        return "Landlock is not implemented; this project has never been run on Linux"
    if os.name == "nt":
        return "no job object or AppContainer; this project has never been run on Windows"
    return "not implemented on this platform"  # pragma: no cover - other Unix

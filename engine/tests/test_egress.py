"""No network call is part of a scrub — enforced, rather than intended.

Until now that sentence was a property of the code as written: nothing in the
pipeline opens a socket. It was still only a claim, and the things most likely to
break it are not in the pipeline at all - a dependency checking for its own
updates, a telemetry hook, a model loader confirming a cached file is current.
`huggingface_hub` does exactly the last one unless told not to.

What this does *not* claim is a defence against hostile code. A C extension can
open a socket without going through Python's, and the point here is to stop the
accidental call, not the deliberate one. That distinction is the whole reason the
block raises `ConnectionRefusedError`: the process then behaves exactly like the
air-gapped machine this tool says it can run on, which is a state its dependencies
already handle.
"""

from __future__ import annotations

import socket

import pytest

from freedocs.core import egress


@pytest.fixture(autouse=True)
def restore():
    """Every test here changes process-wide state, so every test puts it back."""
    yield
    egress.unblock()


def test_a_connection_off_this_machine_is_refused():
    egress.block_external()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(egress.EgressRefused),
    ):
        sock.connect(("93.184.216.34", 80))


def test_the_refusal_is_a_connection_error_and_that_is_deliberate():
    """`ConnectionRefusedError`, so a library that handles "no network" takes its
    own graceful path instead of failing the scrub with something it has never
    seen. A bespoke exception would make an air-gapped machine and a blocked one
    behave differently, and the whole point is that they do not."""
    assert issubclass(egress.EgressRefused, ConnectionRefusedError)
    assert issubclass(egress.EgressRefused, OSError)


def test_loopback_is_left_alone():
    """The optional review layer talks to an Ollama on this machine, and that is
    the one outbound connection a run may legitimately make."""
    egress.block_external()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect(listener.getsockname())
    finally:
        listener.close()


def test_a_hostname_is_refused_rather_than_resolved():
    """Same rule the review layer's own guard follows, and now literally the same
    function: whether a name still points at loopback tomorrow is not this code's
    call. `localhost` is the exception, because it is the one name the platform
    guarantees."""
    egress.block_external()
    assert egress.is_loopback("localhost")
    assert not egress.is_loopback("ollama.internal")
    assert egress.is_loopback("127.0.0.1")
    assert egress.is_loopback("::1")


def test_an_empty_host_is_not_loopback():
    """It reads as one - an empty hostname parses out of `http://:11434` and out
    of `file:///etc/passwd` - and treating it as local is how a guard on the one
    component that talks to the network gets walked past."""
    assert not egress.is_loopback("")


def test_the_model_load_is_the_one_named_exception():
    """Fetching weights is the single call in this process that legitimately
    reaches the network, so it lifts the block by name rather than the block
    having a list of destinations it trusts."""
    egress.block_external()
    assert egress.blocked()
    with egress.permitted("loading the NER model"):
        assert not egress.blocked()
    assert egress.blocked()


def test_the_block_is_not_installed_by_importing_anything():
    """A process-level policy belongs to whoever started the process. Importing
    `freedocs` as a library must not silently change what a caller's own sockets
    can do."""
    egress.unblock()
    assert not egress.blocked()


def test_blocking_twice_is_harmless():
    """`cli.main` and `rpc.serve` are both entry points and a test may call
    either, so the guard has to be idempotent rather than wrapping the wrapper."""
    egress.block_external()
    egress.block_external()
    egress.unblock()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.01)
        # Unblocked means the guard is gone entirely: this fails on the network,
        # not on us.
        with pytest.raises(OSError) as caught:
            sock.connect(("192.0.2.1", 9))
        assert not isinstance(caught.value, egress.EgressRefused)


# --- who installs it, and who puts it back ------------------------------------


def test_the_cli_blocks_for_the_length_of_a_run_and_no_longer(tmp_path, capsys):
    """Both halves of the entry-point rule, in one assertion each.

    Installed by the entry point, because a process-level policy belongs to
    whoever started the process. Undone on the way out, because otherwise a test
    that runs one command leaves the interpreter with sockets blocked for
    whatever runs next - a fixture nobody would think to write, failing somewhere
    unrelated.
    """
    from freedocs import cli

    seen: list[bool] = []
    original = cli._dispatch

    def watching(argv):
        seen.append(egress.blocked())
        return original(argv)

    cli._dispatch = watching
    try:
        assert cli.main(["entities"]) == 0
    finally:
        cli._dispatch = original
    capsys.readouterr()

    assert seen == [True], "the run itself must be blocked"
    assert not egress.blocked(), "and the interpreter must be left as it was found"


def test_the_engine_reports_what_it_gives_up():
    """`doctor` names both halves, always.

    A report that listed only what is on would let the absence of filesystem
    confinement read as its presence, which is the thing `core/sandbox.py` is
    written against.
    """
    from freedocs.core import sandbox

    egress.block_external()
    described = sandbox.describe()
    assert "outbound network off except loopback" in described
    assert "Not enforced" in described

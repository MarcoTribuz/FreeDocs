"""What the lock file is allowed to contain.

One test, guarding one thing that nothing else can see. The engine runs its
encoder on the CPU and never issues a kernel, but the default PyPI `torch` wheel
for Linux pulls the CUDA stack in as real dependencies. That cost lands in a
bundle nobody on this project builds by hand, so it can grow back without anyone
noticing until a user downloads it.
"""

from __future__ import annotations

import re
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "uv.lock"

#: Package name prefixes that mean GPU code. `triton` is the odd one out: it is
#: not called nvidia-anything but it is a CUDA JIT compiler and nothing else.
GPU_PREFIXES = ("nvidia-", "cuda-")
GPU_NAMES = frozenset({"triton"})


def locked_packages() -> set[str]:
    return set(re.findall(r'^name = "([^"]+)"$', LOCK.read_text(), re.M))


def test_no_gpu_stack_is_locked():
    """Measured when this guard was added: 2196 MB of wheels, never executed.

    nvidia-cublas 423 MB, cudnn 366, cufft 214, nccl 206, cusolver 201,
    triton 198, cusparselt 170, cusparse 146, and eleven smaller ones, on top of
    torch's own 527 MB. Fixed by pinning Linux to the CPU index in pyproject.toml;
    this fails if a future `uv lock` quietly undoes that.
    """
    offenders = sorted(
        name for name in locked_packages() if name.startswith(GPU_PREFIXES) or name in GPU_NAMES
    )
    assert not offenders, (
        f"the lock carries GPU packages this engine never calls: {', '.join(offenders)}. "
        "Check [tool.uv.sources] in pyproject.toml still pins torch to the CPU index "
        "on Linux."
    )


def test_torch_resolves_to_a_cpu_build_on_linux():
    """The pin is what keeps the CUDA stack out, so the pin itself is asserted.

    Without this, deleting the `+cpu` source while the GPU packages happened to be
    absent from the resolution would leave the guard above passing and the next
    lock refresh dragging them back.
    """
    assert "+cpu" in LOCK.read_text(), (
        "no CPU-pinned torch in the lock; Linux is resolving against plain PyPI again"
    )

"""Entry point for the frozen engine sidecar.

Deliberately tiny. PyInstaller freezes whatever this imports, so keeping it to one
call means the bundle's contents are decided by the engine's own imports rather
than by anything that lives only in the packaging directory.
"""

from __future__ import annotations

import sys

from freedocs.rpc import serve

if __name__ == "__main__":
    sys.exit(serve())

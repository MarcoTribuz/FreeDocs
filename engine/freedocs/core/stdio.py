"""The process's own standard streams, made UTF-8 whatever the locale says.

Python opens stdin and stdout in the locale's encoding, which on Windows is
cp1252 when the stream is a pipe or a file. Everything on the other end speaks
UTF-8: the Tauri shell writes its requests that way, and a document piped into
`freedocs scrub -` usually is. So on Windows `C:\\Users\\JürgMüller\\...` reached
the engine as `JÃ¼rgMÃ¼ller`, and every file under a name with an accent was
refused as "does not exist" - with the correct path in the message, because the
answer went back through the same mis-encoding in reverse and the shell read it
as UTF-8 again. macOS and Linux never show it: their locale is already UTF-8.

Called by the two entry points that own the process, ``cli.main`` and
``rpc.serve``, for the same reason they install the network block: importing
``freedocs`` as a library must not change a caller's streams.
"""

from __future__ import annotations

from typing import TextIO


def utf8(stream: TextIO) -> TextIO:
    """Re-read ``stream`` as UTF-8, when it is the kind of stream that can be."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    return stream

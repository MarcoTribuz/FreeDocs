"""Pasted text: the loop from a paste to a model and back, with no file.

Text mode is the plaintext handler handed straight to the pipeline. There is no
new format and no new stage: ``Scrubber.read`` and ``Restorer.restore`` already
take a handler, which keeps routing out of a path that has no file to route,
and the per-line anchoring makes an unedited round trip byte-identical.

What is new is the one thing a file never needed: somewhere for the mapping to
live between the scrub and the reply. A file scrub either writes a key file or
throws the mapping away. A paste is scrubbed, sent, answered and restored in a
few minutes, and asking for a passphrase and a folder for a paragraph is the
friction this mode exists to remove. So a caller may ask the engine to **hold**
the mapping under an opaque handle, and that is a stated widening of "the
mapping never reaches disk... a crash cannot leave a re-identification key in a
live process": for the life of the handle, it can. See :class:`TextMaps` for its
bounds, and ``CLAUDE.md`` for why it is opt-in per text and never the default.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from .core.limits import refuse_oversized_text
from .core.mapping import KeyMap
from .formats.plaintext import PlainTextHandler

#: The name a paste goes by, in the report's ``source``, in a key file's
#: ``document`` and in every finding's ``part``. A constant rather than the
#: caller's choice: a name somebody typed is one more place a client's name can
#: travel into a report.
PASTED_NAME = "pasted.txt"

#: Held mappings, at most. Eight texts in flight is more than a person working
#: one conversation at a time has; the ninth drops the oldest rather than being
#: refused, because refusing would fail a scrub the person is looking at in
#: favour of one they have forgotten.
MAX_TEXT_MAPS = 8


def handler_for_text(text: object) -> PlainTextHandler:
    """The plaintext handler over a paste, refusing what is not one."""
    if not isinstance(text, str):
        raise TypeError("'text' must be a string")
    refuse_oversized_text(len(text))
    return PlainTextHandler(Path(PASTED_NAME), text.encode("utf-8"))


def decoded(handler: PlainTextHandler, output: bytes) -> str:
    """The handler's output as text, in the encoding it was read with.

    UTF-8, except for a paste that began with a byte-order mark, which the
    handler reads as ``utf-8-sig`` and writes back the same way.
    """
    return output.decode(handler.encoding)


class UnknownHandle(ValueError):
    """A handle this session is not holding.

    Forgotten, evicted, or issued by an engine process that has since restarted.
    The three are the same answer to the caller - scrub the text again - and the
    message names no value, because the handle is all there is to name.
    """


class TextMaps:
    """The mappings held for pasted text, under random handles.

    Four rules, each closing a way this could become the persistent key store it
    must not be:

    - **Opt-in per request.** Nothing is held unless the caller asked for it on
      that scrub; see ``rpc.scrub_text``.
    - **The handle is random**, never derived from the text or a hash of it: a
      handle that could be recomputed from a document would identify it.
    - **Bounded**, oldest dropped first, and released by ``forget``, by a mode
      change in the window, and by the process ending. No idle timer: that is a
      second thread in a process that deliberately has one.
    - **A restore does not consume it.** A second reply from the same model is
      ordinary use.
    """

    def __init__(self, limit: int = MAX_TEXT_MAPS) -> None:
        self._limit = limit
        self._held: dict[str, KeyMap] = {}

    def __len__(self) -> int:
        return len(self._held)

    def hold(self, key_map: KeyMap) -> str:
        handle = secrets.token_urlsafe(16)
        while len(self._held) >= self._limit:
            # Oldest first: dicts keep insertion order, and the text being
            # worked on now is the one held most recently.
            self._held.pop(next(iter(self._held)))
        self._held[handle] = key_map
        return handle

    def get(self, handle: object) -> KeyMap:
        key_map = self._held.get(handle) if isinstance(handle, str) else None
        if key_map is None:
            raise UnknownHandle(
                "this text's mapping is not held any more - it was forgotten, "
                "or the engine restarted - so scrub the original text again"
            )
        return key_map

    def release(self, handles: object) -> int:
        """Drop the named handles, or every one for ``"all"``. Returns how many."""
        if handles == "all":
            released = len(self._held)
            self._held.clear()
            return released
        if not isinstance(handles, list):
            raise TypeError("'text_maps' must be a list of handles or \"all\"")
        return sum(1 for handle in handles if self._held.pop(str(handle), None) is not None)

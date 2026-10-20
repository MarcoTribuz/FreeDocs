"""Plain text, Markdown and CSV.

The simplest handler, and therefore the one that proves the pipeline: if a
canary value survives a scrub here, the fault is in the core rather than in some
container format's quirks.

Anchoring is per line, with line terminators kept as filler. That makes an
unedited round-trip byte-identical, including CRLF endings and a missing final
newline, which is the baseline the container formats are held to as well.
"""

from __future__ import annotations

import codecs
from pathlib import Path

from ..core.errors import MalformedDocument
from ..core.stream import AnchorEdit, TextStream, TextStreamBuilder, apply_anchor_edits
from .base import FormatHandler

#: Tried in order. latin-1 cannot fail, so it is the terminal fallback and
#: guarantees we never refuse a file merely because its encoding was guessed
#: wrong somewhere upstream. utf-8-sig is deliberately absent: it decodes
#: BOM-less UTF-8 happily, and picking it would add a BOM on write-back.
_ENCODINGS = ("utf-8", "cp1252", "latin-1")

#: Checked before any of the above, and UTF-32 before UTF-16 because the
#: little-endian UTF-32 mark begins with the UTF-16 one. Without this a UTF-16
#: file - what PowerShell's `>` and Excel's "Unicode Text" write - decoded as
#: cp1252 without an error, every character came out followed by a NUL, nothing
#: matched a detector, and the file was written back untouched under "no leak".
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


def _split_terminator(line: str) -> tuple[str, str]:
    """Separate a line's content from its terminator, preserving CRLF exactly."""
    for terminator in ("\r\n", "\n", "\r"):
        if line.endswith(terminator):
            return line[: -len(terminator)], terminator
    return line, ""


class PlainTextHandler(FormatHandler):
    name = "plaintext"
    extensions = (".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".xml")

    def __init__(self, path: Path, data: bytes) -> None:
        super().__init__(path, data)
        self.bom, self.encoding = self._detect_encoding(data)
        text = data[len(self.bom) :].decode(self.encoding)
        if "\x00" in text:
            # The same failure as a UTF-16 file without its mark: text a detector
            # cannot read, scrubbed of nothing and reported clean. Refused, since
            # no guess at the encoding is safe to report as a scrub.
            raise MalformedDocument(
                f"{path.name} contains NUL characters, so it is binary or a UTF-16 "
                "text without a byte-order mark; save it as UTF-8 and try again"
            )
        self._lines: list[tuple[str, str]] = [
            _split_terminator(line) for line in text.splitlines(keepends=True)
        ]

    @staticmethod
    def _detect_encoding(data: bytes) -> tuple[bytes, str]:
        """The byte-order mark to put back on write, and the codec for the rest."""
        # Only claim utf-8-sig when a BOM is genuinely present, so that writing
        # the file back cannot introduce one that was not there before.
        if data.startswith(codecs.BOM_UTF8):
            return b"", "utf-8-sig"
        for bom, encoding in _BOMS:
            if data.startswith(bom):
                return bom, encoding
        for encoding in _ENCODINGS:
            try:
                data.decode(encoding)
            except UnicodeDecodeError:
                continue
            return b"", encoding
        raise AssertionError("latin-1 decodes any byte string; this cannot be reached")

    def extract(self) -> TextStream:
        builder = TextStreamBuilder()
        for index, (content, terminator) in enumerate(self._lines):
            builder.add(content, part=str(self.path.name), locator=index)
            builder.add_filler(terminator)
        return builder.build()

    def write_back(self, edits: list[AnchorEdit]) -> bytes:
        by_line: dict[int, list[AnchorEdit]] = {}
        for edit in edits:
            by_line.setdefault(int(edit.anchor.locator), []).append(edit)

        out: list[str] = []
        for index, (content, terminator) in enumerate(self._lines):
            line_edits = by_line.get(index)
            out.append(apply_anchor_edits(content, line_edits) if line_edits else content)
            out.append(terminator)
        text = "".join(out)
        # Keep the source encoding so an unedited file round-trips byte for byte,
        # BOM included. Fall back to UTF-8 only if a replacement introduced a
        # character the original encoding cannot represent: changing the encoding
        # beats refusing to save.
        try:
            return self.bom + text.encode(self.encoding)
        except UnicodeEncodeError:
            return text.encode("utf-8")

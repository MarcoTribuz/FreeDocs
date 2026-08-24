#!/usr/bin/env python3
"""Throw damaged documents at the readers and see what escapes.

`tests/test_hostile_input.py` covers the classes of hostile input somebody
reasoned about. This covers the ones nobody did. It is the same standing question
either way: **a refusal that names the file, never a traceback out of a library
and never a hang.**

Deliberately not part of `scripts/ci.py check`. A gate has to be deterministic and
this is not: a run that finds nothing proves nothing, and a run that finds
something has found a case for `test_hostile_input.py` rather than a reason to
fail somebody's commit. Run it on purpose, for as long as you feel like.

    python3 scripts/fuzz.py                    # 2000 cases, a couple of minutes
    python3 scripts/fuzz.py --cases 50000      # overnight
    python3 scripts/fuzz.py --seed 12345       # reproduce one

**What counts as a finding.** Not a crash — a crash would be wonderful and is not
what happens. What escapes here is an exception the callers do not know about, so
the pass criterion is the *type*: anything outside the declared set is reported
with the seed that produced it and the bytes written to a file. That is what makes
a finding actionable rather than a log line.

Seeds come from real files rather than from nothing. A structurally valid zip with
one byte changed reaches far deeper into a parser than random noise, which is
rejected by the magic-number check in the first microsecond.
"""

from __future__ import annotations

import argparse
import io
import random
import sys
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
sys.path.insert(0, str(ENGINE))

from freedocs.core.errors import (  # noqa: E402
    InputTooLarge,
    MalformedDocument,
    MissingDependency,
)
from freedocs.core.mapping import BadPassphrase, MalformedMap  # noqa: E402
from freedocs.formats.router import UnsupportedFormat  # noqa: E402

#: Everything a caller already handles. `ValueError` is in here under protest:
#: it is what several handlers still raise for a structurally odd but not
#: malicious file, and narrowing it is a separate piece of work with its own
#: tests. Everything else escaping is a finding.
EXPECTED = (
    UnsupportedFormat,
    MalformedDocument,
    InputTooLarge,
    MissingDependency,
    MalformedMap,
    BadPassphrase,
    ValueError,
    KeyError,
    OSError,
)


def seed_documents() -> list[tuple[str, bytes]]:
    """Real files to damage, built rather than found.

    One of each shape the router can claim, because a fuzzer that only ever sees
    plain text spends its whole run in the one handler with nothing to break.
    """
    seeds: list[tuple[str, bytes]] = [
        (".txt", "Mario Rossi, CH93 0076 2011 6238 5295 7\n".encode()),
    ]

    example = ROOT / "examples" / "offerta-esempio.docx"
    if example.is_file():
        seeds.append((".docx", example.read_bytes()))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "xl/workbook.xml",
            b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<sheets><sheet name="Foglio" sheetId="1" r:id="rId1" xmlns:r="http://schemas.'
            b'openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>',
        )
    seeds.append((".xlsx", buffer.getvalue()))

    try:
        import pymupdf

        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((60, 80), "Mario Rossi", fontname="helv", fontsize=11)
        seeds.append((".pdf", document.tobytes(garbage=4, clean=True, deflate=True)))
        document.close()
    except ImportError:  # pragma: no cover - depends on the environment
        pass
    return seeds


def damage(data: bytes, rng: random.Random) -> bytes:
    """One document, broken in one of the ways a real one breaks.

    Bit flips and truncation are the two that actually happen to files. The
    length change is the interesting one for this codebase, because a size that
    disagrees with a header is exactly what the OOXML and manifest checks reason
    about.
    """
    out = bytearray(data)
    for _ in range(rng.randint(1, 8)):
        choice = rng.random()
        if not out:
            break
        if choice < 0.6:
            index = rng.randrange(len(out))
            out[index] ^= 1 << rng.randrange(8)
        elif choice < 0.8:
            del out[rng.randrange(len(out)) :]
        else:
            index = rng.randrange(len(out))
            out[index:index] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 64)))
    return bytes(out)


def run_document(path: Path) -> None:
    from freedocs.formats.router import handler_for

    handler = handler_for(path)
    handler.extract()
    handler.scrub_hidden()


def run_key_map(path: Path) -> None:
    from freedocs.core.mapping import read_key_map

    read_key_map(path, "correct horse battery staple")


def key_map_seed() -> bytes | None:
    try:
        from freedocs.core.mapping import KeyMap, write_key_map
    except ImportError:  # pragma: no cover - depends on the environment
        return None
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "seed.fdmap"
        try:
            write_key_map(
                path,
                KeyMap(
                    document="d.txt",
                    format_name="plaintext",
                    output_sha256="x",
                    placeholder_language="en",
                    entries=(),
                ),
                "correct horse battery staple",
            )
        except Exception:
            return None
        return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fuzz.py", description=__doc__)
    parser.add_argument("--cases", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--keep",
        type=Path,
        default=ROOT / "dist" / "fuzz-findings",
        help="where a case that escaped is written, so it can be replayed",
    )
    args = parser.parse_args(argv)

    import tempfile

    rng = random.Random(args.seed)
    seeds = seed_documents()
    key_seed = key_map_seed()
    if key_seed:
        seeds.append((".fdmap", key_seed))
    print(f"{len(seeds)} seed shapes: {', '.join(suffix for suffix, _ in seeds)}")

    findings = 0
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        for case in range(args.cases):
            suffix, original = seeds[rng.randrange(len(seeds))]
            payload = damage(original, rng)
            path = workspace / f"case{suffix}"
            path.write_bytes(payload)
            try:
                if suffix == ".fdmap":
                    run_key_map(path)
                else:
                    run_document(path)
            except EXPECTED:
                pass
            except BaseException:  # noqa: BLE001 - the whole point is what got here
                findings += 1
                args.keep.mkdir(parents=True, exist_ok=True)
                kept = args.keep / f"case-{args.seed}-{case}{suffix}"
                kept.write_bytes(payload)
                print(f"\n--- case {case} ({suffix}) -> {kept}")
                traceback.print_exc()
            if case % 200 == 0:
                print(f"  {case}/{args.cases}", end="\r", flush=True)

    print(f"\n{args.cases} cases, {findings} escaped as an unexpected type")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

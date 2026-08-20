"""Command line entry point.

The CLI exists before the GUI on purpose: it is scriptable, testable in CI, and
it forces the engine to be usable without a window. The Tauri app calls the same
code through ``rpc.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.findings import EntityType
from .core.policy import Action, Policy
from .formats.pdf_text import MissingDependency, ScannedPdfNotSupported
from .formats.router import UnsupportedFormat, handler_for
from .pipeline import Scrubber
from .report import build_report, format_console
from .verify import LeakDetected

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_LEAK = 3
EXIT_UNSUPPORTED = 4

#: Conditions where the input cannot be processed correctly and the honest answer
#: is to refuse. Grouped so scrub and inspect report them identically.
REFUSALS = (UnsupportedFormat, ScannedPdfNotSupported, MissingDependency)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freedocs",
        description="Remove confidential data from documents, locally and offline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scrub = sub.add_parser("scrub", help="write a scrubbed copy of one or more files")
    scrub.add_argument("files", nargs="+", type=Path)
    scrub.add_argument(
        "-o", "--output-dir", type=Path, required=True, help="directory for scrubbed copies"
    )
    scrub.add_argument("--report", type=Path, help="write a JSON report to this path")
    scrub.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="ignore findings below this confidence (default: 0.5)",
    )
    scrub.add_argument(
        "--keep",
        action="append",
        default=[],
        metavar="ENTITY",
        help="leave this entity type untouched; repeatable",
    )
    scrub.add_argument(
        "--allow-leaks",
        action="store_true",
        help="write the output even if verification finds surviving values",
    )

    inspect = sub.add_parser(
        "inspect", help="report what would be removed, without writing anything"
    )
    inspect.add_argument("files", nargs="+", type=Path)
    inspect.add_argument("--min-confidence", type=float, default=0.5)

    entities = sub.add_parser("entities", help="list the entity types this build detects")
    entities.set_defaults(files=[])

    return parser


def _policy(args: argparse.Namespace) -> Policy:
    overrides = {}
    for name in getattr(args, "keep", []):
        try:
            overrides[EntityType(name.upper())] = Action.KEEP
        except ValueError as exc:
            raise SystemExit(f"unknown entity type {name!r}; try 'freedocs entities'") from exc
    return Policy(overrides=overrides, min_confidence=args.min_confidence)


def _cmd_scrub(args: argparse.Namespace) -> int:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scrubber = Scrubber(policy=_policy(args), strict=not args.allow_leaks)
    reports = []
    status = EXIT_OK

    for path in args.files:
        try:
            result = scrubber.scrub_file(path)
        except REFUSALS as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            status = EXIT_UNSUPPORTED
            continue
        except LeakDetected as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            print("  nothing written for this file", file=sys.stderr)
            status = EXIT_LEAK
            continue

        destination = args.output_dir / path.name
        destination.write_bytes(result.output)
        print(format_console(result))
        print(f"  written: {destination}")
        reports.append(build_report(result))
        if not result.verify.ok:
            status = EXIT_LEAK

    if args.report and reports:
        args.report.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(f"report: {args.report}")
    return status


def _cmd_inspect(args: argparse.Namespace) -> int:
    scrubber = Scrubber(policy=_policy(args), strict=False)
    for path in args.files:
        try:
            handler = handler_for(path)
            stream = handler.extract()
        except REFUSALS as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            return EXIT_UNSUPPORTED
        findings = scrubber.registry.detect(stream.text)
        print(f"{path.name}  [{handler.name}]  {len(stream.text)} chars")
        for finding in findings:
            action = scrubber.policy.action_for(finding)
            print(
                f"  {finding.span.start:>7}-{finding.span.end:<7} "
                f"{finding.entity.value:<22} {action.value:<9} "
                f"conf={finding.confidence:.2f}  via {finding.detector}"
            )
        if not findings:
            print("  nothing matched")
    return EXIT_OK


def _cmd_entities(_: argparse.Namespace) -> int:
    for entity in EntityType:
        print(entity.value)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {"scrub": _cmd_scrub, "inspect": _cmd_inspect, "entities": _cmd_entities}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

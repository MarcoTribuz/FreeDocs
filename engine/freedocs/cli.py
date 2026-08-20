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

from .core.errors import MissingDependency
from .core.findings import EntityType
from .core.policy import Action, Policy
from .formats.pdf import ScannedPdfNotSupported
from .formats.router import UnsupportedFormat, handler_for
from .pipeline import Scrubber, build_registry, default_registry
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
    scrub.add_argument(
        "--detectors",
        default=None,
        help="layers to use: l1, ner, all, or all:presidio (default: every available layer)",
    )

    inspect = sub.add_parser(
        "inspect", help="report what would be removed, without writing anything"
    )
    inspect.add_argument("files", nargs="+", type=Path)
    inspect.add_argument("--min-confidence", type=float, default=0.5)
    inspect.add_argument("--detectors", default=None)

    entities = sub.add_parser("entities", help="list the entity types this build detects")
    entities.set_defaults(files=[])

    benchmark = sub.add_parser(
        "benchmark", help="measure detector quality against the labelled corpus"
    )
    benchmark.add_argument(
        "--corpus", type=Path, default=None, help="directory of annotated corpus files"
    )
    benchmark.add_argument(
        "--detectors",
        default=None,
        help=(
            "comma-separated configurations to measure, e.g. 'l1,all:gliner2'. "
            "Defaults to the stack a scrub actually uses, so the number means "
            "something about real behaviour."
        ),
    )
    benchmark.add_argument(
        "--language", action="append", default=[], help="restrict to this language; repeatable"
    )
    benchmark.set_defaults(files=[])

    return parser


def _policy(args: argparse.Namespace) -> Policy:
    overrides = {}
    for name in getattr(args, "keep", []):
        try:
            overrides[EntityType(name.upper())] = Action.KEEP
        except ValueError as exc:
            raise SystemExit(f"unknown entity type {name!r}; try 'freedocs entities'") from exc
    return Policy(overrides=overrides, min_confidence=args.min_confidence)


def _scrubber(args: argparse.Namespace, *, strict: bool) -> Scrubber:
    spec = getattr(args, "detectors", None)
    registry = build_registry(spec) if spec else default_registry()
    return Scrubber(policy=_policy(args), registry=registry, strict=strict)


def _cmd_scrub(args: argparse.Namespace) -> int:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        scrubber = _scrubber(args, strict=not args.allow_leaks)
    except (ValueError, MissingDependency) as exc:
        print(f"detectors: {exc}", file=sys.stderr)
        return EXIT_USAGE
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
    try:
        scrubber = _scrubber(args, strict=False)
    except (ValueError, MissingDependency) as exc:
        print(f"detectors: {exc}", file=sys.stderr)
        return EXIT_USAGE
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


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from .evaluation.corpus import CorpusError, load_corpus
    from .evaluation.metrics import evaluate, format_evaluation

    try:
        documents = load_corpus(args.corpus)
    except CorpusError as exc:
        print(f"corpus: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.language:
        wanted = {name.lower() for name in args.language}
        documents = [doc for doc in documents if doc.language in wanted]
        if not documents:
            print(f"no corpus documents for {sorted(wanted)}", file=sys.stderr)
            return EXIT_USAGE

    specs = [part.strip() for part in (args.detectors or "").split(",") if part.strip()]
    for name in specs or [None]:
        try:
            registry = build_registry(name) if name else default_registry()
            # evaluate() is inside the guard too: backends load their model on
            # first prediction, so a missing dependency surfaces here rather than
            # at construction, and an uncaught one would print a traceback and
            # still exit 0.
            result = evaluate(documents, registry)
        except (ValueError, MissingDependency) as exc:
            print(f"{name or 'default'}: {exc}", file=sys.stderr)
            return EXIT_UNSUPPORTED
        label = name or "default (" + ", ".join(type(d).__name__ for d in registry.detectors) + ")"
        print(format_evaluation(result, f"detectors: {label}"))
        for note in registry.notes:
            print(f"  note: {note}")
        print()

    print(
        "The corpus is small and synthetic: these numbers rank detectors against "
        "each other, they are not a benchmark result."
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "scrub": _cmd_scrub,
        "inspect": _cmd_inspect,
        "entities": _cmd_entities,
        "benchmark": _cmd_benchmark,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

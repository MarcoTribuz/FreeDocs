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
from .core.policy import DEFAULT_LOCALE, PLACEHOLDER_LOCALES, Action, Policy
from .detect.llm_review import DEFAULT_HOST, LlmReviewer, RemoteHostRefused, available_models
from .detect.validators import SUPPORTED_COUNTRIES
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
        "--placeholder-language",
        default=DEFAULT_LOCALE,
        choices=PLACEHOLDER_LOCALES,
        help=(
            "language of the placeholder stems written into the output "
            f"(default: {DEFAULT_LOCALE}, which is what a language model reads best)"
        ),
    )
    scrub.add_argument(
        "--countries",
        default=None,
        metavar="CODES",
        help=(
            "comma-separated ISO country codes to look for identifiers and "
            "national phone numbers from, e.g. 'ch,it,de'. Defaults to every "
            "supported country: naming them is a way to raise precision, never "
            "a requirement, because the wrong list produces a file the user "
            "believes is clean. Try 'freedocs countries'."
        ),
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
    scrub.add_argument(
        "--review",
        metavar="MODEL",
        default=None,
        help=(
            "after scrubbing, ask a local Ollama model to read the result and "
            "flag leftovers and quasi-identifiers. Advisory: it never changes the "
            "output. Try 'freedocs review-models' for what is installed."
        ),
    )
    scrub.add_argument(
        "--review-host",
        default=None,
        help="Ollama base URL (default: http://127.0.0.1:11434)",
    )
    scrub.add_argument(
        "--review-remote",
        action="store_true",
        help=(
            "permit a review host that is not on this machine. The scrubbed text "
            "is sent to it, so this is deliberately not the default."
        ),
    )

    inspect = sub.add_parser(
        "inspect", help="report what would be removed, without writing anything"
    )
    inspect.add_argument("files", nargs="+", type=Path)
    inspect.add_argument("--min-confidence", type=float, default=0.5)
    inspect.add_argument("--detectors", default=None)
    inspect.add_argument("--countries", default=None, metavar="CODES")

    entities = sub.add_parser("entities", help="list the entity types this build detects")
    entities.set_defaults(files=[])

    countries = sub.add_parser(
        "countries", help="list the countries whose identifiers this build knows"
    )
    countries.set_defaults(files=[])

    models = sub.add_parser(
        "review-models", help="list the local Ollama models available for --review"
    )
    models.add_argument("--review-host", default=None)
    # Listing is guarded like reviewing is, so the opt-in has to exist here too or
    # --review-host would name a host this command then refuses with no way past it.
    models.add_argument(
        "--review-remote",
        action="store_true",
        help="permit listing the models of a host that is not on this machine",
    )
    models.set_defaults(files=[])

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
    benchmark.add_argument(
        "--countries",
        default=None,
        metavar="CODES",
        help=(
            "measure with only these countries enabled, so the cost of adding "
            "one is a command rather than an experiment"
        ),
    )
    benchmark.set_defaults(files=[])

    return parser


def _countries(args: argparse.Namespace) -> list[str] | None:
    """None for every country, which is what no flag means.

    An empty selection is refused rather than read as "no countries": a typo in
    the value would otherwise silently disable the whole checksum layer, and this
    is the one option where being wrong looks exactly like working.
    """
    raw = getattr(args, "countries", None)
    if raw is None:
        return None
    names = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not names:
        raise SystemExit("--countries was empty; omit it to use every supported country")
    unknown = sorted(set(names) - set(SUPPORTED_COUNTRIES))
    if unknown:
        raise SystemExit(f"unknown country code(s) {', '.join(unknown)}; try 'freedocs countries'")
    return names


def _policy(args: argparse.Namespace) -> Policy:
    overrides = {}
    for name in getattr(args, "keep", []):
        try:
            overrides[EntityType(name.upper())] = Action.KEEP
        except ValueError as exc:
            raise SystemExit(f"unknown entity type {name!r}; try 'freedocs entities'") from exc
    return Policy(
        overrides=overrides,
        min_confidence=args.min_confidence,
        placeholder_locale=getattr(args, "placeholder_language", DEFAULT_LOCALE),
    )


def _reviewer(args: argparse.Namespace) -> LlmReviewer | None:
    model = getattr(args, "review", None)
    if not model:
        return None
    host = getattr(args, "review_host", None) or DEFAULT_HOST
    try:
        return LlmReviewer(
            model=model, host=host, allow_remote=bool(getattr(args, "review_remote", False))
        )
    except RemoteHostRefused as exc:
        raise SystemExit(str(exc)) from exc


def _scrubber(args: argparse.Namespace, *, strict: bool) -> Scrubber:
    spec = getattr(args, "detectors", None)
    countries = _countries(args)
    registry = build_registry(spec, countries=countries) if spec else default_registry(countries)
    return Scrubber(
        policy=_policy(args), registry=registry, strict=strict, reviewer=_reviewer(args)
    )


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


def _cmd_countries(_: argparse.Namespace) -> int:
    """The countries, and what each one actually gets.

    Printed rather than just listed, because "supported" means two different
    things here: twelve countries have identifiers a checksum confirms, and the
    United States is in the list for its numbering plan and the model alone.
    Leaving the reader to infer that from an undifferentiated list would be
    letting them believe a US social security number is checksum-confirmed.
    """
    from .detect.validators import MissingDependency, build_rules

    try:
        rules = build_rules()
    except MissingDependency:
        rules = []
    for code in SUPPORTED_COUNTRIES:
        named = sorted({rule.entity.value for rule in rules if rule.country == code})
        print(f"{code}  {', '.join(named) if named else 'phone numbers and the NER layer only'}")
    return EXIT_OK


def _cmd_review_models(args: argparse.Namespace) -> int:
    host = getattr(args, "review_host", None) or DEFAULT_HOST
    try:
        models = available_models(host, allow_remote=bool(getattr(args, "review_remote", False)))
    except RemoteHostRefused as exc:
        # A stated refusal, not a crash: the message explains the rule, which a
        # traceback would bury. The switch is named here because the shared message
        # speaks of `allow_remote`, and no such thing exists on a command line.
        print(f"{exc} From here that means --review-remote.", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if not models:
        print(
            f"no models available at {host}. Is Ollama running, and has anything been pulled?",
            file=sys.stderr,
        )
        return EXIT_UNSUPPORTED
    for model in models:
        print(model)
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

    countries = _countries(args)
    specs = [part.strip() for part in (args.detectors or "").split(",") if part.strip()]
    for name in specs or [None]:
        try:
            registry = (
                build_registry(name, countries=countries) if name else default_registry(countries)
            )
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
        "countries": _cmd_countries,
        "review-models": _cmd_review_models,
        "benchmark": _cmd_benchmark,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line entry point.

The CLI exists before the GUI on purpose: it is scriptable, testable in CI, and
it forces the engine to be usable without a window. The Tauri app calls the same
code through ``rpc.py``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from .core.egress import block_external, unblock
from .core.errors import (
    InputTooLarge,
    MalformedDocument,
    MissingDependency,
    ModelNotFound,
    OutputRefused,
)
from .core.findings import EntityType
from .core.mapping import (
    BadPassphrase,
    MalformedMap,
    check_passphrase,
    key_map_from,
    map_path_for,
    read_key_map,
    refuse_inside,
    write_key_map,
)
from .core.outputs import private_directory, write_output, write_private, write_private_json
from .core.overrides import Override, parse_override
from .core.policy import DEFAULT_LOCALE, PLACEHOLDER_LOCALES, Action, Policy
from .core.sandbox import harden
from .core.sealed import MalformedSealed
from .core.terms import (
    Term,
    TermList,
    create_terms,
    open_terms,
    read_import,
    rekey_terms,
    save_terms,
    with_terms,
    write_export,
)
from .core.terms import check_passphrase as check_terms_passphrase
from .detect.llm_review import DEFAULT_HOST, LlmReviewer, RemoteHostRefused, available_models
from .detect.validators import SUPPORTED_COUNTRIES
from .diagnostics import Check, engine_version, run_checks
from .formats.pdf import ScannedPdfNotSupported
from .formats.router import UnsupportedFormat
from .pipeline import Scrubber, build_registry, country_coverage, default_registry
from .report import (
    build_report,
    build_restore_report,
    format_console,
    format_restore_console,
)
from .restore import Restorer
from .text_mode import PASTED_NAME, decoded, handler_for_text
from .verify import LeakDetected

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_LEAK = 3
EXIT_UNSUPPORTED = 4
#: A restore that wrote its file and did not finish. Distinct from EXIT_LEAK
#: because it is the opposite failure and the opposite handling: a leak means
#: nothing was written, an incomplete restore means the output is there with a
#: placeholder still visible in it. Kept in step with ``rpc.INCOMPLETE_RESTORE``,
#: as 3 and 4 already are, and a test pins the pairing.
EXIT_INCOMPLETE = 5

#: Conditions where the input cannot be processed correctly and the honest answer
#: is to refuse. Grouped so scrub and inspect report them identically.
REFUSALS = (
    UnsupportedFormat,
    ScannedPdfNotSupported,
    MissingDependency,
    # Both are properties of the file rather than of this build, so they
    # belong beside the other two: named, per file, and the batch continues.
    InputTooLarge,
    MalformedDocument,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freedocs",
        description="Remove confidential data from documents, locally and offline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scrub = sub.add_parser("scrub", help="write a scrubbed copy of one or more files")
    scrub.add_argument(
        "files", nargs="+", type=Path, help="files to scrub, or - to read text from stdin"
    )
    scrub.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="directory for scrubbed copies; not used with -, which writes to stdout",
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
        "--map",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "also write an encrypted key file so the values can be put back with "
            "'freedocs restore'. A directory gets one <stem>.fdmap per document. "
            "Off by default: without it the mapping is destroyed at the end of "
            "the run and the scrub cannot be undone by anyone, including you"
        ),
    )
    scrub.add_argument(
        "--map-passphrase-file",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "read the key file's passphrase from the first line of this file. "
            "There is deliberately no --map-passphrase: a passphrase on a command "
            "line goes into the shell history and into 'ps'. Without this, "
            "FREEDOCS_MAP_PASSPHRASE is read, and failing that you are prompted"
        ),
    )
    scrub.add_argument(
        "--map-in-output-dir",
        action="store_true",
        help=(
            "permit writing the key file inside --output-dir. Refused by default: "
            "the realistic accident is zipping that folder and sending it, which "
            "hands over the scrubbed document and the key to undo it together"
        ),
    )
    _add_removal_arguments(scrub)
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

    restore = sub.add_parser(
        "restore",
        help="put the real values back into a document that came back from a model",
    )
    restore.add_argument(
        "files", nargs="+", type=Path, help="files to restore, or - to read text from stdin"
    )
    restore.add_argument(
        "--map",
        type=Path,
        required=True,
        metavar="PATH",
        help="the key file written by 'freedocs scrub --map'",
    )
    restore.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="directory for restored copies; not used with -, which writes to stdout",
    )
    restore.add_argument(
        "--map-passphrase-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="read the passphrase from the first line of this file",
    )
    restore.add_argument("--report", type=Path, help="write a JSON report to this path")

    inspect = sub.add_parser(
        "inspect", help="report what would be removed, without writing anything"
    )
    inspect.add_argument("files", nargs="+", type=Path)
    inspect.add_argument("--min-confidence", type=float, default=0.5)
    inspect.add_argument("--detectors", default=None)
    inspect.add_argument("--countries", default=None, metavar="CODES")
    _add_removal_arguments(inspect)

    terms = sub.add_parser(
        "terms",
        help="manage an encrypted term list: values removed on every scrub that uses it",
    )
    terms.set_defaults(files=[])
    actions = terms.add_subparsers(dest="terms_command", required=True)
    for name, text in (
        ("create", "create a new, empty term list; refused if FILE exists"),
        ("list", "print the entries, one ENTITY<TAB>value per line"),
        ("add", "add entries and save"),
        ("remove", "remove entries by exact value and save"),
        ("import", "add every entry of a plaintext or CSV file, then tell you to delete it"),
        ("export", "write the list out UNENCRYPTED; you are asked to confirm"),
        ("rekey", "change the passphrase"),
    ):
        action = actions.add_parser(name, help=text)
        action.add_argument("file", type=Path, metavar="FILE")
        action.add_argument(
            "--passphrase-file",
            type=Path,
            default=None,
            metavar="PATH",
            help=(
                f"read the passphrase from the first line of this file; without it "
                f"{TERMS_PASSPHRASE_ENV} is read, and failing that you are prompted"
            ),
        )
        if name == "list":
            action.add_argument("--query", default=None, help="only entries containing this")
        if name in ("add", "remove"):
            action.add_argument("values", nargs="+", metavar="VALUE")
        if name == "add":
            action.add_argument(
                "--entity",
                default="OTHER",
                help="the placeholder family for these values (default: OTHER)",
            )
        if name == "import":
            action.add_argument("source", type=Path, metavar="SOURCE")
        if name == "export":
            action.add_argument("output", type=Path, metavar="OUTPUT")
            action.add_argument(
                "--yes",
                action="store_true",
                help="do not ask for confirmation; the export is still unencrypted",
            )
        if name == "rekey":
            action.add_argument(
                "--new-passphrase-file",
                type=Path,
                default=None,
                metavar="PATH",
                help=f"the new passphrase; otherwise {TERMS_NEW_PASSPHRASE_ENV} or a prompt",
            )

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

    doctor = sub.add_parser(
        "doctor",
        help="check this machine can do everything this build claims",
    )
    doctor.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    doctor.add_argument(
        "--hashes",
        action="store_true",
        help="check the bundled model's weights against their recorded SHA-256, "
        "not just their length. About a second, and the only check that sees "
        "bytes altered without the length changing.",
    )
    doctor.add_argument(
        "--strict",
        action="store_true",
        help=(
            "fail when any optional layer is missing. Off by default: a machine "
            "without Tesseract is a normal machine, and a health check that "
            "calls that an error teaches people to ignore it"
        ),
    )
    doctor.add_argument(
        "--review-host",
        default=DEFAULT_HOST,
        metavar="URL",
        help="which Ollama to ask about",
    )
    doctor.set_defaults(files=[])

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
        "--apply-min-confidence",
        type=float,
        default=None,
        metavar="FLOOR",
        help=(
            "discard findings below this confidence before scoring, so the number "
            "describes what a scrub would do rather than what the detector saw. "
            "Off by default: the benchmark measures the detector"
        ),
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


#: Where a passphrase may come from when no file names one. Read here rather
#: than in each command so the two directions cannot end up with different rules.
PASSPHRASE_ENV = "FREEDOCS_MAP_PASSPHRASE"


def _passphrase(args: argparse.Namespace, *, confirm: bool) -> str:
    """The key file's passphrase, checked whichever of the three sources it came from.

    The check used to sit inside the ``getpass`` branch, so a passphrase from
    ``--map-passphrase-file`` or from the environment was returned unexamined.
    Nothing weak was ever written - ``write_key_map`` checks again - but it raises
    ``ValueError`` from inside the per-file loop, which ``_cmd_scrub`` does not
    catch, so the run died on a traceback with the scrubbed copy already on disk.
    That is verbatim the failure the comment above ``_map_target`` says this
    resolution order prevents, so the check belongs here, once, for everything.
    """
    value = _passphrase_source(args, confirm=confirm)
    try:
        check_passphrase(value)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return value


def _passphrase_source(args: argparse.Namespace, *, confirm: bool) -> str:
    """Where the passphrase comes from, in order, with no opinion on its strength.

    There is no ``--map-passphrase VALUE`` and there must not be one. An argument
    lands in the shell history and is visible in ``ps`` to every other user on the
    machine, which for this particular secret means the key to every value in the
    document.

    A missing passphrase with no terminal to ask at is a usage error, never a
    silent skip: the alternative is a scrub that quietly writes no key file and a
    user who finds out when they try to restore.
    """
    named = getattr(args, "map_passphrase_file", None)
    if named is not None:
        _warn_if_others_can_read(named)
        try:
            first = named.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SystemExit(f"cannot read {named}: {exc.strerror or 'unreadable'}") from exc
        # First line only, so an editor's trailing newline is not part of the
        # secret - a passphrase that works from one editor and not another is the
        # worst kind of intermittent.
        value = first[0] if first else ""
        if not value:
            raise SystemExit(f"{named} is empty; it should hold the passphrase on its first line")
        return value

    # Popped rather than read. PyMuPDF shells out to Tesseract on every scanned
    # page, so anything left here is inherited by a subprocess that has no
    # business holding the key to every value in the document. Not a cross-user
    # leak - /proc/<pid>/environ is owner-only - just an unnecessary copy.
    from_env = os.environ.pop(PASSPHRASE_ENV, None)
    if from_env:
        return from_env

    if not sys.stdin.isatty():
        raise SystemExit(
            "no passphrase for the key file: pass --map-passphrase-file, set "
            f"{PASSPHRASE_ENV}, or run this where a terminal can prompt"
        )
    value = getpass.getpass("Key file passphrase: ")
    if confirm and value != getpass.getpass("Again: "):
        raise SystemExit("the two passphrases do not match; nothing was written")
    return value


def _warn_if_others_can_read(path: Path) -> None:
    """Say so when the passphrase file is group- or world-readable.

    ``ssh`` refuses a private key in this state, and this file opens every value
    in the document. A warning rather than a refusal, because the mode may belong
    to a shared checkout or a mount the user does not control, and breaking a
    working setup over it would be answering a question nobody asked. The mode
    bits mean nothing on Windows, so nothing is claimed there.
    """
    if os.name == "nt":
        return
    try:
        mode = path.stat().st_mode
    except OSError:  # pragma: no cover - the read below reports it properly
        return
    if mode & 0o077:
        print(
            f"warning: {path} is readable by other accounts on this machine "
            f"(mode {mode & 0o777:04o}); it holds the key to every value the scrub removes",
            file=sys.stderr,
        )


#: The term list's passphrase sources, apart from the key file's: they are two
#: different secrets, and one variable for both would hand a scrub that asked
#: for a key file the list's passphrase without anybody deciding that.
TERMS_PASSPHRASE_ENV = "FREEDOCS_TERMS_PASSPHRASE"
TERMS_NEW_PASSPHRASE_ENV = "FREEDOCS_TERMS_NEW_PASSPHRASE"


def _add_removal_arguments(command: argparse.ArgumentParser) -> None:
    """``--remove`` and ``--terms``, shared by scrub and inspect.

    Both, because an inspect is how a person checks what a scrub is about to
    take out, and a preview that ignores the list answers a different question.
    """
    command.add_argument(
        "--remove",
        action="append",
        default=[],
        metavar="VALUE",
        help=(
            "also remove every occurrence of this exact text; repeatable. The pipe "
            "has had this since the preview could add a value, and the command line "
            "had not"
        ),
    )
    command.add_argument(
        "--terms",
        type=Path,
        default=None,
        metavar="FILE",
        help="also remove every entry of this encrypted term list",
    )
    command.add_argument(
        "--terms-passphrase-file",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            f"read the term list's passphrase from this file; without it "
            f"{TERMS_PASSPHRASE_ENV} is read, and failing that you are prompted"
        ),
    )


def _secret(named: Path | None, env: str, prompt: str, what: str, *, confirm: bool) -> str:
    """A passphrase from a file, the environment or a prompt, in that order.

    The term list's copy of :func:`_passphrase_source`, with the same three
    rules: no command-line argument, the variable popped so a Tesseract
    subprocess does not inherit it, and no terminal with neither set is a usage
    error rather than a silent skip.
    """
    if named is not None:
        _warn_if_others_can_read(named)
        try:
            first = named.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SystemExit(f"cannot read {named}: {exc.strerror or 'unreadable'}") from exc
        value = first[0] if first else ""
        if not value:
            raise SystemExit(f"{named} is empty; it should hold the passphrase on its first line")
        return value
    from_env = os.environ.pop(env, None)
    if from_env:
        return from_env
    if not sys.stdin.isatty():
        raise SystemExit(
            f"no passphrase for the {what}: pass a passphrase file, set {env}, or run "
            "this where a terminal can prompt"
        )
    value = getpass.getpass(prompt)
    if confirm and value != getpass.getpass("Again: "):
        raise SystemExit("the two passphrases do not match; nothing was written")
    return value


def _terms_passphrase(args: argparse.Namespace, named: Path | None, *, confirm: bool) -> str:
    value = _secret(
        named, TERMS_PASSPHRASE_ENV, "Term list passphrase: ", "term list", confirm=confirm
    )
    try:
        check_terms_passphrase(value)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return value


def _open_terms_or_exit(path: Path, passphrase: str) -> TermList:
    """Open a list for this process. Every failure is configuration, not input."""
    try:
        return open_terms(path, passphrase)
    except (BadPassphrase, MalformedSealed, InputTooLarge, MissingDependency) as exc:
        raise SystemExit(str(exc)) from exc


def _override(args: argparse.Namespace) -> Override:
    """``--remove`` values and the ``--terms`` list, parsed before any file is read.

    Through ``parse_override`` so the command line and the pipe agree on what a
    removal is. The list is unlocked once for the run; a CLI process is its own
    session, so there is nothing to lock afterwards.
    """
    try:
        override = parse_override(None, list(getattr(args, "remove", []) or []))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    path = getattr(args, "terms", None)
    if path is None:
        return override
    passphrase = _terms_passphrase(args, args.terms_passphrase_file, confirm=False)
    return with_terms(override, _open_terms_or_exit(path, passphrase))


def _map_target(args: argparse.Namespace) -> Path | None:
    """Where the key file goes, refusing the output directory unless told.

    Checked before the first file is read rather than after the last one is
    written: a refusal that arrives once the scrubbed copies are already on disk
    is a refusal the user has to undo by hand.
    """
    target = getattr(args, "map", None)
    if target is None:
        return None
    if not getattr(args, "map_in_output_dir", False):
        complaint = refuse_inside(target, args.output_dir)
        if complaint:
            raise SystemExit(complaint)
    return target


def _scrubber(
    args: argparse.Namespace, *, strict: bool, overrides: Override | None = None
) -> Scrubber:
    spec = getattr(args, "detectors", None)
    countries = _countries(args)
    registry = build_registry(spec, countries=countries) if spec else default_registry(countries)
    return Scrubber(
        policy=_policy(args),
        registry=registry,
        strict=strict,
        reviewer=_reviewer(args),
        overrides=overrides or Override(),
    )


def _reads_stdin(args: argparse.Namespace) -> bool | None:
    """True for ``-``, False for files, None (and a message) for a usage error.

    ``-`` stands alone. Text on stdin has no name to put a copy under, so it goes
    to stdout, and one stream cannot carry a batch's worth of documents; a
    directory is required for files and meaningless for stdin.
    """
    dash = [path for path in args.files if str(path) == "-"]
    if dash and len(args.files) > 1:
        print("- reads text from stdin and cannot be combined with files", file=sys.stderr)
        return None
    if dash:
        if args.output_dir is not None:
            print("-o is not used with -: the result goes to stdout", file=sys.stderr)
            return None
        return True
    if args.output_dir is None:
        print("-o/--output-dir is required for files", file=sys.stderr)
        return None
    return False


def _cmd_scrub(args: argparse.Namespace) -> int:
    stdin = _reads_stdin(args)
    if stdin is None:
        return EXIT_USAGE
    if stdin:
        return _cmd_scrub_text(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Both resolved before anything is read. A bad passphrase rule or a key file
    # aimed at the output directory must stop the run, not interrupt it halfway
    # through with scrubbed copies already on disk.
    map_target = _map_target(args)
    passphrase = _passphrase(args, confirm=True) if map_target else ""
    overrides = _override(args)
    try:
        scrubber = _scrubber(args, strict=not args.allow_leaks, overrides=overrides)
    except (ValueError, MissingDependency) as exc:
        # Unprefixed: this guard covers the detector spec, the country list and
        # the policy, and every one of those messages already names what it is
        # about. Saying "detectors:" in front of a min_confidence complaint sent
        # the reader to the wrong option.
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    reports = []
    status = EXIT_OK

    for path in args.files:
        try:
            result = scrubber.scrub_file(path)
        except ModelNotFound as exc:
            # Configuration, not input: every remaining file would fail the same
            # way, and naming the file in front of it blames the document for a
            # broken FREEDOCS_NER_MODEL.
            print(exc, file=sys.stderr)
            return EXIT_USAGE
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
        try:
            # Left to the umask, unlike the key file and the restored document.
            # This is the one artifact whose purpose is to be sent, and stage 6
            # has already searched it for every value that was meant to be gone.
            write_output(destination, result.output)
        except OutputRefused as exc:
            # Per file, and a usage status: the document was fine and the path was
            # not, so blaming the run rather than the file would send the reader to
            # the wrong place.
            print(f"{path.name}: {exc}", file=sys.stderr)
            status = EXIT_USAGE
            continue
        print(format_console(result))
        print(f"  written: {destination}")

        wrote_key = False
        if map_target is not None:
            key_path = map_path_for(map_target, path)
            key_map = key_map_from(result, placeholder_language=args.placeholder_language)
            try:
                write_key_map(key_path, key_map, passphrase)
            except MissingDependency as exc:
                # The scrubbed file is already on disk and is correct, so this is
                # not a reason to claim the run failed - but the user asked to be
                # able to undo it and cannot, so it is not a success either.
                print(f"{path.name}: {exc}", file=sys.stderr)
                return EXIT_UNSUPPORTED
            wrote_key = True
            print(f"  key file: {key_path}")
            # Said where the key file is written as well as where it is read: the
            # person choosing to keep one is the person who should know its limit.
            for message in key_map.warnings():
                print(f"  warning: {message}")

        reports.append(build_report(result, key_file=wrote_key))
        if not result.verify.ok:
            status = EXIT_LEAK

    if args.report and reports:
        # Owner only. It carries no values since `build_report` was audited, but it
        # does carry where each one was and what the source document was called.
        write_private_json(args.report, reports)
        print(f"report: {args.report}")
    return status


def _cmd_scrub_text(args: argparse.Namespace) -> int:
    """``freedocs scrub -``: stdin in, scrubbed text out, everything else on stderr.

    Stdout is the output here, so the summary, the key file's path and every
    warning go to stderr - a pipe into a model must carry nothing but the text.
    A leak writes nothing to stdout at all, for the reason a leaking file is not
    written. The key file is ``--map`` as for a file; a CLI process ends, so
    there is nothing to hold a mapping in between.
    """
    target = getattr(args, "map", None)
    passphrase = _passphrase(args, confirm=True) if target else ""
    try:
        scrubber = _scrubber(args, strict=not args.allow_leaks, overrides=_override(args))
    except (ValueError, MissingDependency) as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    try:
        handler = handler_for_text(sys.stdin.read())
        result = scrubber.scrub(handler)
    except ModelNotFound as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    except REFUSALS as exc:
        print(f"{PASTED_NAME}: {exc}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    except LeakDetected as exc:
        print(f"{PASTED_NAME}: {exc}", file=sys.stderr)
        print("  nothing written", file=sys.stderr)
        return EXIT_LEAK

    sys.stdout.write(decoded(handler, result.output))
    sys.stdout.flush()
    print(format_console(result), file=sys.stderr)

    wrote_key = False
    if target is not None:
        key_path = map_path_for(target, Path(PASTED_NAME))
        key_map = key_map_from(result, placeholder_language=args.placeholder_language)
        try:
            write_key_map(key_path, key_map, passphrase)
        except (MissingDependency, OutputRefused) as exc:
            print(f"{PASTED_NAME}: {exc}", file=sys.stderr)
            return EXIT_UNSUPPORTED
        wrote_key = True
        print(f"  key file: {key_path}", file=sys.stderr)
        for message in key_map.warnings():
            print(f"  warning: {message}", file=sys.stderr)

    if args.report:
        write_private_json(args.report, [build_report(result, key_file=wrote_key)])
        print(f"report: {args.report}", file=sys.stderr)
    return EXIT_OK if result.verify.ok else EXIT_LEAK


def _cmd_restore(args: argparse.Namespace) -> int:
    """Put the values back, per file, from one key file.

    Shaped like :func:`_cmd_scrub` on purpose - helper construction inside a
    guard, then a loop where a refusal names the file and continues. One
    difference, and it is the whole character of this command: **an incomplete
    restore still writes its file.** A scrub that leaks writes nothing, because a
    nearly-clean document gets sent. A restore that left a placeholder behind has
    produced the caller's best artifact with a visible defect in it, so the bytes
    go to disk, every problem is printed, and the exit code says so.
    """
    stdin = _reads_stdin(args)
    if stdin is None:
        return EXIT_USAGE
    # Owner only when this call creates it, since what lands in it is the
    # originals. An existing directory is left as the user made it.
    if not stdin:
        private_directory(args.output_dir)
    passphrase = _passphrase(args, confirm=False)
    try:
        key_map = read_key_map(args.map, passphrase)
    except MissingDependency as exc:
        print(exc, file=sys.stderr)
        return EXIT_UNSUPPORTED
    except (BadPassphrase, MalformedMap) as exc:
        # Configuration, not input: every file in the list would fail identically,
        # so there is nothing to continue to.
        print(exc, file=sys.stderr)
        return EXIT_USAGE

    # Printed once for the run rather than once per file: it is a property of the
    # key file, and repeating it per document reads as a per-document problem.
    for message in key_map.warnings():
        print(f"warning: {message}", file=sys.stderr)

    if stdin:
        # The originals, on stdout: the caller chose where that goes, and a
        # restored text is for reading, which is what a terminal or a pipe is.
        try:
            handler = handler_for_text(sys.stdin.read())
            result = Restorer(key_map=key_map).restore(handler)
        except REFUSALS as exc:
            print(f"{PASTED_NAME}: {exc}", file=sys.stderr)
            return EXIT_UNSUPPORTED
        sys.stdout.write(decoded(handler, result.output))
        sys.stdout.flush()
        print(format_restore_console(result), file=sys.stderr)
        if args.report:
            write_private_json(args.report, [build_restore_report(result)])
            print(f"report: {args.report}", file=sys.stderr)
        return EXIT_OK if result.ok else EXIT_INCOMPLETE

    reports = []
    status = EXIT_OK
    for path in args.files:
        try:
            result = Restorer(key_map=key_map).restore(path)
        except REFUSALS as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            status = EXIT_UNSUPPORTED
            continue

        destination = args.output_dir / path.name
        try:
            # Owner only. The key file was meticulously 0600 while this - which is
            # the originals, reassembled - went out at whatever the umask said.
            write_private(destination, result.output)
        except OutputRefused as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            status = EXIT_USAGE
            continue
        print(format_restore_console(result))
        print(f"  written: {destination}")
        reports.append(build_restore_report(result))
        if not result.ok:
            status = EXIT_INCOMPLETE

    if args.report and reports:
        write_private_json(args.report, reports)
        print(f"report: {args.report}")
    return status


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Report what a scrub would do, writing nothing.

    Goes through `Scrubber.inspect_file` rather than composing route, extract and
    detect by hand. The hand-rolled copy that used to live here answered a
    different question from the scrub that follows it, in three ways that all
    read as "this file is cleaner than it is": it never called `scrub_hidden`,
    so it reported no comment, tracked deletion, hidden sheet, annotation or
    metadata - the leaks a reader does not expect; it extracted from an
    unscrubbed handler, so its offsets and its finding set were not the ones the
    scrub would produce; and it printed no registry note, so a build without the
    `ner` extra silently reported reduced coverage. One read-and-detect path,
    used by the preview and the scrub.
    """
    overrides = _override(args)
    try:
        scrubber = _scrubber(args, strict=False, overrides=overrides)
    except (ValueError, MissingDependency) as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE

    status = EXIT_OK
    for path in args.files:
        try:
            inspection = scrubber.inspect_file(path)
        except ModelNotFound as exc:
            # Configuration, not input: it will fail identically on every file,
            # so there is nothing to continue to.
            print(exc, file=sys.stderr)
            return EXIT_USAGE
        except REFUSALS as exc:
            # Continue rather than return, as scrub does: one unreadable file in
            # a list is not a reason to say nothing about the rest.
            print(f"{path.name}: {exc}", file=sys.stderr)
            status = EXIT_UNSUPPORTED
            continue

        extraction = inspection.extraction
        text = inspection.stream.text
        print(f"{path.name}  [{extraction.format_name}]  {len(text)} chars")
        for finding in inspection.findings:
            action = scrubber.policy.action_for(finding)
            print(
                f"  {finding.span.start:>7}-{finding.span.end:<7} "
                f"{finding.entity.value:<22} {action.value:<9} "
                f"conf={finding.confidence:.2f}  via {finding.detector}"
            )
        if not inspection.findings:
            print("  nothing matched")

        # Same shape as `report.format_console`, so the terminal and the report
        # describe one document the same way.
        if extraction.hidden:
            print("  hidden content found:")
            for item in extraction.hidden:
                print(f"    {item.part:<12} {item.kind:<26} {item.detail}")
        if inspection.terms is not None:
            print(
                f"  term list: {inspection.terms.matched} of {inspection.terms.loaded} "
                "entries removed something in this document"
            )
        for message in inspection.warnings:
            print(f"  warning: {message}")
    return status


def _cmd_terms(args: argparse.Namespace) -> int:
    """``freedocs terms ...``: one process, one unlock, nothing left open.

    Every change is saved before the command returns, through the same atomic
    writer the window's edits use. ``export`` asks first because it is the one
    way out of the encryption; ``import`` ends by saying the source should be
    deleted and does not delete it, because that is the person's file.
    """
    path: Path = args.file
    command = args.terms_command
    try:
        if command == "create":
            passphrase = _terms_passphrase(args, args.passphrase_file, confirm=True)
            create_terms(path, passphrase)
            print(f"created {path}: an empty term list")
            return EXIT_OK

        passphrase = _terms_passphrase(args, args.passphrase_file, confirm=False)
        terms = _open_terms_or_exit(path, passphrase)

        if command == "list":
            for term in terms.search(args.query):
                print(f"{term.entity.value}\t{term.value}")
            return EXIT_OK
        if command == "add":
            try:
                entity = EntityType(args.entity.upper())
            except ValueError as exc:
                raise SystemExit(
                    f"unknown entity type {args.entity!r}; try 'freedocs entities'"
                ) from exc
            terms, added = terms.with_added(Term(value=v, entity=entity) for v in args.values)
            save_terms(path, terms, passphrase)
            print(f"added {added}, skipped {len(args.values) - added}; {len(terms)} entries")
            return EXIT_OK
        if command == "remove":
            terms, removed = terms.without(args.values)
            save_terms(path, terms, passphrase)
            print(f"removed {removed}; {len(terms)} entries")
            return EXIT_OK
        if command == "import":
            incoming = read_import(args.source)
            terms, added = terms.with_added(incoming)
            save_terms(path, terms, passphrase)
            print(f"imported {added}, skipped {len(incoming) - added}; {len(terms)} entries")
            print(
                f"warning: {args.source} is not encrypted and still holds every entry; "
                "delete it now that the term list has them",
                file=sys.stderr,
            )
            return EXIT_OK
        if command == "export":
            if not args.yes:
                if not sys.stdin.isatty():
                    raise SystemExit(
                        "an export is unencrypted; pass --yes to confirm when no terminal can ask"
                    )
                answer = input(
                    f"{args.output} will NOT be encrypted: anyone who can read it can "
                    "read every entry. Write it? [y/N] "
                )
                if answer.strip().lower() not in ("y", "yes"):
                    print("nothing was written")
                    return EXIT_OK
            write_export(args.output, terms, refuse=[path])
            print(f"exported {len(terms)} entries to {args.output} (unencrypted)")
            return EXIT_OK
        if command == "rekey":
            new = _secret(
                args.new_passphrase_file,
                TERMS_NEW_PASSPHRASE_ENV,
                "New passphrase: ",
                "term list",
                confirm=True,
            )
            rekey_terms(path, passphrase, new)
            print(f"re-sealed {path} under the new passphrase")
            return EXIT_OK
    except (BadPassphrase, MalformedSealed, InputTooLarge, MissingDependency, OutputRefused) as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        # The passphrase floor, raised by `core/sealed.py` without quoting it.
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    raise AssertionError(f"unhandled terms command {command!r}")  # pragma: no cover


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

    Composed by :func:`pipeline.country_coverage`, which the RPC layer also
    serves to the window. One answer for the terminal and the window: two would
    be two things to keep true.
    """
    coverage = country_coverage()
    for country in coverage["countries"]:  # type: ignore[index]
        named = ", ".join(country["entities"]) or country["detail"]
        print(f"{country['code']}  {named}")
    return EXIT_OK


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Report every capability with the fix printed beside the failure.

    The facts are gathered in :mod:`freedocs.diagnostics`; this only prints them.
    """
    checks = run_checks(
        getattr(args, "review_host", None) or DEFAULT_HOST,
        hashes=bool(getattr(args, "hashes", False)),
    )
    if args.json:
        print(
            json.dumps(
                {
                    "version": engine_version(),
                    "ok": all(check.ok or not check.required for check in checks),
                    "checks": [
                        {
                            "name": check.name,
                            "ok": check.ok,
                            "detail": check.detail,
                            "fix": check.fix,
                            "required": check.required,
                        }
                        for check in checks
                    ],
                },
                indent=2,
            )
        )
        return _doctor_exit(checks, strict=args.strict)

    print(f"freedocs {engine_version()}")
    for check in checks:
        mark = "ok  " if check.ok else ("warn" if not check.required else "FAIL")
        print(f"  [{mark}] {check.name:<18} {check.detail}")
        if check.fix:
            print(f"           {'':<18} fix: {check.fix}")
    return _doctor_exit(checks, strict=args.strict)


def _doctor_exit(checks: list[Check], *, strict: bool) -> int:
    """Broken is always an error; degraded is one only when asked."""
    if any(not check.ok and check.required for check in checks):
        return EXIT_USAGE
    if strict and any(check.degraded for check in checks):
        return EXIT_USAGE
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


class _Thresholded:
    """A registry seen through ``Policy.min_confidence``.

    ``evaluate`` calls ``detect`` directly, so the threshold is normally not in
    the loop and the benchmark scores every candidate the detector nominated.
    That is the right default — a corpus trap tuned against a threshold measures
    the threshold — but it charges the detector for findings a scrub discards,
    and with the weak country rules the gap is the whole difference between 0.57%
    and 0.36% over-redaction. Making it a flag lets both numbers be quoted
    without either being the quiet one.
    """

    def __init__(self, inner: object, floor: float) -> None:
        self.inner = inner
        self.floor = floor

    def detect(self, text: str) -> list:
        return [f for f in self.inner.detect(text) if f.confidence >= self.floor]  # type: ignore[attr-defined]


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
    floor = getattr(args, "apply_min_confidence", None)
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
            result = evaluate(documents, _Thresholded(registry, floor) if floor else registry)
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
    """The CLI entry point, and one of the two places that own the process.

    The hardening is applied here rather than at import, and undone on the way
    out. Both halves matter. Importing ``freedocs`` as a library must not
    silently change what a caller's own sockets and limits do - so it belongs to
    an entry point. And restoring means a test that calls this does not leave the
    interpreter with sockets blocked for whatever runs next, which is a fixture
    nobody would think to write.
    """
    harden()
    block_external()
    try:
        return _dispatch(argv)
    finally:
        unblock()


def _dispatch(argv: list[str] | None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "scrub": _cmd_scrub,
        "restore": _cmd_restore,
        "inspect": _cmd_inspect,
        "entities": _cmd_entities,
        "countries": _cmd_countries,
        "review-models": _cmd_review_models,
        "doctor": _cmd_doctor,
        "benchmark": _cmd_benchmark,
        "terms": _cmd_terms,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

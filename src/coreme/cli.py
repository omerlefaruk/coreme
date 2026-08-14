"""Command-line interface for Job creation, proof, and execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from coreme import __version__
from coreme._process import ProcessError
from coreme.brief import BriefError, assemble_brief
from coreme.events import events_path, read_events, read_fail_summary
from coreme.init import InitError, init_job
from coreme.inputs import InputError, SecretError
from coreme.manifest import ManifestError
from coreme.paths import JobPathError, find_repo_root
from coreme.present import (
    RESULT_ENV,
    format_events_text,
    format_fail_summary_text,
    print_error,
    print_note,
    print_repair_footer,
    print_run_footer,
    print_ship_footer,
    write_result_channel,
)
from coreme.proof import test_job
from coreme.repair import (
    RepairError,
    auto_repair_wanted,
    execute_repair,
    maybe_auto_repair,
    next_steps_text,
    resolve_source,
)
from coreme.resolve import describe_resolution, resolve_job_ref
from coreme.runner import run_job
from coreme.seed_from_fail import (
    SeedFromFailError,
    format_plan_text,
    run_seed_plan,
    seed_from_fail,
)
from coreme.ship import ShipError, ship_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreme",
        description="Agent writes Jobs; Runner executes them without AI.",
    )
    parser.add_argument("--version", action="version", version=f"coreme {__version__}")
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Disable color/panels (also COREME_PLAIN=1)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="Create a Job skeleton")
    init_parser.add_argument("path", help="Directory for the new Job")
    init_parser.add_argument("--name", required=True, help="Job name")

    test_parser = commands.add_parser("test", help="Run offline proof")
    test_parser.add_argument(
        "job_path",
        help="Job folder path, or process name (latest release under releases/)",
    )

    run_parser = commands.add_parser("run", help="Execute a Job and write a Run")
    run_parser.add_argument(
        "job_path",
        help="Job folder path, or process name (latest release under releases/)",
    )
    run_parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Declared input as KEY=VALUE; repeat for more inputs",
    )
    run_parser.add_argument(
        "--auto-repair",
        action="store_true",
        default=False,
        help="After a failed Run, deploy host Codex once with the fail brief",
    )
    run_parser.add_argument(
        "--no-auto-repair",
        action="store_true",
        default=False,
        help="Disable auto-repair even if COREME_AUTO_REPAIR is set",
    )
    run_parser.add_argument(
        "--repair-prove",
        action="store_true",
        default=False,
        help="After Codex exit 0, run offline proof on source (auto path already defaults on)",
    )
    run_parser.add_argument(
        "--no-repair-prove",
        action="store_true",
        default=False,
        help="Skip offline proof after Codex (overrides auto default and COREME_REPAIR_PROVE)",
    )

    ship_parser = commands.add_parser("ship", help="Freeze a proven Job as a Release")
    ship_parser.add_argument("job_path", help="Path to Job directory")

    events_parser = commands.add_parser(
        "events",
        help="Show structured events for a Run folder",
    )
    events_parser.add_argument(
        "run_path",
        help="Path to a Run directory (contains events.jsonl)",
    )
    events_parser.add_argument(
        "--output",
        choices=("text", "jsonl"),
        default="text",
        help="text table (default) or raw JSONL",
    )

    brief_parser = commands.add_parser(
        "brief",
        help="Assemble a repair brief from a Run folder",
    )
    brief_parser.add_argument("run_path", help="Path to a Run directory")
    brief_parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Write brief to FILE instead of stdout",
    )
    brief_parser.add_argument(
        "--log-lines",
        type=int,
        default=80,
        metavar="N",
        help="Log tail lines in the brief (default 80)",
    )

    repair_parser = commands.add_parser(
        "repair",
        help="Show repair brief + next steps; --exec deploys host Codex",
    )
    repair_parser.add_argument("run_path", help="Path to a Run directory")
    repair_parser.add_argument(
        "--exec",
        action="store_true",
        default=False,
        dest="do_exec",
        help="Spawn host codex exec once with the fail brief",
    )
    repair_parser.add_argument(
        "--repair-prove",
        action="store_true",
        default=False,
        help="After Codex exit 0, run offline proof once on source",
    )
    repair_parser.add_argument(
        "--no-repair-prove",
        action="store_true",
        default=False,
        help="Skip offline proof after Codex",
    )
    repair_parser.add_argument(
        "--log-lines",
        type=int,
        default=80,
        metavar="N",
        help="Log tail lines in the brief (default 80)",
    )

    seed_parser = commands.add_parser(
        "seed-from-fail",
        help="Stage a Run artifact and print (or exec) a seeded coreme run",
    )
    seed_parser.add_argument(
        "run_path",
        help="Path to a Run directory (contains run.json and artifacts/)",
    )
    seed_parser.add_argument(
        "--artifact",
        metavar="NAME",
        help="File name under artifacts/ (required when multiple candidates)",
    )
    seed_parser.add_argument(
        "--only",
        metavar="PHASES",
        help="Forward as --input only=PHASES on the suggested re-run",
    )
    seed_parser.add_argument(
        "--job",
        metavar="PATH",
        help="Job folder for handoffs.toml and coreme run target",
    )
    seed_parser.add_argument(
        "--stage-dir",
        metavar="DIR",
        help="Stage copy directory (default: <workspace>/.coreme-seed/<job>-<stamp>/)",
    )
    seed_mode = seed_parser.add_mutually_exclusive_group()
    seed_mode.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Resolve and print command without copying the artifact",
    )
    seed_mode.add_argument(
        "--exec",
        action="store_true",
        default=False,
        dest="do_exec",
        help="After staging, run the suggested coreme run via subprocess",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plain = bool(getattr(args, "plain", False))
    try:
        if args.command == "init":
            print(f"Created job at {init_job(args.path, args.name)}")
            return 0
        if args.command == "test":
            root = find_repo_root()
            job = resolve_job_ref(args.job_path, root)
            note = describe_resolution(args.job_path, job, root)
            if note:
                print_note(note, plain_flag=plain)
            return test_job(job)
        if args.command == "run":
            return _cmd_run(args, plain_flag=plain)
        if args.command == "ship":
            release_path, content_hash = ship_job(args.job_path, find_repo_root())
            print_ship_footer(str(release_path), content_hash, plain_flag=plain)
            return 0
        if args.command == "events":
            return _cmd_events(args.run_path, output=args.output, plain_flag=plain)
        if args.command == "brief":
            return _cmd_brief(args, plain_flag=plain)
        if args.command == "repair":
            return _cmd_repair(args, plain_flag=plain)
        if args.command == "seed-from-fail":
            return _cmd_seed_from_fail(args, plain_flag=plain)
    except (
        ManifestError,
        InputError,
        SecretError,
        InitError,
        ShipError,
        JobPathError,
        ProcessError,
        BriefError,
        RepairError,
        SeedFromFailError,
    ) as error:
        print_error(str(error), plain_flag=plain)
        return 2
    return 2


def _cmd_run(args: argparse.Namespace, *, plain_flag: bool) -> int:
    result_fd = _take_machine_result_channel()
    try:
        root = find_repo_root()
        job = resolve_job_ref(args.job_path, root)
        note = describe_resolution(args.job_path, job, root)
        if note:
            print_note(note, plain_flag=plain_flag)
        record = run_job(
            job,
            repo_root=root,
            input_pairs=_parse_cli_inputs(args.input),
        )
        # Write before the human footer/optional repair. The retained duplicate
        # is non-inheritable, and the locator was removed before run_job.
        if result_fd is not None:
            write_result_channel(record, result_fd)
        # Footer first so operators always see the Rich panel immediately.
        print_run_footer(record, plain_flag=plain_flag, repair=None)

        want_auto = auto_repair_wanted(
            flag=True if args.auto_repair else None,
            no_flag=bool(args.no_auto_repair),
        )
        if want_auto:
            repair_outcome = maybe_auto_repair(
                record.run_path,
                repo_root=root,
                status=record.status,
                exit_code=record.exit_code,
                prove_flag=bool(args.repair_prove),
                no_prove_flag=bool(args.no_repair_prove),
                progress=lambda msg: print_note(msg, plain_flag=plain_flag),
            )
            if repair_outcome is not None:
                print_repair_footer(repair_outcome, plain_flag=plain_flag)
        return record.exit_code
    finally:
        if result_fd is not None:
            os.close(result_fd)


def _take_machine_result_channel() -> int | None:
    """Consume the inherited endpoint before Job environment construction."""
    locator = os.environ.pop(RESULT_ENV, None)
    if locator is None:
        return None
    try:
        if locator.startswith("handle:"):
            import msvcrt

            inherited = msvcrt.open_osfhandle(int(locator[7:]), os.O_WRONLY)
        else:
            inherited = int(locator)
        retained = os.dup(inherited)
        os.set_inheritable(retained, False)
        os.close(inherited)
        return retained
    except (OSError, ValueError):
        return None


def _cmd_brief(args: argparse.Namespace, *, plain_flag: bool) -> int:
    root = find_repo_root()
    run_path = Path(args.run_path)
    source = resolve_source(run_path, root) if run_path.is_dir() else None
    text = assemble_brief(
        run_path,
        log_lines=max(0, int(args.log_lines)),
        source_path=source,
    )
    if args.output:
        out = Path(args.output)
        out.write_text(text, encoding="utf-8")
        print_note(f"brief_path={out.resolve()}", plain_flag=plain_flag)
        return 0
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_repair(args: argparse.Namespace, *, plain_flag: bool) -> int:
    root = find_repo_root()
    run_path = Path(args.run_path)
    if not run_path.is_dir():
        print_error(f"not a Run directory: {args.run_path}", plain_flag=plain_flag)
        return 2

    if args.do_exec:
        outcome = execute_repair(
            run_path,
            repo_root=root,
            trigger="manual",
            prove_flag=bool(args.repair_prove),
            no_prove_flag=bool(args.no_repair_prove),
            log_lines=max(0, int(args.log_lines)),
            progress=lambda msg: print_note(msg, plain_flag=plain_flag),
        )
        print_note(f"repair_status={outcome.status}", plain_flag=plain_flag)
        print_note(f"repair_path={outcome.path}", plain_flag=plain_flag)
        if outcome.source_path:
            print_note(f"source_path={outcome.source_path}", plain_flag=plain_flag)
        # Manual exec: nonzero if Codex missing/error; finished with codex!=0 also nonzero.
        if outcome.status in {"codex_missing", "skipped_no_source", "error"}:
            return 1
        if outcome.codex_exit_code is not None and outcome.codex_exit_code != 0:
            return outcome.codex_exit_code
        return 0

    source = resolve_source(run_path, root)
    text = assemble_brief(
        run_path,
        log_lines=max(0, int(args.log_lines)),
        source_path=source,
    )
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.write(next_steps_text(str(source) if source else None))
    return 0


def _cmd_seed_from_fail(args: argparse.Namespace, *, plain_flag: bool) -> int:
    plan = seed_from_fail(
        args.run_path,
        artifact=args.artifact,
        only=args.only,
        job=args.job,
        stage_dir=args.stage_dir,
        dry_run=bool(args.dry_run),
    )
    sys.stdout.write(format_plan_text(plan))
    if args.do_exec:
        # --dry-run and --exec are mutually exclusive in argparse.
        print_note("executing seeded re-run…", plain_flag=plain_flag)
        return run_seed_plan(plan)
    return 0


def _cmd_events(run_path: str, *, output: str, plain_flag: bool) -> int:
    path = Path(run_path)
    if not path.is_dir():
        print_error(f"not a Run directory: {run_path}", plain_flag=plain_flag)
        return 2
    if not events_path(path).is_file():
        print_error(f"no events.jsonl under {run_path}", plain_flag=plain_flag)
        return 2
    if output == "jsonl":
        # Machine mode: pure JSONL, no color.
        sys.stdout.write(events_path(path).read_text(encoding="utf-8"))
        return 0
    fail = read_fail_summary(path)
    if fail is not None:
        sys.stdout.write(format_fail_summary_text(fail))
        sys.stdout.write("\n")
    rows = read_events(path)
    sys.stdout.write(format_events_text(rows))
    return 0


def _parse_cli_inputs(items: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for item in items:
        if "=" not in item:
            raise InputError(f"--input must be KEY=VALUE: {item}")
        name, value = item.split("=", 1)
        if not name:
            raise InputError(f"--input key must not be empty: {item}")
        pairs.append((name, value))
    return pairs

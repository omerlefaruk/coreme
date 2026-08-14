"""CLI for local fleet agent (F1): enqueue, once, drain, list."""

from __future__ import annotations

import argparse
import json
import sys

from coreme_agent import __version__
from coreme_agent.store import (
    LocalQueue,
    QueueError,
    assignment_to_dict,
    parse_input_pairs,
)
from coreme_agent.worker import drain, process_one


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreme-agent",
        description=(
            "Local fleet agent: drain a SQLite queue and run coreme (F1 — no multi-machine hub)."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"coreme-agent {__version__}",
    )
    parser.add_argument(
        "--db",
        default="coreme-agent.db",
        help="SQLite queue path (default: ./coreme-agent.db)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    enq = commands.add_parser("enqueue", help="Create a pending Assignment")
    enq.add_argument(
        "--release",
        required=True,
        help="Local Job or release folder path for coreme run",
    )
    enq.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Declared input; repeat for more",
    )
    enq.add_argument("--id", dest="assignment_id", help="Optional assignment id")
    enq.add_argument("--batch-id", help="Optional batch id for fan-out")

    once = commands.add_parser("once", help="Claim and run at most one Assignment")
    _add_run_flags(once)

    dr = commands.add_parser("drain", help="Run pending Assignments until empty")
    _add_run_flags(dr)
    dr.add_argument(
        "--max",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N Assignments (default: all pending)",
    )

    ls = commands.add_parser("list", help="List Assignments")
    ls.add_argument("--status", help="Filter by status")
    ls.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max rows (default 50)",
    )
    ls.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print JSON array",
    )

    show = commands.add_parser("show", help="Show one Assignment")
    show.add_argument("assignment_id", help="Assignment id")
    show.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print JSON object",
    )

    return parser


def _add_run_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--workspace",
        default=".",
        help="cwd for coreme run (repo root that owns runs/)",
    )
    p.add_argument(
        "--coreme",
        default=None,
        help=(
            "coreme executable or module command as one shell token list "
            "joined by spaces, e.g. 'python -m coreme' (default: same "
            "interpreter -m coreme)"
        ),
    )
    p.add_argument(
        "--timeout-sec",
        type=float,
        default=None,
        help="Agent-level wall timeout for one coreme invocation",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "enqueue":
            return _cmd_enqueue(args)
        if args.command == "once":
            return _cmd_once(args)
        if args.command == "drain":
            return _cmd_drain(args)
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "show":
            return _cmd_show(args)
    except QueueError as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command {args.command!r}")
    return 2


def _open_queue(args: argparse.Namespace) -> LocalQueue:
    return LocalQueue(args.db)


def _coreme_cmd(args: argparse.Namespace) -> list[str] | None:
    if not args.coreme:
        return None
    return args.coreme.split()


def _cmd_enqueue(args: argparse.Namespace) -> int:
    inputs = parse_input_pairs(args.input)
    with _open_queue(args) as queue:
        a = queue.enqueue(
            args.release,
            inputs=inputs,
            assignment_id=args.assignment_id,
            batch_id=args.batch_id,
        )
    print(f"status={a.status}")
    print(f"assignment_id={a.id}")
    print(f"release_path={a.release_path}")
    return 0


def _cmd_once(args: argparse.Namespace) -> int:
    with _open_queue(args) as queue:
        finished = process_one(
            queue,
            workspace=args.workspace,
            coreme_cmd=_coreme_cmd(args),
            timeout_sec=args.timeout_sec,
        )
    if finished is None:
        print("status=idle")
        return 0
    _print_outcome(finished)
    return 0 if finished.status == "succeeded" else 1


def _cmd_drain(args: argparse.Namespace) -> int:
    with _open_queue(args) as queue:
        done = drain(
            queue,
            workspace=args.workspace,
            coreme_cmd=_coreme_cmd(args),
            max_items=args.max,
            timeout_sec=args.timeout_sec,
        )
    if not done:
        print("status=idle count=0")
        return 0
    failed = 0
    for a in done:
        _print_outcome(a)
        if a.status != "succeeded":
            failed += 1
    print(f"count={len(done)} failed={failed}")
    return 1 if failed else 0


def _cmd_list(args: argparse.Namespace) -> int:
    with _open_queue(args) as queue:
        items = queue.list(status=args.status, limit=args.limit)
    if args.as_json:
        print(json.dumps([assignment_to_dict(a) for a in items], indent=2))
        return 0
    if not items:
        print("count=0")
        return 0
    for a in items:
        print(
            f"id={a.id} status={a.status} release={a.release_path}"
            + (f" run_path={a.run_path}" if a.run_path else "")
        )
    print(f"count={len(items)}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    with _open_queue(args) as queue:
        a = queue.get(args.assignment_id)
        attempts = queue.attempts_for(args.assignment_id) if a else []
    if a is None:
        print(f"error=unknown assignment {args.assignment_id}", file=sys.stderr)
        return 2
    if args.as_json:
        payload = assignment_to_dict(a)
        payload["attempts"] = [
            {
                "id": t.id,
                "status": t.status,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
                "exit_code": t.exit_code,
                "run_path": t.run_path,
                "message": t.message,
            }
            for t in attempts
        ]
        print(json.dumps(payload, indent=2))
        return 0
    _print_outcome(a)
    for t in attempts:
        print(
            f"attempt_id={t.id} attempt_status={t.status}"
            + (f" exit_code={t.exit_code}" if t.exit_code is not None else "")
        )
    return 0


def _print_outcome(a) -> None:
    print(f"assignment_id={a.id}")
    print(f"status={a.status}")
    if a.exit_code is not None:
        print(f"exit_code={a.exit_code}")
    if a.run_path:
        print(f"run_path={a.run_path}")
    if a.message:
        print(f"message={a.message}")
    if a.attempt_id:
        print(f"attempt_id={a.attempt_id}")


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for local fleet agent (F1) and hub drain (F2)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import sys
import threading
from pathlib import Path

from coreme_agent import __version__
from coreme_agent.config import (
    AgentConfig,
    ConfigError,
    default_config_path,
    split_csv,
)
from coreme_agent.config import (
    load as load_config,
)
from coreme_agent.config import (
    save as save_config,
)
from coreme_agent.daemon import Daemon, DaemonLocked, acquire_lock, release_lock, setup_logging
from coreme_agent.hub import HubClient, HubClientError, enroll_machine
from coreme_agent.hub_worker import drain as drain_hub
from coreme_agent.hub_worker import execute_claimed
from coreme_agent.hub_worker import process_one as process_one_hub
from coreme_agent.store import (
    LocalQueue,
    QueueError,
    assignment_to_dict,
    parse_input_pairs,
)
from coreme_agent.worker import drain, process_one

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreme-agent",
        description=("Fleet agent: drain a local SQLite queue (F1) or a hub (F2 --hub)."),
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

    en = commands.add_parser(
        "enroll",
        help="Exchange a one-time enroll token for machine credentials",
    )
    en.add_argument("--hub", required=True, help="Hub base URL")
    en.add_argument("--token", required=True, help="One-time enroll token")
    en.add_argument("--tags", default=None, help="Comma-separated machine tags")
    en.add_argument(
        "--config",
        default=None,
        help="Config file to write (default: ~/.coreme/agent.toml)",
    )

    rn = commands.add_parser("run", help="Run the resident daemon (heartbeat + claim)")
    _add_run_flags(rn)
    rn.add_argument("--config", default=None, help="Agent config TOML path")
    rn.add_argument("--poll-interval", type=float, default=None, metavar="SEC")
    rn.add_argument("--heartbeat-interval", type=float, default=None, metavar="SEC")
    rn.add_argument("--slots", type=int, default=None, help="Parallel assignment slots")

    ins = commands.add_parser(
        "install-service",
        help="Print OS service registration for the daemon (print-only)",
    )
    ins.add_argument("--workspace", default=".", help="Workspace for the service")

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
    p.add_argument(
        "--hub",
        default=os.environ.get("COREME_HUB_URL"),
        help="Hub base URL (or COREME_HUB_URL). Local SQLite if omitted.",
    )
    p.add_argument(
        "--machine-id",
        default=os.environ.get("COREME_MACHINE_ID"),
        help="Machine id for hub mode (or COREME_MACHINE_ID)",
    )
    p.add_argument(
        "--machine-token",
        default=os.environ.get("COREME_MACHINE_TOKEN"),
        help="Machine bearer token (or COREME_MACHINE_TOKEN)",
    )
    p.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Machine tag for hub claim match (repeat)",
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
        if args.command == "enroll":
            return _cmd_enroll(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "install-service":
            return _cmd_install_service(args)
    except (QueueError, HubClientError, ConfigError, DaemonLocked) as exc:
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


def _hub_client(args: argparse.Namespace) -> HubClient | None:
    if not args.hub:
        return None
    if not args.machine_id or not args.machine_token:
        raise QueueError("hub mode needs --machine-id and --machine-token")
    return HubClient(args.hub, args.machine_token, args.machine_id)


def _cmd_once(args: argparse.Namespace) -> int:
    hub = _hub_client(args)
    if hub is not None:
        finished = process_one_hub(
            hub,
            tags=list(args.tag),
            workspace=args.workspace,
            coreme_cmd=_coreme_cmd(args),
            timeout_sec=args.timeout_sec,
        )
    else:
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
    hub = _hub_client(args)
    if hub is not None:
        done = drain_hub(
            hub,
            tags=list(args.tag),
            workspace=args.workspace,
            coreme_cmd=_coreme_cmd(args),
            max_items=args.max,
            timeout_sec=args.timeout_sec,
        )
    else:
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


def _cmd_enroll(args: argparse.Namespace) -> int:
    tags = split_csv(args.tags)
    result = enroll_machine(
        args.hub,
        args.token,
        tags=tags,
        agent_version=__version__,
    )
    config = AgentConfig(
        hub_url=args.hub,
        machine_id=result.machine_id,
        machine_token=result.machine_token,
        tags=tuple(result.tags) or tuple(tags),
    )
    path = save_config(config, args.config or default_config_path())
    print("status=enrolled")
    print(f"machine_id={result.machine_id}")
    print(f"config={path}")
    print("next=coreme-agent run")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(
        path=args.config,
        env=os.environ,
        hub_url=args.hub,
        machine_id=args.machine_id,
        machine_token=args.machine_token,
        tags=list(args.tag) if args.tag else None,
        workspace=args.workspace,
        poll_interval_sec=args.poll_interval,
        heartbeat_interval_sec=args.heartbeat_interval,
        slots=args.slots,
    )
    if not config.hub_url or not config.machine_id or not config.machine_token:
        raise ConfigError(
            "daemon needs hub credentials; run 'coreme-agent enroll' first "
            "(or pass --hub/--machine-id/--machine-token)"
        )
    setup_logging(config)
    client = HubClient(config.hub_url, config.machine_token, config.machine_id)
    workspace = Path(config.workspace).resolve()
    lock = acquire_lock(workspace)
    stop = threading.Event()

    def _handle(signum: int, frame: object) -> None:
        if stop.is_set():
            os._exit(130)
        log.info("signal %s: finishing current work", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle)

    coreme_cmd = _coreme_cmd(args)
    timeout_sec = args.timeout_sec
    daemon = Daemon(
        client,
        config,
        runner=lambda c, w: execute_claimed(
            c,
            w,
            workspace=workspace,
            coreme_cmd=coreme_cmd,
            timeout_sec=timeout_sec,
        ),
    )
    print(f"status=running workspace={workspace} slots={config.slots}")
    try:
        return daemon.run(stop)
    except KeyboardInterrupt:
        os._exit(130)
    finally:
        release_lock(lock)


def _cmd_install_service(args: argparse.Namespace) -> int:
    exe = shutil.which("coreme-agent") or "coreme-agent"
    workspace = str(Path(args.workspace).resolve())
    if os.name == "nt":
        print("# Register an at-logon task (run in an elevated prompt):")
        print(
            f'schtasks /Create /TN "CoreMeAgent" /SC ONLOGON /RL HIGHEST /F '
            f'/TR ""{exe}" run --workspace "{workspace}""'
        )
        print("# Start it now:")
        print('schtasks /Run /TN "CoreMeAgent"')
        print("# Note: ONLOGON tasks do not restart on crash. For watchdog behavior prefer NSSM:")
        print(f'#   nssm install CoreMeAgent "{exe}" run --workspace "{workspace}"')
        return 0
    print("# systemd unit — save as /etc/systemd/system/coreme-agent.service:")
    print("[Unit]")
    print("Description=CoreMe robot daemon")
    print("After=network-online.target")
    print("Wants=network-online.target")
    print()
    print("[Service]")
    print(f"ExecStart={exe} run --workspace {workspace}")
    print("Restart=on-failure")
    print("RestartSec=5")
    print()
    print("[Install]")
    print("WantedBy=multi-user.target")
    print()
    print("# systemctl daemon-reload && systemctl enable --now coreme-agent")
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

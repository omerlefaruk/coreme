"""CLI for the hub: migrate, serve, register, enqueue, list, show."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from coreme_hub import __version__
from coreme_hub.db import HubError, StoreError, connect, migrate, resolve_dsn
from coreme_hub.http import serve as serve_http
from coreme_hub.store import (
    assignment_public,
    create_enroll_token,
    create_schedule,
    delete_schedule,
    enqueue,
    enroll_token_public,
    get_assignment,
    latest_evidence,
    list_assignments,
    list_attempts,
    list_enroll_tokens,
    list_machines,
    list_schedules,
    machine_public,
    prune_old,
    register_tree,
    revoke_enroll_token,
    set_machine_drained,
    set_schedule_enabled,
    validate_schedule_template,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreme-hub",
        description="Thin fleet hub: claim, release catalog, evidence (F3).",
    )
    parser.add_argument("--version", action="version", version=f"coreme-hub {__version__}")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("COREME_HUB_DSN"),
        help="Postgres DSN (or COREME_HUB_DSN)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Create hub tables")

    srv = commands.add_parser("serve", help="Serve the claim HTTP API")
    srv.add_argument(
        "--bind",
        default=os.environ.get("COREME_HUB_BIND", "127.0.0.1:8787"),
        help="HOST:PORT (default 127.0.0.1:8787)",
    )
    srv.add_argument(
        "--ops-token",
        default=os.environ.get("COREME_HUB_OPS_TOKEN"),
        help="Ops bearer token (or COREME_HUB_OPS_TOKEN)",
    )
    srv.add_argument(
        "--data",
        default=os.environ.get("COREME_HUB_DATA"),
        help="Blob/evidence directory (or COREME_HUB_DATA)",
    )

    reg = commands.add_parser("register", help="Hash a release folder and store its blob")
    reg.add_argument("--path", required=True, help="Job or release folder")
    reg.add_argument("--name", default=None)
    reg.add_argument("--version", default=None)
    reg.add_argument(
        "--data",
        default=os.environ.get("COREME_HUB_DATA"),
        help="Blob directory (or COREME_HUB_DATA)",
    )

    enq = commands.add_parser("enqueue", help="Create a pending Assignment from the catalog")
    enq.add_argument("--release", help="Catalog name")
    enq.add_argument("--version", default="0.0.0")
    enq.add_argument("--content-hash", default=None)
    enq.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    enq.add_argument("--tag", action="append", default=[], help="Required tag (repeat)")
    enq.add_argument("--secret-name", action="append", default=[])
    enq.add_argument("--lease-seconds", type=int, default=900)
    enq.add_argument("--id", dest="assignment_id")
    enq.add_argument("--batch-id")

    ls = commands.add_parser("list", help="List assignments")
    ls.add_argument("--status")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true", dest="as_json")
    ls.add_argument("--machines", action="store_true", help="List machines instead")

    show = commands.add_parser("show", help="Show one assignment")
    show.add_argument("assignment_id")
    show.add_argument("--json", action="store_true", dest="as_json")

    et = commands.add_parser("enroll-token", help="One-time machine enrollment tokens")
    et_commands = et.add_subparsers(dest="enroll_command", required=True)
    etc = et_commands.add_parser("create", help="Mint a token (printed once)")
    etc.add_argument("--tags", default=None, help="Comma-separated machine tags")
    etc.add_argument("--ttl-hours", type=float, default=1.0)
    et_commands.add_parser("list", help="List enroll tokens")
    etr = et_commands.add_parser("revoke", help="Delete an unused enroll token")
    etr.add_argument("--id", dest="token_id", required=True, help="Token uuid")

    sch = commands.add_parser("schedule", help="Timed Assignment creation (F5)")
    sch_commands = sch.add_subparsers(dest="schedule_command", required=True)
    sc = sch_commands.add_parser("create", help="Create a schedule")
    sc.add_argument("--name", required=True)
    sc.add_argument("--release", required=True, help="Catalog release name")
    sc.add_argument("--version", default="0.0.0")
    sc.add_argument("--interval-sec", type=int, default=None, metavar="SEC")
    sc.add_argument("--daily-utc", default=None, help="HH:MM UTC daily alternative")
    sc.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    sc.add_argument("--tag", action="append", default=[], help="Required tag (repeat)")
    sc.add_argument("--secret-name", action="append", default=[])
    sc.add_argument("--lease-seconds", type=int, default=900)
    sc.add_argument(
        "--data",
        default=os.environ.get("COREME_HUB_DATA"),
        help="Blob directory for manifest validation (or COREME_HUB_DATA)",
    )
    sch_commands.add_parser("list", help="List schedules")
    sen = sch_commands.add_parser("enable", help="Enable a schedule")
    sen.add_argument("--name", required=True)
    sdis = sch_commands.add_parser("disable", help="Disable a schedule (stops new work)")
    sdis.add_argument("--name", required=True)
    sdel = sch_commands.add_parser("delete", help="Delete a schedule")
    sdel.add_argument("--name", required=True)

    mach = commands.add_parser("machine", help="Drain or re-enable one machine (F6)")
    mach_commands = mach.add_subparsers(dest="machine_command", required=True)
    mdr = mach_commands.add_parser("drain", help="Stop new claims; finish current work")
    mdr.add_argument("machine_id")
    mun = mach_commands.add_parser("undrain", help="Re-enable claims for a machine")
    mun.add_argument("machine_id")

    pr = commands.add_parser("prune", help="Delete old terminal assignments + evidence")
    pr.add_argument("--days", type=int, required=True, help="Age cutoff in days")
    pr.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be deleted without deleting",
    )
    pr.add_argument(
        "--data",
        default=os.environ.get("COREME_HUB_DATA"),
        help="Blob/evidence directory (or COREME_HUB_DATA)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        dsn = resolve_dsn(args.dsn)
        if args.command == "migrate":
            migrate(dsn)
            print("status=migrated")
            return 0
        if args.command == "register":
            return _cmd_register(dsn, args)
        if args.command == "serve":
            httpd = serve_http(dsn, bind=args.bind, ops_token=args.ops_token, data_dir=args.data)
            host, port = httpd.server_address[:2]
            host_s = host.decode() if isinstance(host, bytes) else str(host)
            print(f"status=listening bind={host_s}:{port}")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("status=stopped")
            finally:
                httpd.server_close()
            return 0
        if args.command == "enqueue":
            return _cmd_enqueue(dsn, args)
        if args.command == "list":
            return _cmd_list(dsn, args)
        if args.command == "show":
            return _cmd_show(dsn, args)
        if args.command == "enroll-token":
            return _cmd_enroll_token(dsn, args)
        if args.command == "schedule":
            return _cmd_schedule(dsn, args)
        if args.command == "machine":
            return _cmd_machine(dsn, args)
        if args.command == "prune":
            return _cmd_prune(dsn, args)
    except (HubError, StoreError) as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command {args.command!r}")
    return 2


def _cmd_register(dsn: str, args: argparse.Namespace) -> int:
    data = Path(args.data or "coreme-hub-data")
    with connect(dsn) as conn:
        row = register_tree(
            conn,
            data_dir=data,
            source=args.path,
            name=args.name,
            version=args.version,
        )
        conn.commit()
    print("status=registered")
    print(f"name={row['name']}")
    print(f"version={row['version']}")
    print(f"content_hash={row['content_hash']}")
    print(f"blob_url={row['blob_url']}")
    print(f"size_bytes={row['size_bytes']}")
    return 0


def _cmd_enqueue(dsn: str, args: argparse.Namespace) -> int:
    if not args.release and not args.content_hash:
        raise HubError(400, "enqueue needs --release or --content-hash")
    inputs = _pairs(args.input)
    with connect(dsn) as conn:
        row = enqueue(
            conn,
            name=args.release,
            version=args.version,
            content_hash=args.content_hash,
            inputs=inputs,
            secret_names=list(args.secret_name),
            required_tags=list(args.tag),
            lease_seconds=args.lease_seconds,
            assignment_id=args.assignment_id,
            batch_id=args.batch_id,
        )
        conn.commit()
    print(f"status={row['status']}")
    print(f"assignment_id={row['id']}")
    print(f"content_hash={row['content_hash']}")
    return 0


def _cmd_list(dsn: str, args: argparse.Namespace) -> int:
    with connect(dsn) as conn:
        if args.machines:
            rows = [machine_public(m) for m in list_machines(conn)]
        else:
            rows = [
                assignment_public(a)
                for a in list_assignments(conn, status=args.status, limit=args.limit)
            ]
    if args.as_json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("count=0")
        return 0
    for row in rows:
        if args.machines:
            print(
                f"id={row['id']} status={row['status']} tags={','.join(row['tags'])} "
                f"drained={row['drained']}"
            )
        else:
            print(
                f"id={row['id']} status={row['status']} "
                f"release={row['release']['name']} hash={row['release']['content_hash']}"
            )
    print(f"count={len(rows)}")
    return 0


def _cmd_show(dsn: str, args: argparse.Namespace) -> int:
    with connect(dsn) as conn:
        row = get_assignment(conn, args.assignment_id)
        attempts = list_attempts(conn, args.assignment_id) if row else []
        ev = latest_evidence(conn, args.assignment_id) if row else None
    if row is None:
        print(f"error=unknown assignment {args.assignment_id}", file=sys.stderr)
        return 2
    payload = assignment_public(row, evidence=ev)
    payload["attempts"] = [
        {
            "id": t["id"],
            "status": t["status"],
            "started_at": str(t["started_at"]) if t["started_at"] else None,
            "finished_at": str(t["finished_at"]) if t["finished_at"] else None,
            "exit_code": t["exit_code"],
            "run_id": t["run_id"],
        }
        for t in attempts
    ]
    if args.as_json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"assignment_id={payload['id']}")
    print(f"status={payload['status']}")
    print(f"content_hash={payload['release']['content_hash']}")
    if payload.get("evidence"):
        print(f"evidence_bytes={payload['evidence']['size_bytes']}")
    for t in payload["attempts"]:
        print(f"attempt_id={t['id']} attempt_status={t['status']}")
    return 0


def _cmd_enroll_token(dsn: str, args: argparse.Namespace) -> int:
    if args.enroll_command == "create":
        tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
        with connect(dsn) as conn:
            row = create_enroll_token(conn, tags=tags, ttl_hours=args.ttl_hours)
            conn.commit()
        print("status=created")
        print(f"token={row['token']}")
        print("warning=store this token now; it is not shown again")
        return 0
    if args.enroll_command == "list":
        with connect(dsn) as conn:
            rows = [enroll_token_public(t) for t in list_enroll_tokens(conn)]
        for row in rows:
            used = f" used_by={row['used_by']}" if row["used_by"] else ""
            print(
                f"id={row['id']} expires_at={row['expires_at']} tags={','.join(row['tags'])}{used}"
            )
        print(f"count={len(rows)}")
        return 0
    with connect(dsn) as conn:
        revoke_enroll_token(conn, args.token_id)
        conn.commit()
    print("status=revoked")
    return 0


def _cmd_schedule(dsn: str, args: argparse.Namespace) -> int:
    if args.schedule_command == "create":
        inputs = _pairs(args.input)
        data = Path(args.data) if args.data else None
        with connect(dsn) as conn:
            if data is not None:
                validate_schedule_template(
                    conn,
                    data_dir=data,
                    release_name=args.release,
                    release_version=args.version,
                    inputs=inputs,
                )
            row = create_schedule(
                conn,
                name=args.name,
                release_name=args.release,
                release_version=args.version,
                inputs=inputs,
                secret_names=list(args.secret_name),
                required_tags=list(args.tag),
                lease_seconds=args.lease_seconds,
                interval_seconds=args.interval_sec,
                daily_utc=args.daily_utc,
            )
            conn.commit()
        print("status=created")
        print(f"name={row['name']} release={row['release_name']}@{row['release_version']}")
        timing = (
            f"interval_sec={row['interval_seconds']}"
            if row["interval_seconds"] is not None
            else f"daily_utc={row['daily_utc']}"
        )
        print(timing)
        return 0
    if args.schedule_command == "list":
        with connect(dsn) as conn:
            rows = list_schedules(conn)
        for row in rows:
            state = "enabled" if row["enabled"] else "disabled"
            print(
                f"name={row['name']} release={row['release_name']}@{row['release_version']} "
                f"state={state} next_run_at={row['next_run_at']}"
            )
        print(f"count={len(rows)}")
        return 0
    enabled = args.schedule_command == "enable"
    with connect(dsn) as conn:
        if args.schedule_command == "delete":
            deleted = delete_schedule(conn, name=args.name)
        else:
            deleted = set_schedule_enabled(conn, name=args.name, enabled=enabled)
        conn.commit()
    if deleted is None:
        print(f"error=unknown schedule {args.name}", file=sys.stderr)
        return 2
    print(f"status={args.schedule_command}d name={args.name}")
    return 0


def _cmd_machine(dsn: str, args: argparse.Namespace) -> int:
    drained = args.machine_command == "drain"
    with connect(dsn) as conn:
        row = set_machine_drained(conn, machine_id=args.machine_id, drained=drained)
        conn.commit()
    if row is None:
        print(f"error=unknown machine {args.machine_id}", file=sys.stderr)
        return 2
    print(f"machine_id={row['id']} drained={row['drained']}")
    return 0


def _cmd_prune(dsn: str, args: argparse.Namespace) -> int:
    data = Path(args.data) if args.data else None
    with connect(dsn) as conn:
        counts = prune_old(
            conn,
            days=args.days,
            data_dir=data,
            dry_run=args.dry_run,
        )
        conn.commit()
    prefix = "would_delete" if args.dry_run else "deleted"
    print(f"{prefix}_assignments={counts['assignments']}")
    print(f"{prefix}_attempts={counts['attempts']}")
    return 0


def _pairs(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise HubError(400, f"expected KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        out[key] = value
    return out


if __name__ == "__main__":
    raise SystemExit(main())

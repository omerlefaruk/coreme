"""CLI for the hub: migrate, serve, register, enqueue, list, show."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from coreme_hub import __version__
from coreme_hub.db import HubError, connect, migrate, resolve_dsn
from coreme_hub.http import serve as serve_http
from coreme_hub.store import (
    assignment_public,
    create_assignment,
    get_assignment,
    get_release,
    get_release_by_name,
    latest_evidence,
    list_assignments,
    list_attempts,
    list_machines,
    machine_public,
    register_tree,
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
    except HubError as exc:
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
        catalog = None
        if args.content_hash:
            catalog = get_release(conn, args.content_hash)
        if catalog is None and args.release:
            catalog = get_release_by_name(conn, args.release, args.version)
        if catalog is None:
            raise HubError(404, "unknown release; register it first")
        row = create_assignment(
            conn,
            release_name=str(catalog["name"]),
            release_version=str(catalog["version"]),
            content_hash=str(catalog["content_hash"]),
            blob_url=str(catalog["blob_url"]),
            size_bytes=catalog["size_bytes"],
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
            print(f"id={row['id']} status={row['status']} tags={','.join(row['tags'])}")
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

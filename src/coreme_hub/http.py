"""stdlib HTTP for the claim loop, release blobs, and evidence."""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from coreme_hub import __version__
from coreme_hub.blobs import ensure_data_dir, parse_hash, read_blob
from coreme_hub.db import STORE_STATUS, HubError, Pool, StoreError, hash_token
from coreme_hub.store import (
    STATUS_FAILED,
    assignment_public,
    claim,
    complete,
    create_schedule,
    enqueue,
    evidence_index,
    fire_due_schedules,
    get_assignment,
    get_evidence_bytes,
    heartbeat,
    hub_stats,
    latest_evidence,
    list_assignments,
    list_machines,
    list_schedules,
    machine_public,
    put_evidence,
    redeem_enroll_token,
    register_zip,
    release_public,
    renew,
    schedule_public,
    upsert_release,
    validate_schedule_template,
)


class TextResponse(bytes):
    """Body sent as text/plain (Prometheus metrics)."""


def parse_bind(bind: str) -> tuple[str, int]:
    if ":" not in bind:
        raise ValueError("bind must be HOST:PORT")
    host, _, port_s = bind.rpartition(":")
    return host or "127.0.0.1", int(port_s)


def parse_tags(values: list[str] | None) -> list[str]:
    return [v.strip() for v in (values or []) if v.strip()]


class HubContext:
    def __init__(
        self,
        dsn: str,
        ops_token: str,
        schema: str = "public",
        data_dir: str | Path | None = None,
    ) -> None:
        if not ops_token:
            raise HubError(500, "ops token is required")
        self.dsn = dsn
        self.ops_token = ops_token
        self.schema = schema
        self.data_dir = ensure_data_dir(
            data_dir or os.environ.get("COREME_HUB_DATA") or "coreme-hub-data"
        )
        self.max_body = int(os.environ.get("COREME_HUB_MAX_BODY_MB") or 200) * 1_000_000
        self.webhook_url = os.environ.get("COREME_HUB_WEBHOOK_URL") or None
        self.pool = Pool(dsn, schema)

    def conn(self):
        return self.pool.connection()


def make_handler(ctx: HubContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
            try:
                status, body = self._route(method, parts, query)
            except StoreError as exc:
                self._send(STORE_STATUS.get(exc.kind, 500), {"error": str(exc)})
                return
            except HubError as exc:
                self._send(exc.status, {"error": str(exc)})
                return
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid json"})
                return
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
                return
            except Exception as exc:
                self._send(500, {"error": str(exc)})
                return
            if isinstance(body, bytes):
                if isinstance(body, TextResponse):
                    self._send_text(status, body)
                else:
                    self._send_bytes(status, body)
                return
            self._send(status, body)

        def _route(
            self,
            method: str,
            parts: list[str],
            query: dict[str, str],
        ) -> tuple[int, dict[str, Any] | list[Any] | bytes | None]:
            if method == "GET" and parts == ["healthz"]:
                return 200, {"status": "ok"}
            if method == "GET" and parts == ["readyz"]:
                with ctx.conn() as conn:
                    conn.execute("SELECT 1")
                return 200, {"status": "ready"}
            if method == "GET" and parts == ["version"]:
                return 200, {"version": __version__}
            if method == "GET" and parts == ["metrics"]:
                with ctx.conn() as conn:
                    stats = hub_stats(conn)
                return 200, TextResponse(_metrics_text(stats))

            if parts[:1] != ["v1"]:
                raise HubError(404, "not found")
            tail = parts[1:]

            if method == "POST" and tail == ["machines", "enroll"]:
                # No bearer auth: the enroll token itself is the credential.
                body = self._json()
                token = str(body.get("enroll_token") or "")
                if not token:
                    raise HubError(401, "enroll_token is required")
                with ctx.conn() as conn:
                    result = redeem_enroll_token(
                        conn,
                        token=token,
                        tags=parse_tags(_as_str_list(body.get("tags"))),
                        agent_version=_opt_str(body.get("agent_version")),
                    )
                    conn.commit()
                return 200, result

            if method == "POST" and tail == ["machines", "heartbeat"]:
                if self._is_ops():
                    raise HubError(403, "machine token required")
                machine = self._machine()
                body = self._json()
                machine_id = str(body.get("machine_id") or "")
                if not machine_id:
                    raise HubError(400, "machine_id is required")
                if machine is not None and machine["id"] != machine_id:
                    raise HubError(403, "token belongs to a different machine")
                token = self._bearer()
                with ctx.conn() as conn:
                    heartbeat(
                        conn,
                        machine_id=machine_id,
                        token=token,
                        tags=parse_tags(_as_str_list(body.get("tags"))),
                        status=str(body.get("status") or "idle"),
                        agent_version=_opt_str(body.get("agent_version")),
                        running_assignment_id=_opt_str(body.get("running_assignment_id")),
                    )
                    conn.commit()
                return 204, None

            if method == "POST" and tail == ["assignments", "claim"]:
                machine = self._require_machine()
                with ctx.conn() as conn:
                    claimed = claim(conn, machine_id=machine["id"])
                    conn.commit()
                if claimed is None:
                    return 204, None
                return 200, assignment_public(claimed)

            if method == "POST" and len(tail) == 3 and tail[0] == "assignments":
                assignment_id, action = tail[1], tail[2]
                machine = self._require_machine()
                if action == "renew":
                    body = self._json()
                    with ctx.conn() as conn:
                        row = renew(
                            conn,
                            assignment_id=assignment_id,
                            machine_id=machine["id"],
                            attempt_id=str(body.get("attempt_id") or ""),
                        )
                        conn.commit()
                    return 200, assignment_public(row)
                if action == "complete":
                    body = self._json()
                    with ctx.conn() as conn:
                        row = complete(
                            conn,
                            assignment_id=assignment_id,
                            machine_id=machine["id"],
                            attempt_id=str(body.get("attempt_id") or ""),
                            status=str(body.get("status") or ""),
                            run_id=_opt_str(body.get("run_id")),
                            exit_code=_opt_int(body.get("exit_code")),
                            summary=_opt_dict(body.get("summary")),
                            fail=_opt_dict(body.get("fail")),
                            log_tail=_opt_str(body.get("log_tail")),
                        )
                        conn.commit()
                    if row["status"] == STATUS_FAILED and ctx.webhook_url:
                        _notify_fail(ctx.webhook_url, assignment_public(row))
                    return 200, assignment_public(row)
                if action == "evidence":
                    payload = self._raw()
                    attempt_id = query.get("attempt_id") or ""
                    if method == "POST":
                        with ctx.conn() as conn:
                            row = put_evidence(
                                conn,
                                data_dir=ctx.data_dir,
                                assignment_id=assignment_id,
                                attempt_id=attempt_id,
                                machine_id=machine["id"],
                                payload=payload,
                            )
                            conn.commit()
                        return 200, evidence_index(row)
                    raise HubError(404, "not found")
                raise HubError(404, "not found")

            if (
                method == "GET"
                and len(tail) == 3
                and tail[0] == "assignments"
                and tail[2] == "evidence"
            ):
                self._require_ops()
                with ctx.conn() as conn:
                    _attempt, payload = get_evidence_bytes(
                        conn,
                        data_dir=ctx.data_dir,
                        assignment_id=tail[1],
                        attempt_id=_opt_str(query.get("attempt_id")),
                    )
                return 200, payload

            if method == "POST" and tail == ["assignments"]:
                self._require_ops()
                body = self._json()
                release = body.get("release")
                if not isinstance(release, dict):
                    raise HubError(400, "release object is required")
                with ctx.conn() as conn:
                    row = enqueue(
                        conn,
                        name=_opt_str(release.get("name")),
                        version=_opt_str(release.get("version")),
                        content_hash=_opt_str(release.get("content_hash")),
                        blob_url=_opt_str(release.get("blob_url")),
                        size_bytes=_opt_int(release.get("size_bytes")),
                        inputs=_str_dict(body.get("inputs")),
                        secret_names=parse_tags(_as_str_list(body.get("secret_names"))),
                        required_tags=parse_tags(_as_str_list(body.get("required_tags"))),
                        lease_seconds=int(body.get("lease_seconds") or 900),
                        assignment_id=_opt_str(body.get("id")),
                        batch_id=_opt_str(body.get("batch_id")),
                    )
                    conn.commit()
                return 200, assignment_public(row)

            if method == "POST" and tail == ["schedules"]:
                self._require_ops()
                body = self._json()
                release = body.get("release")
                if not isinstance(release, dict):
                    raise HubError(400, "release object is required")
                name = str(body.get("name") or "")
                inputs = _str_dict(body.get("inputs"))
                with ctx.conn() as conn:
                    validate_schedule_template(
                        conn,
                        data_dir=Path(ctx.data_dir),
                        release_name=str(release.get("name") or ""),
                        release_version=str(release.get("version") or "0.0.0"),
                        inputs=inputs,
                    )
                    row = create_schedule(
                        conn,
                        name=name,
                        release_name=str(release.get("name") or ""),
                        release_version=str(release.get("version") or "0.0.0"),
                        inputs=inputs,
                        secret_names=parse_tags(_as_str_list(body.get("secret_names"))),
                        required_tags=parse_tags(_as_str_list(body.get("required_tags"))),
                        lease_seconds=int(body.get("lease_seconds") or 900),
                        interval_seconds=_opt_int(body.get("interval_seconds")),
                        daily_utc=_opt_str(body.get("daily_utc")),
                    )
                    conn.commit()
                return 200, schedule_public(row)

            if method == "GET" and tail == ["schedules"]:
                self._require_ops()
                with ctx.conn() as conn:
                    rows = [schedule_public(s) for s in list_schedules(conn)]
                return 200, rows

            if method == "POST" and tail == ["releases"]:
                self._require_ops()
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype == "application/zip":
                    payload = self._raw()
                    with ctx.conn() as conn:
                        row = register_zip(
                            conn,
                            data_dir=ctx.data_dir,
                            payload=payload,
                            name=_opt_str(self.headers.get("X-Coreme-Name")),
                            version=_opt_str(self.headers.get("X-Coreme-Version")),
                        )
                        conn.commit()
                    return 200, release_public(row)
                body = self._json()
                with ctx.conn() as conn:
                    row = upsert_release(
                        conn,
                        content_hash=str(body.get("content_hash") or ""),
                        name=str(body.get("name") or ""),
                        version=str(body.get("version") or "0.0.0"),
                        blob_url=str(body.get("blob_url") or ""),
                        size_bytes=int(body.get("size_bytes") or 0),
                        file_count=_opt_int(body.get("file_count")),
                    )
                    conn.commit()
                return 200, release_public(row)

            if method == "GET" and len(tail) == 3 and tail[0] == "releases" and tail[2] == "blob":
                self._require_machine_or_ops()
                digest = parse_hash(tail[1])
                return 200, read_blob(ctx.data_dir, digest)

            if method == "GET" and tail == ["machines"]:
                self._require_ops()
                with ctx.conn() as conn:
                    rows = [machine_public(m) for m in list_machines(conn)]
                return 200, rows

            if method == "GET" and tail == ["assignments"]:
                self._require_ops()
                with ctx.conn() as conn:
                    rows = [
                        assignment_public(a)
                        for a in list_assignments(
                            conn,
                            status=_opt_str(query.get("status")),
                            limit=int(query.get("limit") or 50),
                        )
                    ]
                return 200, rows

            if method == "GET" and len(tail) == 2 and tail[0] == "assignments":
                self._require_ops()
                with ctx.conn() as conn:
                    found = get_assignment(conn, tail[1])
                    ev = latest_evidence(conn, tail[1]) if found is not None else None
                if found is None:
                    raise HubError(404, "unknown assignment")
                return 200, assignment_public(found, evidence=ev)

            raise HubError(404, "not found")

        def _raw(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length > ctx.max_body:
                raise HubError(413, "request body too large")
            return self.rfile.read(length) if length else b""

        def _json(self) -> dict[str, Any]:
            raw = self._raw()
            if not raw:
                return {}
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise HubError(400, "json object required")
            return payload

        def _bearer(self) -> str:
            header = self.headers.get("Authorization") or ""
            if not header.startswith("Bearer "):
                raise HubError(401, "bearer token required")
            token = header.removeprefix("Bearer ").strip()
            if not token:
                raise HubError(401, "bearer token required")
            return token

        def _is_ops(self) -> bool:
            token = self._bearer()
            return hmac.compare_digest(token, ctx.ops_token)

        def _require_ops(self) -> None:
            if not self._is_ops():
                raise HubError(403, "ops token required")

        def _machine(self) -> dict[str, Any] | None:
            token = self._bearer()
            if token == ctx.ops_token:
                return None
            with ctx.conn() as conn:
                return _machine_by_token(conn, token)

        def _require_machine(self) -> dict[str, Any]:
            token = self._bearer()
            if token == ctx.ops_token:
                raise HubError(403, "machine token required")
            with ctx.conn() as conn:
                row = _machine_by_token(conn, token)
            if row is None:
                raise HubError(401, "unknown machine token")
            return row

        def _require_machine_or_ops(self) -> None:
            if self._is_ops():
                return
            if self._machine() is None:
                raise HubError(401, "unknown machine token")

        def _send(self, status: int, body: object) -> None:
            if body is None:
                self.send_response(status)
                self.end_headers()
                return
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, status: int, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_text(self, status: int, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _metrics_text(stats: dict[str, Any]) -> bytes:
    lines = [
        f"coreme_machines_total {stats['machines_total']}",
        f"coreme_machines_online {stats['machines_online']}",
        f"coreme_machines_drained {stats['machines_drained']}",
    ]
    for status in ("pending", "claimed", "succeeded", "failed", "error", "timeout"):
        count = stats["assignments_by_status"].get(status, 0)
        lines.append(f'coreme_assignments{{status="{status}"}} {count}')
    lines.append(f"coreme_attempts_failed_total {stats['attempts_failed']}")
    lines.append(f"coreme_attempts_succeeded_total {stats['attempts_succeeded']}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _notify_fail(url: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget webhook; notifications never break the run path."""

    def post() -> None:
        try:
            data = json.dumps({"event": "assignment.failed", "assignment": payload}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            return

    threading.Thread(target=post, daemon=True).start()


def _ticker(ctx: HubContext, tick_seconds: float) -> None:
    while True:
        time.sleep(tick_seconds)
        try:
            with ctx.conn() as conn:
                fired = fire_due_schedules(conn)
                conn.commit()
            for item in fired:
                if item.get("skipped"):
                    print(f"schedule={item['schedule']} skipped={item['skipped']}")
                else:
                    print(f"schedule={item['schedule']} assignment_id={item['assignment_id']}")
        except Exception as exc:
            print(f"ticker error: {exc}")


def serve(
    dsn: str,
    *,
    bind: str = "127.0.0.1:8787",
    ops_token: str | None = None,
    schema: str = "public",
    data_dir: str | Path | None = None,
    tick_seconds: float | None = None,
) -> ThreadingHTTPServer:
    token = ops_token or os.environ.get("COREME_HUB_OPS_TOKEN") or ""
    ctx = HubContext(dsn, token, schema=schema, data_dir=data_dir)
    host, port = parse_bind(bind)
    httpd = ThreadingHTTPServer((host, port), make_handler(ctx))
    if tick_seconds is None:
        tick_seconds = float(os.environ.get("COREME_HUB_TICK_SECONDS") or 30)
    if tick_seconds > 0:
        threading.Thread(target=_ticker, args=(ctx, tick_seconds), daemon=True).start()
    return httpd


def _machine_by_token(conn: Any, token: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT * FROM machines WHERE token_hash = %s",
        (hash_token(token),),
    ).fetchone()


def _as_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    raise HubError(400, "expected a string list")


def _str_dict(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    raise HubError(400, "expected an object")


def _opt_str(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _opt_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.lstrip("-").isdigit():
            return int(value)
        raise HubError(400, "expected an int")
    return value


def _opt_dict(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    raise HubError(400, "expected an object")

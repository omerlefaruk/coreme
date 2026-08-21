"""Machines, assignments, attempts. Claim uses FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from psycopg import Connection
from psycopg.types.json import Jsonb

from coreme.manifest import ManifestError, load_manifest
from coreme.release import ReleaseError, tree_hash
from coreme.ship import verify_release
from coreme_hub.blobs import (
    parse_hash,
    read_blob,
    read_evidence_zip,
    remove_tree,
    sha256_bytes,
    unzip_tree,
    write_blob,
    write_evidence_zip,
    zip_tree,
)
from coreme_hub.db import DEFAULT_LEASE_SECONDS, StoreError, hash_token

STATUS_PENDING = "pending"
STATUS_CLAIMED = "claimed"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_LEASE_LOST = "lease-lost"

COMPLETE_OK = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_ERROR, STATUS_TIMEOUT})
COMPLETE_ALIASES = {
    "success": STATUS_SUCCEEDED,
    "fail": STATUS_FAILED,
}


def heartbeat(
    conn: Connection[dict[str, Any]],
    *,
    machine_id: str,
    token: str,
    tags: list[str],
    status: str = "idle",
    agent_version: str | None = None,
    running_assignment_id: str | None = None,
) -> dict[str, Any]:
    token_hash = hash_token(token)
    row = conn.execute(
        """
        INSERT INTO machines (
            id, token_hash, tags, status, agent_version,
            last_heartbeat, running_assignment_id
        )
        VALUES (%s, %s, %s, %s, %s, now(), %s)
        ON CONFLICT (id) DO UPDATE
           SET tags = EXCLUDED.tags,
               status = EXCLUDED.status,
               agent_version = EXCLUDED.agent_version,
               last_heartbeat = now(),
               running_assignment_id = EXCLUDED.running_assignment_id
         WHERE machines.token_hash = EXCLUDED.token_hash
        RETURNING *
        """,
        (machine_id, token_hash, tags, status, agent_version, running_assignment_id),
    ).fetchone()
    if row is None:
        raise StoreError("forbidden", "machine token does not match")
    return row


def create_enroll_token(
    conn: Connection[dict[str, Any]],
    *,
    tags: list[str] | None = None,
    ttl_hours: float = 1.0,
) -> dict[str, Any]:
    """Mint a one-time enroll token. The plain token is returned exactly once."""
    if ttl_hours <= 0:
        raise StoreError("bad_request", "ttl_hours must be > 0")
    token = secrets.token_urlsafe(32)
    row = conn.execute(
        """
        INSERT INTO enroll_tokens (token_hash, tags, expires_at)
        VALUES (%s, %s, now() + make_interval(secs => %s))
        RETURNING *
        """,
        (hash_token(token), list(tags or []), ttl_hours * 3600),
    ).fetchone()
    assert row is not None
    return {**row, "token": token}


def redeem_enroll_token(
    conn: Connection[dict[str, Any]],
    *,
    token: str,
    tags: list[str] | None = None,
    agent_version: str | None = None,
) -> dict[str, Any]:
    """Exchange a valid unused token for machine credentials (one transaction).

    Creates the machine row with a fresh machine token and marks the token
    used. Unknown or expired tokens raise ``unauthorized``; reused raise
    ``conflict``.
    """
    row = conn.execute(
        "SELECT * FROM enroll_tokens WHERE token_hash = %s FOR UPDATE",
        (hash_token(token),),
    ).fetchone()
    if row is None:
        raise StoreError("unauthorized", "unknown enroll token")
    if row["used_at"] is not None:
        raise StoreError("conflict", "enroll token already used")
    expires_at = row["expires_at"]
    if isinstance(expires_at, datetime) and expires_at <= datetime.now(UTC):
        raise StoreError("unauthorized", "enroll token expired")
    machine_id = str(uuid.uuid4())
    machine_token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO machines (id, token_hash, tags, status, agent_version, last_heartbeat)
        VALUES (%s, %s, %s, 'idle', %s, now())
        """,
        (
            machine_id,
            hash_token(machine_token),
            list(tags) if tags else list(row["tags"] or []),
            agent_version,
        ),
    )
    conn.execute(
        "UPDATE enroll_tokens SET used_at = now(), used_by = %s WHERE id = %s",
        (machine_id, row["id"]),
    )
    return {
        "machine_id": machine_id,
        "machine_token": machine_token,
        "tags": list(tags) if tags else list(row["tags"] or []),
    }


def list_enroll_tokens(conn: Connection[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(conn.execute("SELECT * FROM enroll_tokens ORDER BY expires_at").fetchall())


def revoke_enroll_token(conn: Connection[dict[str, Any]], token_id: str) -> dict[str, Any]:
    try:
        ident = uuid.UUID(str(token_id))
    except ValueError as exc:
        raise StoreError("bad_request", f"invalid enroll token id {token_id!r}") from exc
    row = conn.execute(
        "DELETE FROM enroll_tokens WHERE id = %s RETURNING *",
        (ident,),
    ).fetchone()
    if row is None:
        raise StoreError("not_found", "unknown enroll token")
    return row


def enroll_token_public(row: dict[str, Any]) -> dict[str, Any]:
    """JSON body for CLI listing (never the plain token)."""
    used_by = row.get("used_by")
    return {
        "id": str(row["id"]),
        "tags": list(row["tags"] or []),
        "expires_at": _iso(row.get("expires_at")),
        "used_at": _iso(row.get("used_at")),
        "used_by": str(used_by) if used_by else None,
    }


def create_assignment(
    conn: Connection[dict[str, Any]],
    *,
    release_name: str,
    release_version: str,
    content_hash: str,
    blob_url: str,
    size_bytes: int | None = None,
    inputs: dict[str, str] | None = None,
    secret_names: list[str] | None = None,
    required_tags: list[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    assignment_id: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    if lease_seconds < 1:
        raise StoreError("bad_request", "lease_seconds must be >= 1")
    digest = parse_hash(content_hash)
    url = (blob_url or "").strip()
    if not url:
        raise StoreError("bad_request", "blob_url is required")
    if not (release_name or "").strip():
        raise StoreError("bad_request", "release.name is required")
    row = conn.execute(
        """
        INSERT INTO assignments (
            id, batch_id, release_name, release_version, content_hash,
            blob_url, size_bytes, release_path, inputs, secret_names,
            required_tags, lease_seconds, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            assignment_id or str(uuid.uuid4()),
            batch_id,
            release_name.strip(),
            release_version,
            digest,
            url,
            size_bytes,
            None,
            Jsonb(inputs or {}),
            secret_names or [],
            required_tags or [],
            lease_seconds,
            STATUS_PENDING,
        ),
    ).fetchone()
    assert row is not None
    return row


def enqueue(
    conn: Connection[dict[str, Any]],
    *,
    name: str | None = None,
    version: str | None = None,
    content_hash: str | None = None,
    blob_url: str | None = None,
    size_bytes: int | None = None,
    inputs: dict[str, str] | None = None,
    secret_names: list[str] | None = None,
    required_tags: list[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    assignment_id: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    spec = resolve_release_spec(
        conn,
        name=name,
        version=version,
        content_hash=content_hash,
        blob_url=blob_url,
        size_bytes=size_bytes,
    )
    if not spec.get("name"):
        raise StoreError("bad_request", "release.name is required")
    return create_assignment(
        conn,
        release_name=str(spec["name"]),
        release_version=str(spec.get("version") or "0.0.0"),
        content_hash=str(spec["content_hash"]),
        blob_url=str(spec["blob_url"]),
        size_bytes=spec.get("size_bytes") if isinstance(spec.get("size_bytes"), int) else None,
        inputs=inputs,
        secret_names=secret_names,
        required_tags=required_tags,
        lease_seconds=lease_seconds,
        assignment_id=assignment_id,
        batch_id=batch_id,
    )


def claim(
    conn: Connection[dict[str, Any]],
    *,
    machine_id: str,
) -> dict[str, Any] | None:
    machine = conn.execute(
        "SELECT * FROM machines WHERE id = %s",
        (machine_id,),
    ).fetchone()
    if machine is None:
        raise StoreError("forbidden", "unknown machine; heartbeat first")
    if machine["drained"]:
        return None
    tags = list(machine["tags"] or [])
    picked = conn.execute(
        """
        WITH picked AS (
            SELECT a.id
              FROM assignments a
             WHERE (
                    a.status = %s
                    OR (a.status = %s AND a.lease_until < now())
                   )
               AND a.required_tags <@ %s
             ORDER BY a.created_at
               FOR UPDATE OF a SKIP LOCKED
             LIMIT 1
        )
        UPDATE assignments AS u
           SET status = %s,
               claimed_by = %s,
               claimed_at = now(),
               finished_at = NULL,
               lease_until = now() + make_interval(secs => u.lease_seconds),
               attempt_id = %s,
               run_id = NULL,
               exit_code = NULL,
               summary = NULL,
               fail = NULL,
               log_tail = NULL
          FROM picked
         WHERE u.id = picked.id
        RETURNING u.*
        """,
        (
            STATUS_PENDING,
            STATUS_CLAIMED,
            tags,
            STATUS_CLAIMED,
            machine_id,
            str(uuid.uuid4()),
        ),
    ).fetchone()
    if picked is None:
        return None
    conn.execute(
        """
        UPDATE attempts
           SET status = %s,
               finished_at = now()
         WHERE assignment_id = %s
           AND status = 'running'
        """,
        (STATUS_LEASE_LOST, picked["id"]),
    )
    attempt_id = picked["attempt_id"]
    conn.execute(
        """
        INSERT INTO attempts (id, assignment_id, machine_id, status)
        VALUES (%s, %s, %s, 'running')
        """,
        (attempt_id, picked["id"], machine_id),
    )
    conn.execute(
        """
        UPDATE machines
           SET running_assignment_id = %s,
               status = 'busy',
               last_heartbeat = now()
         WHERE id = %s
        """,
        (picked["id"], machine_id),
    )
    return picked


def renew(
    conn: Connection[dict[str, Any]],
    *,
    assignment_id: str,
    machine_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    fence = _require_attempt_id(attempt_id)
    row = conn.execute(
        """
        UPDATE assignments
           SET lease_until = now() + make_interval(secs => lease_seconds)
         WHERE id = %s
           AND status = %s
           AND claimed_by = %s
           AND attempt_id = %s
        RETURNING *
        """,
        (assignment_id, STATUS_CLAIMED, machine_id, fence),
    ).fetchone()
    if row is None:
        _raise_fence_miss(conn, assignment_id)
    return row


def complete(
    conn: Connection[dict[str, Any]],
    *,
    assignment_id: str,
    machine_id: str,
    attempt_id: str,
    status: str,
    run_id: str | None = None,
    exit_code: int | None = None,
    summary: dict[str, Any] | None = None,
    fail: dict[str, Any] | None = None,
    log_tail: str | None = None,
) -> dict[str, Any]:
    status = COMPLETE_ALIASES.get(status, status)
    if status not in COMPLETE_OK:
        raise StoreError("bad_request", f"invalid complete status {status!r}")
    fence = _require_attempt_id(attempt_id)
    row = conn.execute(
        """
        UPDATE assignments
           SET status = %s,
               finished_at = now(),
               lease_until = NULL,
               run_id = %s,
               exit_code = %s,
               summary = %s,
               fail = %s,
               log_tail = %s
         WHERE id = %s
           AND status = %s
           AND claimed_by = %s
           AND attempt_id = %s
        RETURNING *
        """,
        (
            status,
            run_id,
            exit_code,
            Jsonb(summary) if summary is not None else None,
            Jsonb(fail) if fail is not None else None,
            log_tail,
            assignment_id,
            STATUS_CLAIMED,
            machine_id,
            fence,
        ),
    ).fetchone()
    if row is None:
        _raise_fence_miss(conn, assignment_id)
    conn.execute(
        """
        UPDATE attempts
           SET status = %s,
               finished_at = now(),
               run_id = %s,
               exit_code = %s,
               summary = %s,
               fail = %s,
               log_tail = %s
         WHERE id = %s
        """,
        (
            status,
            run_id,
            exit_code,
            Jsonb(summary) if summary is not None else None,
            Jsonb(fail) if fail is not None else None,
            log_tail,
            row["attempt_id"],
        ),
    )
    conn.execute(
        """
        UPDATE machines
           SET running_assignment_id = NULL,
               status = 'idle',
               last_heartbeat = now()
         WHERE id = %s
        """,
        (machine_id,),
    )
    return row


def register_tree(
    conn: Connection[dict[str, Any]],
    *,
    data_dir: str | Path,
    source: str | Path,
    name: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    root = Path(source)
    if not root.is_dir():
        raise StoreError("bad_request", f"release path is not a directory: {root}")
    recorded: str | None = None
    if (root / "RELEASE.json").is_file():
        try:
            recorded = verify_release(root)
        except ReleaseError as exc:
            raise StoreError("bad_request", f"release verify failed: {exc}") from exc
    try:
        content_hash, file_count = tree_hash(root)
    except ReleaseError as exc:
        raise StoreError("bad_request", f"cannot hash release: {exc}") from exc
    if recorded is not None and recorded != content_hash:
        raise StoreError("bad_request", "RELEASE.json hash does not match tree")
    rel_name, rel_version = _identity(root, name, version)
    payload = zip_tree(root)
    write_blob(data_dir, content_hash, payload)
    blob_url = f"/v1/releases/{parse_hash(content_hash).removeprefix('sha256:')}/blob"
    return upsert_release(
        conn,
        content_hash=content_hash,
        name=rel_name,
        version=rel_version,
        blob_url=blob_url,
        size_bytes=len(payload),
        file_count=file_count,
    )


def register_zip(
    conn: Connection[dict[str, Any]],
    *,
    data_dir: str | Path,
    payload: bytes,
    name: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    if not payload:
        raise StoreError("bad_request", "release zip is empty")
    tmp = Path(tempfile.mkdtemp(prefix="coreme-hub-rel-"))
    try:
        unzip_tree(payload, tmp)
        return register_tree(conn, data_dir=data_dir, source=tmp, name=name, version=version)
    finally:
        remove_tree(tmp)


def upsert_release(
    conn: Connection[dict[str, Any]],
    *,
    content_hash: str,
    name: str,
    version: str,
    blob_url: str,
    size_bytes: int,
    file_count: int | None = None,
) -> dict[str, Any]:
    digest = parse_hash(content_hash)
    if not (name or "").strip():
        raise StoreError("bad_request", "release.name is required")
    if size_bytes < 0:
        raise StoreError("bad_request", "size_bytes must be >= 0")
    if not blob_url.strip():
        raise StoreError("bad_request", "blob_url is required")
    existing_hash = conn.execute(
        "SELECT * FROM releases WHERE name = %s AND version = %s",
        (name, version),
    ).fetchone()
    if existing_hash is not None and existing_hash["content_hash"] != digest:
        raise StoreError(
            "conflict", "release name+version already registered with a different hash"
        )
    same = conn.execute(
        "SELECT * FROM releases WHERE content_hash = %s",
        (digest,),
    ).fetchone()
    if same is not None:
        if same["name"] != name or same["version"] != version:
            raise StoreError("conflict", "content_hash already registered under a different name")
        return same
    row = conn.execute(
        """
        INSERT INTO releases (
            content_hash, name, version, blob_url, size_bytes, file_count
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (digest, name, version, blob_url.strip(), size_bytes, file_count),
    ).fetchone()
    assert row is not None
    return row


def _get_release(conn: Connection[dict[str, Any]], content_hash: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT * FROM releases WHERE content_hash = %s",
        (parse_hash(content_hash),),
    ).fetchone()


def _get_release_by_name(
    conn: Connection[dict[str, Any]],
    name: str,
    version: str,
) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT * FROM releases WHERE name = %s AND version = %s",
        (name, version),
    ).fetchone()


def resolve_release_spec(
    conn: Connection[dict[str, Any]],
    *,
    name: str | None,
    version: str | None,
    content_hash: str | None,
    blob_url: str | None,
    size_bytes: int | None,
) -> dict[str, Any]:
    if content_hash and blob_url:
        digest = parse_hash(content_hash)
        catalog = _get_release(conn, digest)
        return {
            "name": (name or (catalog["name"] if catalog else "") or "").strip(),
            "version": version or (catalog["version"] if catalog else "0.0.0"),
            "content_hash": digest,
            "blob_url": blob_url,
            "size_bytes": size_bytes
            if size_bytes is not None
            else (catalog["size_bytes"] if catalog else None),
        }
    catalog = None
    if content_hash:
        catalog = _get_release(conn, content_hash)
    elif name:
        catalog = _get_release_by_name(conn, name, version or "0.0.0")
    if catalog is None:
        raise StoreError("not_found", "unknown release; register it first")
    return dict(catalog)


def put_evidence(
    conn: Connection[dict[str, Any]],
    *,
    data_dir: str | Path,
    assignment_id: str,
    attempt_id: str,
    machine_id: str,
    payload: bytes,
) -> dict[str, Any]:
    if not payload:
        raise StoreError("bad_request", "evidence zip is empty")
    fence = _require_attempt_id(attempt_id)
    live = conn.execute(
        """
        SELECT id FROM assignments
         WHERE id = %s
           AND claimed_by = %s
           AND attempt_id = %s
        """,
        (assignment_id, machine_id, fence),
    ).fetchone()
    if live is None:
        _raise_fence_miss(conn, assignment_id)
    attempt = conn.execute(
        "SELECT * FROM attempts WHERE id = %s",
        (fence,),
    ).fetchone()
    if attempt is None:
        raise StoreError("not_found", "unknown attempt")
    digest = sha256_bytes(payload)
    write_evidence_zip(data_dir, assignment_id, fence, payload)
    row = conn.execute(
        """
        UPDATE attempts
           SET evidence_bytes = %s,
               evidence_sha256 = %s
         WHERE id = %s
        RETURNING *
        """,
        (len(payload), digest, fence),
    ).fetchone()
    assert row is not None
    return row


def get_evidence_bytes(
    conn: Connection[dict[str, Any]],
    *,
    data_dir: str | Path,
    assignment_id: str,
    attempt_id: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    if attempt_id:
        attempt = conn.execute(
            "SELECT * FROM attempts WHERE id = %s AND assignment_id = %s",
            (attempt_id, assignment_id),
        ).fetchone()
    else:
        attempt = conn.execute(
            """
            SELECT * FROM attempts
             WHERE assignment_id = %s
               AND evidence_bytes IS NOT NULL
             ORDER BY started_at DESC
             LIMIT 1
            """,
            (assignment_id,),
        ).fetchone()
    if attempt is None or attempt.get("evidence_bytes") is None:
        raise StoreError("not_found", "evidence not found")
    payload = read_evidence_zip(data_dir, assignment_id, str(attempt["id"]))
    return attempt, payload


def latest_evidence(conn: Connection[dict[str, Any]], assignment_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM attempts
         WHERE assignment_id = %s
           AND evidence_bytes IS NOT NULL
         ORDER BY started_at DESC
         LIMIT 1
        """,
        (assignment_id,),
    ).fetchone()
    if row is None:
        return None
    return evidence_index(row)


def get_assignment(conn: Connection[dict[str, Any]], assignment_id: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT * FROM assignments WHERE id = %s",
        (assignment_id,),
    ).fetchone()


def list_assignments(
    conn: Connection[dict[str, Any]],
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            """
            SELECT * FROM assignments
             WHERE status = %s
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM assignments
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return list(rows)


def list_attempts(conn: Connection[dict[str, Any]], assignment_id: str) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            """
            SELECT * FROM attempts
             WHERE assignment_id = %s
             ORDER BY started_at
            """,
            (assignment_id,),
        ).fetchall()
    )


def list_machines(conn: Connection[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(conn.execute("SELECT * FROM machines ORDER BY id").fetchall())


def _require_attempt_id(attempt_id: str | None) -> str:
    value = (attempt_id or "").strip()
    if not value:
        raise StoreError("bad_request", "attempt_id is required")
    return value


def _raise_fence_miss(conn: Connection[dict[str, Any]], assignment_id: str) -> NoReturn:
    existing = conn.execute(
        "SELECT id, status, claimed_by FROM assignments WHERE id = %s",
        (assignment_id,),
    ).fetchone()
    if existing is None:
        raise StoreError("not_found", "unknown assignment")
    raise StoreError("conflict", "assignment is not claimed by this attempt")


def assignment_public(
    row: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON body for claim / complete (no secret values)."""
    index = evidence if evidence is not None else evidence_index(row)
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "release": {
            "name": row["release_name"],
            "version": row["release_version"],
            "content_hash": row["content_hash"],
            "blob_url": row["blob_url"],
            "size_bytes": row.get("size_bytes"),
        },
        "inputs": row["inputs"] or {},
        "secret_names": list(row["secret_names"] or []),
        "required_tags": list(row["required_tags"] or []),
        "lease_seconds": row["lease_seconds"],
        "status": row["status"],
        "claimed_by": row["claimed_by"],
        "lease_until": _iso(row.get("lease_until")),
        "attempt_id": row["attempt_id"],
        "run_id": row.get("run_id"),
        "exit_code": row.get("exit_code"),
        "summary": row.get("summary"),
        "fail": row.get("fail"),
        "log_tail": row.get("log_tail"),
        "evidence": index,
        "created_at": _iso(row.get("created_at")),
        "finished_at": _iso(row.get("finished_at")),
    }


def evidence_index(row: dict[str, Any]) -> dict[str, Any] | None:
    size = row.get("evidence_bytes")
    digest = row.get("evidence_sha256")
    if size is None and not digest:
        return None
    return {
        "attempt_id": row.get("attempt_id") or row.get("id"),
        "size_bytes": size,
        "sha256": digest,
    }


def release_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "version": row["version"],
        "content_hash": row["content_hash"],
        "blob_url": row["blob_url"],
        "size_bytes": row["size_bytes"],
        "file_count": row.get("file_count"),
    }


def machine_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tags": list(row["tags"] or []),
        "status": row["status"],
        "agent_version": row["agent_version"],
        "last_heartbeat": _iso(row.get("last_heartbeat")),
        "running_assignment_id": row["running_assignment_id"],
        "drained": bool(row.get("drained")),
    }


def set_machine_drained(
    conn: Connection[dict[str, Any]],
    *,
    machine_id: str,
    drained: bool,
) -> dict[str, Any] | None:
    row = conn.execute(
        "UPDATE machines SET drained = %s WHERE id = %s RETURNING *",
        (drained, machine_id),
    ).fetchone()
    return row


def create_schedule(
    conn: Connection[dict[str, Any]],
    *,
    name: str,
    release_name: str,
    release_version: str = "0.0.0",
    inputs: dict[str, str] | None = None,
    secret_names: list[str] | None = None,
    required_tags: list[str] | None = None,
    lease_seconds: int = 900,
    interval_seconds: int | None = None,
    daily_utc: str | None = None,
) -> dict[str, Any]:
    """Create a schedule. Timing is interval_seconds OR daily_utc (HH:MM UTC)."""
    if not name:
        raise StoreError("bad_request", "schedule name is required")
    if interval_seconds is None and daily_utc is None:
        raise StoreError("bad_request", "schedule needs --interval-sec or --daily-utc")
    if interval_seconds is not None and interval_seconds <= 0:
        raise StoreError("bad_request", "interval_seconds must be > 0")
    if daily_utc is not None and not re.fullmatch(r"\d{2}:\d{2}", daily_utc):
        raise StoreError("bad_request", "daily_utc must be HH:MM")
    row = conn.execute(
        """
        INSERT INTO schedules (name, release_name, release_version, inputs,
                               secret_names, required_tags, lease_seconds,
                               interval_seconds, daily_utc)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            name,
            release_name,
            release_version,
            json.dumps(inputs or {}),
            list(secret_names or []),
            list(required_tags or []),
            lease_seconds,
            interval_seconds,
            daily_utc,
        ),
    ).fetchone()
    assert row is not None
    return row


def list_schedules(conn: Connection[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(conn.execute("SELECT * FROM schedules ORDER BY name").fetchall())


def get_schedule(conn: Connection[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return conn.execute("SELECT * FROM schedules WHERE name = %s", (name,)).fetchone()


def set_schedule_enabled(
    conn: Connection[dict[str, Any]], *, name: str, enabled: bool
) -> dict[str, Any] | None:
    return conn.execute(
        "UPDATE schedules SET enabled = %s WHERE name = %s RETURNING *",
        (enabled, name),
    ).fetchone()


def delete_schedule(conn: Connection[dict[str, Any]], *, name: str) -> dict[str, Any] | None:
    return conn.execute("DELETE FROM schedules WHERE name = %s RETURNING *", (name,)).fetchone()


def fire_due_schedules(conn: Connection[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create one Assignment per due schedule; advance next_run_at. Caller commits."""
    due = conn.execute(
        """
        SELECT * FROM schedules
         WHERE enabled AND next_run_at <= now()
         ORDER BY next_run_at
         FOR UPDATE SKIP LOCKED
        """
    ).fetchall()
    fired: list[dict[str, Any]] = []
    for schedule in due:
        batch_id = f"sched:{schedule['name']}:{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        skipped: str | None = None
        try:
            row = enqueue(
                conn,
                name=str(schedule["release_name"]),
                version=str(schedule["release_version"]),
                inputs={str(k): str(v) for k, v in (schedule["inputs"] or {}).items()},
                secret_names=list(schedule["secret_names"] or []),
                required_tags=list(schedule["required_tags"] or []),
                lease_seconds=int(schedule["lease_seconds"]),
                batch_id=batch_id,
            )
            assignment_id = str(row["id"])
        except StoreError as exc:
            # Missing release etc.: still advance so a broken schedule cannot
            # hot-loop; surface the skip to the caller.
            assignment_id = ""
            skipped = str(exc)
        _advance_schedule(conn, schedule)
        item: dict[str, Any] = {
            "schedule": str(schedule["name"]),
            "assignment_id": assignment_id,
            "batch_id": batch_id,
        }
        if skipped:
            item["skipped"] = skipped
        fired.append(item)
    return fired


def _advance_schedule(conn: Connection[dict[str, Any]], schedule: dict[str, Any]) -> None:
    base = datetime.now(UTC)
    interval = schedule["interval_seconds"]
    daily = schedule["daily_utc"]
    if interval is not None:
        next_run = base + timedelta(seconds=int(interval))
    elif daily is not None:
        hh, mm = str(daily).split(":")
        candidate = base.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if candidate <= base:
            candidate += timedelta(days=1)
        next_run = candidate
    else:
        next_run = base + timedelta(seconds=900)
    conn.execute(
        "UPDATE schedules SET next_run_at = %s WHERE id = %s",
        (next_run, schedule["id"]),
    )


def validate_schedule_template(
    conn: Connection[dict[str, Any]],
    *,
    data_dir: Path,
    release_name: str,
    release_version: str,
    inputs: dict[str, str],
) -> None:
    """Reject templates that could only produce failed Assignments.

    Reads the release manifest from its stored blob and mirrors the kernel's
    input rules: unknown keys are rejected; required inputs without defaults
    must be present.
    """
    spec = resolve_release_spec(
        conn,
        name=release_name,
        version=release_version or "0.0.0",
        content_hash=None,
        blob_url=None,
        size_bytes=None,
    )
    digest = parse_hash(str(spec["content_hash"]))
    blob = read_blob(Path(data_dir), digest)
    manifest = _manifest_from_blob(blob, str(spec["name"]))
    if manifest is None:
        return
    declared = set(manifest.inputs)
    unknown = sorted(set(inputs) - declared)
    if unknown:
        raise StoreError(
            "bad_request",
            f"unknown inputs for {spec['name']}: {', '.join(unknown)}",
        )
    missing = sorted(
        key
        for key, item in manifest.inputs.items()
        if key not in inputs and item.required and item.default is None
    )
    if missing:
        raise StoreError(
            "bad_request",
            f"missing required inputs for {spec['name']}: {', '.join(missing)}",
        )


def _manifest_from_blob(blob: bytes, name: str):
    """Load the manifest from a release blob; None when the Job has none."""
    with tempfile.TemporaryDirectory() as tmp:
        unzip_tree(blob, Path(tmp))
        try:
            return load_manifest(tmp)
        except ManifestError as exc:
            raise StoreError(
                "bad_request", f"release {name} has an invalid manifest: {exc}"
            ) from exc


def schedule_public(row: dict[str, Any]) -> dict[str, Any]:
    daily = row.get("daily_utc")
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "release": {"name": row["release_name"], "version": row["release_version"]},
        "inputs": row["inputs"] or {},
        "secret_names": list(row["secret_names"] or []),
        "required_tags": list(row["required_tags"] or []),
        "lease_seconds": row["lease_seconds"],
        "interval_seconds": row["interval_seconds"],
        "daily_utc": str(daily) if daily is not None else None,
        "enabled": bool(row["enabled"]),
        "next_run_at": _iso(row.get("next_run_at")),
    }


def hub_stats(conn: Connection[dict[str, Any]]) -> dict[str, Any]:
    machines = conn.execute(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE last_heartbeat > now() - interval '2 minutes') AS online,
               count(*) FILTER (WHERE drained) AS drained
          FROM machines
        """
    ).fetchone()
    by_status = conn.execute(
        "SELECT status, count(*) AS n FROM assignments GROUP BY status"
    ).fetchall()
    attempts = conn.execute(
        """
        SELECT count(*) FILTER (WHERE status = 'failed') AS failed,
               count(*) FILTER (WHERE status = 'succeeded') AS succeeded
          FROM attempts
        """
    ).fetchone()
    assert machines is not None and attempts is not None
    return {
        "machines_total": int(machines["total"]),
        "machines_online": int(machines["online"]),
        "machines_drained": int(machines["drained"]),
        "assignments_by_status": {str(r["status"]): int(r["n"]) for r in by_status},
        "attempts_failed": int(attempts["failed"]),
        "attempts_succeeded": int(attempts["succeeded"]),
    }


def prune_old(
    conn: Connection[dict[str, Any]],
    *,
    days: int,
    data_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Delete terminal assignments (and their attempts/evidence) older than days."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = conn.execute(
        """
        SELECT id FROM assignments
         WHERE finished_at IS NOT NULL AND finished_at < %s
        """,
        (cutoff,),
    ).fetchall()
    ids = [str(r["id"]) for r in rows]
    counts = {"assignments": len(ids), "attempts": 0}
    if not ids:
        return counts
    if dry_run:
        counted = conn.execute(
            "SELECT count(*) AS n FROM attempts WHERE assignment_id = ANY(%s)",
            (ids,),
        ).fetchone()
        assert counted is not None
        counts["attempts"] = int(counted["n"])
        return counts
    deleted = conn.execute(
        "WITH gone AS (DELETE FROM attempts WHERE assignment_id = ANY(%s) RETURNING 1) "
        "SELECT count(*) AS n FROM gone",
        (ids,),
    ).fetchone()
    assert deleted is not None
    counts["attempts"] = int(deleted["n"])
    removed = conn.execute(
        "WITH gone AS (DELETE FROM assignments WHERE id = ANY(%s) RETURNING 1) "
        "SELECT count(*) AS n FROM gone",
        (ids,),
    ).fetchone()
    assert removed is not None
    counts["assignments"] = int(removed["n"])
    if data_dir is not None:
        for assignment_id in ids:
            shutil.rmtree(Path(data_dir) / "evidence" / assignment_id, ignore_errors=True)
    return counts


def _identity(root: Path, name: str | None, version: str | None) -> tuple[str, str]:
    if name and version:
        return name, version
    try:
        manifest = load_manifest(root)
    except ManifestError as exc:
        if not name:
            raise StoreError("bad_request", f"cannot read JOB.toml: {exc}") from exc
        return name, version or "0.0.0"
    return name or manifest.name, version or manifest.version


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        text = value.isoformat()
        if text.endswith("+00:00"):
            return text.replace("+00:00", "Z")
        return text
    return str(value)

"""Postgres connection and hub schema (F2 claim + F3 catalog)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row

DEFAULT_LEASE_SECONDS = 900
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS machines (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    tags TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'idle',
    agent_version TEXT,
    last_heartbeat TIMESTAMPTZ,
    running_assignment_id TEXT,
    drained BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS releases (
    content_hash TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    blob_url TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    file_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_releases_name_version
    ON releases (name, version);

CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    release_name TEXT NOT NULL,
    release_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    blob_url TEXT NOT NULL,
    size_bytes BIGINT,
    release_path TEXT,
    inputs JSONB NOT NULL DEFAULT '{}',
    secret_names TEXT[] NOT NULL DEFAULT '{}',
    required_tags TEXT[] NOT NULL DEFAULT '{}',
    lease_seconds INTEGER NOT NULL DEFAULT 900,
    status TEXT NOT NULL,
    claimed_by TEXT REFERENCES machines(id),
    lease_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    attempt_id TEXT,
    run_id TEXT,
    exit_code INTEGER,
    summary JSONB,
    fail JSONB,
    log_tail TEXT
);

CREATE INDEX IF NOT EXISTS idx_assignments_claim
    ON assignments (created_at)
    WHERE status IN ('pending', 'claimed');

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL REFERENCES assignments(id),
    machine_id TEXT NOT NULL REFERENCES machines(id),
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    run_id TEXT,
    exit_code INTEGER,
    summary JSONB,
    fail JSONB,
    log_tail TEXT,
    evidence_bytes BIGINT,
    evidence_sha256 TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_assignment
    ON attempts (assignment_id);

CREATE TABLE IF NOT EXISTS enroll_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash TEXT UNIQUE NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    used_by UUID
);

CREATE TABLE IF NOT EXISTS schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    release_name TEXT NOT NULL,
    release_version TEXT NOT NULL DEFAULT '0.0.0',
    inputs JSONB NOT NULL DEFAULT '{}',
    secret_names TEXT[] NOT NULL DEFAULT '{}',
    required_tags TEXT[] NOT NULL DEFAULT '{}',
    lease_seconds INTEGER NOT NULL DEFAULT 900,
    interval_seconds INTEGER,
    daily_utc TIME,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

MIGRATE_ALTER_SQL = """
ALTER TABLE assignments ALTER COLUMN release_path DROP NOT NULL;
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS evidence_bytes BIGINT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS evidence_sha256 TEXT;
ALTER TABLE machines ADD COLUMN IF NOT EXISTS drained BOOLEAN NOT NULL DEFAULT FALSE;
"""


class StoreError(Exception):
    """Hub store error. HTTP status is mapped in the HTTP adapter."""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


STORE_STATUS = {
    "bad_request": 400,
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
}


class HubError(Exception):
    """HTTP adapter error with a status code."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_dsn(explicit: str | None = None) -> str:
    dsn = explicit or os.environ.get("COREME_HUB_DSN")
    if not dsn:
        raise HubError(500, "COREME_HUB_DSN or --dsn is required")
    return dsn


def connect(dsn: str, schema: str = "public") -> Connection[dict[str, Any]]:
    conn = cast(
        Connection[dict[str, Any]],
        psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5),
    )
    if schema != "public":
        ident = sql.Identifier(schema)
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
        conn.execute(sql.SQL("SET search_path TO {}").format(ident))
    return conn


class Pool:
    """Tiny thread-safe connection pool. Validates on checkout; grows on demand."""

    def __init__(self, dsn: str, schema: str = "public", max_size: int = 8) -> None:
        self._dsn = dsn
        self._schema = schema
        self._max = max(1, max_size)
        self._idle: queue.LifoQueue[Connection[dict[str, Any]] | None] = queue.LifoQueue()
        self._lock = threading.Lock()
        self._size = 0

    @contextmanager
    def connection(self) -> Iterator[Connection[dict[str, Any]]]:
        conn = self._checkout()
        try:
            yield conn
        except Exception:
            self._discard(conn)
            raise
        else:
            self._checkin(conn)

    def close(self) -> None:
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                return
            if conn is not None:
                conn.close()

    def _checkout(self) -> Connection[dict[str, Any]]:
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                with self._lock:
                    if self._size < self._max:
                        self._size += 1
                        return connect(self._dsn, self._schema)
                # At capacity: block for a returned connection.
                conn = self._idle.get()
            if conn is not None and self._alive(conn):
                return conn
            if conn is not None:
                self._drop(conn)

    def _checkin(self, conn: Connection[dict[str, Any]]) -> None:
        if conn.closed:
            self._drop(conn)
            return
        with contextlib.suppress(Exception):
            conn.rollback()
        self._idle.put(conn)

    def _discard(self, conn: Connection[dict[str, Any]]) -> None:
        with contextlib.suppress(Exception):
            conn.rollback()
        self._drop(conn)

    def _drop(self, conn: Connection[dict[str, Any]]) -> None:
        with contextlib.suppress(Exception):
            conn.close()
        with self._lock:
            self._size -= 1

    def _alive(self, conn: Connection[dict[str, Any]]) -> bool:
        try:
            conn.execute("SELECT 1")
            return not conn.closed
        except Exception:
            return False


def migrate(dsn: str, schema: str = "public") -> None:
    with connect(dsn, schema) as conn:
        conn.execute(SCHEMA_SQL)
        conn.execute(MIGRATE_ALTER_SQL)
        conn.commit()

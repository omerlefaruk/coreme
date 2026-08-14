"""Postgres connection and hub schema (F2 claim + F3 catalog)."""

from __future__ import annotations

import hashlib
import os
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
    running_assignment_id TEXT
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
"""

MIGRATE_ALTER_SQL = """
ALTER TABLE assignments ALTER COLUMN release_path DROP NOT NULL;
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS evidence_bytes BIGINT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS evidence_sha256 TEXT;
"""


class HubError(Exception):
    """Hub domain error with an HTTP status."""

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


def migrate(dsn: str, schema: str = "public") -> None:
    with connect(dsn, schema) as conn:
        conn.execute(SCHEMA_SQL)
        conn.execute(MIGRATE_ALTER_SQL)
        conn.commit()

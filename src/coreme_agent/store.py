"""SQLite local queue for Assignments and Attempts (F1)."""

from __future__ import annotations

import builtins
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# Assignment lifecycle for local queue
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"

TERMINAL = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_ERROR, STATUS_TIMEOUT})


@dataclass(frozen=True)
class Assignment:
    id: str
    release_path: str
    inputs: dict[str, str]
    status: str
    created_at: str
    claimed_at: str | None = None
    finished_at: str | None = None
    batch_id: str | None = None
    attempt_id: str | None = None
    run_path: str | None = None
    exit_code: int | None = None
    message: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL


@dataclass(frozen=True)
class Attempt:
    id: str
    assignment_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    exit_code: int | None = None
    run_path: str | None = None
    message: str | None = None


class LocalQueue:
    """File-backed SQLite queue next to the agent process."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> LocalQueue:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                release_path TEXT NOT NULL,
                inputs_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                finished_at TEXT,
                batch_id TEXT,
                attempt_id TEXT,
                run_path TEXT,
                exit_code INTEGER,
                message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_assignments_status
                ON assignments(status, created_at);

            CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY,
                assignment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                exit_code INTEGER,
                run_path TEXT,
                message TEXT,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id)
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_assignment
                ON attempts(assignment_id);
            """
        )

    def enqueue(
        self,
        release_path: str | Path,
        *,
        inputs: dict[str, str] | None = None,
        assignment_id: str | None = None,
        batch_id: str | None = None,
    ) -> Assignment:
        aid = assignment_id or str(uuid.uuid4())
        rel = str(Path(release_path).resolve())
        created = _utc_now()
        inputs = dict(inputs or {})
        try:
            self._conn.execute(
                """
                INSERT INTO assignments (
                    id, release_path, inputs_json, status, created_at, batch_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    aid,
                    rel,
                    json.dumps(inputs, ensure_ascii=False, sort_keys=True),
                    STATUS_PENDING,
                    created,
                    batch_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise QueueError(f"assignment id already exists: {aid}") from exc
        return Assignment(
            id=aid,
            release_path=rel,
            inputs=inputs,
            status=STATUS_PENDING,
            created_at=created,
            batch_id=batch_id,
        )

    def claim_next(self) -> Assignment | None:
        """Atomically claim the oldest pending assignment."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                """
                SELECT * FROM assignments
                WHERE status = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (STATUS_PENDING,),
            ).fetchone()
            if row is None:
                self._conn.execute("COMMIT")
                return None
            attempt_id = str(uuid.uuid4())
            now = _utc_now()
            self._conn.execute(
                """
                UPDATE assignments
                SET status = ?, claimed_at = ?, attempt_id = ?
                WHERE id = ? AND status = ?
                """,
                (STATUS_RUNNING, now, attempt_id, row["id"], STATUS_PENDING),
            )
            self._conn.execute(
                """
                INSERT INTO attempts (id, assignment_id, status, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (attempt_id, row["id"], STATUS_RUNNING, now),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(row["id"])

    def complete(
        self,
        assignment_id: str,
        *,
        status: str,
        exit_code: int | None = None,
        run_path: str | None = None,
        message: str | None = None,
    ) -> Assignment:
        if status not in TERMINAL:
            raise QueueError(f"complete status must be terminal, got {status!r}")
        now = _utc_now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT * FROM assignments WHERE id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                self._conn.execute("ROLLBACK")
                raise QueueError(f"unknown assignment: {assignment_id}")
            if row["status"] != STATUS_RUNNING:
                self._conn.execute("ROLLBACK")
                raise QueueError(f"assignment {assignment_id} is {row['status']}, not running")
            attempt_id = row["attempt_id"]
            self._conn.execute(
                """
                UPDATE assignments
                SET status = ?, finished_at = ?, run_path = ?,
                    exit_code = ?, message = ?
                WHERE id = ?
                """,
                (
                    status,
                    now,
                    run_path,
                    exit_code,
                    message,
                    assignment_id,
                ),
            )
            if attempt_id:
                self._conn.execute(
                    """
                    UPDATE attempts
                    SET status = ?, finished_at = ?, exit_code = ?,
                        run_path = ?, message = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        now,
                        exit_code,
                        run_path,
                        message,
                        attempt_id,
                    ),
                )
            self._conn.execute("COMMIT")
        except QueueError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(assignment_id)  # type: ignore[return-value]

    def get(self, assignment_id: str) -> Assignment | None:
        row = self._conn.execute(
            "SELECT * FROM assignments WHERE id = ?",
            (assignment_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_assignment(row)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Assignment]:
        if status:
            rows = self._conn.execute(
                """
                SELECT * FROM assignments
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM assignments
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_assignment(r) for r in rows]

    def attempts_for(self, assignment_id: str) -> builtins.list[Attempt]:
        rows = self._conn.execute(
            """
            SELECT * FROM attempts
            WHERE assignment_id = ?
            ORDER BY started_at ASC
            """,
            (assignment_id,),
        ).fetchall()
        return [_row_to_attempt(r) for r in rows]


class QueueError(Exception):
    """Local queue contract error."""


def _row_to_assignment(row: sqlite3.Row) -> Assignment:
    inputs: dict[str, str] = json.loads(row["inputs_json"] or "{}")
    return Assignment(
        id=row["id"],
        release_path=row["release_path"],
        inputs={str(k): str(v) for k, v in inputs.items()},
        status=row["status"],
        created_at=row["created_at"],
        claimed_at=row["claimed_at"],
        finished_at=row["finished_at"],
        batch_id=row["batch_id"],
        attempt_id=row["attempt_id"],
        run_path=row["run_path"],
        exit_code=row["exit_code"],
        message=row["message"],
    )


def _row_to_attempt(row: sqlite3.Row) -> Attempt:
    return Attempt(
        id=row["id"],
        assignment_id=row["assignment_id"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        exit_code=row["exit_code"],
        run_path=row["run_path"],
        message=row["message"],
    )


def parse_input_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse ``key=value`` CLI pairs into a dict (last key wins)."""
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise QueueError(f"input must be KEY=VALUE, got {raw!r}")
        key, _, value = raw.partition("=")
        if not key:
            raise QueueError(f"input key empty in {raw!r}")
        out[key] = value
    return out


def assignment_to_dict(a: Assignment) -> dict[str, Any]:
    return {
        "id": a.id,
        "release_path": a.release_path,
        "inputs": a.inputs,
        "status": a.status,
        "created_at": a.created_at,
        "claimed_at": a.claimed_at,
        "finished_at": a.finished_at,
        "batch_id": a.batch_id,
        "attempt_id": a.attempt_id,
        "run_path": a.run_path,
        "exit_code": a.exit_code,
        "message": a.message,
    }

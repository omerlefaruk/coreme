"""Append-only structured events for a Run (``events.jsonl``).

Schema v1: one UTF-8 JSON object per line. Kernel writes lifecycle events;
Jobs may append step markers via ``coreme.joblog.emit``.

Failed runs also get a small ``fail.json`` brief for repair agents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coreme.util import iso_utc, json_dumps

SCHEMA_VERSION = 1
EVENTS_FILENAME = "events.jsonl"
FAIL_FILENAME = "fail.json"

_STEP_EVENTS = frozenset({"step.start", "step.ok", "step.skip", "step.fail"})


def events_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / EVENTS_FILENAME


def fail_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / FAIL_FILENAME


def append_event(
    run_dir: str | Path,
    event: str,
    *,
    level: str = "info",
    **fields: Any,
) -> None:
    """Append one JSONL event. Line-atomic write (one write call per line).

    Emits strict, standards-compliant JSON: non-finite floats (NaN / Infinity)
    and unserializable values are rejected with a clear error before any byte
    is written, so a rejected event never corrupts the file.
    """
    row: dict[str, Any] = {
        "v": SCHEMA_VERSION,
        "ts": iso_utc(timespec="seconds"),
        "level": level,
        "event": event,
    }
    for key, value in fields.items():
        if value is not None:
            row[key] = value
    path = events_path(run_dir)
    try:
        line = json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    except (TypeError, ValueError) as error:
        raise ValueError(f"cannot append event {event!r}: {error}") from error
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()


def read_events(run_dir: str | Path) -> list[dict[str, Any]]:
    """Parse all complete JSON lines from a Run's events file.

    Tolerant reader: malformed or truncated lines (e.g. a hard kill mid-write)
    and non-object rows are skipped; valid rows are preserved in file order.
    """
    path = events_path(run_dir)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_fail_summary(run_dir: str | Path, summary: dict[str, Any]) -> Path:
    """Write ``fail.json`` (pretty JSON). Returns the path written."""
    path = fail_path(run_dir)
    path.write_text(json_dumps(summary), encoding="utf-8")
    return path


def read_fail_summary(run_dir: str | Path) -> dict[str, Any] | None:
    """Load ``fail.json`` if present; else ``None``."""
    path = fail_path(run_dir)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_fail_summary(
    *,
    job: str,
    version: str,
    exit_code: int,
    status: str,
    kind: str,
    message: str | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a v1 fail brief from lifecycle/step events (newest-first scan)."""
    rows = events or []
    failed_step: dict[str, Any] | None = None
    last_step: dict[str, Any] | None = None

    for row in reversed(rows):
        event = row.get("event")
        if failed_step is None and event == "step.fail":
            failed_step = {}
            if "step" in row:
                failed_step["step"] = row["step"]
            if row.get("name") is not None:
                failed_step["name"] = row["name"]
            if row.get("total") is not None:
                failed_step["total"] = row["total"]
            if row.get("message"):
                failed_step["message"] = row["message"]
        if last_step is None and event in _STEP_EVENTS:
            last_step = {"event": event}
            if "step" in row:
                last_step["step"] = row["step"]
            if row.get("name") is not None:
                last_step["name"] = row["name"]
            if row.get("total") is not None:
                last_step["total"] = row["total"]
        if failed_step is not None and last_step is not None:
            break

    if not message:
        if kind == "process" and failed_step and failed_step.get("message"):
            message = str(failed_step["message"])
        elif kind == "process":
            message = f"job exited with code {exit_code}"
        elif kind == "timeout":
            message = f"timeout (exit_code={exit_code})"
        elif kind == "start_error":
            message = "failed to start job"
        else:
            message = f"job failed (exit_code={exit_code})"

    return {
        "v": 1,
        "kind": kind,
        "status": status,
        "exit_code": exit_code,
        "message": message,
        "job": job,
        "version": version,
        "failed_step": failed_step,
        "last_step": last_step,
        "evidence": {
            "log": "log.txt",
            "events": EVENTS_FILENAME,
            "run_json": "run.json",
        },
    }

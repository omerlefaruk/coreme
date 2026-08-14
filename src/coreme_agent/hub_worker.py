"""Hub Assignment run: claim → hash pull → execute → outbox."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from coreme_agent import __version__
from coreme_agent.cache import ReleasePullError, resolve_release, zip_tree
from coreme_agent.executor import ExecResult, execute_assignment
from coreme_agent.hub import CompletePayload, HubClient
from coreme_agent.outbox import flush_item, flush_outbox, write_outbox
from coreme_agent.run import RunOutcome, RunRequest
from coreme_agent.store import STATUS_FAILED


def process_one(
    client: HubClient,
    *,
    tags: list[str],
    workspace: str | Path | None = None,
    coreme_cmd: list[str] | None = None,
    timeout_sec: float | None = None,
    cache_dir: str | Path | None = None,
    outbox_dir: str | Path | None = None,
) -> RunOutcome | None:
    """Heartbeat, claim one Assignment, pull, run coreme, complete. None if idle."""
    root = Path(workspace).resolve() if workspace else Path.cwd()
    cache = Path(cache_dir) if cache_dir else root / ".coreme-agent" / "cache"
    outbox = Path(outbox_dir) if outbox_dir else root / ".coreme-agent" / "outbox"
    flush_outbox(client, outbox)
    client.heartbeat(tags=tags, status="idle", agent_version=__version__)
    claimed = client.claim()
    if claimed is None:
        return None
    client.heartbeat(
        tags=tags,
        status="busy",
        agent_version=__version__,
        running_assignment_id=claimed.id,
    )
    stop = threading.Event()
    interval = max(1.0, claimed.lease_seconds / 3)
    renewer = threading.Thread(
        target=_renew_loop,
        args=(client, claimed.id, claimed.attempt_id, stop, interval),
        daemon=True,
    )
    renewer.start()
    pull_fail: dict[str, Any] | None = None
    try:
        try:
            local = resolve_release(
                claimed.content_hash,
                claimed.blob_url,
                cache_dir=cache,
                download=client.download,
                size_bytes=claimed.size_bytes,
            )
        except ReleasePullError as exc:
            result = ExecResult(STATUS_FAILED, None, None, str(exc), "", "")
            pull_fail = {"kind": "release-hash", "message": str(exc)}
            local = None
        else:
            request = RunRequest(
                id=claimed.id,
                release_path=str(local),
                inputs=claimed.inputs,
                batch_id=claimed.batch_id,
                attempt_id=claimed.attempt_id,
            )
            result = execute_assignment(
                request,
                workspace=root,
                coreme_cmd=coreme_cmd,
                timeout_sec=timeout_sec,
            )
        complete_body = _complete_body(result, fail=pull_fail)
        evidence = None
        if result.status != "succeeded" and result.run_path:
            run_dir = Path(result.run_path)
            if run_dir.is_dir():
                evidence = zip_tree(run_dir)
        item = write_outbox(
            outbox,
            assignment_id=claimed.id,
            attempt_id=claimed.attempt_id,
            complete=complete_body,
            evidence=evidence,
        )
        flush_item(client, item)
    finally:
        stop.set()
        renewer.join(timeout=2)
        client.heartbeat(tags=tags, status="idle", agent_version=__version__)
    return RunOutcome(
        id=claimed.id,
        status=result.status,
        exit_code=result.exit_code,
        run_path=result.run_path,
        message=result.message,
        attempt_id=claimed.attempt_id,
        batch_id=claimed.batch_id,
    )


def drain(
    client: HubClient,
    *,
    tags: list[str],
    workspace: str | Path | None = None,
    coreme_cmd: list[str] | None = None,
    max_items: int | None = None,
    timeout_sec: float | None = None,
    cache_dir: str | Path | None = None,
    outbox_dir: str | Path | None = None,
) -> list[RunOutcome]:
    done: list[RunOutcome] = []
    while max_items is None or len(done) < max_items:
        finished = process_one(
            client,
            tags=tags,
            workspace=workspace,
            coreme_cmd=coreme_cmd,
            timeout_sec=timeout_sec,
            cache_dir=cache_dir,
            outbox_dir=outbox_dir,
        )
        if finished is None:
            break
        done.append(finished)
    return done


def _complete_body(result: ExecResult, *, fail: dict[str, Any] | None) -> CompletePayload:
    fail_body = fail if fail is not None else _load_fail(result.run_path)
    log_tail = _log_tail(result)
    summary: dict[str, Any] = {
        "status": result.status,
        "run_id": result.run_path,
        "exit_code": result.exit_code,
        "message": result.message,
    }
    return CompletePayload(
        status=result.status,
        run_id=result.run_path,
        exit_code=result.exit_code,
        summary=summary,
        fail=fail_body,
        log_tail=log_tail,
    )


def _load_fail(run_path: str | None) -> dict[str, Any] | None:
    if not run_path:
        return None
    path = Path(run_path) / "fail.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _log_tail(result: ExecResult) -> str | None:
    if result.run_path:
        log = Path(result.run_path) / "log.txt"
        if log.is_file():
            text = log.read_text(encoding="utf-8", errors="replace")
            return text[-4000:] or None
    text = (result.stdout or result.stderr)[-4000:]
    return text or None


def _renew_loop(
    client: HubClient,
    assignment_id: str,
    attempt_id: str,
    stop: threading.Event,
    interval: float,
) -> None:
    while not stop.wait(interval):
        try:
            client.renew(assignment_id, attempt_id=attempt_id)
        except Exception:
            return

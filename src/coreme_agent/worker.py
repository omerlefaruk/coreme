"""Claim → execute → complete loop for the local agent."""

from __future__ import annotations

from pathlib import Path

from coreme_agent.executor import ExecResult, execute_assignment
from coreme_agent.run import RunOutcome, RunRequest
from coreme_agent.store import LocalQueue


def process_one(
    queue: LocalQueue,
    *,
    workspace: str | Path | None = None,
    coreme_cmd: list[str] | None = None,
    timeout_sec: float | None = None,
) -> RunOutcome | None:
    """Claim one pending Assignment, run coreme, record Attempt. None if idle."""
    request = queue.claim_next()
    if request is None:
        return None
    result = execute_assignment(
        request,
        workspace=workspace,
        coreme_cmd=coreme_cmd,
        timeout_sec=timeout_sec,
    )
    return _finish(queue, request, result)


def drain(
    queue: LocalQueue,
    *,
    workspace: str | Path | None = None,
    coreme_cmd: list[str] | None = None,
    max_items: int | None = None,
    timeout_sec: float | None = None,
) -> list[RunOutcome]:
    """Process pending Assignments until empty or *max_items* reached."""
    done: list[RunOutcome] = []
    while max_items is None or len(done) < max_items:
        finished = process_one(
            queue,
            workspace=workspace,
            coreme_cmd=coreme_cmd,
            timeout_sec=timeout_sec,
        )
        if finished is None:
            break
        done.append(finished)
    return done


def _finish(
    queue: LocalQueue,
    request: RunRequest,
    result: ExecResult,
) -> RunOutcome:
    return queue.complete(
        request.id,
        status=result.status,
        exit_code=result.exit_code,
        run_path=result.run_path,
        message=result.message,
    )

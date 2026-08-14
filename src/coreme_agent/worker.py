"""Claim → execute → complete loop for the local agent."""

from __future__ import annotations

from pathlib import Path

from coreme_agent.executor import ExecResult, execute_assignment
from coreme_agent.store import Assignment, LocalQueue


def process_one(
    queue: LocalQueue,
    *,
    workspace: str | Path | None = None,
    coreme_cmd: list[str] | None = None,
    timeout_sec: float | None = None,
) -> Assignment | None:
    """Claim one pending Assignment, run coreme, record Attempt. None if idle."""
    assignment = queue.claim_next()
    if assignment is None:
        return None
    result = execute_assignment(
        assignment,
        workspace=workspace,
        coreme_cmd=coreme_cmd,
        timeout_sec=timeout_sec,
    )
    return _finish(queue, assignment, result)


def drain(
    queue: LocalQueue,
    *,
    workspace: str | Path | None = None,
    coreme_cmd: list[str] | None = None,
    max_items: int | None = None,
    timeout_sec: float | None = None,
) -> list[Assignment]:
    """Process pending Assignments until empty or *max_items* reached."""
    done: list[Assignment] = []
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
    assignment: Assignment,
    result: ExecResult,
) -> Assignment:
    return queue.complete(
        assignment.id,
        status=result.status,
        exit_code=result.exit_code,
        run_path=result.run_path,
        message=result.message,
    )

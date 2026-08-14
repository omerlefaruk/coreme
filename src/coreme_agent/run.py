"""Run request and outcome shared by the local queue and the hub run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunRequest:
    id: str
    release_path: str
    inputs: dict[str, str]
    batch_id: str | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class RunOutcome:
    id: str
    status: str
    exit_code: int | None
    run_path: str | None
    message: str | None
    attempt_id: str | None = None
    batch_id: str | None = None

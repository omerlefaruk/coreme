"""F3 agent cache and evidence outbox (no Postgres)."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import write_job

from coreme.ship import hash_job_tree
from coreme_agent.cache import ReleasePullError, resolve_release, zip_tree
from coreme_agent.hub import HubClientError
from coreme_agent.outbox import flush_item, flush_outbox, load_pending, write_outbox


class _FakeHub:
    def __init__(self) -> None:
        self.completes: list[tuple[str, dict]] = []
        self.evidence: list[tuple[str, str, bytes]] = []
        self.fail_complete = False
        self.fail_evidence = False

    def complete(self, assignment_id: str, **kwargs: object) -> dict:
        if self.fail_complete:
            raise HubClientError(503, "hub down")
        self.completes.append((assignment_id, dict(kwargs)))
        return {"status": kwargs.get("status")}

    def put_evidence(self, assignment_id: str, *, attempt_id: str, payload: bytes) -> dict:
        if self.fail_evidence:
            raise HubClientError(503, "hub down")
        self.evidence.append((assignment_id, attempt_id, payload))
        return {"size_bytes": len(payload)}


def test_cache_reuses_verified_tree(tmp_path: Path) -> None:
    job = write_job(tmp_path / "hello", name="hello", version="1.0.0")
    digest, _count = hash_job_tree(job)
    payload = zip_tree(job)
    hits = {"n": 0}

    def download(_url: str) -> bytes:
        hits["n"] += 1
        return payload

    cache = tmp_path / "cache"
    first = resolve_release(digest, "http://hub/blob", cache_dir=cache, download=download)
    second = resolve_release(digest, "http://hub/blob", cache_dir=cache, download=download)
    assert first == second
    assert hits["n"] == 1
    assert hash_job_tree(first)[0] == digest


def test_cache_rejects_wrong_hash(tmp_path: Path) -> None:
    job = write_job(tmp_path / "hello", name="hello", version="1.0.0")
    payload = zip_tree(job)

    def download(_url: str) -> bytes:
        return payload

    with pytest.raises(ReleasePullError, match="mismatch"):
        resolve_release(
            "sha256:" + "00" * 32,
            "http://hub/blob",
            cache_dir=tmp_path / "cache",
            download=download,
        )


def test_outbox_replays_after_complete_error(tmp_path: Path) -> None:
    hub = _FakeHub()
    hub.fail_complete = True
    item = write_outbox(
        tmp_path / "outbox",
        assignment_id="a1",
        attempt_id="t1",
        complete={"status": "failed", "exit_code": 1, "summary": {"status": "failed"}},
        evidence=b"PK\x03\x04fake",
    )
    with pytest.raises(HubClientError):
        flush_item(hub, item)  # type: ignore[arg-type]
    assert load_pending(tmp_path / "outbox")
    hub.fail_complete = False
    flush_outbox(hub, tmp_path / "outbox")  # type: ignore[arg-type]
    assert hub.completes
    assert hub.evidence
    assert load_pending(tmp_path / "outbox") == []


def test_outbox_drops_stale_attempt(tmp_path: Path) -> None:
    class _Stale(_FakeHub):
        def complete(self, assignment_id: str, **kwargs: object) -> dict:
            raise HubClientError(409, "stale")

    write_outbox(
        tmp_path / "outbox",
        assignment_id="a1",
        attempt_id="t1",
        complete={"status": "succeeded", "exit_code": 0},
    )
    flush_outbox(_Stale(), tmp_path / "outbox")  # type: ignore[arg-type]
    assert load_pending(tmp_path / "outbox") == []

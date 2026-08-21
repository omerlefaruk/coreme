"""Agent config parsing and resident daemon loop (unit, no network)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from coreme_agent.config import (
    AgentConfig,
    ConfigError,
    default_config_path,
    load,
    save,
    split_csv,
)
from coreme_agent.daemon import Daemon, DaemonLocked, acquire_lock, release_lock
from coreme_agent.hub import ClaimedWork, HubClientError
from coreme_agent.run import RunOutcome

# ---------------------------------------------------------------- config


def test_load_defaults_without_file(tmp_path: Path) -> None:
    cfg = load(path=tmp_path / "missing.toml", env={})
    assert cfg.hub_url is None
    assert cfg.poll_interval_sec == 15.0
    assert cfg.heartbeat_interval_sec == 30.0
    assert cfg.slots == 1
    assert cfg.tags == ()


def test_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "agent.toml"
    save(
        AgentConfig(
            hub_url="http://hub:8787",
            machine_id="pc-1",
            machine_token="tok",
            tags=("site=lab", "role=invoice"),
            workspace=str(tmp_path),
        ),
        path,
    )
    cfg = load(path=path, env={})
    assert cfg.hub_url == "http://hub:8787"
    assert cfg.machine_id == "pc-1"
    assert cfg.machine_token == "tok"
    assert cfg.tags == ("site=lab", "role=invoice")


def test_precedence_env_beats_file_cli_beats_env(tmp_path: Path) -> None:
    path = tmp_path / "agent.toml"
    path.write_text(
        '[hub]\nurl = "http://file"\n[agent]\npoll_interval_sec = 5\n',
        encoding="utf-8",
    )
    from_file = load(path=path, env={})
    assert from_file.hub_url == "http://file"
    assert from_file.poll_interval_sec == 5.0

    from_env = load(path=path, env={"COREME_HUB_URL": "http://env"})
    assert from_env.hub_url == "http://env"

    from_cli = load(path=path, env={"COREME_HUB_URL": "http://env"}, hub_url="http://cli")
    assert from_cli.hub_url == "http://cli"


def test_invalid_values_raise(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[agent]\npoll_interval_sec = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(path=bad, env={})
    # slots=0 clamps to one slot instead of failing.
    clamped = load(path=tmp_path / "missing.toml", env={}, slots=0)
    assert clamped.slots == 1


def test_split_csv_and_default_path(monkeypatch: pytest.MonkeyPatch) -> None:
    assert split_csv("a, b,,c") == ["a", "b", "c"]
    assert split_csv(None) == []
    monkeypatch.delenv("COREME_AGENT_CONFIG", raising=False)
    expected = Path.home() / ".coreme" / "agent.toml"
    assert default_config_path({}) == expected


# ---------------------------------------------------------------- daemon


def _work(i: int) -> ClaimedWork:
    return ClaimedWork(
        id=f"a{i}",
        content_hash="sha256:" + "ab" * 32,
        blob_url="/v1/releases/ab/blob",
        size_bytes=None,
        inputs={},
        secret_names=[],
        batch_id=None,
        lease_seconds=900,
        attempt_id=f"t{i}",
    )


class FakeClient:
    def __init__(
        self,
        claims: list[ClaimedWork] | None = None,
        fail_first: int = 0,
    ) -> None:
        self._claims = list(claims or [])
        self._fail_first = fail_first
        self._lock = threading.Lock()
        self.heartbeats: list[tuple[str, str | None]] = []

    def claim(self) -> ClaimedWork | None:
        with self._lock:
            if self._fail_first > 0:
                self._fail_first -= 1
                raise HubClientError(503, "try later")
            if self._claims:
                return self._claims.pop(0)
            return None

    def heartbeat(
        self,
        *,
        tags: list[str],
        status: str = "idle",
        agent_version: str | None = None,
        running_assignment_id: str | None = None,
    ) -> None:
        with self._lock:
            self.heartbeats.append((status, running_assignment_id))


def _runner(record: list[tuple[str, str]], delay: float = 0.05) -> Any:
    def run(client: Any, claimed: ClaimedWork) -> RunOutcome:
        record.append(("start", claimed.id))
        time.sleep(delay)
        record.append(("end", claimed.id))
        return RunOutcome(
            id=claimed.id,
            status="succeeded",
            exit_code=0,
            run_path=None,
            message=None,
            attempt_id=claimed.attempt_id,
        )

    return run


def _cfg(tmp_path: Path, **overrides: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "hub_url": "http://hub",
        "machine_id": "pc",
        "machine_token": "tok",
        "workspace": str(tmp_path),
        "poll_interval_sec": 0.01,
        "heartbeat_interval_sec": 60.0,
        "slots": 1,
    }
    values.update(overrides)
    return AgentConfig(**values)


def _run_in_thread(daemon: Daemon, stop: threading.Event) -> threading.Thread:
    thread = threading.Thread(target=daemon.run, args=(stop,), daemon=True)
    thread.start()
    return thread


def test_claims_respect_single_slot(tmp_path: Path) -> None:
    client = FakeClient([_work(1), _work(2)])
    record: list[tuple[str, str]] = []
    daemon = Daemon(client, _cfg(tmp_path), runner=_runner(record))
    stop = threading.Event()
    thread = _run_in_thread(daemon, stop)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        ends = [kind for kind, _ in record if kind == "end"]
        if len(ends) >= 2:
            break
        time.sleep(0.01)
    stop.set()
    thread.join(timeout=5)
    kinds = [kind for kind, _ in record]
    started = [e for kind, e in record if kind == "start"]
    assert sorted(started) == ["a1", "a2"]
    # slots=1 forces strict serialization: second start after first end.
    starts = [i for i, kind in enumerate(kinds) if kind == "start"]
    ends = [i for i, kind in enumerate(kinds) if kind == "end"]
    assert len(starts) == 2 and len(ends) == 2
    assert starts[1] > ends[0]


def test_stop_event_ends_idle_daemon(tmp_path: Path) -> None:
    client = FakeClient()
    daemon = Daemon(client, _cfg(tmp_path), runner=_runner([]))
    stop = threading.Event()
    thread = _run_in_thread(daemon, stop)
    time.sleep(0.1)
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_backoff_recovers_after_hub_error(tmp_path: Path) -> None:
    client = FakeClient([_work(7)], fail_first=2)
    record: list[tuple[str, str]] = []
    daemon = Daemon(client, _cfg(tmp_path), runner=_runner(record))
    stop = threading.Event()
    thread = _run_in_thread(daemon, stop)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and "a7" not in [e for _, e in record]:
        time.sleep(0.05)
    stop.set()
    thread.join(timeout=5)
    assert "a7" in [e for _, e in record]


def test_heartbeat_reports_busy_then_idle(tmp_path: Path) -> None:
    client = FakeClient([_work(3)])
    record: list[tuple[str, str]] = []
    daemon = Daemon(
        client,
        _cfg(tmp_path, heartbeat_interval_sec=0.02),
        runner=_runner(record, delay=0.3),
    )
    stop = threading.Event()
    thread = _run_in_thread(daemon, stop)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with client._lock:
            beats = list(client.heartbeats)
        ended = any(kind == "end" for kind, _ in record)
        if ended and len(beats) >= 2 and beats[-1][0] == "idle":
            break
        time.sleep(0.02)
    stop.set()
    thread.join(timeout=5)
    statuses = [s for s, _ in client.heartbeats]
    assert "busy" in statuses
    assert "idle" in statuses[-2:] or statuses[-1] == "idle"


def test_workspace_lock_is_exclusive_and_stale_aware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = acquire_lock(tmp_path)
    with pytest.raises(DaemonLocked):
        acquire_lock(tmp_path)
    release_lock(lock)
    lock_again = acquire_lock(tmp_path)
    release_lock(lock_again)

    # A stale lock (dead pid) is replaced instead of blocking startup.
    stale = tmp_path / ".coreme-agent" / "daemon.lock"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("999999", encoding="utf-8")
    monkeypatch.setattr("coreme_agent.daemon._pid_alive", lambda pid: False)
    replaced = acquire_lock(tmp_path)
    assert replaced == stale
    release_lock(replaced)

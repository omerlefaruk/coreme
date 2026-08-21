"""Resident robot daemon: idle heartbeat, claim loop, parallel slots.

The daemon is a thin supervisor. Workers reuse ``hub_worker.execute_claimed``
(lease renew, hash pull, contained run, outbox), so crash recovery and
evidence semantics stay in one home.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from coreme_agent import __version__
from coreme_agent.config import AgentConfig
from coreme_agent.hub import ClaimedWork, HubClient, HubClientError
from coreme_agent.hub_worker import execute_claimed, flush_outbox
from coreme_agent.run import RunOutcome

log = logging.getLogger(__name__)

MIN_BACKOFF_SEC = 2.0
MAX_BACKOFF_SEC = 60.0
DRAIN_TIMEOUT_SEC = 30.0


class DaemonLocked(Exception):
    """Another daemon instance holds the workspace lock."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        super().__init__(f"another daemon holds the lock (pid {pid})")


Runner = Callable[[HubClient, ClaimedWork], RunOutcome]


def default_runner(config: AgentConfig) -> Runner:
    """Bind workspace from config; coreme command resolution stays default."""
    workspace = Path(config.workspace).resolve() if config.workspace else None

    def runner(client: HubClient, claimed: ClaimedWork) -> RunOutcome:
        return execute_claimed(client, claimed, workspace=workspace)

    return runner


def lock_path(workspace: str | Path) -> Path:
    return Path(workspace) / ".coreme-agent" / "daemon.lock"


def acquire_lock(workspace: str | Path) -> Path:
    """Create the single-instance lock; replace it only when stale."""
    path = lock_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = _read_pid(path)
            if pid is not None and _pid_alive(pid):
                raise DaemonLocked(pid) from None
            log.warning("removing stale daemon lock (pid %s)", pid)
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return path


def release_lock(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)


def setup_logging(config: AgentConfig) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if config.log_file:
        handlers.append(
            RotatingFileHandler(
                config.log_file,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        )
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


class Daemon:
    """Claim-loop supervisor with parallel slots and idle heartbeats."""

    def __init__(
        self,
        client: HubClient,
        config: AgentConfig,
        *,
        runner: Runner | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._runner = runner if runner is not None else default_runner(config)
        self._lock = threading.Lock()
        self._active: dict[str, ClaimedWork] = {}
        self._workers: list[threading.Thread] = []

    def run(self, stop: threading.Event) -> int:
        heartbeat = threading.Thread(target=self._heartbeat_loop, args=(stop,), daemon=True)
        heartbeat.start()
        backoff = MIN_BACKOFF_SEC
        next_poll = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now < next_poll:
                stop.wait(min(0.2, next_poll - now))
                continue
            if len(self._active) >= self._config.slots:
                next_poll = now + self._config.poll_interval_sec
                continue
            if not self._active:
                self._flush_outbox()
            try:
                claimed = self._client.claim()
                backoff = MIN_BACKOFF_SEC
            except (HubClientError, OSError) as exc:
                log.warning("hub error: %s; backing off %.1fs", exc, backoff)
                next_poll = time.monotonic() + backoff
                backoff = min(MAX_BACKOFF_SEC, backoff * 2)
                continue
            if claimed is None:
                next_poll = now + self._config.poll_interval_sec
                continue
            self._dispatch(claimed)
        self._drain_workers()
        return 0

    def _dispatch(self, claimed: ClaimedWork) -> None:
        with self._lock:
            self._active[claimed.id] = claimed
        worker = threading.Thread(target=self._work, args=(claimed,), daemon=True)
        worker.start()
        self._workers.append(worker)

    def _work(self, claimed: ClaimedWork) -> None:
        try:
            outcome = self._runner(self._client, claimed)
            log.info(
                "assignment %s finished status=%s run=%s",
                claimed.id,
                outcome.status,
                outcome.run_path or "-",
            )
        except Exception as exc:  # daemon must survive worker crashes
            log.exception("assignment %s crashed: %s", claimed.id, exc)
        finally:
            with self._lock:
                self._active.pop(claimed.id, None)

    def _heartbeat_loop(self, stop: threading.Event) -> None:
        interval = self._config.heartbeat_interval_sec
        while not stop.wait(interval):
            with self._lock:
                active = list(self._active.values())
            try:
                self._client.heartbeat(
                    tags=list(self._config.tags),
                    status="busy" if active else "idle",
                    agent_version=__version__,
                    running_assignment_id=active[0].id if active else None,
                )
            except Exception as exc:
                log.warning("heartbeat failed: %s", exc)

    def _flush_outbox(self) -> None:
        outbox = Path(self._config.workspace) / ".coreme-agent" / "outbox"
        try:
            flush_outbox(self._client, outbox)
        except Exception as exc:
            log.warning("outbox flush failed: %s", exc)

    def _drain_workers(self) -> None:
        for worker in list(self._workers):
            worker.join(timeout=DRAIN_TIMEOUT_SEC)
        self._flush_outbox()


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

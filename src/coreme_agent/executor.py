"""Invoke coreme for one run request through a contained process tree.

Machine state is exactly one version-1 JSON frame read from an inherited
anonymous pipe. Human ``--plain`` output has no authority. The CLI consumes
and hides its write endpoint before ``run_job``; absent, malformed, oversized,
duplicate, or exit-inconsistent frames are agent errors. An outer agent
timeout is always ``timeout``/124 and ignores any partial frame.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from coreme._process import ProcessError, _WindowsJob
from coreme.present import RESULT_ENV, RESULT_MAX_BYTES, RESULT_SCHEMA, RESULT_VERSION
from coreme_agent.run import RunRequest
from coreme_agent.store import (
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    STATUS_TIMEOUT,
)

_OUTPUT_LIMIT = 1024 * 1024
_TEARDOWN_SEC = 2.0
_REQUIRED_RESULT_KEYS = {
    "schema",
    "version",
    "status",
    "exit_code",
    "run_path",
    "job",
    "job_version",
}
_OPTIONAL_RESULT_KEYS = {"started_at", "finished_at", "fail_path", "fail_message", "failed_step"}


@dataclass(frozen=True)
class ExecResult:
    status: str
    exit_code: int | None
    run_path: str | None
    message: str | None
    stdout: str
    stderr: str


def default_coreme_cmd() -> list[str]:
    return [sys.executable, "-m", "coreme"]


def build_run_argv(request: RunRequest, *, coreme_cmd: list[str] | None = None) -> list[str]:
    argv = [*(coreme_cmd or default_coreme_cmd()), "--plain", "run", request.release_path]
    for key, value in sorted(request.inputs.items()):
        argv.extend(["--input", f"{key}={value}"])
    return argv


def execute_assignment(
    request: RunRequest,
    *,
    workspace: str | Path | None = None,
    coreme_cmd: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout_sec: float | None = None,
) -> ExecResult:
    argv = build_run_argv(request, coreme_cmd=coreme_cmd)
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    run_env.update(COREME_PLAIN="1", COREME_ASSIGNMENT_ID=request.id)
    if request.batch_id:
        run_env["COREME_BATCH_ID"] = request.batch_id
    if request.attempt_id:
        run_env["COREME_ATTEMPT_ID"] = request.attempt_id

    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    reader = _FrameReader(read_fd)
    reader.start()
    error_result = None
    try:
        stdout, stderr, returncode, timed_out = _run_coreme(
            argv,
            cwd=str(Path(workspace).resolve() if workspace else Path.cwd()),
            env=run_env,
            timeout_sec=timeout_sec,
            result_write_fd=write_fd,
        )
    except FileNotFoundError as exc:
        error_result = ExecResult(
            STATUS_ERROR,
            None,
            None,
            f"coreme command not found: {exc}",
            "",
            str(exc),
        )
    except ProcessError as exc:
        error_result = ExecResult(
            STATUS_ERROR,
            None,
            None,
            f"failed to contain or stop coreme: {exc}",
            exc.stdout,
            exc.stderr,
        )
    except OSError as exc:
        error_result = ExecResult(
            STATUS_ERROR, None, None, f"failed to start coreme: {exc}", "", str(exc)
        )
    finally:
        with contextlib.suppress(OSError):
            os.close(write_fd)

    if error_result is not None:
        reader.stop_bounded()
        return error_result

    if timed_out:
        reader.stop_bounded()
        return ExecResult(
            STATUS_TIMEOUT,
            124,
            None,
            f"agent-level timeout after {timeout_sec}s",
            stdout,
            stderr,
        )

    frame, frame_error = reader.finish_bounded()
    if frame_error is not None:
        return ExecResult(STATUS_ERROR, returncode, None, frame_error, stdout, stderr)
    assert frame is not None
    consistency_error = _validate_consistency(frame, returncode)
    if consistency_error:
        return ExecResult(STATUS_ERROR, returncode, None, consistency_error, stdout, stderr)
    status = _status_from_exit(returncode)
    message = None
    if status != STATUS_SUCCEEDED:
        value = frame.get("fail_message")
        message = (
            value[:500] if isinstance(value, str) and value.strip() else f"coreme exit {returncode}"
        )
    return ExecResult(
        status,
        returncode,
        cast(str, frame["run_path"]),
        message,
        stdout,
        stderr,
    )


class _BoundedOutput:
    def __init__(self, pipe) -> None:
        # Read a duplicate with os.read. The pump exclusively owns and closes
        # it; its stop event avoids cross-thread close and descriptor reuse.
        self.fd = os.dup(pipe.fileno())
        pipe.close()
        self.data = bytearray()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._pump, daemon=True)

    def _pump(self) -> None:
        try:
            while not self.stop.is_set():
                if not _pipe_read_ready(self.fd, self.stop):
                    continue
                chunk = os.read(self.fd, 8192)
                if not chunk:
                    return
                room = _OUTPUT_LIMIT - len(self.data)
                if room > 0:
                    self.data.extend(chunk[:room])
        except (OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError):
                os.close(self.fd)

    def stop_bounded(self) -> None:
        self.stop.set()
        self.thread.join(_TEARDOWN_SEC)

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")


class _FrameReader:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.data = bytearray()
        self.oversized = False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._pump, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _pump(self) -> None:
        try:
            while not self.stop.is_set():
                if not _pipe_read_ready(self.fd, self.stop):
                    continue
                chunk = os.read(self.fd, 8192)
                if not chunk:
                    return
                if len(self.data) + len(chunk) > RESULT_MAX_BYTES + 4:
                    self.oversized = True
                room = RESULT_MAX_BYTES + 5 - len(self.data)
                if room > 0:
                    self.data.extend(chunk[:room])
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                os.close(self.fd)

    def stop_bounded(self) -> None:
        self.stop.set()
        self.thread.join(_TEARDOWN_SEC)

    def finish_bounded(self) -> tuple[dict[str, object] | None, str | None]:
        self.thread.join(_TEARDOWN_SEC)
        if self.thread.is_alive():
            self.stop_bounded()
            return None, "machine result channel did not close"
        return _decode_result(bytes(self.data), self.oversized)


def _pipe_read_ready(fd: int, stop: threading.Event) -> bool:
    """Wait briefly for pipe data without surrendering fd ownership.

    The reader thread is the sole closer. Polling lets its owner request a
    bounded stop without closing a descriptor that the reader could later
    mistake for a newly reused descriptor.
    """
    if sys.platform != "win32":
        readable, _, _ = select.select([fd], [], [], 0.05)
        return bool(readable)

    import ctypes
    import msvcrt
    from ctypes import wintypes

    available = wintypes.DWORD()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    ready = kernel32.PeekNamedPipe(
        wintypes.HANDLE(msvcrt.get_osfhandle(fd)),
        None,
        0,
        None,
        ctypes.byref(available),
        None,
    )
    if not ready:
        error = ctypes.get_last_error()
        if error == 109:  # ERROR_BROKEN_PIPE: os.read will return EOF.
            return True
        raise OSError(error, "PeekNamedPipe failed")
    if available.value:
        return True
    stop.wait(0.05)
    return False


def _run_coreme(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout_sec: float | None,
    result_write_fd: int,
) -> tuple[str, str, int, bool]:
    creationflags = 0
    startupinfo = None
    job = None
    popen_extra: dict[str, Any] = {}
    if sys.platform == "win32":
        import msvcrt

        from coreme._process import _CREATE_SUSPENDED, _WindowsJob

        handle = msvcrt.get_osfhandle(result_write_fd)
        os.set_handle_inheritable(handle, True)
        run_env = dict(env)
        run_env[RESULT_ENV] = f"handle:{handle}"
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.lpAttributeList = {"handle_list": [handle]}
        creationflags = _CREATE_SUSPENDED
        job = _WindowsJob()
    else:
        run_env = dict(env)
        run_env[RESULT_ENV] = str(result_write_fd)
        popen_extra = {"pass_fds": (result_write_fd,), "start_new_session": True}

    process = None
    out = None
    err = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            startupinfo=startupinfo,
            close_fds=True,
            **popen_extra,
        )
        if job is not None:
            job.assign(process)
            job.resume(process.pid)
        assert process.stdout is not None and process.stderr is not None
        out = _BoundedOutput(process.stdout)
        err = _BoundedOutput(process.stderr)
        out.thread.start()
        err.thread.start()
        try:
            process.wait(timeout=timeout_sec)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(process, job)
        _finish_output(process, out, err)
        return out.text(), err.text(), 124 if timed_out else int(process.returncode), timed_out
    except BaseException:
        if process is not None and process.poll() is None:
            _terminate(process, job)
        raise
    finally:
        if out is not None and err is not None:
            assert process is not None
            _finish_output(process, out, err)
        if job is not None:
            job.close()


def _terminate(process: subprocess.Popen[bytes], job: _WindowsJob | None) -> None:
    if job is not None:
        job.terminate()
    else:
        import signal

        killpg = getattr(os, "killpg", None)
        sigkill = getattr(signal, "SIGKILL", None)
        if killpg is not None and sigkill is not None:
            with contextlib.suppress(ProcessLookupError):
                killpg(process.pid, sigkill)
    try:
        process.wait(timeout=_TEARDOWN_SEC)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            process.kill()


def _finish_output(process: subprocess.Popen[bytes], *readers: _BoundedOutput) -> None:
    deadline = time.monotonic() + _TEARDOWN_SEC
    for reader in readers:
        reader.thread.join(max(0.0, deadline - time.monotonic()))
    for reader in readers:
        if reader.thread.is_alive():
            reader.stop.set()
    cancel_deadline = time.monotonic() + 0.2
    for reader in readers:
        reader.thread.join(max(0.0, cancel_deadline - time.monotonic()))


def _decode_result(raw: bytes, oversized: bool) -> tuple[dict[str, object] | None, str | None]:
    if oversized or len(raw) > RESULT_MAX_BYTES + 4:
        return None, "machine result payload oversized"
    if len(raw) < 4:
        return None, "machine result payload missing"
    length = int.from_bytes(raw[:4], "big")
    if length > RESULT_MAX_BYTES:
        return None, "machine result payload oversized"
    if len(raw) != length + 4:
        kind = "duplicate" if len(raw) > length + 4 else "incomplete"
        return None, f"machine result payload {kind}"
    try:
        pairs = json.loads(raw[4:].decode("utf-8"), object_pairs_hook=lambda x: x)
        if not isinstance(pairs, list) or any(
            not isinstance(p, tuple) or len(p) != 2 for p in pairs
        ):
            return None, "machine result payload malformed"
        keys = [p[0] for p in pairs]
        if len(keys) != len(set(keys)):
            return None, "machine result payload duplicate keys"
        data = dict(pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None, "machine result payload malformed"
    extra = set(data) - (_REQUIRED_RESULT_KEYS | _OPTIONAL_RESULT_KEYS)
    if extra or not set(data) >= _REQUIRED_RESULT_KEYS:
        return None, "machine result schema invalid"
    if data.get("schema") != RESULT_SCHEMA or data.get("version") != RESULT_VERSION:
        return None, "machine result version invalid"
    if data.get("status") not in {"succeeded", "failed"}:
        return None, "machine result status invalid"
    if isinstance(data.get("exit_code"), bool) or not isinstance(data.get("exit_code"), int):
        return None, "machine result exit code invalid"
    for key in ("run_path", "job", "job_version"):
        value = data.get(key)
        if not isinstance(value, str) or not value or len(value) > 4096:
            return None, f"machine result {key} invalid"
    for key in _OPTIONAL_RESULT_KEYS:
        if key in data and (not isinstance(data[key], str) or len(data[key]) > 4096):
            return None, f"machine result {key} invalid"
    return data, None


def _validate_consistency(result: dict[str, object], returncode: int) -> str | None:
    if result["exit_code"] != returncode:
        return "machine result exit disagrees with subprocess exit"
    expected = "succeeded" if returncode == 0 else "failed"
    if result["status"] != expected:
        return "machine result status disagrees with subprocess exit"
    return None


def _status_from_exit(exit_code: int) -> str:
    if exit_code == 0:
        return STATUS_SUCCEEDED
    if exit_code == 124:
        return STATUS_TIMEOUT
    return STATUS_FAILED

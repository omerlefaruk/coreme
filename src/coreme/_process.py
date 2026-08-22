"""Run child processes with one cross-platform timeout policy."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import TextIO

_CREATE_SUSPENDED = 0x00000004
_EXTENDED_LIMIT_INFORMATION = 9
_KILL_ON_JOB_CLOSE = 0x00002000
_BREAKAWAY_OK = 0x00000800
_SNAP_THREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_INVALID_DWORD = 0xFFFFFFFF
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class ProcessError(Exception):
    """A process could not be contained or stopped safely.

    When output was already collected (streaming mode), the partial child
    output is attached as ``stdout`` so callers can still write evidence.
    """

    def __init__(
        self,
        message: str,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", wintypes.LARGE_INTEGER),
        ("per_job_user_time_limit", wintypes.LARGE_INTEGER),
        ("limit_flags", wintypes.DWORD),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", wintypes.ULARGE_INTEGER),
        ("write_operation_count", wintypes.ULARGE_INTEGER),
        ("other_operation_count", wintypes.ULARGE_INTEGER),
        ("read_transfer_count", wintypes.ULARGE_INTEGER),
        ("write_transfer_count", wintypes.ULARGE_INTEGER),
        ("other_transfer_count", wintypes.ULARGE_INTEGER),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
        ("owner_process_id", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("priority_delta", wintypes.LONG),
        ("flags", wintypes.DWORD),
    ]


def _windows_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ThreadEntry),
    ]
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ThreadEntry),
    ]
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


class _WindowsJob:
    def __init__(self) -> None:
        self._kernel32 = _windows_kernel32()
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ProcessError("Cannot create Windows Job Object")
        info = _ExtendedLimitInformation()
        info.basic_limit_information.limit_flags = _KILL_ON_JOB_CLOSE | _BREAKAWAY_OK
        if not self._kernel32.SetInformationJobObject(
            self._handle,
            _EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            self.close()
            raise ProcessError("Cannot configure Windows Job Object")

    def assign(self, process: subprocess.Popen[str]) -> None:
        if not self._kernel32.AssignProcessToJobObject(
            self._handle, wintypes.HANDLE(process._handle)
        ):
            raise ProcessError("Cannot contain process tree")

    def resume(self, process_id: int) -> None:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(_SNAP_THREAD, 0)
        if snapshot == _INVALID_HANDLE:
            raise ProcessError("Cannot inspect suspended process")
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = self._kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.owner_process_id == process_id:
                    thread = self._kernel32.OpenThread(
                        _THREAD_SUSPEND_RESUME, False, entry.thread_id
                    )
                    if not thread:
                        raise ProcessError("Cannot open suspended process thread")
                    try:
                        if self._kernel32.ResumeThread(thread) == _INVALID_DWORD:
                            raise ProcessError("Cannot resume contained process")
                    finally:
                        self._kernel32.CloseHandle(thread)
                    return
                found = self._kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self._kernel32.CloseHandle(snapshot)
        raise ProcessError("Cannot find suspended process thread")

    def terminate(self) -> None:
        if not self._kernel32.TerminateJobObject(self._handle, 1):
            raise ProcessError("Cannot stop process tree")

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def run_process(
    command: str | list[str],
    *,
    cwd: str | Path,
    timeout_sec: int,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
    shell: bool = False,
    stream: TextIO | None = None,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str, str, bool]:
    job = _WindowsJob() if os.name == "nt" else None
    streaming = stream is not None or on_line is not None
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            shell=shell,
            stdout=subprocess.PIPE if capture_output or streaming else None,
            stderr=(
                subprocess.STDOUT if streaming else subprocess.PIPE if capture_output else None
            ),
            text=True,
            encoding="utf-8" if streaming else None,
            errors="replace" if streaming else None,
            bufsize=1 if streaming else -1,
            creationflags=_CREATE_SUSPENDED if job is not None else 0,
            start_new_session=os.name != "nt",
        )
    except BaseException:
        if job is not None:
            job.close()
        raise
    if job is not None:
        try:
            job.assign(process)
            job.resume(process.pid)
        except BaseException:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                raise ProcessError("Cannot stop uncontained process") from cleanup_error
            finally:
                job.close()
            raise

    chunks: list[str] = []
    reader: threading.Thread | None = None
    if streaming:

        def pump() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                chunks.append(line)  # always plain for log.txt
                try:
                    if on_line is not None:
                        on_line(line)
                    elif stream is not None:
                        stream.write(line)
                        stream.flush()
                except Exception:
                    pass

        reader = threading.Thread(target=pump, name="coreme-process-output", daemon=True)
        reader.start()

    try:
        if reader is not None:
            deadline = time.monotonic() + timeout_sec
            process.wait(timeout=timeout_sec)
            reader.join(timeout=max(0, deadline - time.monotonic()))
            if reader.is_alive():
                raise subprocess.TimeoutExpired(command, timeout_sec)
            stdout, stderr = "".join(chunks), ""
        else:
            stdout, stderr = process.communicate(timeout=timeout_sec)
        return int(process.returncode), stdout or "", stderr or "", False
    except subprocess.TimeoutExpired:
        try:
            _terminate_process_tree(process, job)
        except ProcessError as error:
            if reader is not None:
                error.stdout = "".join(chunks)
            raise
        if reader is not None:
            reader.join(timeout=5)
            if reader.is_alive():
                raise ProcessError(
                    "Cannot drain stopped process output",
                    stdout="".join(chunks),
                ) from None
            stdout, stderr = "".join(chunks), ""
        else:
            stdout, stderr = process.communicate()
        return 124, stdout or "", stderr or "", True
    finally:
        if job is not None:
            job.close()


def _terminate_process_tree(process: subprocess.Popen[str], job: _WindowsJob | None) -> None:
    if job is not None:
        job.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as error:
            raise ProcessError("Cannot stop process tree") from error
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as error:
        raise ProcessError("Cannot stop process tree") from error

"""Execute a Job locally and write Run evidence.

Live progress is a kernel guarantee: the entry always runs as ``python -u`` with
``PYTHONUNBUFFERED=1``, stdout/stderr are streamed to the terminal line-by-line,
and the full text is written to ``log.txt``. Structured lifecycle markers go to
``events.jsonl``. Failed runs also get a small ``fail.json`` brief. Jobs should
still flush their own progress lines so steps appear immediately under every
host stdio mode.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import coreme
from coreme import paths
from coreme._process import ProcessError, run_process
from coreme.events import (
    append_event,
    build_fail_summary,
    read_events,
    write_fail_summary,
)
from coreme.inputs import resolve_inputs, resolve_secrets
from coreme.manifest import JobManifest, load_manifest
from coreme.ship import verify_release
from coreme.util import iso_utc, json_dumps


@dataclass(frozen=True)
class RunRecord:
    job: str
    version: str
    started_at: str
    finished_at: str
    exit_code: int
    status: str
    command: list[str]
    job_path: str
    run_path: str
    inputs: dict[str, str] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)
    release: bool = False
    content_hash: str | None = None


def run_job(
    job_path: str | Path,
    repo_root: Path | None = None,
    *,
    input_pairs: list[tuple[str, str]] | None = None,
) -> RunRecord:
    root = paths.assert_safe_job_path(job_path)
    is_release = False
    content_hash: str | None = None
    if os.path.lexists(root / "RELEASE.json"):
        content_hash = verify_release(root)
        is_release = True
    manifest = load_manifest(root)
    resolved_inputs = resolve_inputs(manifest, input_pairs or [])
    secret_names = resolve_secrets(manifest)
    return _execute(
        manifest,
        repo_root or paths.find_repo_root(),
        resolved_inputs,
        secret_names,
        release=is_release,
        content_hash=content_hash,
    )


def _execute(
    manifest: JobManifest,
    repo_root: Path,
    resolved_inputs: dict[str, str],
    secret_names: list[str],
    *,
    release: bool = False,
    content_hash: str | None = None,
) -> RunRecord:
    started = datetime.now(UTC)
    runs = repo_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run_path = runs / f"{manifest.name}-{started:%Y%m%d-%H%M%S}"
    suffix = 1
    while run_path.exists():
        run_path = runs / f"{manifest.name}-{started:%Y%m%d-%H%M%S}-{suffix}"
        suffix += 1

    artifacts = run_path / "artifacts"
    artifacts.mkdir(parents=True)
    used_inputs = _copy_file_inputs(manifest, resolved_inputs, run_path)
    inputs_json = run_path / "inputs.json"
    inputs_json.write_text(json_dumps(used_inputs), encoding="utf-8")

    env = os.environ.copy()
    # Jobs often print non-ASCII; Windows default console encodings crash otherwise.
    # Unbuffered is required so live progress appears while stdout is a pipe.
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONUTF8", "1")
    env["PYTHONUNBUFFERED"] = "1"
    # Jobs may import coreme.joblog / coreme.events; pytest pythonpath does not
    # reach the entry subprocess. Prepend the package parent so source checkouts
    # and installed layouts both work under the same interpreter as the CLI.
    env["PYTHONPATH"] = _coreme_import_root(env.get("PYTHONPATH", ""))
    env.update(
        {
            "COREME_RUN_DIR": str(run_path.resolve()),
            "COREME_ARTIFACTS_DIR": str(artifacts.resolve()),
            "COREME_INPUTS_JSON": str(inputs_json.resolve()),
        }
    )
    for name, value in used_inputs.items():
        env[f"COREME_INPUT_{name}"] = value

    append_event(
        run_path,
        "run.start",
        job=manifest.name,
        version=manifest.version,
        release=release,
        content_hash=content_hash,
    )

    # -u: force unbuffered stdout/stderr even when piped (live terminal stream).
    command = [sys.executable, "-u", manifest.entry]
    timed_out = False
    start_error: str | None = None
    process_error: str | None = None
    try:
        from coreme.present import echo_job_line

        exit_code, stdout, stderr, timed_out = run_process(
            command,
            cwd=manifest.job_path,
            env=env,
            stream=sys.stdout,  # enables line pump; echo via on_line for color
            on_line=lambda line: echo_job_line(sys.stdout, line),
            timeout_sec=manifest.timeout_sec,
        )
        log = stdout
        if stderr:
            log += ("\n" if log and not log.endswith("\n") else "") + stderr
        if timed_out:
            if log and not log.endswith("\n"):
                log += "\n"
            log += f"[coreme] timeout after {manifest.timeout_sec}s (exit_code=124)\n"
            with suppress(Exception):
                sys.stdout.write(
                    f"[coreme] timeout after {manifest.timeout_sec}s (exit_code=124)\n"
                )
                sys.stdout.flush()
    except OSError as error:
        exit_code = 1
        log = f"[coreme] failed to start job: {error}\n"
        start_error = str(error)
    except ProcessError as error:
        # Containment/teardown failure after the Run was created: still write
        # complete evidence. Keep any output the child already produced.
        exit_code = 1
        partial = error.stdout or ""
        note = f"[coreme] process containment error: {error}\n"
        if partial:
            log = partial if partial.endswith("\n") else partial + "\n"
            log += note
        else:
            log = note
        process_error = str(error)

    (run_path / "log.txt").write_text(log, encoding="utf-8")
    status = "succeeded" if exit_code == 0 else "failed"

    # One finalization path: pick the fail kind, build the fail summary once
    # (before the terminal event so fail.json never includes it), then emit the
    # terminal lifecycle event and write fail.json. Success only emits run.end.
    fail_kind: str | None = None
    fail_message: str | None = None
    fail_summary: dict | None = None
    if process_error is not None:
        fail_kind = "process_error"
        fail_message = f"process containment error: {process_error}"
    elif start_error is not None:
        fail_kind = "start_error"
        fail_message = f"failed to start job: {start_error}"
    elif timed_out:
        fail_kind = "timeout"
        fail_message = f"timeout after {manifest.timeout_sec}s"
    elif status == "failed":
        fail_kind = "process"

    if fail_kind is None:
        append_event(run_path, "run.end", status=status, exit_code=exit_code)
    else:
        # The process kind derives its message from step.* events; the other
        # kinds pass an explicit message. Events are read once, pre-terminal.
        fail_summary = build_fail_summary(
            job=manifest.name,
            version=manifest.version,
            exit_code=exit_code,
            status=status,
            kind=fail_kind,
            message=fail_message,
            events=read_events(run_path),
        )
        fail_message = str(fail_summary["message"])
        if fail_kind == "timeout":
            append_event(
                run_path,
                "run.timeout",
                level="error",
                kind=fail_kind,
                exit_code=124,
                status="failed",
                message=fail_message,
            )
        elif fail_kind == "process":
            append_event(
                run_path,
                "run.end",
                level="error",
                kind=fail_kind,
                status=status,
                exit_code=exit_code,
                message=fail_message,
            )
        else:  # start_error / process_error
            append_event(
                run_path,
                "run.error",
                level="error",
                kind=fail_kind,
                message=fail_message,
                exit_code=exit_code,
                status=status,
            )
        write_fail_summary(run_path, fail_summary)

    record = RunRecord(
        job=manifest.name,
        version=manifest.version,
        started_at=iso_utc(started),
        finished_at=iso_utc(datetime.now(UTC)),
        exit_code=exit_code,
        status=status,
        command=command,
        job_path=manifest.job_path,
        run_path=str(run_path.resolve()),
        inputs=used_inputs,
        secrets=list(secret_names),
        release=release,
        content_hash=content_hash,
    )
    (run_path / "run.json").write_text(json_dumps(asdict(record)), encoding="utf-8")
    return record


def _coreme_import_root(existing_pythonpath: str = "") -> str:
    """Directory that must be on PYTHONPATH for ``import coreme`` in Job children."""
    package_parent = str(Path(coreme.__file__).resolve().parent.parent)
    parts = [package_parent]
    for part in existing_pythonpath.split(os.pathsep):
        if part and part not in parts:
            parts.append(part)
    return os.pathsep.join(parts)


def _copy_file_inputs(
    manifest: JobManifest, resolved: dict[str, str], run_path: Path
) -> dict[str, str]:
    used = dict(resolved)
    for name, spec in manifest.inputs.items():
        if spec.type != "file" or name not in used:
            continue
        destination = run_path / "inputs" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(used[name], destination)
        used[name] = str(destination.resolve())
    return used

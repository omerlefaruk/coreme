"""Codex repair coordinator: brief + spawn host ``codex exec`` + write repair.json.

Day 7 repair runs **after** a failed Run (manual or ``--auto-repair``).
It must not enable, copy, or reuse a Job's runtime-Codex contract.
Edits target **source** only; never ``releases/``.

Spawn/env: :mod:`coreme.repair_spawn`.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from coreme.brief import BriefError, assemble_brief, extract_crash_signature, find_fail_png
from coreme.events import append_event, fail_path
from coreme.manifest import ManifestError, load_manifest
from coreme.repair_spawn import (
    CODEX_LOG,
    CODEX_SUMMARY,
    DEFAULT_CODEX_TIMEOUT_SEC,
    cleaned_codex_env,
    codex_argv,
    codex_prompt,
    default_spawn,
    find_codex,
    resolve_sandbox,
    run_prove,
)
from coreme.util import env_flag, iso_utc, json_dumps

# Re-export public helpers used by CLI and tests.
__all__ = [
    "AUTO_REPAIR_ENV",
    "DEFAULT_CODEX_TIMEOUT_SEC",
    "REPAIR_BRIEF",
    "REPAIR_JSON",
    "REPAIR_PROVE_ENV",
    "REPAIR_RERUN_ENV",
    "RepairError",
    "RepairOutcome",
    "auto_repair_wanted",
    "cleaned_codex_env",
    "execute_repair",
    "find_codex",
    "maybe_auto_repair",
    "next_steps_text",
    "read_repair",
    "repair_json_path",
    "repair_prove_wanted",
    "resolve_source",
]

AUTO_REPAIR_ENV = "COREME_AUTO_REPAIR"
REPAIR_PROVE_ENV = "COREME_REPAIR_PROVE"
REPAIR_RERUN_ENV = "COREME_REPAIR_RERUN"
REPAIR_JSON = "repair.json"
REPAIR_BRIEF = "repair-brief.md"
_SKIP_DIR_NAMES = frozenset(
    {"releases", "runs", ".git", ".venv", "venv", "src", "tests", "__pycache__"}
)


@dataclass(frozen=True)
class RepairOutcome:
    """Result of an attempted repair (auto or manual --exec)."""

    status: str
    path: str
    trigger: str
    message: str = ""
    codex_exit_code: int | None = None
    source_path: str | None = None
    prove: dict[str, Any] | None = None
    rerun: dict[str, Any] | None = None


@dataclass(frozen=True)
class _OutcomeWriter:
    """Immutable serialization context for one repair attempt."""

    repair_file: Path
    trigger: str
    started: datetime
    source_path: Path | str | None = None
    brief_path: Path | None = None
    codex_available: bool = False
    sandbox: str | None = None
    codex_log: Path | None = None
    summary_path: Path | None = None

    def write(
        self,
        *,
        status: str,
        message: str,
        codex_exit_code: int | None = None,
        prove: dict[str, Any] | None = None,
        rerun: dict[str, Any] | None = None,
    ) -> RepairOutcome:
        finished = datetime.now(UTC)
        body: dict[str, Any] = {
            "v": 1,
            "status": status,
            "trigger": self.trigger,
            "codex_available": self.codex_available,
            "codex_exit_code": codex_exit_code,
            "source_path": (str(Path(self.source_path).resolve()) if self.source_path else None),
            "brief_path": str(self.brief_path.resolve()) if self.brief_path else None,
            "sandbox": self.sandbox,
            "codex_log": str(self.codex_log.resolve()) if self.codex_log else None,
            "summary_path": (str(self.summary_path.resolve()) if self.summary_path else None),
            "started_at": iso_utc(self.started),
            "finished_at": iso_utc(finished),
            "message": message,
            "prove": prove,
            "rerun": rerun,
        }
        self.repair_file.write_text(json_dumps(body), encoding="utf-8")
        return RepairOutcome(
            status=status,
            path=str(self.repair_file.resolve()),
            trigger=self.trigger,
            message=message,
            codex_exit_code=codex_exit_code,
            source_path=(str(Path(self.source_path).resolve()) if self.source_path else None),
            prove=prove,
            rerun=rerun,
        )


class RepairError(Exception):
    """Repair coordinator error (bad path, etc.)."""


def auto_repair_wanted(*, flag: bool | None, no_flag: bool) -> bool:
    """Resolve whether auto-repair should run.

    * ``--no-auto-repair`` always wins (author safety).
    * ``--auto-repair`` turns on.
    * Else ``COREME_AUTO_REPAIR`` truthy (1/true/yes/y/on).
    """
    if no_flag:
        return False
    if flag is True:
        return True
    return env_flag(AUTO_REPAIR_ENV)


def repair_prove_wanted(
    *,
    flag: bool = False,
    no_flag: bool = False,
    trigger: str = "manual",
) -> bool:
    """Whether to run offline ``coreme test`` after Codex exit 0.

    * ``--no-repair-prove`` wins.
    * ``--repair-prove`` turns on.
    * Auto path defaults **on** (unless env ``COREME_REPAIR_PROVE=0``).
    * Manual defaults **off** unless flag or env truthy.
    """
    if no_flag:
        return False
    if flag:
        return True
    if REPAIR_PROVE_ENV in os.environ:
        return env_flag(REPAIR_PROVE_ENV)
    # Auto: prove by default. Manual: opt-in.
    return trigger == "auto"


def repair_rerun_wanted() -> bool:
    """Optional one source re-run after Codex 0 + prove (env only; default off)."""
    return env_flag(REPAIR_RERUN_ENV)


def execute_repair(
    run_path: str | Path,
    *,
    repo_root: Path,
    trigger: str = "manual",
    prove: bool | None = None,
    prove_flag: bool = False,
    no_prove_flag: bool = False,
    log_lines: int = 80,
    codex_timeout_sec: int | None = DEFAULT_CODEX_TIMEOUT_SEC,
    spawn: Callable[..., int] | None = None,
    progress: Callable[[str], None] | None = None,
    quiet: bool | None = None,
) -> RepairOutcome:
    """Write brief, spawn Codex (if available), write repair.json. Never masks Job failure."""
    root = Path(run_path).resolve()
    if not root.is_dir():
        raise RepairError(f"not a Run directory: {run_path}")

    run_data = load_run_json(root) or {}
    started = datetime.now(UTC)
    source = resolve_source(root, repo_root, run_data=run_data)
    brief_path = root / REPAIR_BRIEF
    repair_file = root / REPAIR_JSON
    codex_log = root / CODEX_LOG
    summary_path = root / CODEX_SUMMARY
    outcome_writer = _OutcomeWriter(repair_file, trigger, started)

    if prove is None:
        prove = repair_prove_wanted(
            flag=prove_flag,
            no_flag=no_prove_flag,
            trigger=trigger,
        )

    def _prog(msg: str) -> None:
        if progress is not None:
            progress(msg)
        else:
            print(msg, flush=True)

    # Always assemble + write brief for audit (even if we skip spawn).
    try:
        brief_text = assemble_brief(root, log_lines=log_lines, source_path=source)
    except BriefError as error:
        return replace(outcome_writer, sandbox=resolve_sandbox()).write(
            status="error",
            message=str(error),
        )

    brief_path.write_text(brief_text, encoding="utf-8")
    outcome_writer = replace(outcome_writer, brief_path=brief_path)

    if source is None:
        _prog("repair: skipped (no source path; will not patch releases/)")
        append_event(
            root,
            "repair.end",
            level="warn",
            status="skipped_no_source",
            trigger=trigger,
            message="no editable source resolved",
        )
        return replace(
            outcome_writer,
            codex_available=bool(find_codex()),
            sandbox=resolve_sandbox(),
        ).write(
            status="skipped_no_source",
            message="No editable source resolved; releases/ left untouched",
        )

    codex = find_codex()
    if not codex:
        _prog("repair: codex missing on PATH")
        append_event(
            root,
            "repair.end",
            level="warn",
            status="codex_missing",
            trigger=trigger,
            message="codex not found on PATH",
            source_path=str(source),
        )
        return replace(
            outcome_writer,
            source_path=source,
            sandbox=resolve_sandbox(),
        ).write(
            status="codex_missing",
            message="codex not found on PATH; install Codex CLI for host repair",
        )

    secret_names = list(run_data.get("secrets") or [])
    log_text = ""
    log_file = root / "log.txt"
    if log_file.is_file():
        try:
            log_text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
    crash = extract_crash_signature(log_text)
    fail_png = find_fail_png(root)

    prompt = codex_prompt(
        brief_path,
        source,
        root,
        crash_signature=crash,
        fail_png=fail_png,
    )

    add_dirs: list[Path] = []
    # Allow reading/writing evidence under the Run and repo root (workspace-write).
    add_dirs.append(root)
    try:
        repo = Path(repo_root).resolve()
        if repo.is_dir() and repo != source.resolve():
            add_dirs.append(repo)
    except OSError:
        pass

    sandbox = resolve_sandbox()
    outcome_writer = replace(
        outcome_writer,
        source_path=source,
        codex_available=True,
        sandbox=sandbox,
    )
    argv = codex_argv(
        codex,
        source,
        prompt,
        sandbox=sandbox,
        add_dirs=add_dirs,
        images=[fail_png] if fail_png is not None else None,
        output_last_message=summary_path,
    )

    _prog(f"repair: deploying Codex (sandbox={sandbox})…")
    append_event(
        root,
        "repair.start",
        trigger=trigger,
        source_path=str(source),
        brief_path=str(brief_path.resolve()),
        sandbox=sandbox,
    )

    env = cleaned_codex_env(secret_names)
    try:
        if spawn is None:
            exit_code = default_spawn(
                argv,
                cwd=str(source),
                env=env,
                timeout_sec=codex_timeout_sec,
                log_path=codex_log,
                quiet=quiet,
            )
        else:
            exit_code = spawn(
                argv,
                cwd=str(source),
                env=env,
                timeout_sec=codex_timeout_sec,
            )
    except subprocess.TimeoutExpired:
        _prog("repair: Codex timed out")
        append_event(
            root,
            "repair.end",
            level="error",
            status="error",
            trigger=trigger,
            message="codex timed out",
            source_path=str(source),
        )
        return replace(
            outcome_writer,
            codex_log=codex_log if codex_log.is_file() else None,
        ).write(
            status="error",
            message=f"codex timed out after {codex_timeout_sec}s",
        )
    except OSError as error:
        _prog(f"repair: failed to start Codex: {error}")
        append_event(
            root,
            "repair.end",
            level="error",
            status="error",
            trigger=trigger,
            message=str(error),
            source_path=str(source),
        )
        return replace(
            outcome_writer,
            codex_log=codex_log if codex_log.is_file() else None,
        ).write(
            status="error",
            message=f"failed to start codex: {error}",
        )

    prove_result: dict[str, Any] | None = None
    if prove and exit_code == 0:
        prove_result = run_prove(source)
        _prog(
            f"repair: prove exit_code={prove_result.get('exit_code')} "
            f"({prove_result.get('status')})"
        )

    rerun_result: dict[str, Any] | None = None
    if (
        repair_rerun_wanted()
        and exit_code == 0
        and (prove_result is None or prove_result.get("exit_code") == 0)
    ):
        rerun_result = _maybe_rerun_source(source, repo_root=repo_root, progress=_prog)

    status = "finished"
    message = (
        f"Codex process exited {exit_code}; re-prove source before ship"
        if exit_code == 0
        else f"Codex process exited {exit_code}"
    )
    if prove_result is not None:
        message += f"; prove={prove_result.get('status')}"
    if rerun_result is not None:
        message += f"; rerun_exit={rerun_result.get('exit_code')}"
    _prog(f"repair: finished (codex exit {exit_code})")
    if codex_log.is_file():
        _prog(f"repair: codex_log={codex_log}")
    if summary_path.is_file():
        _prog(f"repair: summary={summary_path}")
    append_event(
        root,
        "repair.end",
        level="info" if exit_code == 0 else "warn",
        status=status,
        trigger=trigger,
        codex_exit_code=exit_code,
        source_path=str(source),
        message=message,
        sandbox=sandbox,
    )
    return replace(
        outcome_writer,
        codex_log=codex_log if codex_log.is_file() else None,
        summary_path=summary_path if summary_path.is_file() else None,
    ).write(
        status=status,
        message=message,
        codex_exit_code=exit_code,
        prove=prove_result,
        rerun=rerun_result,
    )


def maybe_auto_repair(
    run_path: str | Path,
    *,
    repo_root: Path,
    status: str,
    exit_code: int,
    prove: bool | None = None,
    prove_flag: bool = False,
    no_prove_flag: bool = False,
    progress: Callable[[str], None] | None = None,
) -> RepairOutcome | None:
    """If this Run failed and has fail.json, run one Codex deploy. Else None."""
    if status == "succeeded" or exit_code == 0:
        return None
    root = Path(run_path)
    if not fail_path(root).is_file():
        return None
    return execute_repair(
        root,
        repo_root=repo_root,
        trigger="auto",
        prove=prove,
        prove_flag=prove_flag,
        no_prove_flag=no_prove_flag,
        progress=progress,
    )


def repair_json_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / REPAIR_JSON


def read_repair(run_dir: str | Path) -> dict[str, Any] | None:
    path = repair_json_path(run_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_source(
    run_path: str | Path,
    repo_root: Path,
    *,
    run_data: dict[str, Any] | None = None,
) -> Path | None:
    """Locate the editable source Job for this Run. Never returns a release path to patch."""
    root = Path(run_path).resolve()
    data = run_data if run_data is not None else load_run_json(root)
    if not data:
        return None

    job_name = str(data.get("job") or "")
    is_release = bool(data.get("release"))
    job_path_raw = data.get("job_path")
    job_path = Path(str(job_path_raw)).resolve() if job_path_raw else None

    if not is_release:
        if job_path is not None and is_job_dir(job_path, expected_name=job_name or None):
            if looks_like_release(job_path):
                return find_source_by_name(repo_root, job_name) if job_name else None
            return job_path
        if job_name:
            return find_source_by_name(repo_root, job_name)
        return None

    if not job_name:
        return None
    return find_source_by_name(repo_root, job_name)


def load_run_json(run_path: Path) -> dict[str, Any] | None:
    path = run_path / "run.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def is_job_dir(path: Path, *, expected_name: str | None = None) -> bool:
    if not path.is_dir() or not (path / "JOB.toml").is_file():
        return False
    try:
        manifest = load_manifest(path)
    except ManifestError:
        return False
    if expected_name is None:
        return True
    return manifest.name == expected_name


def looks_like_release(path: Path) -> bool:
    if (path / "RELEASE.json").is_file():
        return True
    parts = {p.lower() for p in path.parts}
    return "releases" in parts


def find_source_by_name(repo_root: Path, job_name: str) -> Path | None:
    if not job_name:
        return None
    root = repo_root.resolve()
    preferred = [
        root / job_name,
        root / "examples" / job_name,
    ]
    for candidate in preferred:
        if is_job_dir(candidate, expected_name=job_name) and not looks_like_release(candidate):
            return candidate.resolve()

    matches: list[Path] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir():
            continue
        if child.name in _SKIP_DIR_NAMES:
            continue
        if looks_like_release(child):
            continue
        if is_job_dir(child, expected_name=job_name):
            matches.append(child.resolve())
        if child.name == "examples":
            continue
        try:
            sub_children = list(child.iterdir())
        except OSError:
            continue
        for sub in sub_children:
            if (
                sub.is_dir()
                and is_job_dir(sub, expected_name=job_name)
                and not looks_like_release(sub)
            ):
                matches.append(sub.resolve())

    uniq: list[Path] = []
    seen: set[str] = set()
    for match in matches:
        key = str(match)
        if key not in seen:
            seen.add(key)
            uniq.append(match)
    if len(uniq) == 1:
        return uniq[0]
    named = [m for m in uniq if m.name == job_name]
    if len(named) == 1:
        return named[0]
    return None


def next_steps_text(source_path: str | None) -> str:
    """Human next steps after ``coreme repair`` (no spawn)."""
    src = source_path or "<source-job>"
    return "\n".join(
        [
            "## Next steps",
            "",
            "1. Read the brief above (crash signature, fail.json / log.txt / events.jsonl).",
            f"2. Patch **source** only: `{src}` — never `releases/`.",
            f"3. Prove: `coreme test {src}`",
            f"4. Re-run source: `coreme run {src}`",
            "5. Ship only if a human asked: bump version + `coreme ship` (never auto).",
            "6. Or spawn host Codex now: `coreme repair <run_path> --exec`",
            "7. Prod auto path: `coreme run <job>` with "
            "`COREME_AUTO_REPAIR=1` (or `--auto-repair`).",
            "8. Full Codex session log lives on the Run as `codex.log` when repair ran.",
            "",
        ]
    )


def _maybe_rerun_source(
    source: Path,
    *,
    repo_root: Path,
    progress: Callable[[str], None],
) -> dict[str, Any]:
    """One offline-safe re-run of source after a successful Codex+prove (opt-in)."""
    from coreme.runner import run_job

    progress("repair: re-running source once (COREME_REPAIR_RERUN=1)…")
    try:
        record = run_job(source, repo_root=repo_root)
    except Exception as error:  # surface as rerun failure, not a traceback wall
        return {
            "status": "error",
            "exit_code": None,
            "message": str(error),
            "run_path": None,
        }
    return {
        "status": record.status,
        "exit_code": record.exit_code,
        "run_path": record.run_path,
        "message": f"source re-run status={record.status} exit={record.exit_code}",
    }

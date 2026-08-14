"""Stage a mid-chain Run artifact and print (or exec) a seeded re-run command.

Always a **new** Run via existing ``seed`` file input + optional Job ``only`` /
``skip`` — not resume, not a phase DAG, not auto-ship.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Names that are common evidence/noise, not handoff seeds.
_NOISE_NAMES = frozenset({"fail.png", "result.txt", "operator.txt"})


class SeedFromFailError(Exception):
    """User-facing seed-from-fail failure (missing Run, ambiguous artifact, …)."""


@dataclass(frozen=True)
class SeedPlan:
    """Resolved artifact + staged path + suggested ``coreme run`` argv."""

    run_path: Path
    artifact_src: Path
    artifact_name: str
    stage_dir: Path
    staged_path: Path
    job_ref: str
    only: str | None
    command: list[str]
    notes: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def command_text(self) -> str:
        return " ".join(_quote_arg(a) for a in self.command)


def seed_from_fail(
    run_path: str | Path,
    *,
    artifact: str | None = None,
    only: str | None = None,
    job: str | Path | None = None,
    stage_dir: str | Path | None = None,
    dry_run: bool = False,
    workspace: str | Path | None = None,
    cwd: str | Path | None = None,
) -> SeedPlan:
    """Resolve and optionally stage a seeded re-run plan.

    Always returns a :class:`SeedPlan`. When *dry_run* is false, copies the
    artifact into the stage directory. Does **not** invoke ``coreme run`` —
    callers print with :func:`format_plan_text` and exec with
    :func:`run_seed_plan` (CLI ``--exec`` uses that path).
    """
    plan = build_seed_plan(
        run_path,
        artifact=artifact,
        only=only,
        job=job,
        stage_dir=stage_dir,
        dry_run=dry_run,
        workspace=workspace,
        cwd=cwd,
    )
    if not dry_run:
        stage_artifact(plan)
    return plan


def build_seed_plan(
    run_path: str | Path,
    *,
    artifact: str | None = None,
    only: str | None = None,
    job: str | Path | None = None,
    stage_dir: str | Path | None = None,
    dry_run: bool = False,
    workspace: str | Path | None = None,
    cwd: str | Path | None = None,
) -> SeedPlan:
    """Resolve artifact and command without copying (unless caller stages later)."""
    root = Path(run_path).resolve()
    if not root.is_dir():
        raise SeedFromFailError(f"not a Run directory: {run_path}")
    run_json = root / "run.json"
    if not run_json.is_file():
        raise SeedFromFailError(f"missing run.json under {root}")

    run_data = _load_run_json(run_json)
    job_path = resolve_job_folder(job=job, run_data=run_data)
    job_ref = resolve_job_ref_for_command(job=job, job_path=job_path, run_data=run_data)
    artifact_src = resolve_artifact(root, artifact=artifact, job_path=job_path)

    ws = Path(workspace).resolve() if workspace is not None else infer_workspace(root, cwd=cwd)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    job_name = _safe_job_name(run_data.get("job"), job_ref, root.name)
    dest_dir = (
        Path(stage_dir).resolve()
        if stage_dir is not None
        else (ws / ".coreme-seed" / f"{job_name}-{stamp}").resolve()
    )
    staged_path = dest_dir / artifact_src.name

    only_clean = only.strip() if only and only.strip() else None
    command = build_run_command(job_ref, seed_path=staged_path, only=only_clean)

    notes: list[str] = []
    if only_clean is None:
        notes.append(
            "No --only given: add --input only=<phases> or --input skip=<phases> "
            "if you are retrying mid-chain (seed alone re-runs the Job defaults)."
        )
    notes.append("Always a new Run (not resume). Secrets still come from process env.")

    return SeedPlan(
        run_path=root,
        artifact_src=artifact_src,
        artifact_name=artifact_src.name,
        stage_dir=dest_dir,
        staged_path=staged_path,
        job_ref=job_ref,
        only=only_clean,
        command=command,
        notes=notes,
        dry_run=dry_run,
    )


def stage_artifact(plan: SeedPlan) -> Path:
    """Copy the resolved artifact into the stage directory. Returns staged path."""
    plan.stage_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan.artifact_src, plan.staged_path)
    return plan.staged_path


def run_seed_plan(plan: SeedPlan, *, cwd: str | Path | None = None) -> int:
    """Invoke ``python -m coreme run …`` with the plan command. Returns exit code."""
    # plan.command is ["coreme", "run", ...] — rewrite to module form for reliability.
    if len(plan.command) < 2 or plan.command[0] != "coreme":
        raise SeedFromFailError(f"internal: unexpected command: {plan.command!r}")
    argv = [sys.executable, "-m", "coreme", *plan.command[1:]]
    work = Path(cwd).resolve() if cwd is not None else Path.cwd()
    completed = subprocess.run(argv, cwd=str(work), check=False)
    return int(completed.returncode)


def format_plan_text(plan: SeedPlan) -> str:
    """Human-readable plan (no secrets)."""
    lines = [
        f"run_path={plan.run_path}",
        f"artifact={plan.artifact_src}",
        f"stage_dir={plan.stage_dir}",
        f"staged={plan.staged_path}",
        f"job_ref={plan.job_ref}",
        f"dry_run={plan.dry_run}",
        f"command={plan.command_text}",
    ]
    for note in plan.notes:
        lines.append(f"note={note}")
    return "\n".join(lines) + "\n"


def resolve_job_folder(
    *,
    job: str | Path | None,
    run_data: dict[str, Any],
) -> Path | None:
    """Job directory for handoffs.toml (if known and exists)."""
    if job is not None:
        path = Path(job).resolve()
        if not path.is_dir():
            raise SeedFromFailError(f"--job is not a directory: {job}")
        return path
    raw = run_data.get("job_path")
    if raw:
        path = Path(str(raw))
        if path.is_dir():
            return path.resolve()
    return None


def resolve_job_ref_for_command(
    *,
    job: str | Path | None,
    job_path: Path | None,
    run_data: dict[str, Any],
) -> str:
    """String used as the first argument to ``coreme run``."""
    if job is not None:
        return str(Path(job).resolve())
    if job_path is not None:
        return str(job_path)
    name = run_data.get("job")
    if isinstance(name, str) and name.strip():
        return name.strip()
    raise SeedFromFailError(
        "cannot determine Job for re-run: pass --job PATH "
        "(run.json has no usable job_path or job name)"
    )


def resolve_artifact(
    run_path: Path,
    *,
    artifact: str | None = None,
    job_path: Path | None = None,
) -> Path:
    """Pick the durable artifact file under ``run_path/artifacts/``."""
    artifacts = run_path / "artifacts"
    if artifact:
        # Bare file name only — reject separators / traversal.
        norm = artifact.replace("\\", "/")
        if "/" in norm or artifact in {".", ".."} or Path(artifact).name != artifact:
            raise SeedFromFailError(
                f"--artifact must be a file name under artifacts/, not a path: {artifact}"
            )
        candidate = artifacts / artifact
        if not candidate.is_file():
            available = _list_artifact_names(artifacts)
            raise SeedFromFailError(
                f"artifact not found: {candidate}" + _available_suffix(available)
            )
        return candidate.resolve()

    # handoffs.toml seed_candidates (first existing)
    if job_path is not None:
        for name in load_seed_candidates(job_path):
            candidate = artifacts / name
            if candidate.is_file():
                return candidate.resolve()

    # Auto: exactly one non-noise file
    files = _list_artifact_files(artifacts)
    non_noise = [p for p in files if not is_noise_artifact(p.name)]
    if len(non_noise) == 1:
        return non_noise[0].resolve()

    available = [p.name for p in files]
    if not available:
        raise SeedFromFailError(
            f"no files under {artifacts}; pass --artifact after a Run that wrote handoffs"
        )
    if len(non_noise) == 0:
        raise SeedFromFailError(
            "only noise artifacts found "
            f"(excluded: fail.png, result.txt, operator.txt, *.log); "
            f"pass --artifact NAME{_available_suffix(available)}"
        )
    raise SeedFromFailError(
        "multiple artifact candidates; pass --artifact NAME" + _available_suffix(available)
    )


def load_seed_candidates(job_path: Path) -> list[str]:
    """Read optional Job ``handoffs.toml`` → ``seed_candidates`` list.

    Missing file or key → empty list. Not part of strict JOB.toml.
    """
    path = Path(job_path) / "handoffs.toml"
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = tomllib.loads(raw)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SeedFromFailError(f"cannot parse handoffs.toml at {path}: {error}") from error
    if not isinstance(data, dict):
        return []
    cands = data.get("seed_candidates")
    if not isinstance(cands, list):
        return []
    out: list[str] = []
    for item in cands:
        if isinstance(item, str) and item.strip():
            # Bare names only.
            name = item.strip().replace("\\", "/")
            if "/" in name or name in {".", ".."}:
                continue
            out.append(name)
    return out


def is_noise_artifact(name: str) -> bool:
    return name in _NOISE_NAMES or name.lower().endswith(".log")


def infer_workspace(run_path: Path, *, cwd: str | Path | None = None) -> Path:
    """Prefer parent of ``runs/`` when *run_path* lives under ``…/runs/<run>``."""
    resolved = Path(run_path).resolve()
    if resolved.parent.name.lower() == "runs":
        return resolved.parent.parent
    return Path(cwd or Path.cwd()).resolve()


def build_run_command(
    job_ref: str,
    *,
    seed_path: Path,
    only: str | None = None,
) -> list[str]:
    """Argv-style command starting with ``coreme`` (display + rewrite for --exec)."""
    cmd = [
        "coreme",
        "run",
        job_ref,
        "--input",
        f"seed={seed_path}",
    ]
    if only:
        cmd.extend(["--input", f"only={only}"])
    return cmd


def _load_run_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SeedFromFailError(f"cannot read run.json: {error}") from error
    if not isinstance(data, dict):
        raise SeedFromFailError("run.json must be a JSON object")
    return data


def _list_artifact_files(artifacts: Path) -> list[Path]:
    if not artifacts.is_dir():
        return []
    try:
        return sorted(p for p in artifacts.iterdir() if p.is_file())
    except OSError as error:
        raise SeedFromFailError(f"cannot list artifacts: {error}") from error


def _list_artifact_names(artifacts: Path) -> list[str]:
    return [p.name for p in _list_artifact_files(artifacts)]


def _available_suffix(names: list[str]) -> str:
    if not names:
        return " (artifacts/ empty or missing)"
    return f"\navailable: {', '.join(names)}"


def _safe_job_name(*candidates: Any) -> str:
    for raw in candidates:
        if not raw:
            continue
        text = str(raw).strip()
        if not text:
            continue
        # Prefer last path segment if it looks like a path.
        name = Path(text).name or text
        cleaned = "".join(c if c.isalnum() or c in "-_." else "-" for c in name)
        cleaned = cleaned.strip(".-") or "job"
        return cleaned[:80]
    return "job"


def _quote_arg(arg: str) -> str:
    if not arg:
        return '""'
    if any(ch in arg for ch in ' \t\n"'):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg

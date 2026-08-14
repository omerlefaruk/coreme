"""seed-from-fail: stage Run artifact + suggest/exec seeded coreme run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coreme.cli import main as cli_main
from coreme.seed_from_fail import (
    SeedFromFailError,
    build_seed_plan,
    format_plan_text,
    is_noise_artifact,
    load_seed_candidates,
    resolve_artifact,
    seed_from_fail,
    stage_artifact,
)


def _write_run(
    root: Path,
    *,
    job: str = "phased-demo",
    job_path: Path | None = None,
    artifacts: dict[str, str] | None = None,
    run_json: bool = True,
) -> Path:
    """Create a fake Run directory under root/runs/<job>-fake."""
    run = root / "runs" / f"{job}-fake"
    run.mkdir(parents=True, exist_ok=True)
    arts = run / "artifacts"
    arts.mkdir(exist_ok=True)
    for name, body in (artifacts or {"prepared.txt": "prepared body\n"}).items():
        (arts / name).write_text(body, encoding="utf-8")
    if run_json:
        data = {
            "job": job,
            "version": "0.1.0",
            "status": "failed",
            "exit_code": 1,
            "job_path": str(job_path) if job_path is not None else "",
            "run_path": str(run),
            "inputs": {},
            "secrets": [],
            "release": False,
        }
        (run / "run.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return run


def test_stages_copy_and_command_includes_seed(tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "phased-demo"
    job.mkdir(parents=True)
    (job / "JOB.toml").write_text('name = "phased-demo"\n', encoding="utf-8")
    run = _write_run(tmp_path, job_path=job)

    plan = seed_from_fail(run, only="report", workspace=tmp_path)
    assert plan.staged_path.is_file()
    assert plan.staged_path.read_text(encoding="utf-8") == "prepared body\n"
    assert "seed=" in plan.command_text
    assert str(plan.staged_path) in plan.command_text
    assert "only=report" in plan.command_text
    assert plan.job_ref == str(job.resolve())
    assert ".coreme-seed" in str(plan.stage_dir)


def test_artifact_required_when_multiple_candidates(tmp_path: Path) -> None:
    run = _write_run(
        tmp_path,
        artifacts={
            "prepared.txt": "a\n",
            "manager.xml": "<x/>\n",
        },
    )
    with pytest.raises(SeedFromFailError, match="multiple artifact"):
        build_seed_plan(run, workspace=tmp_path)

    plan = build_seed_plan(run, artifact="manager.xml", workspace=tmp_path)
    assert plan.artifact_name == "manager.xml"


def test_missing_run_json_errors(tmp_path: Path) -> None:
    run = _write_run(tmp_path, run_json=False)
    with pytest.raises(SeedFromFailError, match="run.json"):
        build_seed_plan(run, workspace=tmp_path)


def test_dry_run_does_not_create_stage_files(tmp_path: Path) -> None:
    run = _write_run(tmp_path)
    plan = seed_from_fail(run, dry_run=True, workspace=tmp_path)
    assert plan.dry_run is True
    assert not plan.staged_path.exists()
    assert not plan.stage_dir.exists()
    assert "seed=" in plan.command_text
    # Explicit stage later still works.
    stage_artifact(plan)
    assert plan.staged_path.is_file()


def test_noise_artifacts_excluded_from_auto_pick(tmp_path: Path) -> None:
    run = _write_run(
        tmp_path,
        artifacts={
            "fail.png": "x",
            "result.txt": "y",
            "operator.txt": "z",
            "session.log": "log",
            "prepared.txt": "good\n",
        },
    )
    plan = build_seed_plan(run, workspace=tmp_path)
    assert plan.artifact_name == "prepared.txt"


def test_handoffs_toml_picks_first_existing(tmp_path: Path) -> None:
    job = tmp_path / "myjob"
    job.mkdir()
    (job / "handoffs.toml").write_text(
        'seed_candidates = ["missing.txt", "prepared.txt", "other.txt"]\n',
        encoding="utf-8",
    )
    run = _write_run(
        tmp_path,
        job="myjob",
        job_path=job,
        artifacts={
            "prepared.txt": "p\n",
            "other.txt": "o\n",
            "extra.txt": "e\n",
        },
    )
    plan = build_seed_plan(run, workspace=tmp_path)
    assert plan.artifact_name == "prepared.txt"
    assert load_seed_candidates(job) == ["missing.txt", "prepared.txt", "other.txt"]


def test_cli_seed_from_fail_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _write_run(tmp_path)
    code = cli_main(
        [
            "seed-from-fail",
            str(run),
            "--dry-run",
            "--only",
            "report",
            "--stage-dir",
            str(tmp_path / "stage"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "seed=" in out
    assert "only=report" in out
    assert "dry_run=True" in out
    assert not (tmp_path / "stage").exists()


def test_cli_missing_run_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_main(["seed-from-fail", str(tmp_path / "nope")])
    assert code == 2
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "error:" in text or "not a Run" in text


def test_cli_missing_run_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = tmp_path / "emptyrun"
    empty.mkdir()
    code = cli_main(["seed-from-fail", str(empty)])
    assert code == 2
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "run.json" in text


def test_format_plan_text_has_keys(tmp_path: Path) -> None:
    run = _write_run(tmp_path)
    plan = build_seed_plan(run, only="report", workspace=tmp_path)
    text = format_plan_text(plan)
    assert "command=" in text
    assert "artifact=" in text
    assert "only=report" in text


def test_is_noise_artifact() -> None:
    assert is_noise_artifact("fail.png")
    assert is_noise_artifact("result.txt")
    assert is_noise_artifact("operator.txt")
    assert is_noise_artifact("codex.log")
    assert not is_noise_artifact("prepared.txt")


def test_resolve_artifact_explicit(tmp_path: Path) -> None:
    run = _write_run(
        tmp_path,
        artifacts={"a.txt": "1", "b.txt": "2"},
    )
    path = resolve_artifact(run, artifact="b.txt")
    assert path.name == "b.txt"
    with pytest.raises(SeedFromFailError, match="not a path"):
        resolve_artifact(run, artifact="../escape.txt")


def test_job_name_fallback_without_job_path(tmp_path: Path) -> None:
    run = _write_run(tmp_path, job="demo-job", job_path=None)
    # Clear job_path in run.json
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    data["job_path"] = ""
    (run / "run.json").write_text(json.dumps(data) + "\n", encoding="utf-8")
    plan = build_seed_plan(run, workspace=tmp_path)
    assert plan.job_ref == "demo-job"
    assert "seed=" in plan.command_text

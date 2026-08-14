"""Day 1 hardening: failure / timeout / init / CLI wiring.

Covers the gaps listed in the "Medium — worth fixing" note:
  * non-zero entry exit -> status failed, CLI exit != 0, log captured
  * timeout -> 124 + timeout line in log.txt
  * init on empty vs non-empty path
  * CLI main(["run", ...]) / main(["test", ...]) / main(["init", ...]) wiring
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from helpers import make_repo, write_job

from coreme import _process as process_module
from coreme._process import ProcessError
from coreme.cli import main as cli_main
from coreme.events import read_events
from coreme.init import InitError, init_job
from coreme.proof import test_job as prove_job
from coreme.runner import run_job


def _write_job(
    tmp: Path,
    offline: str = "pytest -q",
    timeout_sec: int | None = None,
    entry_content: str = "print('x')\n",
) -> Path:
    return write_job(
        tmp,
        offline=offline,
        timeout_sec=timeout_sec,
        entry_content=entry_content,
    )


def _repo(tmp: Path) -> Path:
    return make_repo(tmp)


# ---------------------------------------------------------------------------
# non-zero entry exit
# ---------------------------------------------------------------------------


def test_run_nonzero_exit_status_failed(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "j",
        entry_content="import sys; print('boom', file=sys.stderr); sys.exit(7)\n",
    )
    repo = _repo(tmp_path)
    record = run_job(job, repo_root=repo)
    assert record.exit_code == 7
    assert record.status == "failed"
    log = (Path(record.run_path) / "log.txt").read_text(encoding="utf-8")
    assert "boom" in log
    data = json.loads((Path(record.run_path) / "run.json").read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["exit_code"] == 7


def test_cli_run_nonzero_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _write_job(
        tmp_path / "j2",
        entry_content="import sys; sys.exit(3)\n",
    )
    repo = _repo(tmp_path)
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["run", str(job)])

    assert code == 3
    assert next((repo / "runs").glob("demo-*/run.json")).is_file()


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------


def test_offline_proof_timeout_returns_124(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = write_job(
        tmp_path / "job",
        proof_py="import time; time.sleep(2)\n",
        timeout_sec=1,
    )

    assert prove_job(job) == 124
    assert "offline proof timed out after 1s" in capsys.readouterr().err


def test_run_timeout_124_and_log_line(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "jt",
        timeout_sec=1,
        entry_content="import time; time.sleep(10)\n",
    )
    repo = _repo(tmp_path)
    record = run_job(job, repo_root=repo)
    assert record.exit_code == 124
    assert record.status == "failed"
    log = (Path(record.run_path) / "log.txt").read_text(encoding="utf-8")
    assert "timeout after 1s" in log
    assert "exit_code=124" in log
    data = json.loads((Path(record.run_path) / "run.json").read_text(encoding="utf-8"))
    assert data["exit_code"] == 124
    assert data["status"] == "failed"


def test_run_contains_child_before_job_code_starts(tmp_path: Path) -> None:
    marker = tmp_path / "late.txt"
    job = _write_job(
        tmp_path / "job-tree",
        timeout_sec=1,
        entry_content=("import subprocess, sys\nsubprocess.Popen([sys.executable, 'child.py'])\n"),
    )
    (job / "child.py").write_text(
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(3)\n"
        "print('late child output')\n"
        f"Path({str(marker)!r}).write_text('late', encoding='utf-8')\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    record = run_job(job, repo_root=_repo(tmp_path))

    assert record.exit_code == 124
    assert time.monotonic() - started < 2
    log = (Path(record.run_path) / "log.txt").read_text(encoding="utf-8")
    assert "late child output" not in log
    assert "timeout after 1s" in log
    time.sleep(2.5)
    assert not marker.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
def test_assignment_failure_reaps_suspended_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "started.txt"
    started: list[process_module.subprocess.Popen[str]] = []
    real_popen = process_module.subprocess.Popen

    def record_process(*args: object, **kwargs: object):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    def fail_assignment(
        job: process_module._WindowsJob,
        process: process_module.subprocess.Popen[str],
    ) -> None:
        raise ProcessError("assignment failed")

    monkeypatch.setattr(process_module.subprocess, "Popen", record_process)
    monkeypatch.setattr(process_module._WindowsJob, "assign", fail_assignment)
    try:
        with pytest.raises(ProcessError, match="assignment failed"):
            process_module.run_process(
                [
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
                ],
                cwd=tmp_path,
                timeout_sec=5,
            )

        assert len(started) == 1
        assert started[0].poll() is not None
        assert not marker.exists()
    finally:
        if started and started[0].poll() is None:
            started[0].kill()
            started[0].wait()


def test_cli_run_timeout_exits_124(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _write_job(
        tmp_path / "jt2",
        timeout_sec=1,
        entry_content="import time; time.sleep(10)\n",
    )
    repo = _repo(tmp_path)
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["run", str(job)])

    assert code == 124
    assert next((repo / "runs").glob("demo-*/run.json")).is_file()


# ---------------------------------------------------------------------------
# ProcessError containment failures (complete Run evidence, honest CLI exit)
# ---------------------------------------------------------------------------


def test_process_error_writes_complete_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ProcessError after Run creation still yields log.txt, a terminal lifecycle
    event (kind=process_error), fail.json, and run.json."""
    job = _write_job(
        tmp_path / "jpe",
        entry_content="print('never', flush=True)\n",
    )
    repo = _repo(tmp_path)
    error = ProcessError("Cannot stop process tree")
    error.stdout = "partial job output\n"

    def boom(*_args: object, **_kwargs: object) -> tuple[int, str, str, bool]:
        raise error

    monkeypatch.setattr("coreme.runner.run_process", boom)
    record = run_job(job, repo_root=repo)

    assert record.status == "failed"
    assert record.exit_code == 1
    run_dir = Path(record.run_path)
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    assert "partial job output" in log
    assert "[coreme] process containment error: Cannot stop process tree" in log
    rows = read_events(run_dir)
    names = [r["event"] for r in rows]
    assert names[0] == "run.start"
    assert names[-1] == "run.error"
    terminal = rows[-1]
    assert terminal["kind"] == "process_error"
    assert terminal["level"] == "error"
    assert terminal["status"] == "failed"
    summary = json.loads((run_dir / "fail.json").read_text(encoding="utf-8"))
    assert summary["kind"] == "process_error"
    assert summary["exit_code"] == 1
    assert summary["message"] == "process containment error: Cannot stop process tree"
    data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["exit_code"] == 1


def test_cli_run_process_error_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI honours the failed Run: exits nonzero matching run.json, instead of
    leaking a ProcessError without any Run evidence."""
    job = _write_job(
        tmp_path / "jpe-cli",
        entry_content="print('never', flush=True)\n",
    )
    repo = _repo(tmp_path)
    error = ProcessError("Cannot stop process tree")

    def boom(*_args: object, **_kwargs: object) -> tuple[int, str, str, bool]:
        raise error

    monkeypatch.setattr("coreme.runner.run_process", boom)
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["run", str(job)])

    assert code == 1
    run_json = next((repo / "runs").glob("demo-*/run.json"))
    data = json.loads(run_json.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["exit_code"] == 1


def test_run_process_attaches_partial_output_on_terminate_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ProcessError raised while stopping a timed-out process carries the
    partial child output so the runner can still write complete evidence."""
    import io

    def fail_terminate(
        process: process_module.subprocess.Popen[str],
        job: process_module._WindowsJob | None,
    ) -> None:
        process.kill()
        process.wait(timeout=5)
        raise ProcessError("Cannot stop process tree")

    monkeypatch.setattr(process_module, "_terminate_process_tree", fail_terminate)
    with pytest.raises(ProcessError, match="Cannot stop process tree") as excinfo:
        process_module.run_process(
            [
                sys.executable,
                "-u",
                "-c",
                "import time; print('started', flush=True); time.sleep(30)",
            ],
            cwd=tmp_path,
            timeout_sec=1,
            stream=io.StringIO(),
        )
    assert "started" in excinfo.value.stdout


# ---------------------------------------------------------------------------
# init empty vs non-empty
# ---------------------------------------------------------------------------


def test_init_on_empty_path(tmp_path: Path) -> None:
    dest = tmp_path / "newjob"
    root = init_job(dest, "myjob")
    assert root.is_dir()
    assert (root / "JOB.toml").is_file()
    assert (root / "JOB.md").is_file()
    job_md = (root / "JOB.md").read_text(encoding="utf-8")
    assert job_md.startswith("# myjob\n")
    assert "## One sentence" in job_md
    assert "## Machine contract" in job_md
    assert (root / "main.py").is_file()
    assert (root / "tests" / "test_myjob.py").is_file()


def test_init_on_empty_existing_dir(tmp_path: Path) -> None:
    dest = tmp_path / "empty"
    dest.mkdir()
    root = init_job(dest, "myjob")
    assert root.is_dir()
    assert (dest / "JOB.toml").is_file()


def test_init_on_nonempty_refuses(tmp_path: Path) -> None:
    dest = tmp_path / "nonempty"
    dest.mkdir()
    (dest / "existing.txt").write_text("x", encoding="utf-8")
    with pytest.raises(InitError, match="non-empty"):
        init_job(dest, "myjob")


def test_init_on_existing_file_refuses(tmp_path: Path) -> None:
    destination = tmp_path / "existing.txt"
    destination.write_text("x", encoding="utf-8")

    with pytest.raises(InitError, match="not a directory"):
        init_job(destination, "myjob")


def test_init_nonexistent_parent_creates(tmp_path: Path) -> None:
    dest = tmp_path / "a" / "b" / "c"
    root = init_job(dest, "myjob")
    assert root.is_dir()
    assert (root / "JOB.toml").is_file()


def test_init_empty_name_rejected(tmp_path: Path) -> None:
    with pytest.raises(InitError, match="--name"):
        init_job(tmp_path / "j", "")


@pytest.mark.parametrize("name", ["1bad", "bad name", "../bad", "bad.py"])
def test_init_bad_name_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(InitError, match="identifier"):
        init_job(tmp_path / "j", name)


def test_cli_duplicate_input_returns_2_without_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _write_job(tmp_path / "input-job")
    manifest = (job / "JOB.toml").read_text(encoding="utf-8")
    (job / "JOB.toml").write_text(
        manifest + '\n[inputs.name]\ntype = "string"\nrequired = true\n',
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["run", str(job), "--input", "name=Ada", "--input", "name=Bob"])

    assert code == 2
    assert not (repo / "runs").exists()


# ---------------------------------------------------------------------------
# CLI main wiring
# ---------------------------------------------------------------------------


def test_cli_init_wiring(tmp_path: Path) -> None:
    dest = tmp_path / "cli_init"
    code = cli_main(["init", str(dest), "--name", "cli_demo"])
    assert code == 0
    assert (dest / "JOB.toml").is_file()
    assert (dest / "JOB.md").is_file()
    assert (dest / "main.py").is_file()


def test_cli_init_nonempty_returns_2(tmp_path: Path) -> None:
    dest = tmp_path / "cli_nonempty"
    dest.mkdir()
    (dest / "x").write_text("x", encoding="utf-8")
    code = cli_main(["init", str(dest), "--name", "cli_demo"])
    assert code == 2


def test_cli_test_wiring_pass(tmp_path: Path) -> None:
    job = tmp_path / "jtest"
    init_job(job, "jtest")
    # offline is "pytest -q" by default; should pass (tests/test_jtest.py exists)
    code = cli_main(["test", str(job)])
    assert code == 0


def test_cli_test_wiring_fail(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "jfail",
        offline="pytest -q",
        entry_content="print('hi')\n",
    )
    # make a failing offline test
    tdir = job / "tests"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "test_fail.py").write_text("def test_fail(): assert False\n", encoding="utf-8")
    (tdir / "__init__.py").write_text("", encoding="utf-8")
    code = cli_main(["test", str(job)])
    assert code != 0


def test_cli_run_wiring_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = tmp_path / "jrun"
    init_job(job, "jrun")
    (job / "main.py").write_text("print('ok')\n", encoding="utf-8")
    repo = _repo(tmp_path)
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["run", str(job)])

    assert code == 0
    assert next((repo / "runs").glob("jrun-*/run.json")).is_file()


def test_cli_run_missing_job_returns_2(tmp_path: Path) -> None:
    code = cli_main(["run", str(tmp_path / "nope")])
    assert code == 2


def test_cli_test_missing_job_returns_2(tmp_path: Path) -> None:
    code = cli_main(["test", str(tmp_path / "nope2")])
    assert code == 2


def test_cli_run_manifest_error_returns_2(tmp_path: Path) -> None:
    # job dir without JOB.toml
    d = tmp_path / "bad"
    d.mkdir()
    (d / "main.py").write_text("print('x')\n", encoding="utf-8")
    code = cli_main(["run", str(d)])
    assert code == 2

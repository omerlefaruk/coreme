"""Kernel guarantee: Job stdout streams live and stays unbuffered when piped."""

from __future__ import annotations

import sys
from pathlib import Path

from helpers import make_repo, write_job

from coreme.runner import run_job

_PROOF_OK = "raise SystemExit(0)\n"


def test_entry_command_forces_unbuffered_python(tmp_path: Path) -> None:
    job = write_job(
        tmp_path / "j",
        entry_content="print('hello')\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))

    assert record.status == "succeeded"
    assert record.command[0] == sys.executable
    assert record.command[1] == "-u"
    assert record.command[2] == "main.py"


def test_job_can_import_coreme_joblog(tmp_path: Path) -> None:
    """Day 6 helpers are a public import surface for Jobs under coreme run."""
    entry = """\
from coreme.joblog import say, emit
from pathlib import Path
import os
say("joblog-ok")
emit("domain", detail={"probe": 1})
Path(os.environ["COREME_ARTIFACTS_DIR"], "joblog.txt").write_text(
    "ok", encoding="utf-8"
)
"""
    job = write_job(
        tmp_path / "joblog",
        name="joblog",
        entry_content=entry,
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert record.status == "succeeded"
    run_path = Path(record.run_path)
    assert (run_path / "artifacts" / "joblog.txt").read_text(encoding="utf-8") == "ok"
    log = (run_path / "log.txt").read_text(encoding="utf-8")
    assert "joblog-ok" in log
    events = (run_path / "events.jsonl").read_text(encoding="utf-8")
    assert "domain" in events


def test_job_sees_pythonunbuffered_and_utf8_env(tmp_path: Path) -> None:
    entry = """\
import os
from pathlib import Path
Path(os.environ["COREME_ARTIFACTS_DIR"], "env.txt").write_text(
    "\\n".join(
        [
            f"PYTHONUNBUFFERED={os.environ.get('PYTHONUNBUFFERED', '')}",
            f"PYTHONUTF8={os.environ.get('PYTHONUTF8', '')}",
            f"PYTHONIOENCODING={os.environ.get('PYTHONIOENCODING', '')}",
        ]
    ),
    encoding="utf-8",
)
print("probe-ok", flush=True)
"""
    job = write_job(
        tmp_path / "envjob",
        name="envjob",
        entry_content=entry,
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    body = (Path(record.run_path) / "artifacts" / "env.txt").read_text(encoding="utf-8")
    assert record.status == "succeeded"
    assert "PYTHONUNBUFFERED=1" in body
    assert "PYTHONUTF8=1" in body
    assert "utf-8" in body.lower()
    log = (Path(record.run_path) / "log.txt").read_text(encoding="utf-8")
    assert "probe-ok" in log


def test_run_streams_stdout_to_caller_and_log(tmp_path: Path, capsys: object) -> None:
    entry = """\
import sys
print("step-a", flush=True)
print("step-b", flush=True)
sys.stdout.flush()
"""
    job = write_job(
        tmp_path / "stream",
        name="stream",
        entry_content=entry,
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    log = (Path(record.run_path) / "log.txt").read_text(encoding="utf-8")

    assert record.status == "succeeded"
    assert "step-a" in log and "step-b" in log
    assert "step-a" in captured.out and "step-b" in captured.out

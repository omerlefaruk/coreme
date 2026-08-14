"""Day 7: assemble_brief from Run evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import make_repo, write_job

from coreme.brief import BriefError, assemble_brief
from coreme.cli import main as cli_main
from coreme.runner import run_job


def _failed_run(tmp_path: Path, *, secrets: bool = False) -> tuple[Path, Path]:
    secrets_toml = ""
    if secrets:
        secrets_toml = '[secrets]\nnames = ["DEMO_SECRET"]\n'
    job = write_job(
        tmp_path / "demo",
        name="demo",
        entry_content=(
            "import sys\n"
            "from coreme.joblog import emit, say\n"
            "say('1/1 boom')\n"
            "emit('step.start', step=1, total=1, name='boom')\n"
            "emit('step.fail', step=1, name='boom', message='deliberate fail', level='error')\n"
            "sys.exit(1)\n"
        ),
        secrets_toml=secrets_toml,
    )
    repo = make_repo(tmp_path)
    if secrets:
        # runner needs secret present
        import os

        os.environ["DEMO_SECRET"] = "super-secret-value-xyz"
    try:
        record = run_job(job, repo_root=repo)
    finally:
        if secrets:
            os.environ.pop("DEMO_SECRET", None)
    assert record.status == "failed"
    return repo, Path(record.run_path)


def test_brief_from_failed_run(tmp_path: Path) -> None:
    _repo, run_path = _failed_run(tmp_path)
    text = assemble_brief(run_path, source_path=tmp_path / "demo")
    assert "coreme repair brief" in text
    assert "FAILED" in text
    assert "demo" in text
    assert "fail.json" in text or "fail.kind" in text
    assert "deliberate fail" in text or "exit" in text
    assert str((tmp_path / "demo").resolve()) in text or "demo" in text
    assert "Never" in text or "never" in text
    assert "releases/" in text
    assert "Do **not** add, enable, or reuse Job-owned runtime Codex" in text
    assert "never** call an LLM" not in text
    assert "Crash signature" in text
    assert "Done when" in text


def test_extract_crash_signature_from_traceback() -> None:
    from coreme.brief import extract_crash_signature

    log = (
        "1/3 Loading…\n"
        "Traceback (most recent call last):\n"
        '  File "main.py", line 10, in main\n'
        "    page.locator(\"button:has-text('StartChallenge')\").click()\n"
        "playwright._impl._errors.TimeoutError: Locator.click: Timeout 15000ms exceeded.\n"
        "waiting for locator(\"button:has-text('StartChallenge')\")\n"
    )
    sig = extract_crash_signature(log)
    assert "Traceback" in sig
    assert "StartChallenge" in sig
    assert "TimeoutError" in sig


def test_brief_success_run_is_non_failure(tmp_path: Path) -> None:
    job = write_job(
        tmp_path / "ok",
        name="ok",
        entry_content="print('ok')\n",
    )
    repo = make_repo(tmp_path)
    record = run_job(job, repo_root=repo)
    assert record.status == "succeeded"
    text = assemble_brief(record.run_path)
    assert "non-failure" in text or "success" in text.lower()
    assert "FAILED Run" not in text


def test_brief_secret_names_only_not_values(tmp_path: Path) -> None:
    _repo, run_path = _failed_run(tmp_path, secrets=True)
    text = assemble_brief(run_path)
    assert "DEMO_SECRET" in text
    assert "super-secret-value-xyz" not in text


def test_brief_cli_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, run_path = _failed_run(tmp_path)
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)
    out = tmp_path / "out.md"
    code = cli_main(["brief", str(run_path), "-o", str(out)])
    assert code == 0
    assert out.is_file()
    assert "repair brief" in out.read_text(encoding="utf-8")


def test_brief_missing_dir_raises() -> None:
    with pytest.raises(BriefError):
        assemble_brief("/nonexistent/run/path")

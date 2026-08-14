"""Day 7: repair coordinator + auto-repair on coreme run (fake Codex)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from helpers import make_repo, write_job

from coreme.cli import main as cli_main
from coreme.repair import (
    auto_repair_wanted,
    cleaned_codex_env,
    execute_repair,
    read_repair,
    repair_prove_wanted,
    resolve_source,
)
from coreme.repair_spawn import codex_argv, codex_prompt, resolve_sandbox
from coreme.runner import run_job
from coreme.ship import ship_job


def _assert_repair_v1_shape(
    repair: dict[str, object],
    *,
    status: str,
    trigger: str,
    codex_available: bool,
    codex_exit_code: int | None,
    source_path: str | None,
    brief_path: str | None,
    sandbox: str,
    codex_log: str | None,
    message: str,
) -> None:
    assert repair == {
        "v": 1,
        "status": status,
        "trigger": trigger,
        "codex_available": codex_available,
        "codex_exit_code": codex_exit_code,
        "source_path": source_path,
        "brief_path": brief_path,
        "sandbox": sandbox,
        "codex_log": codex_log,
        "summary_path": None,
        "started_at": repair["started_at"],
        "finished_at": repair["finished_at"],
        "message": message,
        "prove": None,
        "rerun": None,
    }


def _failing_job(tmp_path: Path, name: str = "broken") -> Path:
    return write_job(
        tmp_path / name,
        name=name,
        entry_content="import sys; print('boom'); sys.exit(9)\n",
        proof_py="print('ok')\n",
    )


def _install_fake_codex(bin_dir: Path, log_path: Path, *, exit_code: int = 0) -> None:
    """PATH shim: codex records argv and exits."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    recorder = bin_dir / "_fake_codex_record.py"
    recorder.write_text(
        "import sys\n"
        f"from pathlib import Path\n"
        f"Path(r'''{log_path}''').write_text('\\n'.join(sys.argv), encoding='utf-8')\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        (bin_dir / "codex.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{recorder}" %*\r\n',
            encoding="utf-8",
        )
    else:
        codex = bin_dir / "codex"
        codex.write_text(
            f"#!/usr/bin/env python3\nimport runpy\nrunpy.run_path(r'''{recorder}''')\n",
            encoding="utf-8",
        )
        codex.chmod(0o755)


def test_auto_repair_wanted_flag_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COREME_AUTO_REPAIR", raising=False)
    assert auto_repair_wanted(flag=None, no_flag=False) is False
    assert auto_repair_wanted(flag=True, no_flag=False) is True
    monkeypatch.setenv("COREME_AUTO_REPAIR", "1")
    assert auto_repair_wanted(flag=None, no_flag=False) is True
    assert auto_repair_wanted(flag=None, no_flag=True) is False
    assert auto_repair_wanted(flag=True, no_flag=True) is False


def test_repair_prove_wanted_auto_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COREME_REPAIR_PROVE", raising=False)
    assert repair_prove_wanted(trigger="auto") is True
    assert repair_prove_wanted(trigger="manual") is False
    assert repair_prove_wanted(flag=True, trigger="manual") is True
    assert repair_prove_wanted(no_flag=True, trigger="auto") is False
    monkeypatch.setenv("COREME_REPAIR_PROVE", "0")
    assert repair_prove_wanted(trigger="auto") is False
    monkeypatch.setenv("COREME_REPAIR_PROVE", "1")
    assert repair_prove_wanted(trigger="manual") is True


def test_resolve_sandbox_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COREME_CODEX_SANDBOX", raising=False)
    assert resolve_sandbox() == "danger-full-access"
    monkeypatch.setenv("COREME_CODEX_SANDBOX", "workspace-write")
    assert resolve_sandbox() == "workspace-write"
    monkeypatch.setenv("COREME_CODEX_SANDBOX", "bypass")
    assert resolve_sandbox() == "bypass"


def test_codex_argv_includes_authority_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COREME_CODEX_PROFILE", raising=False)
    monkeypatch.delenv("COREME_CODEX_IGNORE_USER_CONFIG", raising=False)
    monkeypatch.delenv("COREME_CODEX_INHERIT_ENV", raising=False)
    monkeypatch.delenv("COREME_CODEX_SANDBOX", raising=False)
    argv = codex_argv(
        "codex",
        Path("C:/src"),
        "fix me",
        add_dirs=[Path("C:/runs/x")],
        output_last_message=Path("C:/runs/x/repair-summary.md"),
    )
    assert "exec" in argv
    assert "-s" in argv
    assert "danger-full-access" in argv
    assert "--add-dir" in argv
    assert "shell_environment_policy.inherit=all" in argv
    assert "-o" in argv
    prompt = codex_prompt(Path("b.md"), Path("src"), Path("run"), crash_signature="TimeoutError: x")
    assert "CRASH SIGNATURE" in prompt
    assert "TimeoutError" in prompt
    assert "Do not add, enable, or reuse Job-owned runtime Codex" in prompt
    assert "never call an LLM" not in prompt


def test_run_auto_repair_off_no_repair_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _failing_job(tmp_path)
    repo = make_repo(tmp_path)
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)
    monkeypatch.delenv("COREME_AUTO_REPAIR", raising=False)

    code = cli_main(["--plain", "run", str(job)])
    assert code == 9
    run_dir = next((repo / "runs").glob("broken-*"))
    assert not (run_dir / "repair.json").is_file()
    assert (run_dir / "fail.json").is_file()


def test_run_auto_repair_on_fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _failing_job(tmp_path)
    repo = make_repo(tmp_path)
    log = tmp_path / "codex-argv.txt"
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)
    monkeypatch.delenv("COREME_AUTO_REPAIR", raising=False)

    # Auto prove runs offline proof (job fixture prints ok) — skip if noisy.
    monkeypatch.setenv("COREME_REPAIR_PROVE", "0")
    code = cli_main(["--plain", "run", str(job), "--auto-repair"])
    assert code == 9  # Job failure not masked
    run_dir = next((repo / "runs").glob("broken-*"))
    repair = read_repair(run_dir)
    assert repair is not None
    assert repair["trigger"] == "auto"
    assert repair["status"] == "finished"
    assert repair["codex_exit_code"] == 0
    assert repair.get("sandbox") == "danger-full-access"
    _assert_repair_v1_shape(
        repair,
        status="finished",
        trigger="auto",
        codex_available=True,
        codex_exit_code=0,
        source_path=str(job.resolve()),
        brief_path=str((run_dir / "repair-brief.md").resolve()),
        sandbox="danger-full-access",
        codex_log=str((run_dir / "codex.log").resolve()),
        message="Codex process exited 0; re-prove source before ship",
    )
    assert (run_dir / "repair-brief.md").is_file()
    brief = (run_dir / "repair-brief.md").read_text(encoding="utf-8")
    assert "boom" in brief or "FAILED" in brief
    assert "Crash signature" in brief
    assert log.is_file()
    argv_text = log.read_text(encoding="utf-8")
    assert "exec" in argv_text
    # Quiet tee: codex session log under the Run
    assert (run_dir / "codex.log").is_file()


def test_run_success_with_auto_repair_skips_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = write_job(
        tmp_path / "ok",
        name="ok",
        entry_content="print('ok')\n",
    )
    repo = make_repo(tmp_path)
    log = tmp_path / "codex-argv.txt"
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["--plain", "run", str(job), "--auto-repair"])
    assert code == 0
    run_dir = next((repo / "runs").glob("ok-*"))
    assert not (run_dir / "repair.json").is_file()
    assert not log.is_file()


def test_no_auto_repair_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _failing_job(tmp_path)
    repo = make_repo(tmp_path)
    log = tmp_path / "codex-argv.txt"
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("COREME_AUTO_REPAIR", "1")
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["--plain", "run", str(job), "--no-auto-repair"])
    assert code == 9
    run_dir = next((repo / "runs").glob("broken-*"))
    assert not (run_dir / "repair.json").is_file()
    assert not log.is_file()


def test_missing_secrets_no_run_no_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = write_job(
        tmp_path / "sec",
        name="sec",
        entry_content="print('x')\n",
        secrets_toml='[secrets]\nnames = ["MUST_HAVE"]\n',
    )
    repo = make_repo(tmp_path)
    log = tmp_path / "codex-argv.txt"
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.delenv("MUST_HAVE", raising=False)
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["--plain", "run", str(job), "--auto-repair"])
    assert code == 2
    runs = repo / "runs"
    assert not runs.exists() or not any(runs.iterdir())
    assert not log.is_file()


def test_release_without_source_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Release fail with no matching source → skipped_no_source; release tree intact."""
    job = write_job(
        tmp_path / "srcjob",
        name="orphan",
        entry_content="import sys; sys.exit(1)\n",
        proof_py="print('ok')\n",
    )
    repo = make_repo(tmp_path)
    # Put source outside repo discovery (only under tmp, ship from job)
    # Ship into repo releases, then remove/rename source so resolve fails.
    release_path, _ = ship_job(job, repo)
    # Move source away so name cannot be found under repo_root
    gone = tmp_path / "gone"
    job.rename(gone)

    log = tmp_path / "codex-argv.txt"
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    # Hash files before
    main_before = (release_path / "main.py").read_bytes()

    code = cli_main(["--plain", "run", str(release_path), "--auto-repair"])
    assert code == 1
    run_dir = next((repo / "runs").glob("orphan-*"))
    repair = read_repair(run_dir)
    assert repair is not None
    assert repair["status"] == "skipped_no_source"
    _assert_repair_v1_shape(
        repair,
        status="skipped_no_source",
        trigger="auto",
        codex_available=True,
        codex_exit_code=None,
        source_path=None,
        brief_path=str((run_dir / "repair-brief.md").resolve()),
        sandbox="danger-full-access",
        codex_log=None,
        message="No editable source resolved; releases/ left untouched",
    )
    assert (release_path / "main.py").read_bytes() == main_before
    assert not log.is_file()  # no codex spawn


def test_repair_exec_manual_fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _failing_job(tmp_path, name="manual")
    repo = make_repo(tmp_path)
    record = run_job(job, repo_root=repo)
    log = tmp_path / "codex-argv.txt"
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["--plain", "repair", record.run_path, "--exec"])
    assert code == 0
    repair = read_repair(record.run_path)
    assert repair is not None
    assert repair["trigger"] == "manual"
    assert repair["status"] == "finished"
    assert log.is_file()
    assert "exec" in log.read_text(encoding="utf-8")


def test_codex_missing_soft_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _failing_job(tmp_path)
    repo = make_repo(tmp_path)
    # Empty PATH so which finds nothing
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)

    code = cli_main(["--plain", "run", str(job), "--auto-repair"])
    assert code == 9
    run_dir = next((repo / "runs").glob("broken-*"))
    repair = read_repair(run_dir)
    assert repair is not None
    assert repair["status"] == "codex_missing"


def test_resolve_source_dev_job(tmp_path: Path) -> None:
    job = _failing_job(tmp_path)
    repo = make_repo(tmp_path)
    record = run_job(job, repo_root=repo)
    source = resolve_source(record.run_path, repo)
    assert source is not None
    assert source.resolve() == job.resolve()


def test_resolve_source_release_finds_examples_style(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    src = write_job(
        repo / "mytool",
        name="mytool",
        entry_content="import sys; sys.exit(1)\n",
        proof_py="print('ok')\n",
    )
    release_path, _ = ship_job(src, repo)
    record = run_job(release_path, repo_root=repo)
    assert record.release is True
    source = resolve_source(record.run_path, repo)
    assert source is not None
    assert source.resolve() == src.resolve()
    assert "releases" not in source.parts or source != release_path


def test_brief_strips_secret_values_in_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = write_job(
        tmp_path / "secjob",
        name="secjob",
        entry_content="import sys; sys.exit(1)\n",
        secrets_toml='[secrets]\nnames = ["PLANT_SECRET"]\n',
    )
    repo = make_repo(tmp_path)
    planted = "planted-secret-value-999"
    monkeypatch.setenv("PLANT_SECRET", planted)
    record = run_job(job, repo_root=repo)

    def fake_spawn(argv, *, cwd, env, timeout_sec):
        return 0

    monkeypatch.setattr("coreme.repair.find_codex", lambda: "codex")
    outcome = execute_repair(
        record.run_path,
        repo_root=repo,
        trigger="manual",
        spawn=fake_spawn,
        progress=lambda _m: None,
    )
    assert outcome.status == "finished"
    brief = Path(record.run_path, "repair-brief.md").read_text(encoding="utf-8")
    assert "PLANT_SECRET" in brief
    assert planted not in brief


def test_cleaned_env_drops_secret_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("JOB_TOKEN", "xxx")
    monkeypatch.setenv("MY_SECRET", "yyy")
    monkeypatch.setenv("CODEX_HOME", "/tmp/c")
    monkeypatch.setenv("HARMLESS_HOST_VAR", "keep-me")
    monkeypatch.delenv("COREME_CODEX_FULL_HOST_ENV", raising=False)
    env = cleaned_codex_env(["MY_SECRET"])
    assert "MY_SECRET" not in env
    assert "JOB_TOKEN" not in env  # suffix filter
    assert env.get("CODEX_HOME") == "/tmp/c" or any(k.upper() == "CODEX_HOME" for k in env)
    # Full host env (default): non-secret host vars kept
    assert env.get("HARMLESS_HOST_VAR") == "keep-me"
    # COREME_* always stripped from child
    monkeypatch.setenv("COREME_AUTO_REPAIR", "1")
    env2 = cleaned_codex_env([])
    assert "COREME_AUTO_REPAIR" not in env2


def test_auto_repair_prove_default_records_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _failing_job(tmp_path, name="proved")
    repo = make_repo(tmp_path)
    log = tmp_path / "codex-argv.txt"
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr("coreme.cli.find_repo_root", lambda: repo)
    monkeypatch.delenv("COREME_AUTO_REPAIR", raising=False)
    monkeypatch.delenv("COREME_REPAIR_PROVE", raising=False)

    code = cli_main(["--plain", "run", str(job), "--auto-repair"])
    assert code == 9
    run_dir = next((repo / "runs").glob("proved-*"))
    repair = read_repair(run_dir)
    assert repair is not None
    assert repair["prove"] is not None
    assert repair["prove"]["status"] == "passed"
    assert repair["prove"]["exit_code"] == 0

"""Tests for coreme doctor workspace checks."""

from pathlib import Path

from coreme.doctor import run_doctor


def _workspace(tmp_path: Path, *, with_docs: bool = False, with_git: bool = False) -> Path:
    if with_docs:
        (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
        (tmp_path / "START-HERE.md").write_text("start", encoding="utf-8")
    if with_git:
        (tmp_path / ".git").mkdir()
    return tmp_path


def _by_name(checks: list) -> dict:
    return {check.name: check for check in checks}


def test_fresh_workspace_warns_but_never_fails(tmp_path: Path) -> None:
    checks = run_doctor(workspace=str(_workspace(tmp_path)))
    by_name = _by_name(checks)
    assert by_name["agents"].status == "warn"
    assert "skills install" in by_name["agents"].detail
    assert by_name["start-here"].status == "warn"
    assert by_name["git"].status == "warn"
    assert all(check.status != "fail" for name, check in by_name.items() if name != "workspace")


def test_installed_workspace_passes_doc_checks(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, with_docs=True, with_git=True)
    by_name = _by_name(run_doctor(workspace=str(ws)))
    assert by_name["agents"].status == "pass"
    assert by_name["start-here"].status == "pass"
    assert by_name["git"].status == "pass"

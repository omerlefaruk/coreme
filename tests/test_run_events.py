"""Kernel events.jsonl lifecycle and Job emit helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import make_repo, write_job

from coreme.events import append_event, fail_path, read_events, read_fail_summary
from coreme.joblog import (
    emit,
    flush_operator_transcript,
    operator_show,
    reset_operator_transcript,
    say_fail,
    short_error,
    summary_lines,
)
from coreme.runner import run_job

_PROOF_OK = "raise SystemExit(0)\n"


def test_successful_run_has_start_and_end(tmp_path: Path) -> None:
    job = write_job(
        tmp_path / "j",
        name="evt",
        entry_content="print('ok', flush=True)\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    rows = read_events(record.run_path)
    assert record.status == "succeeded"
    events = [r["event"] for r in rows]
    assert events[0] == "run.start"
    assert events[-1] == "run.end"
    for row in rows:
        assert row["v"] == 1
        assert "ts" in row
        assert "level" in row
        assert "event" in row
    end = rows[-1]
    assert end["status"] == "succeeded"
    assert end["exit_code"] == 0
    start = rows[0]
    assert start["job"] == "evt"
    assert start["version"] == "0.1.0"


def test_timeout_emits_timeout_event(tmp_path: Path) -> None:
    entry = "import time\nprint('hang', flush=True)\ntime.sleep(30)\n"
    job = write_job(
        tmp_path / "slow",
        name="slow",
        entry_content=entry,
        proof_py=_PROOF_OK,
        timeout_sec=1,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert record.exit_code == 124
    rows = read_events(record.run_path)
    names = [r["event"] for r in rows]
    assert "run.start" in names
    assert "run.timeout" in names
    timeout = next(r for r in rows if r["event"] == "run.timeout")
    assert timeout["exit_code"] == 124


def test_job_emit_appends_between_kernel_events(tmp_path: Path) -> None:
    entry = """\
import os
from pathlib import Path
# Minimal emit without importing coreme (isolation) — use env path directly
import json
from datetime import datetime, timezone
run = os.environ["COREME_RUN_DIR"]
row = {
    "v": 1,
    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "level": "info",
    "event": "step.ok",
    "step": 1,
    "name": "probe",
}
with open(os.path.join(run, "events.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(row, sort_keys=True) + "\\n")
print("done", flush=True)
"""
    job = write_job(
        tmp_path / "jobevt",
        name="jobevt",
        entry_content=entry,
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    rows = read_events(record.run_path)
    names = [r["event"] for r in rows]
    assert names == ["run.start", "step.ok", "run.end"]


def test_emit_noop_without_run_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COREME_RUN_DIR", raising=False)
    emit("step.ok", step=1)  # must not raise


def test_emit_with_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COREME_RUN_DIR", str(tmp_path))
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    emit("idle", message="clean", detail={"n": 0})
    rows = read_events(tmp_path)
    assert len(rows) == 1
    assert rows[0]["event"] == "idle"
    assert rows[0]["detail"] == {"n": 0}


def test_read_events_skips_malformed_and_truncated_lines(tmp_path: Path) -> None:
    """Malformed / truncated rows never break reading; valid rows survive."""
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(
            {"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "run.start"},
            sort_keys=True,
        )
        + "\n"
        + "not-json-at-all\n"
        + '{"v": 1, "event": "step.ok", "trunc'  # truncated mid-object
        + "\n"
        + "\n"  # blank line
        + json.dumps(
            {"v": 1, "event": "run.end", "status": "succeeded"},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    rows = read_events(tmp_path)
    assert [r["event"] for r in rows] == ["run.start", "run.end"]


def test_read_events_skips_non_object_rows(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('[1, 2, 3]\n{"v": 1, "event": "run.end"}\n', encoding="utf-8")
    rows = read_events(tmp_path)
    assert [r["event"] for r in rows] == ["run.end"]


def test_append_event_rejects_nan_and_infinity(tmp_path: Path) -> None:
    """Non-finite floats are rejected before any byte is written."""
    path = tmp_path / "events.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Out of range float values"):
        append_event(tmp_path, "run.end", score=float("nan"))
    with pytest.raises(ValueError, match="Out of range float values"):
        append_event(tmp_path, "run.end", score=float("inf"))
    assert path.read_text(encoding="utf-8") == ""  # nothing partial written
    append_event(tmp_path, "run.end", status="succeeded")
    assert len(read_events(tmp_path)) == 1


def test_summary_lines_plain() -> None:
    lines = summary_lines([("status", "ok")], title="SUMMARY")
    assert "SUMMARY" in lines[0]
    assert "status: ok" in lines


def test_short_error_timeout_picks_waiting_line() -> None:
    class TimeoutError(Exception):
        pass

    exc = TimeoutError(
        "Locator.click: Timeout 15000ms exceeded.\n"
        "Call log:\n"
        "  - waiting for locator(\"button:has-text('StartChallenge')\")\n"
    )
    msg = short_error(exc)
    assert "Timeout" in msg
    assert "StartChallenge" in msg
    assert "Call log" not in msg


def test_say_fail_prints_block_and_emits(
    capsys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COREME_PLAIN", "1")
    monkeypatch.setenv("COREME_RUN_DIR", str(tmp_path))
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    reset_operator_transcript()
    reason = say_fail(
        3,
        4,
        "Filling forms…",
        name="fill",
        reason="Timeout — waiting for Start",
        evidence="artifacts/fail.png",
    )
    assert reason.startswith("Timeout")
    out = capsys.readouterr().out
    assert "✗ FAIL 3/4" in out
    assert "── FAIL ──" in out or "FAIL" in out
    assert "reason: Timeout" in out
    assert "evidence: artifacts/fail.png" in out
    rows = read_events(tmp_path)
    assert rows[-1]["event"] == "step.fail"
    assert rows[-1]["step"] == 3
    assert rows[-1]["total"] == 4
    assert rows[-1]["name"] == "fill"


def test_operator_show_plain_prints_once(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    """Single live surface: plain path prints once; records transcript."""
    monkeypatch.setenv("COREME_PLAIN", "1")
    reset_operator_transcript()
    operator_show("1/3 step")
    out = capsys.readouterr().out
    assert out.count("1/3 step") == 1
    body = flush_operator_transcript()
    assert "1/3 step" in body


def test_operator_show_paint_skips_stdout_print(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    """When paint succeeds, do not also print plain (prevents double under coreme)."""
    monkeypatch.delenv("COREME_PLAIN", raising=False)
    reset_operator_transcript()
    painted: list[str] = []

    class FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            painted.append(str(args[0]) if args else "")

    import coreme.joblog as joblog

    monkeypatch.setattr(joblog, "get_tty_console", lambda: FakeConsole())
    operator_show("1/3 step", paint=lambda c: c.print("fancy 1/3"))
    out = capsys.readouterr().out
    assert "1/3 step" not in out  # no stdout twin
    assert painted == ["fancy 1/3"]
    assert "1/3 step" in flush_operator_transcript()


def test_log_txt_stays_plain_job_stream(tmp_path: Path) -> None:
    job = write_job(
        tmp_path / "plainlog",
        name="plainlog",
        entry_content="print('step-line', flush=True)\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    log = (Path(record.run_path) / "log.txt").read_text(encoding="utf-8")
    assert "step-line" in log
    # No ANSI escape in this Job stream
    assert "\x1b[" not in log


def test_cli_events_jsonl_and_text(tmp_path: Path) -> None:
    from coreme.cli import main

    job = write_job(
        tmp_path / "cli_evt",
        name="cli_evt",
        entry_content="print('x', flush=True)\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert main(["--plain", "events", record.run_path, "--output", "jsonl"]) == 0
    assert main(["--plain", "events", record.run_path, "--output", "text"]) == 0
    assert main(["--plain", "events", str(tmp_path / "missing")]) == 2


# --- fail.json brief ---


def test_nonzero_exit_writes_fail_json(tmp_path: Path) -> None:
    job = write_job(
        tmp_path / "boom",
        name="boom",
        entry_content="raise SystemExit(1)\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert record.status == "failed"
    assert record.exit_code == 1
    summary = read_fail_summary(record.run_path)
    assert summary is not None
    assert summary["v"] == 1
    assert summary["kind"] == "process"
    assert summary["status"] == "failed"
    assert summary["exit_code"] == 1
    assert summary["job"] == "boom"
    assert summary["version"] == "0.1.0"
    assert summary["message"] == "job exited with code 1"
    assert summary["failed_step"] is None
    assert summary["evidence"]["log"] == "log.txt"
    assert summary["evidence"]["events"] == "events.jsonl"
    assert summary["evidence"]["run_json"] == "run.json"
    end = next(r for r in read_events(record.run_path) if r["event"] == "run.end")
    assert end["level"] == "error"
    assert end["kind"] == "process"
    assert end["message"]


def test_success_has_no_fail_json(tmp_path: Path) -> None:
    job = write_job(
        tmp_path / "okjob",
        name="okjob",
        entry_content="print('ok', flush=True)\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert record.status == "succeeded"
    assert not fail_path(record.run_path).is_file()
    assert read_fail_summary(record.run_path) is None


def test_timeout_fail_json_kind(tmp_path: Path) -> None:
    entry = "import time\nprint('hang', flush=True)\ntime.sleep(30)\n"
    job = write_job(
        tmp_path / "slowfail",
        name="slowfail",
        entry_content=entry,
        proof_py=_PROOF_OK,
        timeout_sec=1,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert record.exit_code == 124
    summary = read_fail_summary(record.run_path)
    assert summary is not None
    assert summary["kind"] == "timeout"
    assert summary["exit_code"] == 124
    assert "timeout" in summary["message"]


def test_start_error_writes_fail_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = write_job(
        tmp_path / "nospawn",
        name="nospawn",
        entry_content="print('never', flush=True)\n",
        proof_py=_PROOF_OK,
    )

    def boom(*_args: object, **_kwargs: object) -> tuple[int, str, str, bool]:
        raise OSError("simulated spawn failure")

    monkeypatch.setattr("coreme.runner.run_process", boom)
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert record.status == "failed"
    assert record.exit_code == 1
    summary = read_fail_summary(record.run_path)
    assert summary is not None
    assert summary["kind"] == "start_error"
    assert summary["exit_code"] == 1
    assert summary["job"] == "nospawn"
    assert "simulated spawn failure" in summary["message"]
    assert summary["failed_step"] is None
    err = next(r for r in read_events(record.run_path) if r["event"] == "run.error")
    assert err["kind"] == "start_error"


def test_step_fail_populates_failed_step(tmp_path: Path) -> None:
    entry = """\
import json
import os
from datetime import datetime, timezone
run = os.environ["COREME_RUN_DIR"]
row = {
    "v": 1,
    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "level": "error",
    "event": "step.fail",
    "step": 2,
    "name": "checkout",
    "message": "cart empty",
}
with open(os.path.join(run, "events.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(row, sort_keys=True) + "\\n")
raise SystemExit(1)
"""
    job = write_job(
        tmp_path / "stepfail",
        name="stepfail",
        entry_content=entry,
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    summary = read_fail_summary(record.run_path)
    assert summary is not None
    assert summary["kind"] == "process"
    assert summary["failed_step"] == {
        "step": 2,
        "name": "checkout",
        "message": "cart empty",
    }
    assert summary["last_step"]["event"] == "step.fail"
    assert summary["last_step"]["step"] == 2
    assert summary["message"] == "cart empty"


def test_cli_events_text_shows_fail_header(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from coreme.cli import main

    job = write_job(
        tmp_path / "cli_fail",
        name="cli_fail",
        entry_content="raise SystemExit(3)\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    assert main(["--plain", "events", record.run_path, "--output", "text"]) == 0
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "kind=process" in out
    assert "exit=3" in out
    assert "job exited with code 3" in out
    assert "run.end" in out


def test_print_run_footer_plain_includes_fail_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from coreme.present import print_run_footer

    job = write_job(
        tmp_path / "foot",
        name="foot",
        entry_content="raise SystemExit(1)\n",
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    print_run_footer(record, plain_flag=True)
    out = capsys.readouterr().out
    assert "fail_path=" in out
    assert "fail.json" in out
    assert "fail_message=" in out


def test_print_run_footer_plain_includes_failed_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from coreme.present import print_run_footer

    entry = """\
from coreme.joblog import say_fail
say_fail(2, 3, "Checkout…", name="checkout", reason="cart empty")
raise SystemExit(1)
"""
    job = write_job(
        tmp_path / "footstep",
        name="footstep",
        entry_content=entry,
        proof_py=_PROOF_OK,
    )
    record = run_job(job, repo_root=make_repo(tmp_path))
    print_run_footer(record, plain_flag=True)
    out = capsys.readouterr().out
    assert "failed_step=" in out
    assert "checkout" in out or "2" in out
    assert "cart empty" in out
    log = (Path(record.run_path) / "log.txt").read_text(encoding="utf-8")
    assert "✗ FAIL 2/3" in log
    assert "── FAIL ──" in log or "reason: cart empty" in log
    assert "Traceback" not in log

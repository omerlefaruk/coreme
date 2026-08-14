"""CLI presentation: plain mode stable; pretty path safe without TTY."""

from __future__ import annotations

from types import SimpleNamespace

from coreme.present import (
    _style_job_line,
    format_events_text,
    is_plain,
    print_error,
    print_repair_footer,
    print_run_footer,
    print_ship_footer,
)


def _record(**overrides: object) -> SimpleNamespace:
    base = {
        "job": "demo",
        "version": "0.1.0",
        "status": "succeeded",
        "exit_code": 0,
        "run_path": r"C:\runs\demo-1",
        "release": False,
        "content_hash": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_is_plain_flag_and_env(monkeypatch) -> None:
    monkeypatch.delenv("COREME_PLAIN", raising=False)
    assert is_plain(plain_flag=True) is True
    monkeypatch.setenv("COREME_PLAIN", "1")
    assert is_plain(plain_flag=False) is True
    monkeypatch.setenv("COREME_PLAIN", "0")
    # Without TTY (pytest), still plain
    assert is_plain(plain_flag=False) is True


def test_plain_run_footer_strings(capsys, monkeypatch) -> None:
    monkeypatch.setenv("COREME_PLAIN", "1")
    print_run_footer(_record(), plain_flag=True)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "status=succeeded exit_code=0" in out
    assert "run_path=" in out
    assert "C:\\runs\\demo-1" in out or "runs" in out


def test_plain_ship_footer(capsys) -> None:
    print_ship_footer("/releases/demo-0.1.0", "abc123", plain_flag=True)
    out = capsys.readouterr().out
    assert "release_path=/releases/demo-0.1.0" in out
    assert "content_hash=abc123" in out


def test_pretty_run_footer_does_not_crash_without_tty(capsys, monkeypatch) -> None:
    monkeypatch.delenv("COREME_PLAIN", raising=False)
    # Force non-plain path even under capture by calling pretty internals via flag off
    # and patching is_plain — exercise Rich branch through direct panel attempt.
    from coreme import present

    monkeypatch.setattr(present, "is_plain", lambda plain_flag=False: False)
    print_run_footer(
        _record(status="failed", exit_code=1),
        plain_flag=False,
    )  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "failed" in out or "exit" in out


def test_print_error_plain(capsys) -> None:
    print_error("missing secret DEMO_TOKEN", plain_flag=True)
    err = capsys.readouterr().err
    assert err.strip() == "error: missing secret DEMO_TOKEN"


def test_style_job_line_roles() -> None:
    step = _style_job_line("3/4 Filling forms…")
    assert "3/4" in step.plain
    fail = _style_job_line("✗ FAIL 3/4 Filling forms…")
    assert "FAIL" in fail.plain
    reason = _style_job_line("reason: Timeout — waiting for locator")
    assert "reason" in reason.plain


def test_print_repair_footer_plain(capsys) -> None:
    print_repair_footer(
        SimpleNamespace(status="finished", path=r"C:\runs\x\repair.json", message="ok"),
        plain_flag=True,
    )
    out = capsys.readouterr().out
    assert "repair_status=finished" in out
    assert "repair_path=" in out


def test_format_events_text() -> None:
    text = format_events_text(
        [
            {
                "ts": "2026-08-07T12:00:00Z",
                "level": "info",
                "event": "run.start",
                "job": "demo",
            },
            {
                "ts": "2026-08-07T12:00:01Z",
                "level": "info",
                "event": "run.end",
                "status": "succeeded",
                "exit_code": 0,
            },
        ]
    )
    assert "run.start" in text
    assert "run.end" in text
    assert "succeeded" in text

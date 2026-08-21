"""Offline proof for report-demo (no Run env required)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_main():
    path = ROOT / "main.py"
    spec = importlib.util.spec_from_file_location("report_demo_main", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_normalize_mode_idle_aliases() -> None:
    mod = _load_main()
    assert mod.normalize_mode("idle") == "idle"
    assert mod.normalize_mode("clean") == "idle"
    assert mod.normalize_mode("work") == "work"
    assert mod.normalize_mode(None) == "work"


def test_summary_shape_via_joblog() -> None:
    from coreme.joblog import summary_lines

    lines = summary_lines([("status", "clean"), ("pending", 0)], title="ÖZET")
    assert lines[0].startswith("── ÖZET")
    assert "status: clean" in lines
    assert "pending: 0" in lines

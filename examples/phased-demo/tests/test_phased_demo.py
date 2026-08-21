"""Offline proof for examples/phased-demo (no live Run env required)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

JOB_DIR = Path(__file__).resolve().parent.parent
FIXTURE = JOB_DIR / "fixtures" / "prepared.txt"


def _load_main():
    spec = importlib.util.spec_from_file_location("phased_demo_main", JOB_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_entry_and_manifest_exist() -> None:
    assert (JOB_DIR / "main.py").is_file()
    assert (JOB_DIR / "JOB.toml").is_file()
    text = (JOB_DIR / "JOB.toml").read_text(encoding="utf-8")
    assert "[inputs.only]" in text
    assert "[inputs.skip]" in text
    assert "[inputs.seed]" in text
    assert "[phases]" not in text


def test_selected_phases_default_and_controls() -> None:
    mod = _load_main()
    assert mod.selected_phases("", "") == ("prepare", "report")
    assert mod.selected_phases("report", "") == ("report",)
    assert mod.selected_phases("prepare", "") == ("prepare",)
    assert mod.selected_phases("", "prepare") == ("report",)
    assert mod.selected_phases("", "report") == ("prepare",)
    # Fixed order even when only lists names out of order
    assert mod.selected_phases("report,prepare", "") == ("prepare", "report")
    # Whitespace and empty segments ignored
    assert mod.selected_phases(" report , ", "") == ("report",)


def test_selected_phases_rejects_bad_controls() -> None:
    mod = _load_main()
    cases = (
        ("prepare", "report"),  # both set
        ("missing", ""),  # unknown only
        ("", "missing"),  # unknown skip
        ("report,report", ""),  # duplicate
        ("", "prepare,report"),  # empty selection via skip-all
    )
    for only, skip in cases:
        with pytest.raises(ValueError):
            mod.selected_phases(only, skip)


def test_format_report_and_fixture_match_prepared_body() -> None:
    mod = _load_main()
    fixture = FIXTURE.read_text(encoding="utf-8")
    assert fixture == mod.PREPARED_BODY
    assert mod.format_report(fixture) == f"report:\n{fixture}"

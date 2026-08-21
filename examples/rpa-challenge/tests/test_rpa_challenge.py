"""Offline proof for examples/rpa-challenge (no live browser or network)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent
FIXTURE = JOB_DIR / "fixtures" / "challenge.csv"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_manifest_contract() -> None:
    text = (JOB_DIR / "JOB.toml").read_text(encoding="utf-8")
    assert 'name = "rpa-challenge"' in text
    assert "[inputs.mode]" in text
    assert "[inputs.headless]" in text
    assert "timeout_sec = 300" in text
    assert "playwright" in (JOB_DIR / "requirements.txt").read_text(encoding="utf-8")


def test_load_fixture_and_fill_plan() -> None:
    ch = _load("rpa_challenge_helpers", JOB_DIR / "challenge.py")
    rows = ch.load_rows(FIXTURE)
    assert len(rows) == 10
    assert rows[0]["First Name"] == "John"
    assert rows[0]["Email"] == "jsmith@itsolutions.co.uk"

    plan = ch.fill_plan(rows, max_rows=3)
    assert len(plan) == 3
    assert plan[0]["index"] == 1
    selectors = {f["selector"] for f in plan[0]["fields"]}
    assert 'input[ng-reflect-name="labelFirstName"]' in selectors
    assert 'input[ng-reflect-name="labelPhone"]' in selectors
    values = {f["column"]: f["value"] for f in plan[0]["fields"]}
    assert values["Last Name"] == "Smith"


def test_helpers_mode_and_result() -> None:
    ch = _load("rpa_challenge_helpers2", JOB_DIR / "challenge.py")
    assert ch.normalize_mode("live") == "live"
    assert ch.normalize_mode("offline") == "offline"
    assert ch.normalize_mode(None) == "offline"
    assert ch.truthy("1") is True
    assert ch.truthy("0") is False
    assert ch.parse_max_rows("5") == 5
    body = ch.format_result(mode="offline", rows_filled=10, message="dry-run")
    assert "rows_filled: 10" in body
    assert "status: ok" in body


def test_fill_plan_json_serializable() -> None:
    ch = _load("rpa_challenge_helpers3", JOB_DIR / "challenge.py")
    plan = ch.fill_plan(ch.load_rows(FIXTURE), max_rows=2)
    raw = json.dumps(plan)
    assert "labelEmail" in raw

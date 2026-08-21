"""Offline proof for daily-summary (no browser, no live Opera)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = JOB_DIR / "fixtures" / "input"
sys.path.insert(0, str(JOB_DIR))

SPEC = importlib.util.spec_from_file_location("daily_summary_main", JOB_DIR / "main.py")
assert SPEC is not None and SPEC.loader is not None
MAIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAIN)

import parsers  # noqa: E402
import reports_catalog  # noqa: E402


def test_selected_phases_default_full() -> None:
    assert MAIN.selected_phases("", "") == (
        "prepare",
        "download",
        "parse",
        "report",
    )


def test_selected_phases_skip_download() -> None:
    assert MAIN.selected_phases("", "download") == ("prepare", "parse", "report")


def test_selected_phases_only() -> None:
    assert MAIN.selected_phases("parse,report", "") == ("parse", "report")


def test_selected_phases_reject_both() -> None:
    try:
        MAIN.selected_phases("parse", "report")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "both" in str(e)


def test_resolve_mode() -> None:
    assert MAIN.resolve_mode("live") == "live"
    assert MAIN.resolve_mode("offline") == "offline"
    assert MAIN.resolve_mode("") == "offline"


def test_resolve_reports_default_manager_only() -> None:
    specs = reports_catalog.resolve_reports("manager")
    assert len(specs) == 1
    assert specs[0].key == "manager"
    assert specs[0].internal_name == "manager_report"


def test_resolve_reports_all() -> None:
    specs = reports_catalog.resolve_reports("all")
    assert len(specs) == len(reports_catalog.CATALOG)


def test_resolve_reports_unknown() -> None:
    try:
        reports_catalog.resolve_reports("nope")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unknown" in str(e)


def test_parse_master_and_extract_rules() -> None:
    rows = parsers.parse_master_rows(FIXTURE_DIR / "manager.xml")
    assert any(r["Description"] == "Rooms Occupied" for r in rows)
    occ = next(r for r in rows if r["Description"] == "Rooms Occupied")
    assert occ["DAY"] == "130"
    metrics = parsers.extract_by_rules(rows, parsers.MANAGER_RULES)
    assert metrics["Rooms Occupied B"] == "130"
    assert "% Rooms Occupied B" in metrics
    assert "Room Revenue B" in metrics


def test_parse_forecast_and_extract() -> None:
    rows = parsers.parse_forecast_rows(FIXTURE_DIR / "manager.xml")
    assert len(rows) >= 2
    assert rows[0]["Arr. Rooms"] == 22
    m = parsers.extract_forecast_metrics(rows)
    assert m["Arr. Rooms-2"] == "22"
    assert m["Total Occ.-2"] == "130"


def test_gross_extract() -> None:
    rows = parsers.parse_master_rows(FIXTURE_DIR / "manager_gross.xml")
    m = parsers.extract_by_rules(rows, parsers.GROSS_RULES, key_suffix=" GROSS")
    assert m["ADR GROSS B"] == "355,20" or m["ADR GROSS B"].startswith("355")
    assert "Room Revenue GROSS B" in m


def test_discover_controls_partial() -> None:
    controls = parsers.discover_controls(FIXTURE_DIR)
    assert controls["manager_file"] is True
    assert controls["manager_gross_file"] is True
    assert controls["arrivals_VIP_file"] is False


def test_format_amount() -> None:
    assert parsers.format_amount("72.50") == "72,50"
    assert parsers.format_amount("1,240.00") == "1.240,00"


def test_chunk_specs_and_workers() -> None:
    import opera

    assert opera.parse_workers("3") == 3
    assert opera.parse_workers("99") == 4  # cap
    assert opera.DOWNLOAD_TIMEOUT_MS <= 60_000  # fail-fast, not 180s

    from reports_catalog import CATALOG

    specs = tuple(CATALOG.values())
    chunks = opera._chunk_specs(specs, 3)
    assert len(chunks) == 3
    assert sum(len(c) for c in chunks) == len(specs)
    # round-robin covers all keys once
    keys = [s.key for c in chunks for s in c]
    assert sorted(keys) == sorted(s.key for s in specs)

"""Pure parsers for Opera Cloud manager-style XML exports.

Ported from the Kronnika / The Marmara Pera "prod daily summary" harness
(read Manager + Manager GROSS paths). No network, no Excel dependency —
stdlib XML + plain dicts/CSV so offline proof stays light.
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Column letters in the original openpyxl extract map to period slots
# on the manager master sheet: B=DAY, C=MONTH, D=YEAR for current year,
# E=DAY, F=MONTH, G=YEAR for prior year (when present).
_COL_TO_PERIOD = {
    "B": "DAY",
    "C": "MONTH",
    "D": "YEAR",
    "E": "DAY_PY",
    "F": "MONTH_PY",
    "G": "YEAR_PY",
}

# Original Read Manager-Manager Table extract rules (row label → columns).
MANAGER_RULES: dict[str, list[str]] = {
    "Rooms Occupied": ["B", "C", "D"],
    "Total Rooms in Hotel minus OOO Rooms": ["B", "C", "D", "E", "F", "G"],
    "Complimentary Rooms": ["B"],
    "House Use Rooms": ["B"],
    "Rooms Occupied minus Comp and House Use": ["B", "C", "D", "E", "F", "G"],
    "Out of Order Rooms": ["B", "C", "D"],
    "Company Rooms In-House": ["B"],
    "Travel Agent Rooms In-House": ["B"],
    "Group Rooms In-House": ["B"],
    "% Rooms Occupied": ["B", "C", "D"],
    "% Rooms Occupied minus OOO": ["B", "C", "D"],
    "% Rooms Occupied minus Comp, House and OOO": ["B", "C", "D", "E", "F", "G"],
    "Walk-in Rooms": ["B"],
    "Walk-in Persons": ["B"],
    "ADR minus Comp and House": ["B", "C", "D", "E", "F", "G"],
    "Room Revenue": ["B", "C", "D", "E", "F", "G"],
    "Food And Beverage Revenue": ["B", "C", "D"],
    "Total Revenue": ["B", "C", "D"],
}

GROSS_RULES: dict[str, list[str]] = {
    "ADR": ["B", "C", "D"],
    "Room Revenue": ["B", "C", "D"],
}

# Forecast table header → extract rows (1-based data rows; row 1 is header).
# Original used header names with row numbers 2.. on the forecast sheet.
FORECAST_RULES: dict[str, list[int]] = {
    "Arr. Rooms": [2],
    "Dep. Rooms": [2],
    "Total Occ.": [2, 3, 4, 5, 6, 7, 8, 9],
    "Occ. %": [2, 3, 4, 5, 6, 7, 8, 9],
    "Average Room Rate": [2],
}

# Expected download flags (Yeni Görev control map) — offline Job sets True
# only when the matching fixture/file is present under input_dir.
REPORT_FILES: dict[str, str] = {
    "manager_file": "manager.xml",
    "manager_gross_file": "manager_gross.xml",
    "countrybyday_file": "countrybyday.xml",
    "countrybymon_file": "countrybymon.xml",
    "resenteredon_file": "resenteredon.xml",
    "gibyroom_SUT_file": "gibyroom_SUT.xml",
    "gibyroom_VIP_file": "gibyroom_VIP.xml",
    "arrivals_group_file": "arrivals_group.xml",
    "arrivals_VIP_file": "arrivals_VIP.xml",
    "group_in_house_file": "group_in_house.xml",
}


def format_amount(raw: str | None) -> str:
    """Normalize Opera FORMATTED_AMOUNT-ish strings for display (TR-ish)."""
    if not raw:
        return ""
    deger = str(raw).strip()
    if "," in deger and "." in deger:
        deger = deger.replace(",", "-").replace(".", ",").replace("-", ".")
        return deger
    if "." in deger:
        deger = deger.replace(".", ",")
        parts = deger.split(",")
        if parts[0].isdigit():
            whole = f"{int(parts[0]):,}".replace(",", ".")
            return whole + "," + parts[1]
        return deger
    if deger.isdigit():
        n = int(deger)
        if n >= 1000:
            return f"{n:,}".replace(",", ".")
        return deger
    return deger


def _years_from_amounts(amounts: dict[tuple[str, str], str]) -> tuple[str, str]:
    years = sorted({y for (y, _p) in amounts.keys() if y and y.isdigit()}, reverse=True)
    if not years:
        return ("", "")
    if len(years) == 1:
        return (years[0], "")
    return (years[0], years[1])


def parse_master_rows(xml_path: Path) -> list[dict[str, str]]:
    """Parse G_MASTER_VALUE blocks into rows with period columns."""
    root = ET.parse(xml_path).getroot()
    rows: list[dict[str, str]] = []
    for master in root.findall(".//G_MASTER_VALUE"):
        desc = (master.findtext("DESCRIPTION") or "").strip()
        amounts: dict[tuple[str, str], str] = {}
        for h_order in master.findall(".//G_HEADING_1_ORDER"):
            year = (h_order.findtext("HEADING_1") or "").strip()
            period = (h_order.findtext("HEADING_2") or "").strip()
            amount_node = h_order.find(".//FORMATTED_AMOUNT")
            if amount_node is None:
                amount_node = h_order.find(".//AMOUNT")
            ham = amount_node.text if amount_node is not None else ""
            amounts[(year, period)] = format_amount(ham)
        cur_y, pri_y = _years_from_amounts(amounts)
        rows.append(
            {
                "Description": desc,
                "DAY": amounts.get((cur_y, "DAY"), ""),
                "MONTH": amounts.get((cur_y, "MONTH"), ""),
                "YEAR": amounts.get((cur_y, "YEAR"), ""),
                "DAY_PY": amounts.get((pri_y, "DAY"), "") if pri_y else "",
                "MONTH_PY": amounts.get((pri_y, "MONTH"), "") if pri_y else "",
                "YEAR_PY": amounts.get((pri_y, "YEAR"), "") if pri_y else "",
                "current_year": cur_y,
                "prior_year": pri_y,
            }
        )
    return rows


def extract_by_rules(
    rows: list[dict[str, str]],
    rules: dict[str, list[str]],
    *,
    key_suffix: str = "",
) -> dict[str, str]:
    """Map description rows + column rules → flat metrics (harness `ornek` dict)."""
    by_desc = {r["Description"]: r for r in rows if r.get("Description")}
    out: dict[str, str] = {}
    for label, cols in rules.items():
        row = by_desc.get(label)
        if not row:
            continue
        for col in cols:
            period = _COL_TO_PERIOD.get(col)
            if not period:
                continue
            value = row.get(period, "")
            if value is None or value == "":
                continue
            # Match original key style: "Rooms Occupied B" or "ADR GROSS B"
            if key_suffix:
                out[f"{label}{key_suffix} {col}"] = str(value)
            else:
                out[f"{label} {col}"] = str(value)
    return out


def parse_forecast_rows(xml_path: Path) -> list[dict[str, Any]]:
    """Parse G_FORECAST snapshot rows (manager table export)."""
    root = ET.parse(xml_path).getroot()
    rows: list[dict[str, Any]] = []
    for forecast in root.findall(".//G_FORECAST"):
        occ_perc = float(forecast.findtext("CF_FS_PERC_OCC_ROOMS") or "0")
        adr = float(forecast.findtext("CF_FS_AVG_ROOM_RATE") or "0")
        room_rev = float(forecast.findtext("FS_ROOM_REVENUE") or "0")
        total_rev = float(forecast.findtext("FS_TOTAL_REVENUE") or "0")
        rows.append(
            {
                "Date": forecast.findtext("FS_CONSIDERED_DATE_CHAR") or "",
                "Day": forecast.findtext("FS_CONSIDERED_DATE_DAY") or "",
                "Arr. Rooms": int(forecast.findtext("FS_ARR_ROOMS") or "0"),
                "Dep. Rooms": int(forecast.findtext("FS_DEP_ROOMS") or "0"),
                "Total Occ.": int(forecast.findtext("FS_NO_ROOMS") or "0"),
                "Occ. %": format_amount(f"{occ_perc:.2f}%"),
                "Adl. & Chl.": int(forecast.findtext("FS_GUESTS") or "0"),
                "Average Room Rate": format_amount(f"{adr:.2f}"),
                "Room Revenue": format_amount(f"{room_rev:.2f}"),
                "Total Revenue": format_amount(f"{total_rev:.2f}"),
            }
        )
    return rows


def extract_forecast_metrics(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Extract forecast sheet metrics using original header/row rules.

    Row numbers are 1-based including header: data row 2 is rows[0].
    """
    out: dict[str, str] = {}
    for header, row_nos in FORECAST_RULES.items():
        for row_no in row_nos:
            idx = row_no - 2  # row 2 → index 0
            if idx < 0 or idx >= len(rows):
                continue
            value = rows[idx].get(header)
            if value is None or value == "":
                continue
            out[f"{header}-{row_no}"] = str(value)
    return out


def discover_controls(input_dir: Path) -> dict[str, bool]:
    """Return Yeni-Görev-style download flags from files present on disk."""
    return {
        flag: (input_dir / filename).is_file()
        for flag, filename in REPORT_FILES.items()
    }


def failed_controls(controls: dict[str, bool]) -> list[str]:
    return [name for name, ok in controls.items() if not ok]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_metrics_lines(path: Path, metrics: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(metrics.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

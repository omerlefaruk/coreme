"""Pure helpers for RPA Challenge form fill — offline-safe, no browser."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

# Public challenge site (Angular form; fields reorder after each submit).
CHALLENGE_URL = "https://www.rpachallenge.com/"

# Stable Angular attribute — do not use name/id (they reshuffle).
FIELD_SELECTORS: dict[str, str] = {
    "First Name": 'input[ng-reflect-name="labelFirstName"]',
    "Last Name": 'input[ng-reflect-name="labelLastName"]',
    "Company Name": 'input[ng-reflect-name="labelCompanyName"]',
    "Role in Company": 'input[ng-reflect-name="labelRole"]',
    "Address": 'input[ng-reflect-name="labelAddress"]',
    "Email": 'input[ng-reflect-name="labelEmail"]',
    "Phone Number": 'input[ng-reflect-name="labelPhone"]',
}

REQUIRED_COLUMNS = tuple(FIELD_SELECTORS.keys())


def truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_mode(value: str | None) -> str:
    raw = (value or "offline").strip().lower()
    if raw in {"live", "browser", "online"}:
        return "live"
    return "offline"


def parse_max_rows(value: str | None, *, default: int = 10) -> int:
    raw = (value or "").strip()
    if not raw:
        return default
    n = int(raw)
    if n < 1:
        raise ValueError("max_rows must be >= 1")
    return n


def load_rows(path: Path) -> list[dict[str, str]]:
    """Load challenge rows from CSV. Keys are exact header names."""
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row")
    headers = [h.strip() for h in reader.fieldnames if h]
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise ValueError(f"CSV missing columns: {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    for i, raw in enumerate(reader, start=1):
        row = {col: (raw.get(col) or "").strip() for col in REQUIRED_COLUMNS}
        if not any(row.values()):
            continue
        empty = [c for c, v in row.items() if not v]
        if empty:
            raise ValueError(f"row {i} missing values: {', '.join(empty)}")
        rows.append(row)
    if not rows:
        raise ValueError("CSV has no data rows")
    return rows


def fill_plan(rows: list[dict[str, str]], max_rows: int) -> list[dict[str, Any]]:
    """Map each row to selector → value pairs (for offline proof / dry-run)."""
    plan: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:max_rows], start=1):
        fields = [
            {"column": col, "selector": FIELD_SELECTORS[col], "value": row[col]}
            for col in REQUIRED_COLUMNS
        ]
        plan.append({"index": index, "fields": fields})
    return plan


def format_result(
    *,
    mode: str,
    rows_filled: int,
    message: str = "",
    elapsed_ms: int | None = None,
) -> str:
    lines = [
        "ÖZET",
        f"  status: ok",
        f"  mode: {mode}",
        f"  rows_filled: {rows_filled}",
    ]
    if elapsed_ms is not None:
        lines.append(f"  elapsed_ms: {elapsed_ms}")
    if message:
        lines.append(f"  message: {message}")
    return "\n".join(lines) + "\n"

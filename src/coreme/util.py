"""Small shared helpers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime


def json_dumps(value: object) -> str:
    """Serialize JSON with stable formatting and a trailing newline."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def iso_utc(
    value: datetime | None = None,
    *,
    timespec: str = "milliseconds",
) -> str:
    """Format UTC ISO-8601 with ``Z`` suffix. Defaults to now when *value* is None."""
    moment = value if value is not None else datetime.now(UTC)
    return moment.isoformat(timespec=timespec).replace("+00:00", "Z")


def env_flag(name: str) -> bool:
    """True when env var is a common truthy string (1/true/yes/y/on)."""
    raw = os.environ.get(name, "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}

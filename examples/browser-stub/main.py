"""Offline-safe browser-shaped Job: operator UX + secrets + headless input.

Real browser Jobs add Playwright (or similar) in *their* requirements.txt.
This example proves the contract without a browser engine in the kernel or CI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_stdio() -> None:
    """Windows consoles often default to cp1252; non-ASCII must not crash prints."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(message: str) -> None:
    """Operator-facing progress; always flush so live terminal streaming works."""
    print(message, flush=True)


def truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_mode(value: str | None) -> str:
    """Return 'work' or 'idle'. Idle is success with nothing to process."""
    raw = (value or "work").strip().lower()
    if raw in {"idle", "empty", "none", "clean"}:
        return "idle"
    return "work"


def has_login_secrets(env: dict[str, str] | None = None) -> bool:
    """True when both secret names are present and non-empty (values never returned)."""
    source = env if env is not None else os.environ
    user = source.get("SITE_USER")
    password = source.get("SITE_PASSWORD")
    return bool(user) and bool(password)


def format_summary(*, mode: str, headless: bool, items: int) -> str:
    """Durable summary line; never includes secret values."""
    if mode == "idle" or items == 0:
        return "result=clean nothing_to_do\n"
    return f"result=ok mode={mode} headless={int(headless)} items={items}\n"


def simulated_queue_size(mode: str) -> int:
    """Stand-in for 'rows on the grid' without a real browser."""
    return 0 if mode == "idle" else 2


def main() -> None:
    configure_stdio()
    if not has_login_secrets():
        raise SystemExit("SITE_USER and SITE_PASSWORD are required at live run")

    mode = normalize_mode(os.environ.get("COREME_INPUT_mode"))
    headless = truthy(os.environ.get("COREME_INPUT_headless", "1"))
    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])

    say("1/3 Checking login secrets…")
    # Kernel already required the names; Job confirms and never prints values.
    say("1/3 Login ready (secrets present)")

    say(f"2/3 Opening site ({'headless' if headless else 'headed'})…")
    items = simulated_queue_size(mode)
    if items == 0:
        # Idle path: success language, not "failed to find rows".
        say("2/3 Nothing to process — queue is clean")
        body = format_summary(mode="idle", headless=headless, items=0)
        (artifacts / "result.txt").write_text(body, encoding="utf-8")
        say("3/3 Done — nothing to do / clean")
        return

    say(f"2/3 Found {items} item(s) to process")
    say("3/3 Finishing…")
    body = format_summary(mode="work", headless=headless, items=items)
    (artifacts / "result.txt").write_text(body, encoding="utf-8")
    say(f"3/3 Done — processed {items} item(s)")


if __name__ == "__main__":
    main()

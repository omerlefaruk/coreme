"""Day-4 Job: require DEMO_TOKEN at run; never emit its value."""

from __future__ import annotations

import os
from pathlib import Path

# Fixed offline-safe marker written when the secret is present at live run.
OK_ARTIFACT = "secret-ok\n"
OK_STDOUT = "secret-echo ok"


def has_secret(env: dict[str, str] | None = None) -> bool:
    """Return True when DEMO_TOKEN is present and non-empty (no value returned)."""
    source = env if env is not None else os.environ
    value = source.get("DEMO_TOKEN")
    return value is not None and value != ""


def format_ok() -> str:
    """Return the durable artifact line (never includes a secret value)."""
    return OK_ARTIFACT


def main() -> None:
    if not has_secret():
        raise SystemExit("DEMO_TOKEN is required at live run")
    artifacts = os.environ.get("COREME_ARTIFACTS_DIR")
    if artifacts:
        Path(artifacts, "secret-ok.txt").write_text(format_ok(), encoding="utf-8")
    print(OK_STDOUT)


if __name__ == "__main__":
    main()

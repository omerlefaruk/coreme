"""Trivial Day-1 Job: print hello ok and write an artifact."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    print("hello ok")
    artifacts = os.environ.get("COREME_ARTIFACTS_DIR")
    if artifacts:
        path = Path(artifacts) / "hello.txt"
        path.write_text("ok\n", encoding="utf-8")


if __name__ == "__main__":
    main()

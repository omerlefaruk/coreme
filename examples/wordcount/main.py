"""Count words in a declared file input and write artifacts/count.txt."""

from __future__ import annotations

import os
from pathlib import Path


def count_words(text: str) -> int:
    """Return the number of whitespace-separated words in *text*."""
    return len(text.split())


def format_count(n: int) -> str:
    """Return the durable artifact line for a word count."""
    return f"words={n}\n"


def main() -> None:
    path = Path(os.environ["COREME_INPUT_path"])
    text = path.read_text(encoding="utf-8")
    n = count_words(text)
    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])
    (artifacts / "count.txt").write_text(format_count(n), encoding="utf-8")
    print(f"words={n}")


if __name__ == "__main__":
    main()

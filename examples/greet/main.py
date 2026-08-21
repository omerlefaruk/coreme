"""Write a greeting for the declared name input."""

import os
from pathlib import Path


def greeting(name: str) -> str:
    return f"Hello, {name}!\n"


def main() -> None:
    name = os.environ["COREME_INPUT_name"]
    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])
    (artifacts / "greeting.txt").write_text(greeting(name), encoding="utf-8")


if __name__ == "__main__":
    main()

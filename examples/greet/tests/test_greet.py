"""Offline proof for the greet Job."""

import importlib.util
from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("greet_main", JOB_DIR / "main.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_greeting_uses_name() -> None:
    assert MODULE.greeting("Ada") == "Hello, Ada!\n"

"""Offline proof for the wordcount Job."""

import importlib.util
from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent
FIXTURE = JOB_DIR / "fixtures" / "sample.txt"
SPEC = importlib.util.spec_from_file_location("wordcount_main", JOB_DIR / "main.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_count_words_on_fixture() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert MODULE.count_words(text) == 5


def test_format_count() -> None:
    assert MODULE.format_count(5) == "words=5\n"


def test_count_words_empty() -> None:
    assert MODULE.count_words("") == 0
    assert MODULE.count_words("   \n\t  ") == 0

"""Offline proof for examples/hello."""

from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent


def test_entry_exists() -> None:
    assert (JOB_DIR / "main.py").is_file()


def test_job_toml_exists() -> None:
    assert (JOB_DIR / "JOB.toml").is_file()


def test_entry_importable() -> None:
    # Ensure main.py is syntactically valid and has main()
    import importlib.util

    spec = importlib.util.spec_from_file_location("hello_main", JOB_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(getattr(mod, "main", None))

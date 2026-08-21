"""Offline proof for examples/secret-echo (no live DEMO_TOKEN required)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent


def _load_main():
    spec = importlib.util.spec_from_file_location("secret_echo_main", JOB_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_entry_and_manifest_exist() -> None:
    assert (JOB_DIR / "main.py").is_file()
    assert (JOB_DIR / "JOB.toml").is_file()
    text = (JOB_DIR / "JOB.toml").read_text(encoding="utf-8")
    assert "DEMO_TOKEN" in text
    assert "[secrets]" in text


def test_helpers_do_not_require_live_env() -> None:
    mod = _load_main()
    assert mod.has_secret({}) is False
    assert mod.has_secret({"DEMO_TOKEN": ""}) is False
    assert mod.has_secret({"DEMO_TOKEN": "x"}) is True
    assert mod.format_ok() == "secret-ok\n"
    assert "DEMO_TOKEN" not in mod.format_ok()

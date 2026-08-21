"""Offline proof for examples/browser-stub (no live secrets or browser)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent


def _load_main():
    spec = importlib.util.spec_from_file_location("browser_stub_main", JOB_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_manifest_declares_secrets_and_inputs() -> None:
    text = (JOB_DIR / "JOB.toml").read_text(encoding="utf-8")
    assert "SITE_USER" in text
    assert "SITE_PASSWORD" in text
    assert "[inputs.headless]" in text
    assert "[inputs.mode]" in text


def test_helpers_offline() -> None:
    mod = _load_main()
    assert mod.has_login_secrets({}) is False
    assert mod.has_login_secrets({"SITE_USER": "a", "SITE_PASSWORD": ""}) is False
    assert mod.has_login_secrets({"SITE_USER": "a", "SITE_PASSWORD": "b"}) is True
    assert mod.normalize_mode("idle") == "idle"
    assert mod.normalize_mode("work") == "work"
    assert mod.truthy("1") is True
    assert mod.truthy("0") is False
    idle = mod.format_summary(mode="idle", headless=True, items=0)
    assert "clean" in idle
    assert "password" not in idle.lower()
    work = mod.format_summary(mode="work", headless=False, items=2)
    assert "items=2" in work
    assert mod.simulated_queue_size("idle") == 0
    assert mod.simulated_queue_size("work") == 2

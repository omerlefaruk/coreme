"""Offline proof: URL building and popup command without network/UI."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main

JOB_DIR = Path(__file__).resolve().parent.parent


def test_job_files_exist() -> None:
    assert (JOB_DIR / "JOB.toml").is_file()
    assert (JOB_DIR / "main.py").is_file()


def test_build_search_url() -> None:
    assert main.build_search_url("koala") == "https://www.google.com/search?q=koala"


def test_build_search_url_encodes() -> None:
    assert main.build_search_url("koala bear") == "https://www.google.com/search?q=koala+bear"
    assert main.build_search_url("a&b") == "https://www.google.com/search?q=a%26b"


def test_build_popup_code() -> None:
    code = main.build_popup_code("a", "koala")
    assert "MessageBoxW" in code
    assert "'a'" in code or '"a"' in code
    assert "koala" in code


def test_get_popup_python_returns_string() -> None:
    exe = main.get_popup_python()
    assert isinstance(exe, str)
    assert exe.lower().endswith(".exe")


def test_main_spawns_browser_and_messagebox(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("COREME_INPUT_query", "koala")
    monkeypatch.setenv("COREME_INPUT_message", "a")
    monkeypatch.setenv("COREME_ARTIFACTS_DIR", str(tmp_path))

    with (
        mock.patch("main.webbrowser.open", return_value=True) as mock_open,
        mock.patch("main.spawn_messagebox") as mock_spawn,
    ):
        main.main()
        mock_open.assert_called_once()
        args, _ = mock_open.call_args
        assert "google.com/search?q=koala" in args[0]
        mock_spawn.assert_called_once_with("a")

    assert (tmp_path / "url.txt").read_text(encoding="utf-8").strip().endswith("q=koala")
    assert (tmp_path / "message.txt").read_text(encoding="utf-8").strip() == "a"


def test_main_defaults_when_no_env(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("COREME_INPUT_query", raising=False)
    monkeypatch.delenv("COREME_INPUT_message", raising=False)
    monkeypatch.setenv("COREME_ARTIFACTS_DIR", str(tmp_path))

    with (
        mock.patch("main.webbrowser.open", return_value=True),
        mock.patch("main.spawn_messagebox") as mock_spawn,
    ):
        main.main()
        mock_spawn.assert_called_once_with("a")

"""Koala job: open Google search for koala and popup messagebox 'a'."""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.parse
import webbrowser
from pathlib import Path


def build_search_url(query: str) -> str:
    """Build Google search URL for query."""
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)


def build_popup_code(message: str, title: str = "koala") -> str:
    """Return python -c code that shows a MessageBox."""
    return f"import ctypes; ctypes.windll.user32.MessageBoxW(0, {message!r}, {title!r}, 64)"


def get_popup_python() -> str:
    """Prefer pythonw.exe to avoid console flash."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    if candidate.is_file():
        return str(candidate)
    return sys.executable


def spawn_messagebox(message: str, title: str = "koala") -> None:
    """Spawn detached MessageBox so Run does not block on OK."""
    exe = get_popup_python()
    code = build_popup_code(message, title)
    cmd = [exe, "-c", code]
    flags = 0
    if sys.platform == "win32":
        flags |= 0x00000008  # DETACHED_PROCESS
        flags |= 0x00000200  # CREATE_NEW_PROCESS_GROUP
        flags |= 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(cmd, creationflags=flags, close_fds=False)
    else:
        subprocess.Popen(cmd, close_fds=False)


def main() -> None:
    query = os.environ.get("COREME_INPUT_query", "koala") or "koala"  # noqa: SIM112
    message = os.environ.get("COREME_INPUT_message", "a") or "a"  # noqa: SIM112
    url = build_search_url(query)

    print(f"opening google search: {url}")
    try:
        opened = webbrowser.open(url)
        print(f"browser opened: {opened}")
    except Exception as exc:
        print(f"browser open failed: {exc}")

    print(f"popping messagebox: {message!r}")
    try:
        spawn_messagebox(message)
        print("messagebox spawned (detached)")
    except Exception as exc:
        print(f"messagebox spawn failed: {exc}")
        # Fallback to blocking MessageBox if spawn fails and we are on Windows
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(0, message, "koala", 64)
                print("fallback blocking messagebox shown")
            except Exception as exc2:
                print(f"fallback messagebox failed: {exc2}")

    artifacts = os.environ.get("COREME_ARTIFACTS_DIR")
    if artifacts:
        out = Path(artifacts)
        out.mkdir(parents=True, exist_ok=True)
        (out / "url.txt").write_text(url + "\n", encoding="utf-8")
        (out / "message.txt").write_text(message + "\n", encoding="utf-8")
        print(f"artifacts written to {out}")

    print("done: koala search + popup a")


if __name__ == "__main__":
    main()

"""Environment self-check for a CoreMe machine (agent-friendly)."""

from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PASS = "pass"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def run_doctor(
    *,
    hub_url: str | None = None,
    workspace: str | Path | None = None,
    python: str = sys.executable,
) -> list[Check]:
    checks: list[Check] = []
    checks.append(_check_python())
    checks.append(_check_rich())
    checks.append(_check_codex())
    checks.extend(_check_workspace(Path(workspace) if workspace else Path.cwd()))
    if hub_url:
        checks.append(_check_hub(hub_url))
    return checks


def doctor_ok(checks: list[Check]) -> bool:
    return all(c.status != FAIL for c in checks)


def render_plain(checks: list[Check]) -> str:
    lines = [f"check={c.name} status={c.status} detail={c.detail}" for c in checks]
    verdict = "ok" if doctor_ok(checks) else "failed"
    lines.append(f"doctor={verdict}")
    return "\n".join(lines)


def render_json(checks: list[Check]) -> str:
    payload = {
        "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks],
        "ok": doctor_ok(checks),
    }
    return json.dumps(payload, indent=2)


def _check_python() -> Check:
    version = sys.version_info
    if version >= (3, 11):
        return Check("python", PASS, f"{version.major}.{version.minor}.{version.micro}")
    return Check("python", FAIL, f"3.11+ required, found {version.major}.{version.minor}")


def _check_rich() -> Check:
    try:
        import rich  # noqa: F401

        return Check("rich", PASS, "importable")
    except ImportError:
        return Check("rich", WARN, "not installed; CLI falls back to plain output")


def _check_codex() -> Check:
    if shutil.which("codex"):
        return Check("codex", PASS, "on PATH; auto-repair available")
    return Check("codex", WARN, "not on PATH; repair --exec unavailable")


def _check_workspace(root: Path) -> list[Check]:
    resolved = root.resolve()
    writable = _writable_dir(resolved)
    yield_check = Check(
        "workspace",
        PASS if writable else FAIL,
        str(resolved) if writable else f"not writable: {resolved}",
    )
    runs = resolved / "runs"
    releases = resolved / "releases"
    layout = Check(
        "layout",
        PASS if runs.is_dir() or releases.is_dir() else WARN,
        "runs/ + releases/ found" if runs.is_dir() else "no runs/ yet (fresh machine?)",
    )
    free = _free_gb(resolved)
    disk = Check(
        "disk",
        WARN if free is not None and free < 1.0 else PASS,
        f"{free:.1f} GiB free" if free is not None else "unknown",
    )
    return [yield_check, layout, disk]


def _check_hub(hub_url: str) -> Check:
    url = hub_url.rstrip("/") + "/healthz"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status == 200:
                return Check("hub", PASS, f"{hub_url} reachable")
            return Check("hub", FAIL, f"{hub_url} answered {resp.status}")
    except urllib.error.URLError as exc:
        return Check("hub", FAIL, f"{hub_url} unreachable ({exc.reason})")
    except Exception as exc:
        return Check("hub", FAIL, f"{hub_url}: {exc}")


def _writable_dir(path: Path) -> bool:
    probe = path / ".coreme-doctor-probe"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _free_gb(path: Path) -> float | None:
    try:
        return shutil.disk_usage(path).free / (1024**3)
    except OSError:
        return None

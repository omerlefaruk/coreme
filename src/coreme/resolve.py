"""Resolve a Job path or bare process name to a runnable directory."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from coreme.paths import (
    JobPathError,
    assert_safe_job_path,
    reject_link,
    require_regular_file,
)


def version_sort_key(version: str) -> tuple:
    """Order versions so 0.1.10 > 0.1.2; non-numeric tails sort after numbers."""
    parts: list[tuple[int, int | str]] = []
    for piece in version.split("."):
        if piece.isdigit():
            parts.append((0, int(piece)))
        else:
            parts.append((1, piece))
    return tuple(parts)


def resolve_job_ref(ref: str | Path, repo_root: Path) -> Path:
    """Resolve ``ref`` to a Job/Release directory.

    Resolution order:
    1. Explicit path (contains ``/`` or ``\\``, or is absolute) → that folder.
    2. Bare process name → newest release under ``repo_root/releases/``.
    Raises JobPathError when no release matches.
    """
    raw = str(ref).strip()
    if not raw:
        raise JobPathError("Job path or process name is empty")

    as_path = Path(raw)

    # Explicit paths always win (./job, releases/name-1.0.0, absolute).
    # A bare process name must NOT bind to a same-named source folder first —
    # ops want the latest release when one exists.
    if _looks_like_path(raw):
        if not as_path.exists():
            raise JobPathError(f"Job path is not a directory: {raw}")
        return assert_safe_job_path(as_path)

    name = raw
    latest = find_latest_release(repo_root, name)
    if latest is not None:
        return assert_safe_job_path(latest)

    raise JobPathError(
        f"No release named {name!r}. "
        f"Ship one first (coreme ship <job>), or pass a source Job folder path. "
        f"Looked under: {Path(repo_root).resolve() / 'releases'}"
    )


def find_latest_release(repo_root: Path, name: str) -> Path | None:
    """Return the highest-version release directory for ``name``, or None."""
    releases = Path(repo_root) / "releases"
    reject_link(releases, "releases/")
    if not releases.is_dir():
        return None

    candidates: list[tuple[tuple, Path]] = []
    for child in releases.iterdir():
        reject_link(child, "release directory")
        if not child.is_dir() or child.name.startswith("."):
            continue
        meta = _release_identity(child)
        if meta is None:
            continue
        rel_name, rel_version = meta
        if rel_name != name:
            continue
        candidates.append((version_sort_key(rel_version), child))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def describe_resolution(ref: str | Path, resolved: Path, repo_root: Path) -> str | None:
    """Human line for CLI when a bare name was used; None for explicit paths."""
    raw = str(ref).strip()
    if _looks_like_path(raw):
        return None
    meta = _release_identity(resolved)
    if meta is None:
        return f"using {resolved}"
    name, version = meta
    return f"using release {name}-{version} (latest under releases/)"


def _looks_like_path(raw: str) -> bool:
    if raw in {".", ".."}:
        return True
    if "/" in raw or "\\" in raw:
        return True
    return bool(re.match(r"^[A-Za-z]:", raw))


def _release_identity(path: Path) -> tuple[str, str] | None:
    reject_link(path, "release directory")
    release_json = path / "RELEASE.json"
    if not os.path.lexists(release_json):
        return None
    require_regular_file(release_json, "RELEASE.json")
    try:
        data = json.loads(release_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        name = data.get("name")
        version = data.get("version")
        if isinstance(name, str) and isinstance(version, str) and name and version:
            return name, version

    return None

"""Locate editable source Job folders for repair (never ``releases/``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coreme.manifest import ManifestError, load_manifest

_SKIP_DIR_NAMES = frozenset(
    {"releases", "runs", ".git", ".venv", "venv", "src", "tests", "__pycache__"}
)


def resolve_source(
    run_path: str | Path,
    repo_root: Path,
    *,
    run_data: dict[str, Any] | None = None,
) -> Path | None:
    """Locate the editable source Job for this Run. Never returns a release path to patch."""
    root = Path(run_path).resolve()
    data = run_data if run_data is not None else load_run_json(root)
    if not data:
        return None

    job_name = str(data.get("job") or "")
    is_release = bool(data.get("release"))
    job_path_raw = data.get("job_path")
    job_path = Path(str(job_path_raw)).resolve() if job_path_raw else None

    if not is_release:
        if job_path is not None and is_job_dir(job_path, expected_name=job_name or None):
            # Refuse to treat a releases/ tree as source even if release flag missing.
            if looks_like_release(job_path):
                return find_source_by_name(repo_root, job_name) if job_name else None
            return job_path
        if job_name:
            return find_source_by_name(repo_root, job_name)
        return None

    # Release run: never patch job_path (under releases/). Search source.
    if not job_name:
        return None
    return find_source_by_name(repo_root, job_name)


def load_run_json(run_path: Path) -> dict[str, Any] | None:
    path = run_path / "run.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def is_job_dir(path: Path, *, expected_name: str | None = None) -> bool:
    """True when *path* is a loadable Job; optionally name must match *expected_name*."""
    if not path.is_dir() or not (path / "JOB.toml").is_file():
        return False
    try:
        manifest = load_manifest(path)
    except ManifestError:
        return False
    if expected_name is None:
        return True
    return manifest.name == expected_name


def looks_like_release(path: Path) -> bool:
    if (path / "RELEASE.json").is_file():
        return True
    parts = {p.lower() for p in path.parts}
    return "releases" in parts


def find_source_by_name(repo_root: Path, job_name: str) -> Path | None:
    """Prefer exact folder name under workspace root, then examples/, then one-level scan."""
    if not job_name:
        return None
    root = repo_root.resolve()
    preferred = [
        root / job_name,
        root / "examples" / job_name,
    ]
    for candidate in preferred:
        if is_job_dir(candidate, expected_name=job_name) and not looks_like_release(candidate):
            return candidate.resolve()

    matches: list[Path] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir():
            continue
        if child.name in _SKIP_DIR_NAMES:
            continue
        if looks_like_release(child):
            continue
        if is_job_dir(child, expected_name=job_name):
            matches.append(child.resolve())
        # one level: examples already preferred; also scan other containers once
        if child.name == "examples":
            continue
        try:
            sub_children = list(child.iterdir())
        except OSError:
            continue
        for sub in sub_children:
            if (
                sub.is_dir()
                and is_job_dir(sub, expected_name=job_name)
                and not looks_like_release(sub)
            ):
                matches.append(sub.resolve())

    uniq: list[Path] = []
    seen: set[str] = set()
    for match in matches:
        key = str(match)
        if key not in seen:
            seen.add(key)
            uniq.append(match)
    if len(uniq) == 1:
        return uniq[0]
    # Ambiguous: only accept if one path's folder name equals job name
    named = [m for m in uniq if m.name == job_name]
    if len(named) == 1:
        return named[0]
    return None

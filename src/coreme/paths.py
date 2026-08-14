"""Path safety for Job and Release roots."""

from __future__ import annotations

import os
import stat
from pathlib import Path

_REPARSE = 0x400


class JobPathError(Exception):
    """Job path is missing, not a directory, or a link/reparse point."""


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for parent in (current, *current.parents):
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file():
            try:
                text = pyproject.read_text(encoding="utf-8")
            except OSError:
                continue
            if 'name = "coreme"' in text or "name = 'coreme'" in text:
                return parent
    return Path.cwd().resolve()


def assert_safe_job_path(job_path: str | Path) -> Path:
    """Reject linked/reparse Job roots and JOB.toml before loading."""
    root = Path(job_path)
    reject_link(root, "Job root")
    if not root.is_dir():
        raise JobPathError(f"Job path is not a directory: {root}")
    require_regular_file(root / "JOB.toml", "JOB.toml")
    return root


def require_regular_file(
    path: Path,
    label: str,
    *,
    error_cls: type[Exception] = JobPathError,
) -> None:
    if not os.path.lexists(path):
        raise error_cls(f"{label} not found: {path}")
    st = lstat(path, error_cls=error_cls)
    if stat.S_ISLNK(st.st_mode) or is_reparse(st):
        raise error_cls(f"Symbolic link or reparse point not allowed ({label}): {path}")
    if not stat.S_ISREG(st.st_mode):
        raise error_cls(f"{label} must be a regular file")


def reject_link(
    path: Path,
    label: str,
    *,
    error_cls: type[Exception] = JobPathError,
) -> None:
    if not os.path.lexists(path):
        return
    st = lstat(path, error_cls=error_cls)
    if stat.S_ISLNK(st.st_mode) or is_reparse(st):
        raise error_cls(f"Symbolic link or reparse point not allowed ({label}): {path}")


def lstat(path: Path, *, error_cls: type[Exception] = JobPathError) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as error:
        raise error_cls(f"Cannot stat {path}: {error}") from error


def is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)

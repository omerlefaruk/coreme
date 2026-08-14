"""Release identity: tree hash, hash form, and zip pack/unpack."""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import zipfile
from pathlib import Path

from coreme.paths import is_reparse, lstat, reject_link

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
EXCLUDE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"})
EXCLUDE_SUFFIXES = (".pyc", ".pyo")


class ReleaseError(Exception):
    """Tree hash, hash form, or zip pack/unpack failed."""


def parse_hash(value: str | None) -> str:
    text = (value or "").strip()
    if HEX_RE.fullmatch(text):
        return f"sha256:{text}"
    if HASH_RE.fullmatch(text):
        return text
    raise ReleaseError("content_hash must be sha256: + 64 lowercase hex")


def hash_hex(value: str) -> str:
    return parse_hash(value).removeprefix("sha256:")


def tree_hash(
    job_path: str | Path,
    *,
    error_cls: type[Exception] = ReleaseError,
) -> tuple[str, int]:
    """Return (content_hash, file_count) for a Job/Release tree."""
    files = collect_files(Path(job_path), error_cls=error_cls)
    digest = hashlib.sha256()
    for relative, absolute in files:
        path_bytes = relative.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        try:
            data = absolute.read_bytes()
        except OSError as error:
            raise error_cls(f"Cannot read {absolute}: {error}") from error
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return f"sha256:{digest.hexdigest()}", len(files)


def zip_tree(root: str | Path) -> bytes:
    src = Path(root)
    if not src.is_dir():
        raise ReleaseError(f"not a directory: {src}")
    files = collect_files(src)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, absolute in files:
            archive.write(absolute, relative)
    return buf.getvalue()


def unzip_tree(payload: bytes, dest: str | Path) -> None:
    target = Path(dest)
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            if name.startswith("/") or ".." in Path(name).parts:
                raise ReleaseError(f"unsafe zip path: {info.filename}")
            out = (target / name).resolve()
            if not out.is_relative_to(root):
                raise ReleaseError(f"unsafe zip path: {info.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(info))


def collect_files(
    root: Path,
    *,
    error_cls: type[Exception] = ReleaseError,
) -> list[tuple[str, Path]]:
    reject_link(root, "Job root", error_cls=error_cls)
    if not root.is_dir():
        raise error_cls(f"Job path is not a directory: {root}")
    root_resolved = root.resolve()
    collected: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in _walk(root, error_cls=error_cls):
        base = Path(dirpath)
        if base != root:
            reject_link(base, "directory", error_cls=error_cls)
        for name in sorted(dirnames):
            child = base / name
            reject_link(child, "directory", error_cls=error_cls)
            _reject_outside(child, root_resolved, error_cls=error_cls)
        dirnames[:] = [name for name in dirnames if name not in EXCLUDE_DIRS]
        for name in sorted(filenames):
            path = base / name
            relative = path.relative_to(root).as_posix()
            st = lstat(path, error_cls=error_cls)
            if stat.S_ISLNK(st.st_mode) or is_reparse(st):
                raise error_cls(f"Symbolic link or reparse point not allowed (file): {path}")
            if not stat.S_ISREG(st.st_mode):
                raise error_cls(f"Not a regular file: {path}")
            _reject_outside(path, root_resolved, error_cls=error_cls)
            if name.endswith(EXCLUDE_SUFFIXES) or relative == "RELEASE.json":
                continue
            collected.append((relative, path))
    collected.sort(key=lambda item: item[0])
    return collected


def _walk(root: Path, *, error_cls: type[Exception], topdown: bool = True):
    def on_error(error: OSError) -> None:
        raise error_cls(f"Cannot walk Job tree: {error}") from error

    return os.walk(root, topdown=topdown, followlinks=False, onerror=on_error)


def _reject_outside(path: Path, root_resolved: Path, *, error_cls: type[Exception]) -> None:
    try:
        resolved = path.resolve()
    except OSError as error:
        raise error_cls(f"Cannot resolve {path}: {error}") from error
    if not resolved.is_relative_to(root_resolved):
        raise error_cls(f"Path escapes Job root: {path}")

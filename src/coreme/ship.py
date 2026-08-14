"""Ship a proven Job as an immutable Release and verify content hashes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from coreme import __version__
from coreme.manifest import ManifestError, load_manifest
from coreme.paths import (
    assert_safe_job_path,
    is_reparse,
    lstat,
    reject_link,
    require_regular_file,
)
from coreme.proof import test_job
from coreme.util import iso_utc, json_dumps

VERSION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._]*[A-Za-z0-9])?$")
EXCLUDE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"})
EXCLUDE_SUFFIXES = (".pyc", ".pyo")
RELEASE_KEYS = frozenset(
    {
        "name",
        "version",
        "content_hash",
        "shipped_at",
        "source_path",
        "coreme_version",
        "file_count",
    }
)


class ShipError(Exception):
    """Ship or release verification failed."""


def hash_job_tree(job_path: str | Path) -> tuple[str, int]:
    """Return (content_hash, file_count) for a Job/Release tree."""
    files = _collect_files(Path(job_path))
    digest = hashlib.sha256()
    for relative, absolute in files:
        path_bytes = relative.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        try:
            data = absolute.read_bytes()
        except OSError as error:
            raise ShipError(f"Cannot read {absolute}: {error}") from error
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return f"sha256:{digest.hexdigest()}", len(files)


def ship_job(job_path: str | Path, repo_root: Path) -> tuple[Path, str]:
    """Copy, prove, hash, and publish a Release. Returns (release_path, content_hash)."""
    source = assert_safe_job_path(job_path)
    try:
        manifest = load_manifest(source)
    except ManifestError as error:
        raise ShipError(str(error)) from error
    if not VERSION_RE.fullmatch(manifest.version):
        raise ShipError(f"version must be one safe path segment (no '-'): {manifest.version!r}")

    releases = _ensure_releases_dir(Path(repo_root) / "releases")
    destination = releases / f"{manifest.name}-{manifest.version}"
    if destination.resolve().parent != releases.resolve():
        raise ShipError(f"Release destination escapes releases/: {destination}")
    if os.path.lexists(destination):
        raise ShipError(f"Release already exists: {destination}")

    temp_dir: Path | None = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix=".tmp-ship-", dir=str(releases)))
        _copy_tree(source, temp_dir)
        content_hash, file_count = hash_job_tree(temp_dir)
        if test_job(temp_dir) != 0:
            raise ShipError("Offline proof failed with nonzero exit code")
        _purge_excluded(temp_dir)
        after_hash, after_count = hash_job_tree(temp_dir)
        if after_hash != content_hash or after_count != file_count:
            raise ShipError("Offline proof mutated included Job content")
        shipped_at = iso_utc(datetime.now(UTC))
        try:
            (temp_dir / "RELEASE.json").write_text(
                json_dumps(
                    {
                        "name": manifest.name,
                        "version": manifest.version,
                        "content_hash": content_hash,
                        "shipped_at": shipped_at,
                        "source_path": str(source.resolve()),
                        "coreme_version": __version__,
                        "file_count": file_count,
                    }
                ),
                encoding="utf-8",
            )
        except OSError as error:
            raise ShipError(f"Cannot write RELEASE.json: {error}") from error
        if os.path.lexists(destination):
            raise ShipError(f"Release already exists: {destination}")
        try:
            temp_dir.rename(destination)
        except OSError as error:
            raise ShipError(f"Cannot publish release to {destination}: {error}") from error
        temp_dir = None
        return destination.resolve(), content_hash
    finally:
        if temp_dir is not None and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except OSError as error:
                raise ShipError(f"Cannot clean temporary release {temp_dir}: {error}") from error


def verify_release(job_path: str | Path) -> str:
    """Verify a Release tree. Returns content_hash or raises ShipError."""
    root = assert_safe_job_path(job_path)
    envelope_path = root / "RELEASE.json"
    if not os.path.lexists(envelope_path):
        raise ShipError(f"RELEASE.json not found: {envelope_path}")
    require_regular_file(envelope_path, "RELEASE.json", error_cls=ShipError)

    try:
        raw = json.loads(envelope_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ShipError(f"Invalid RELEASE.json: {error}") from error
    if not isinstance(raw, dict):
        raise ShipError("RELEASE.json must be a JSON object")
    missing = RELEASE_KEYS - set(raw)
    unknown = set(raw) - RELEASE_KEYS
    if missing or unknown:
        raise ShipError(
            "Invalid RELEASE.json keys: "
            + "; ".join(
                p
                for p in (
                    f"missing {', '.join(sorted(missing))}" if missing else "",
                    f"unknown {', '.join(sorted(unknown))}" if unknown else "",
                )
                if p
            )
        )

    name, version = raw["name"], raw["version"]
    recorded_hash, file_count = raw["content_hash"], raw["file_count"]
    for key in ("name", "version", "shipped_at", "source_path", "coreme_version"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise ShipError(f"RELEASE.json {key} must be a non-empty string")
    if not isinstance(recorded_hash, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", recorded_hash
    ):
        raise ShipError("RELEASE.json content_hash must be sha256: + 64 lowercase hex")
    if not isinstance(file_count, int) or isinstance(file_count, bool) or file_count < 0:
        raise ShipError("RELEASE.json file_count must be a non-negative integer")

    computed_hash, computed_count = hash_job_tree(root)
    if computed_count != file_count:
        raise ShipError(
            f"Release file_count mismatch: recorded={file_count} computed={computed_count}"
        )
    if computed_hash != recorded_hash:
        raise ShipError(
            f"Release content hash mismatch: recorded={recorded_hash} computed={computed_hash}"
        )
    try:
        manifest = load_manifest(root)
    except ManifestError as error:
        raise ShipError(str(error)) from error
    if manifest.name != name or manifest.version != version:
        raise ShipError(
            f"RELEASE.json name/version ({name!r}, {version!r}) "
            f"do not match JOB.toml ({manifest.name!r}, {manifest.version!r})"
        )
    return computed_hash


def _ensure_releases_dir(releases: Path) -> Path:
    if os.path.lexists(releases):
        reject_link(releases, "releases/", error_cls=ShipError)
        if not releases.is_dir():
            raise ShipError(f"releases path is not a directory: {releases}")
        return releases
    try:
        releases.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ShipError(f"Cannot create releases/: {error}") from error
    reject_link(releases, "releases/", error_cls=ShipError)
    return releases


def _collect_files(root: Path) -> list[tuple[str, Path]]:
    reject_link(root, "Job root", error_cls=ShipError)
    if not root.is_dir():
        raise ShipError(f"Job path is not a directory: {root}")
    root_resolved = root.resolve()
    collected: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in _walk(root, topdown=True):
        base = Path(dirpath)
        if base != root:
            reject_link(base, "directory", error_cls=ShipError)
        for name in sorted(dirnames):
            child = base / name
            reject_link(child, "directory", error_cls=ShipError)
            _reject_outside(child, root_resolved)
        dirnames[:] = [name for name in dirnames if name not in EXCLUDE_DIRS]
        for name in sorted(filenames):
            path = base / name
            relative = path.relative_to(root).as_posix()
            st = lstat(path, error_cls=ShipError)
            if stat.S_ISLNK(st.st_mode) or is_reparse(st):
                raise ShipError(f"Symbolic link or reparse point not allowed (file): {path}")
            if not stat.S_ISREG(st.st_mode):
                raise ShipError(f"Not a regular file: {path}")
            _reject_outside(path, root_resolved)
            if name.endswith(EXCLUDE_SUFFIXES) or relative == "RELEASE.json":
                continue
            collected.append((relative, path))
    collected.sort(key=lambda item: item[0])
    return collected


def _copy_tree(source: Path, destination: Path) -> None:
    for relative, absolute in _collect_files(source):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(absolute, target, follow_symlinks=False)
        except OSError as error:
            raise ShipError(f"Cannot copy {absolute}: {error}") from error


def _purge_excluded(root: Path) -> None:
    for dirpath, dirnames, filenames in _walk(root, topdown=True):
        base = Path(dirpath)
        reject_link(base, "directory", error_cls=ShipError)
        for name in dirnames:
            reject_link(base / name, "directory", error_cls=ShipError)
        for name in filenames:
            reject_link(base / name, "file", error_cls=ShipError)
    for dirpath, dirnames, filenames in _walk(root, topdown=False):
        base = Path(dirpath)
        reject_link(base, "directory", error_cls=ShipError)
        for name in filenames:
            reject_link(base / name, "file", error_cls=ShipError)
        for name in dirnames:
            reject_link(base / name, "directory", error_cls=ShipError)
        for name in filenames:
            if name.endswith(EXCLUDE_SUFFIXES):
                try:
                    (base / name).unlink()
                except OSError as error:
                    raise ShipError(
                        f"Cannot remove excluded file {base / name}: {error}"
                    ) from error
        for name in dirnames:
            if name in EXCLUDE_DIRS:
                try:
                    shutil.rmtree(base / name)
                except OSError as error:
                    raise ShipError(
                        f"Cannot remove excluded directory {base / name}: {error}"
                    ) from error


def _walk(root: Path, *, topdown: bool):
    return os.walk(root, topdown=topdown, followlinks=False, onerror=_walk_error)


def _walk_error(error: OSError) -> None:
    raise ShipError(f"Cannot walk Job tree: {error}") from error


def _reject_outside(path: Path, root_resolved: Path) -> None:
    try:
        resolved = path.resolve()
    except OSError as error:
        raise ShipError(f"Cannot resolve {path}: {error}") from error
    if not resolved.is_relative_to(root_resolved):
        raise ShipError(f"Path escapes Job root: {path}")

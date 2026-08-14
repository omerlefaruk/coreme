"""Ship a proven Job as an immutable Release and verify content hashes."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from coreme import __version__
from coreme.manifest import ManifestError, load_manifest
from coreme.paths import (
    assert_safe_job_path,
    reject_link,
    require_regular_file,
)
from coreme.proof import test_job
from coreme.release import (
    EXCLUDE_DIRS,
    EXCLUDE_SUFFIXES,
    HASH_RE,
    ReleaseError,
    collect_files,
    tree_hash,
)
from coreme.util import iso_utc, json_dumps

VERSION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._]*[A-Za-z0-9])?$")
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


class ShipError(ReleaseError):
    """Ship or release verification failed."""


def hash_job_tree(job_path: str | Path) -> tuple[str, int]:
    """Return (content_hash, file_count) for a Job/Release tree."""
    return tree_hash(job_path, error_cls=ShipError)


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
    if not isinstance(recorded_hash, str) or not HASH_RE.fullmatch(recorded_hash):
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


def _copy_tree(source: Path, destination: Path) -> None:
    for relative, absolute in collect_files(source, error_cls=ShipError):
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

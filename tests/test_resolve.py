"""Bare process name → latest release resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import make_repo, write_job

from coreme.paths import JobPathError
from coreme.resolve import find_latest_release, resolve_job_ref, version_sort_key


def test_version_sort_numeric() -> None:
    versions = ["0.1.10", "0.1.2", "0.1.0", "0.2.0"]
    ordered = sorted(versions, key=version_sort_key)
    assert ordered == ["0.1.0", "0.1.2", "0.1.10", "0.2.0"]


def test_find_latest_release_by_name(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    releases = root / "releases"
    releases.mkdir()
    for version in ("0.1.0", "0.1.2", "0.1.1"):
        dest = releases / f"sample-job-{version}"
        write_job(dest, name="sample-job", version=version)
        (dest / "RELEASE.json").write_text(
            json.dumps(
                {
                    "name": "sample-job",
                    "version": version,
                    "content_hash": "sha256:x",
                    "shipped_at": "t",
                    "source_path": "x",
                    "coreme_version": "0.1.0",
                    "file_count": 1,
                }
            ),
            encoding="utf-8",
        )
    # distractor other job
    other = releases / "other-1.0.0"
    write_job(other, name="other", version="1.0.0")
    (other / "RELEASE.json").write_text(
        json.dumps(
            {
                "name": "other",
                "version": "1.0.0",
                "content_hash": "sha256:y",
                "shipped_at": "t",
                "source_path": "x",
                "coreme_version": "0.1.0",
                "file_count": 1,
            }
        ),
        encoding="utf-8",
    )

    latest = find_latest_release(root, "sample-job")
    assert latest is not None
    assert latest.name == "sample-job-0.1.2"


def test_resolve_bare_name_to_latest(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    releases = root / "releases"
    releases.mkdir()
    for version in ("0.1.0", "0.1.2"):
        dest = releases / f"demo-{version}"
        write_job(dest, name="demo", version=version)
        (dest / "RELEASE.json").write_text(
            json.dumps(
                {
                    "name": "demo",
                    "version": version,
                    "content_hash": "sha256:x",
                    "shipped_at": "t",
                    "source_path": "x",
                    "coreme_version": "0.1.0",
                    "file_count": 1,
                }
            ),
            encoding="utf-8",
        )

    resolved = resolve_job_ref("demo", root)
    assert resolved.name == "demo-0.1.2"


def test_resolve_explicit_path_still_works(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    job = write_job(root / "demo", name="demo", version="0.1.0")
    resolved = resolve_job_ref(str(job), root)
    assert resolved.resolve() == job.resolve()


def test_resolve_missing_name_errors(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    with pytest.raises(JobPathError, match="No release named"):
        resolve_job_ref("missing-job", root)


def test_bare_name_does_not_resolve_source_job(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write_job(root / "demo", name="demo", version="0.1.0")
    with pytest.raises(JobPathError, match="No release named"):
        resolve_job_ref("demo", root)


def test_metadata_free_or_invalid_release_is_not_a_candidate(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    releases = root / "releases"
    releases.mkdir()
    write_job(releases / "demo-0.1.0", name="demo", version="0.1.0")
    invalid = write_job(releases / "demo-0.2.0", name="demo", version="0.2.0")
    (invalid / "RELEASE.json").write_text("not json", encoding="utf-8")

    assert find_latest_release(root, "demo") is None
    with pytest.raises(JobPathError, match="No release named"):
        resolve_job_ref("demo", root)


def test_linked_release_paths_are_rejected_before_metadata_read(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    releases = root / "releases"
    releases.mkdir()
    target = write_job(tmp_path / "target", name="demo", version="0.1.0")
    linked_root = releases / "demo-0.1.0"
    try:
        linked_root.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available on this platform/user")

    with pytest.raises(JobPathError, match="release directory"):
        find_latest_release(root, "demo")

    linked_root.unlink()
    release = write_job(releases / "demo-0.1.0", name="demo", version="0.1.0")
    metadata = tmp_path / "RELEASE.json"
    metadata.write_text('{"name": "demo", "version": "0.1.0"}', encoding="utf-8")
    try:
        (release / "RELEASE.json").symlink_to(metadata)
    except OSError:
        pytest.skip("symlinks not available on this platform/user")

    with pytest.raises(JobPathError, match="RELEASE.json"):
        find_latest_release(root, "demo")


def test_bare_name_prefers_release_over_source(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write_job(root / "demo", name="demo", version="0.0.1")
    releases = root / "releases"
    releases.mkdir()
    dest = releases / "demo-0.2.0"
    write_job(dest, name="demo", version="0.2.0")
    (dest / "RELEASE.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.2.0",
                "content_hash": "sha256:x",
                "shipped_at": "t",
                "source_path": "x",
                "coreme_version": "0.1.0",
                "file_count": 1,
            }
        ),
        encoding="utf-8",
    )
    resolved = resolve_job_ref("demo", root)
    assert resolved.resolve() == dest.resolve()


def test_explicit_source_path_still_runs_dev_tree(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    job = write_job(root / "demo", name="demo", version="0.0.1")
    releases = root / "releases"
    releases.mkdir()
    dest = releases / "demo-0.2.0"
    write_job(dest, name="demo", version="0.2.0")
    (dest / "RELEASE.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "0.2.0",
                "content_hash": "sha256:x",
                "shipped_at": "t",
                "source_path": "x",
                "coreme_version": "0.1.0",
                "file_count": 1,
            }
        ),
        encoding="utf-8",
    )
    resolved = resolve_job_ref(str(job), root)
    assert resolved.resolve() == job.resolve()

"""One home for tree hash, hash form, and zip pack/unpack."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from helpers import write_job

from coreme.release import (
    ReleaseError,
    hash_hex,
    parse_hash,
    tree_hash,
    unzip_tree,
    zip_tree,
)
from coreme.ship import hash_job_tree


def test_parse_hash_accepts_bare_and_prefixed() -> None:
    digest = "ab" * 32
    assert parse_hash(digest) == f"sha256:{digest}"
    assert parse_hash(f"sha256:{digest}") == f"sha256:{digest}"
    assert hash_hex(digest) == digest


def test_parse_hash_rejects_bad_form() -> None:
    with pytest.raises(ReleaseError, match="sha256"):
        parse_hash("not-a-hash")


def test_tree_hash_matches_ship_alias(tmp_path: Path) -> None:
    job = write_job(tmp_path / "hello", name="hello", version="1.0.0")
    assert tree_hash(job) == hash_job_tree(job)


def test_zip_round_trip_preserves_tree_hash(tmp_path: Path) -> None:
    job = write_job(tmp_path / "hello", name="hello", version="1.0.0")
    digest, count = tree_hash(job)
    dest = tmp_path / "unpacked"
    unzip_tree(zip_tree(job), dest)
    got, got_count = tree_hash(dest)
    assert got == digest
    assert got_count == count


def test_unzip_rejects_zip_slip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../escape.txt", b"nope")
    with pytest.raises(ReleaseError, match="unsafe zip path"):
        unzip_tree(buf.getvalue(), tmp_path / "dest")

"""On-disk release blobs and evidence zips. Paths use hash hex only (no colon)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from coreme import release as release_identity
from coreme.release import ReleaseError
from coreme_hub.db import StoreError


def parse_hash(value: str | None) -> str:
    try:
        return release_identity.parse_hash(value)
    except ReleaseError as exc:
        raise StoreError("bad_request", str(exc)) from exc


def hash_hex(value: str) -> str:
    try:
        return release_identity.hash_hex(value)
    except ReleaseError as exc:
        raise StoreError("bad_request", str(exc)) from exc


def ensure_data_dir(data_dir: str | Path) -> Path:
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def blob_path(data_dir: str | Path, content_hash: str) -> Path:
    return ensure_data_dir(data_dir) / "blobs" / f"{hash_hex(content_hash)}.zip"


def evidence_file(data_dir: str | Path, assignment_id: str, attempt_id: str) -> Path:
    return ensure_data_dir(data_dir) / "evidence" / assignment_id / f"{attempt_id}.zip"


def zip_tree(root: str | Path) -> bytes:
    try:
        return release_identity.zip_tree(root)
    except ReleaseError as exc:
        raise StoreError("bad_request", str(exc)) from exc


def unzip_tree(payload: bytes, dest: str | Path) -> None:
    try:
        release_identity.unzip_tree(payload, dest)
    except ReleaseError as exc:
        raise StoreError("bad_request", str(exc)) from exc


def write_blob(data_dir: str | Path, content_hash: str, payload: bytes) -> Path:
    path = blob_path(data_dir, content_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".zip.partial")
    tmp.write_bytes(payload)
    tmp.replace(path)
    return path


def read_blob(data_dir: str | Path, content_hash: str) -> bytes:
    path = blob_path(data_dir, content_hash)
    if not path.is_file():
        raise StoreError("not_found", "release blob not found")
    return path.read_bytes()


def write_evidence_zip(
    data_dir: str | Path, assignment_id: str, attempt_id: str, payload: bytes
) -> Path:
    path = evidence_file(data_dir, assignment_id, attempt_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".zip.partial")
    tmp.write_bytes(payload)
    tmp.replace(path)
    return path


def read_evidence_zip(data_dir: str | Path, assignment_id: str, attempt_id: str) -> bytes:
    path = evidence_file(data_dir, assignment_id, attempt_id)
    if not path.is_file():
        raise StoreError("not_found", "evidence not found")
    return path.read_bytes()


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def remove_tree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()

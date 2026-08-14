"""On-disk release blobs and evidence zips. Paths use hash hex only (no colon)."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import zipfile
from pathlib import Path

from coreme_hub.db import HubError

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_hash(value: str | None) -> str:
    text = (value or "").strip()
    if HEX_RE.fullmatch(text):
        return f"sha256:{text}"
    if HASH_RE.fullmatch(text):
        return text
    raise HubError(400, "content_hash must be sha256: + 64 lowercase hex")


def hash_hex(value: str) -> str:
    return parse_hash(value).removeprefix("sha256:")


def ensure_data_dir(data_dir: str | Path) -> Path:
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def blob_path(data_dir: str | Path, content_hash: str) -> Path:
    return ensure_data_dir(data_dir) / "blobs" / f"{hash_hex(content_hash)}.zip"


def evidence_file(data_dir: str | Path, assignment_id: str, attempt_id: str) -> Path:
    return ensure_data_dir(data_dir) / "evidence" / assignment_id / f"{attempt_id}.zip"


def zip_tree(root: str | Path) -> bytes:
    src = Path(root)
    if not src.is_dir():
        raise HubError(400, f"not a directory: {src}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(src).as_posix())
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
                raise HubError(400, f"unsafe zip path: {info.filename}")
            out = (target / name).resolve()
            if not out.is_relative_to(root):
                raise HubError(400, f"unsafe zip path: {info.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(info))


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
        raise HubError(404, "release blob not found")
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
        raise HubError(404, "evidence not found")
    return path.read_bytes()


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def remove_tree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()

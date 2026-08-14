"""Content-addressed release cache. Hash is the cache key; verify before run."""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

from coreme.ship import ShipError, hash_job_tree

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleasePullError(Exception):
    """Download or hash verify failed. Attempt should fail without running."""


def parse_hash(value: str | None) -> str:
    text = (value or "").strip()
    if HEX_RE.fullmatch(text):
        return f"sha256:{text}"
    if HASH_RE.fullmatch(text):
        return text
    raise ReleasePullError("content_hash must be sha256: + 64 lowercase hex")


def hash_hex(value: str) -> str:
    return parse_hash(value).removeprefix("sha256:")


def unzip_tree(payload: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            if name.startswith("/") or ".." in Path(name).parts:
                raise ReleasePullError(f"unsafe zip path: {info.filename}")
            out = (dest / name).resolve()
            if not out.is_relative_to(root):
                raise ReleasePullError(f"unsafe zip path: {info.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(info))


def zip_tree(root: Path) -> bytes:
    if not root.is_dir():
        raise ReleasePullError(f"not a directory: {root}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return buf.getvalue()


def resolve_release(
    content_hash: str,
    blob_url: str,
    *,
    cache_dir: str | Path,
    download: Callable[[str], bytes],
    size_bytes: int | None = None,
) -> Path:
    """Return a verified cache directory for *content_hash*.

    Reuses a matching tree. Re-downloads when the cache is missing or dirty.
    """
    digest = parse_hash(content_hash)
    dest = Path(cache_dir) / hash_hex(digest)
    if dest.is_dir():
        if _tree_hash(dest) == digest:
            return dest
        shutil.rmtree(dest)
    payload = download(blob_url)
    if size_bytes is not None and len(payload) != size_bytes:
        raise ReleasePullError(f"blob size mismatch: expected {size_bytes} got {len(payload)}")
    tmp = dest.with_name(dest.name + ".partial")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        unzip_tree(payload, tmp)
        got = _tree_hash(tmp)
        if got != digest:
            raise ReleasePullError(f"content hash mismatch: expected {digest} got {got}")
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dest


def _tree_hash(root: Path) -> str:
    try:
        digest, _count = hash_job_tree(root)
    except ShipError as exc:
        raise ReleasePullError(f"cannot hash release: {exc}") from exc
    return digest

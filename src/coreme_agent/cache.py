"""Content-addressed release cache. Hash is the cache key; verify before run."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from coreme.release import ReleaseError, hash_hex, parse_hash, tree_hash, unzip_tree


class ReleasePullError(Exception):
    """Download or hash verify failed. Attempt should fail without running."""


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
    try:
        digest = parse_hash(content_hash)
    except ReleaseError as exc:
        raise ReleasePullError(str(exc)) from exc
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
        try:
            unzip_tree(payload, tmp)
        except ReleaseError as exc:
            raise ReleasePullError(str(exc)) from exc
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
        digest, _count = tree_hash(root)
    except ReleaseError as exc:
        raise ReleasePullError(f"cannot hash release: {exc}") from exc
    return digest

"""Bundled agent documentation: list, read, install.

The wheel ships synced copies of AGENTS.md and skills/** under
``coreme/agentdocs/`` so a pipx-installed coreme can teach any coding agent
how to author Jobs and operate a fleet without cloning this repo.
Regenerate the copies with ``scripts/sync_agentdocs.py``; repo files stay
the source of truth.
"""

from __future__ import annotations

import shutil
from pathlib import Path

AGENTDOCS_DIR = Path(__file__).resolve().parent / "agentdocs"


class AgentDocsError(Exception):
    """Raised for unknown doc slugs or missing bundled docs."""


def list_docs() -> dict[str, Path]:
    """Map doc slug (posix relative path) -> bundled file."""
    if not AGENTDOCS_DIR.is_dir():
        raise AgentDocsError(f"bundled docs missing at {AGENTDOCS_DIR}; rebuild the package")
    return {
        path.relative_to(AGENTDOCS_DIR).as_posix(): path
        for path in sorted(AGENTDOCS_DIR.rglob("*.md"))
        if path.is_file()
    }


def read_doc(slug: str) -> str:
    """Return the text of one bundled doc by slug."""
    docs = list_docs()
    path = docs.get(slug) or docs.get(f"{slug}.md")
    if path is None:
        known = "\n".join(docs) or "(none)"
        raise AgentDocsError(f"unknown doc {slug!r}; bundled docs:\n{known}")
    return path.read_text(encoding="utf-8")


def install_docs(target: Path) -> list[Path]:
    """Copy every bundled doc into target, preserving relative layout."""
    written: list[Path] = []
    for slug, source in list_docs().items():
        destination = target / slug
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        written.append(destination)
    return written

"""Sync agent-facing docs (AGENTS.md, skills/) into src/coreme/agentdocs/.

The wheel bundles these copies so any pipx-installed coreme carries its own
agent instructions (`coreme skills`). Repo files stay the source of truth;
run with --check in the gate to fail on drift.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST = REPO_ROOT / "src" / "coreme" / "agentdocs"


def _doc_files() -> list[Path]:
    files = [REPO_ROOT / "AGENTS.md"]
    skills = REPO_ROOT / "skills"
    files.extend(sorted(p for p in skills.rglob("*.md") if p.is_file()))
    return [p for p in files if p.is_file()]


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def sync(*, check: bool) -> int:
    drifted = False
    for source in _doc_files():
        target = DEST / source.relative_to(REPO_ROOT)
        current = target.read_bytes() if target.is_file() else b""
        updated = source.read_bytes()
        if hashlib.sha256(current).digest() == hashlib.sha256(updated).digest():
            continue
        if check:
            print(f"out of date: {_relative(source)}")
            drifted = True
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        print(f"synced: {_relative(source)}")
    if not drifted:
        print("agentdocs in sync")
    return 1 if drifted else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if copies are stale")
    args = parser.parse_args()
    return sync(check=args.check)


if __name__ == "__main__":
    sys.exit(main())

"""Create a minimal Job folder."""

from __future__ import annotations

from pathlib import Path

from coreme.manifest import IDENTIFIER

JOB_TOML = """\
name = "{name}"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"

[runtime]
timeout_sec = 60
"""

MAIN_PY = '''\
"""Job entry."""

import os
from pathlib import Path


def main() -> None:
    print("{name} ok")
    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])
    (artifacts / "{name}.txt").write_text("ok\\n", encoding="utf-8")


if __name__ == "__main__":
    main()
'''

TEST_PY = '''\
"""Offline proof for {name}."""

from pathlib import Path

JOB_DIR = Path(__file__).resolve().parent.parent


def test_job_files_exist() -> None:
    assert (JOB_DIR / "JOB.toml").is_file()
    assert (JOB_DIR / "main.py").is_file()
'''

JOB_MD = """\
# {name}

## One sentence

«What this Job does in one line.»

## Machine contract

Source of truth: `JOB.toml` (strict; secret **names** only).

| Field | Value |
|-------|--------|
| name | {name} |
| entry | main.py |
| proof | `coreme test` → `[proof].offline` |
| timeout_sec | 60 |

### Inputs

| Key | Type | Default / required | Role |
|-----|------|--------------------|------|
| — | — | — | none yet |

### Secrets (names only)

None declared.

## Runtime modes

| Mode / path | When | Notes |
|-------------|------|--------|
| default | full entry | «fill if modes differ» |

## Phases (if multistep)

None — single path. Delete this section or fill `PHASE_ORDER` if multistep.

## Artifacts (success)

| Path under `artifacts/` | Meaning |
|-------------------------|---------|
| {name}.txt | proof of success |

## Fail surface

- Job: nonzero exit + clear line in `log.txt`.
- Kernel: `fail.json` on failed Runs.

## Seed / mid-chain (if any)

None.

## Never

- Secret values in Job tree, git, `releases/`, structured evidence
- Edit under `releases/`
- Undocumented LLM / Codex from Job code; live Codex in `coreme test`
- Using Day 7 repair / `--auto-repair` as this Job's runtime-AI path

## Author loop

```text
coreme test ./{name}
coreme run ./{name}
```

## Ops loop

Workspace `OPS.md` after handoff. Bare `coreme run {name}` → latest release.
"""


class InitError(Exception):
    """The Job folder cannot be created."""


def init_job(path: str | Path, name: str) -> Path:
    if not IDENTIFIER.fullmatch(name):
        raise InitError("--name must be an identifier: [A-Za-z][A-Za-z0-9_-]*")

    root = Path(path).resolve()
    if root.exists():
        if not root.is_dir():
            raise InitError(f"Init target is not a directory: {root}")
        if any(root.iterdir()):
            raise InitError(f"Refusing to init into non-empty directory: {root}")

    root.mkdir(parents=True, exist_ok=True)
    (root / "JOB.toml").write_text(JOB_TOML.format(name=name), encoding="utf-8")
    (root / "JOB.md").write_text(JOB_MD.format(name=name), encoding="utf-8")
    (root / "main.py").write_text(MAIN_PY.format(name=name), encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    test_name = name.replace("-", "_")
    (tests / f"test_{test_name}.py").write_text(TEST_PY.format(name=name), encoding="utf-8")
    return root

"""Shared fixtures for kernel tests. Prefer examples/ for product e2e."""

from __future__ import annotations

from pathlib import Path

DEFAULT_ENTRY = (
    "import os\n"
    "from pathlib import Path\n"
    "print('ok')\n"
    "Path(os.environ.get('COREME_ARTIFACTS_DIR', '.'), 'out.txt')"
    ".write_text('ok\\n', encoding='utf-8')\n"
)


def make_repo(root: Path) -> Path:
    """Minimal repo root so ``find_repo_root`` / ship ``releases/`` work."""
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text('name = "coreme"\n', encoding="utf-8")
    return repo


def write_job(
    job: Path,
    *,
    name: str = "demo",
    version: str = "0.1.0",
    entry: str = "main.py",
    entry_content: str | None = None,
    offline: str = "pytest -q",
    proof_py: str | None = None,
    timeout_sec: int | None = 60,
    inputs_toml: str = "",
    secrets_toml: str = "",
) -> Path:
    """Write a Job directory at *job*.

    If *proof_py* is set, writes ``proof_offline.py`` and uses
    ``python proof_offline.py`` as the offline command (overrides *offline*).
    *inputs_toml* / *secrets_toml* are raw TOML fragments (optional leading newline).
    """
    job.mkdir(parents=True, exist_ok=True)
    if proof_py is not None:
        (job / "proof_offline.py").write_text(proof_py, encoding="utf-8")
        offline = "python proof_offline.py"
    if entry_content is None:
        entry_content = DEFAULT_ENTRY if proof_py is not None else "print('x')\n"

    parts = [
        f'name = "{name}"',
        f'version = "{version}"',
        f'entry = "{entry}"',
        "",
        "[proof]",
        f'offline = "{offline}"',
        "",
    ]
    if timeout_sec is not None:
        parts += ["[runtime]", f"timeout_sec = {timeout_sec}", ""]
    text = "\n".join(parts)
    for fragment in (inputs_toml, secrets_toml):
        if fragment:
            text = text.rstrip() + "\n" + fragment.lstrip("\n")
            if not text.endswith("\n"):
                text += "\n"
    (job / "JOB.toml").write_text(text, encoding="utf-8")
    (job / entry).write_text(entry_content, encoding="utf-8")
    return job


def write_job_manifest(job: Path, body: str, entry_content: str = "print('x')\n") -> Path:
    """Write a Job with a full custom JOB.toml body (manifest tests)."""
    job.mkdir(parents=True, exist_ok=True)
    (job / "JOB.toml").write_text(body, encoding="utf-8")
    (job / "main.py").write_text(entry_content, encoding="utf-8")
    return job

"""Integration: runner executes a tiny job and writes a Run folder."""

from __future__ import annotations

import json
from pathlib import Path

from helpers import make_repo

from coreme.init import init_job
from coreme.runner import run_job


def test_run_writes_run_folder(tmp_path: Path) -> None:
    job = tmp_path / "hello"
    init_job(job, "hello")
    # Override entry to always succeed and use env artifacts
    (job / "main.py").write_text(
        """\
import os
from pathlib import Path
print("hello ok")
art = os.environ["COREME_ARTIFACTS_DIR"]
Path(art, "hello.txt").write_text("ok\\n", encoding="utf-8")
""",
        encoding="utf-8",
    )

    repo = make_repo(tmp_path)

    record = run_job(job, repo_root=repo)
    assert record.status == "succeeded"
    assert record.exit_code == 0
    run_path = Path(record.run_path)
    assert run_path.is_dir()
    assert (run_path / "run.json").is_file()
    assert (run_path / "log.txt").is_file()
    assert "hello ok" in (run_path / "log.txt").read_text(encoding="utf-8")
    assert (run_path / "artifacts" / "hello.txt").read_text(encoding="utf-8") == "ok\n"

    data = json.loads((run_path / "run.json").read_text(encoding="utf-8"))
    assert data["status"] == "succeeded"
    assert data["job"] == "hello"
    assert data["exit_code"] == 0
    assert "command" in data

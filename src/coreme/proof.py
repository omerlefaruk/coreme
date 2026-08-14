"""Offline proof for a Job (author-controlled command)."""

from __future__ import annotations

import sys
from pathlib import Path

from coreme._process import run_process
from coreme.manifest import load_manifest


def test_job(job_path: str | Path) -> int:
    """Run the author-controlled offline proof command in the Job folder.

    Applies ``timeout_sec``. On timeout, prints to stderr and returns 124.
    """
    manifest = load_manifest(job_path)
    exit_code, _, _, timed_out = run_process(
        manifest.offline,
        cwd=manifest.job_path,
        timeout_sec=manifest.timeout_sec,
        shell=True,
    )
    if timed_out:
        print(
            f"[coreme] offline proof timed out after {manifest.timeout_sec}s (exit_code=124)",
            file=sys.stderr,
        )
    return exit_code

"""Run evidence for declared inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import write_job

from coreme.inputs import InputError
from coreme.runner import run_job

_INPUT_ENTRY = """\
import json
import os
from pathlib import Path

inputs_path = Path(os.environ["COREME_INPUTS_JSON"])
inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
assert inputs["name"] == os.environ["COREME_INPUT_name"]
assert inputs["source"] == os.environ["COREME_INPUT_source"]
source = Path(inputs["source"])
output = Path(os.environ["COREME_ARTIFACTS_DIR"]) / "result.txt"
output.write_text(f"{inputs['name']}:{source.read_text(encoding='utf-8')}", encoding="utf-8")
"""


def _write_input_job(root: Path) -> Path:
    return write_job(
        root / "job",
        name="input-demo",
        entry_content=_INPUT_ENTRY,
        inputs_toml="""
[inputs.name]
type = "string"
required = true

[inputs.source]
type = "file"
required = true
""",
    )


def test_run_copies_file_input_and_records_used_path(tmp_path: Path) -> None:
    job = _write_input_job(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    repo = tmp_path / "repo"

    record = run_job(
        job,
        repo_root=repo,
        input_pairs=[("name", "Ada"), ("source", str(source))],
    )

    run_path = Path(record.run_path)
    copied_source = run_path / "inputs" / "source"
    evidence = json.loads((run_path / "inputs.json").read_text(encoding="utf-8"))
    run_record = json.loads((run_path / "run.json").read_text(encoding="utf-8"))
    assert record.status == "succeeded"
    assert copied_source.read_text(encoding="utf-8") == "payload"
    assert evidence == record.inputs
    assert run_record["inputs"] == evidence
    assert evidence["source"] == str(copied_source.resolve())
    assert (run_path / "artifacts" / "result.txt").read_text(encoding="utf-8") == "Ada:payload"


def test_invalid_inputs_do_not_create_run_folder(tmp_path: Path) -> None:
    job = _write_input_job(tmp_path)
    repo = tmp_path / "repo"

    with pytest.raises(InputError, match="Missing required input"):
        run_job(job, repo_root=repo)

    assert not (repo / "runs").exists()

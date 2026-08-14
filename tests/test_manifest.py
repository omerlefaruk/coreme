"""Kernel tests for JOB.toml loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import write_job_manifest as _write_job

from coreme.manifest import ManifestError, load_manifest


def test_load_valid_manifest(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "j",
        """\
name = "demo"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"

[runtime]
timeout_sec = 30
""",
    )
    m = load_manifest(job)
    assert m.name == "demo"
    assert m.version == "0.1.0"
    assert m.entry == "main.py"
    assert m.offline == "pytest -q"
    assert m.timeout_sec == 30
    assert Path(m.job_path) == job.resolve()


def test_default_timeout(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "j",
        """\
name = "demo"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"
""",
    )
    m = load_manifest(job)
    assert m.timeout_sec == 60


def test_reject_unknown_top_level(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "j",
        """\
name = "demo"
version = "0.1.0"
entry = "main.py"
ship = true

[proof]
offline = "pytest -q"
""",
    )
    with pytest.raises(ManifestError, match="Unknown top-level"):
        load_manifest(job)


def test_missing_job_toml(tmp_path: Path) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ManifestError, match="JOB.toml not found"):
        load_manifest(d)


def test_missing_entry_file(tmp_path: Path) -> None:
    d = tmp_path / "j"
    d.mkdir()
    (d / "JOB.toml").write_text(
        """\
name = "demo"
version = "0.1.0"
entry = "missing.py"

[proof]
offline = "pytest -q"
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="Entry file not found"):
        load_manifest(d)


def test_load_day2_inputs(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "j",
        """\
name = "demo"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"

[inputs.name]
type = "string"
required = true

[inputs.count]
type = "int"
default = "1"

[inputs.source]
type = "file"
required = false
""",
    )

    manifest = load_manifest(job)

    assert manifest.inputs["name"].required is True
    assert manifest.inputs["count"].default == "1"
    assert manifest.inputs["source"].type == "file"


def test_reject_entry_outside_job_folder(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    job = _write_job(
        tmp_path / "job",
        """\
name = "demo"
version = "0.1.0"
entry = "../outside.py"

[proof]
offline = "pytest -q"
""",
    )

    with pytest.raises(ManifestError, match="inside job folder"):
        load_manifest(job)


def test_reject_unknown_input_field(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "job",
        """\
name = "demo"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"

[inputs.name]
type = "string"
description = "extra"
""",
    )

    with pytest.raises(ManifestError, match="Unknown key"):
        load_manifest(job)


def test_reject_bad_input_type(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "job",
        """\
name = "demo"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"

[inputs.name]
type = "bool"
""",
    )

    with pytest.raises(ManifestError, match="type must be one of"):
        load_manifest(job)


def test_reject_unsafe_manifest_name(tmp_path: Path) -> None:
    job = _write_job(
        tmp_path / "job",
        """\
name = "../escape"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"
""",
    )

    with pytest.raises(ManifestError, match="identifier"):
        load_manifest(job)

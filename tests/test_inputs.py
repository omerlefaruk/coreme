"""Input resolution through the Day 2 public contract."""

from pathlib import Path

import pytest

from coreme import paths
from coreme.inputs import InputError, resolve_inputs
from coreme.manifest import InputSpec, JobManifest


def _manifest(job_path: Path, inputs: dict[str, InputSpec]) -> JobManifest:
    return JobManifest(
        name="demo",
        version="0.1.0",
        entry="main.py",
        offline="pytest -q",
        job_path=str(job_path),
        inputs=inputs,
    )


def test_resolve_inputs_uses_cli_and_string_default(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        {
            "name": InputSpec("string", required=True),
            "count": InputSpec("int", default="1"),
        },
    )

    assert resolve_inputs(manifest, [("name", "Ada")]) == {
        "name": "Ada",
        "count": "1",
    }


@pytest.mark.parametrize(
    ("inputs", "pairs", "message"),
    [
        ({"name": InputSpec("string", required=True)}, [], "Missing required"),
        ({"count": InputSpec("int")}, [("count", "x")], "must be an integer"),
        ({"name": InputSpec("string")}, [("other", "x")], "Unknown input"),
        ({"name": InputSpec("string")}, [("name", "a"), ("name", "b")], "Duplicate input"),
        ({"source": InputSpec("file")}, [("source", "missing.txt")], "file not found"),
    ],
)
def test_resolve_inputs_rejects_invalid_values(
    tmp_path: Path,
    inputs: dict[str, InputSpec],
    pairs: list[tuple[str, str]],
    message: str,
) -> None:
    with pytest.raises(InputError, match=message):
        resolve_inputs(_manifest(tmp_path, inputs), pairs)


def test_resolve_inputs_rejects_values_for_job_without_inputs(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="declares no inputs"):
        resolve_inputs(_manifest(tmp_path, {}), [("name", "Ada")])


def test_root_discovery_is_owned_by_paths_not_runner() -> None:
    import coreme.runner as runner

    assert not hasattr(runner, "find_repo_root")
    assert callable(paths.find_repo_root)

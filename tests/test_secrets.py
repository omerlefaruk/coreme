"""Thin secrets — manifest contract, resolve, evidence names only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import make_repo, write_job, write_job_manifest

from coreme.cli import main
from coreme.inputs import SecretError, resolve_secrets
from coreme.manifest import ManifestError, load_manifest
from coreme.runner import run_job
from coreme.ship import ShipError, ship_job

CANARY = "CANARY_SECRET_VALUE_day4_never_in_evidence"

_BASE = """\
name = "demo"
version = "0.1.0"
entry = "main.py"

[proof]
offline = "pytest -q"

"""


def _scan_tree(root: Path, needle: str) -> list[str]:
    hits: list[str] = []
    if not root.exists():
        return hits
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text:
            hits.append(str(path))
    return hits


def test_valid_secrets_load(tmp_path: Path) -> None:
    job = write_job_manifest(
        tmp_path / "j",
        _BASE + '[secrets]\nnames = ["DEMO_TOKEN", "OTHER_KEY"]\n',
    )
    assert load_manifest(job).secrets == ["DEMO_TOKEN", "OTHER_KEY"]


def test_omitted_secrets_empty_and_run_json(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    job = write_job(tmp_path / "demo", proof_py="print('ok')\n")
    assert load_manifest(job).secrets == []
    record = run_job(job, repo_root=repo)
    data = json.loads(Path(record.run_path).joinpath("run.json").read_text(encoding="utf-8"))
    assert data["secrets"] == []
    assert record.secrets == []


@pytest.mark.parametrize(
    ("secrets_toml", "match"),
    [
        ('[secrets]\nnames = ["DEMO_TOKEN"]\nvault = "nope"\n', "Unknown key"),
        ("[secrets]", "names is required"),
        ('[secrets]\nnames = "DEMO_TOKEN"', "must be an array"),
        ('[secrets]\nnames = ["DEMO_TOKEN", 1]', "non-empty strings"),
        ('[secrets]\nnames = [""]', "non-empty"),
        ('[secrets]\nnames = ["bad-name"]', "Invalid secret name"),
        ('[secrets]\nnames = ["TOKEN", "token"]', "Duplicate"),
        ("[secrets]\nnames = []", "must not be empty"),
        ('[secrets]\nnames = ["COREME_TOKEN"]', "COREME_"),
        ('[secrets]\nnames = ["coreme_token"]', "COREME_"),
        ('[secrets]\nnames = ["Coreme_X"]', "COREME_"),
    ],
)
def test_secrets_schema_rejects(tmp_path: Path, secrets_toml: str, match: str) -> None:
    job = write_job_manifest(tmp_path / "j", _BASE + secrets_toml)
    with pytest.raises(ManifestError, match=match):
        load_manifest(job)


def test_missing_or_empty_secret_exits_before_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        tmp_path / "demo",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["MISSING_TOKEN_DAY4"]\n',
    )
    monkeypatch.delenv("MISSING_TOKEN_DAY4", raising=False)
    before = set((repo / "runs").iterdir()) if (repo / "runs").exists() else set()
    with pytest.raises(SecretError, match="Missing secret"):
        run_job(job, repo_root=repo)
    after = set((repo / "runs").iterdir()) if (repo / "runs").exists() else set()
    assert after == before

    monkeypatch.setenv("MISSING_TOKEN_DAY4", "")
    with pytest.raises(SecretError, match="Missing secret"):
        run_job(job, repo_root=repo)
    after = set((repo / "runs").iterdir()) if (repo / "runs").exists() else set()
    assert after == before


def test_missing_secrets_keep_order_and_no_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        tmp_path / "demo",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["FIRST_MISSING", "SECOND_MISSING"]\n',
    )
    monkeypatch.delenv("FIRST_MISSING", raising=False)
    monkeypatch.delenv("SECOND_MISSING", raising=False)
    before = set((repo / "runs").iterdir()) if (repo / "runs").exists() else set()
    with pytest.raises(SecretError) as exc_info:
        run_job(job, repo_root=repo)
    assert str(exc_info.value) == "Missing secret(s): FIRST_MISSING, SECOND_MISSING"
    after = set((repo / "runs").iterdir()) if (repo / "runs").exists() else set()
    assert after == before

    job2 = write_job(
        tmp_path / "demo2",
        name="demo2",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["PRESENT_KEY", "ABSENT_KEY"]\n',
    )
    monkeypatch.setenv("PRESENT_KEY", CANARY)
    monkeypatch.delenv("ABSENT_KEY", raising=False)
    with pytest.raises(SecretError) as exc_info:
        run_job(job2, repo_root=repo)
    assert str(exc_info.value) == "Missing secret(s): ABSENT_KEY"
    assert CANARY not in str(exc_info.value)


def test_present_secrets_run_order_and_canary_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        tmp_path / "demo",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["BETA_KEY", "ALPHA_KEY"]\n',
        entry_content=(
            "import os\n"
            "assert os.environ['BETA_KEY']\n"
            "assert os.environ['ALPHA_KEY']\n"
            "print('ok')\n"
        ),
    )
    monkeypatch.setenv("BETA_KEY", "b")
    monkeypatch.setenv("ALPHA_KEY", "a")
    record = run_job(job, repo_root=repo)
    assert record.status == "succeeded"
    assert record.secrets == ["BETA_KEY", "ALPHA_KEY"]

    canary_job = write_job(
        tmp_path / "canary",
        name="canary",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["CANARY_TOKEN"]\n',
        entry_content=(
            "import os\n"
            "from pathlib import Path\n"
            "assert os.environ['CANARY_TOKEN']\n"
            "Path(os.environ['COREME_ARTIFACTS_DIR'], 'ok.txt')"
            ".write_text('ok\\n', encoding='utf-8')\n"
            "print('done')\n"
        ),
    )
    monkeypatch.setenv("CANARY_TOKEN", CANARY)
    record = run_job(canary_job, repo_root=repo)
    assert record.status == "succeeded"
    run_path = Path(record.run_path)
    for path in (run_path / "run.json", run_path / "inputs.json"):
        text = path.read_text(encoding="utf-8")
        assert CANARY not in text
    assert _scan_tree(run_path, CANARY) == []


def test_dirty_release_hash_before_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        tmp_path / "demo",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["REL_TOKEN"]\n',
    )
    release, _ = ship_job(job, repo)
    (release / "main.py").write_text("print('dirty')\n", encoding="utf-8")
    monkeypatch.delenv("REL_TOKEN", raising=False)
    before = set((repo / "runs").iterdir()) if (repo / "runs").exists() else set()
    with pytest.raises(ShipError, match="hash mismatch"):
        run_job(release, repo_root=repo)
    after = set((repo / "runs").iterdir()) if (repo / "runs").exists() else set()
    assert after == before


def test_clean_release_with_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        tmp_path / "demo",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["REL_TOKEN"]\n',
        entry_content=("import os\nassert os.environ.get('REL_TOKEN')\nprint('release-ok')\n"),
    )
    release, content_hash = ship_job(job, repo)
    monkeypatch.setenv("REL_TOKEN", "present")
    record = run_job(release, repo_root=repo)
    assert record.status == "succeeded"
    assert record.release is True
    assert record.content_hash == content_hash
    assert record.secrets == ["REL_TOKEN"]


def test_cli_missing_secret_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        tmp_path / "demo",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["CLI_MISSING"]\n',
    )
    monkeypatch.chdir(repo)
    monkeypatch.delenv("CLI_MISSING", raising=False)
    assert main(["run", str(job)]) == 2


def test_resolve_secrets_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job = write_job(
        tmp_path / "demo",
        proof_py="print('ok')\n",
        secrets_toml='[secrets]\nnames = ["A", "B"]\n',
    )
    monkeypatch.setenv("A", "1")
    monkeypatch.setenv("B", "2")
    assert resolve_secrets(load_manifest(job)) == ["A", "B"]


def test_namespace_overlap_input_and_secret_allowed(tmp_path: Path) -> None:
    job = write_job_manifest(
        tmp_path / "j",
        _BASE
        + """\
[inputs.TOKEN]
type = "string"
required = true

[secrets]
names = ["TOKEN"]
""",
    )
    manifest = load_manifest(job)
    assert "TOKEN" in manifest.inputs
    assert manifest.secrets == ["TOKEN"]

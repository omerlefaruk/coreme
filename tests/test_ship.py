"""Day 3: content hash, ship, and release verification."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from helpers import make_repo, write_job

import coreme.ship as ship_module
from coreme.cli import main
from coreme.paths import JobPathError
from coreme.runner import run_job
from coreme.ship import ShipError, hash_job_tree, ship_job, verify_release


def _repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def _write_job(
    root: Path,
    *,
    name: str = "demo",
    version: str = "0.1.0",
    entry_body: str | None = None,
    proof_py: str = "print('ok')\n",
    inputs: str = "",
    timeout_sec: int = 60,
) -> Path:
    return write_job(
        root / name,
        name=name,
        version=version,
        entry_content=entry_body,
        proof_py=proof_py,
        inputs_toml=inputs,
        timeout_sec=timeout_sec,
    )


def test_hash_stable_and_sensitive(tmp_path: Path) -> None:
    job = _write_job(tmp_path)
    first, count = hash_job_tree(job)
    second, count2 = hash_job_tree(job)
    assert first == second
    assert count == count2 >= 2
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64

    (job / "main.py").write_text("print('changed')\n", encoding="utf-8")
    changed, _ = hash_job_tree(job)
    assert changed != first


def test_hash_excludes_pycache_and_root_release(tmp_path: Path) -> None:
    job = _write_job(tmp_path)
    base, base_count = hash_job_tree(job)

    cache = job / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython-311.pyc").write_bytes(b"\x00\x01")
    (job / "main.pyc").write_bytes(b"\x02\x03")
    (job / "RELEASE.json").write_text("{}", encoding="utf-8")
    nested = job / "nested"
    nested.mkdir()
    (nested / "RELEASE.json").write_text('{"nested": true}\n', encoding="utf-8")

    with_noise, noise_count = hash_job_tree(job)
    assert with_noise != base
    assert noise_count == base_count + 1

    (nested / "RELEASE.json").unlink()
    again, again_count = hash_job_tree(job)
    assert again == base
    assert again_count == base_count


def test_hash_nul_content_does_not_collide(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "f").write_bytes(b"a\x00b")
    (b / "f").write_bytes(b"a")
    (b / "g").write_bytes(b"b")
    # Different trees must not share a digest even with embedded NUL
    ha, _ = hash_job_tree(a)
    hb, _ = hash_job_tree(b)
    assert ha != hb

    c = tmp_path / "c"
    c.mkdir()
    (c / "x").write_bytes(b"ab")
    (c / "y").write_bytes(b"")
    # Length prefixes keep path/content boundaries distinct
    assert hash_job_tree(a)[0] != hash_job_tree(c)[0]


def test_ship_creates_release_and_refuses_duplicate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, content_hash = ship_job(job, repo)
    assert release == (repo / "releases" / "demo-0.1.0").resolve()
    envelope = json.loads((release / "RELEASE.json").read_text(encoding="utf-8"))
    assert envelope["content_hash"] == content_hash
    assert envelope["name"] == "demo"
    assert envelope["version"] == "0.1.0"
    assert envelope["content_hash"].startswith("sha256:")
    assert envelope["file_count"] >= 2
    assert (release / "main.py").is_file()
    assert (release / "JOB.toml").is_file()
    temps = [p for p in (repo / "releases").iterdir() if p.name.startswith(".tmp-ship-")]
    assert temps == []

    with pytest.raises(ShipError, match="already exists"):
        ship_job(job, repo)


def test_ship_fails_when_proof_fails_leaves_no_release(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path, proof_py="raise SystemExit(1)\n")
    with pytest.raises(ShipError, match="Offline proof failed"):
        ship_job(job, repo)
    releases = repo / "releases"
    if releases.exists():
        leftovers = list(releases.iterdir())
        assert leftovers == []


def test_ship_rejects_mutating_proof(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(
        tmp_path,
        proof_py="open('main.py', 'a', encoding='utf-8').write('#x\\n')\n",
    )
    with pytest.raises(ShipError, match="mutated"):
        ship_job(job, repo)
    assert list((repo / "releases").iterdir()) == []


def test_ship_strips_proof_caches(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(
        tmp_path,
        proof_py=(
            "import os\n"
            "os.makedirs('__pycache__', exist_ok=True)\n"
            "open('__pycache__/x.pyc', 'wb').write(b'1')\n"
            "open('junk.pyc', 'wb').write(b'2')\n"
        ),
    )
    release, _ = ship_job(job, repo)
    assert not (release / "__pycache__").exists()
    assert not (release / "junk.pyc").exists()


def test_clean_release_run_records_hash(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, _ = ship_job(job, repo)
    record = run_job(release, repo_root=repo)
    assert record.status == "succeeded"
    assert record.release is True
    assert record.content_hash is not None
    data = json.loads(Path(record.run_path).joinpath("run.json").read_text(encoding="utf-8"))
    assert data["release"] is True
    assert data["content_hash"] == record.content_hash


def test_dirty_release_refuses_before_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, _ = ship_job(job, repo)
    (release / "main.py").write_text("print('dirty')\n", encoding="utf-8")
    with pytest.raises(ShipError, match="hash mismatch"):
        run_job(release, repo_root=repo)
    runs = repo / "runs"
    assert not runs.exists() or list(runs.iterdir()) == []


def test_release_name_version_mismatch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, _ = ship_job(job, repo)
    envelope = json.loads((release / "RELEASE.json").read_text(encoding="utf-8"))
    envelope["name"] = "other"
    (release / "RELEASE.json").write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Hash no longer matches envelope content either — still refuse
    with pytest.raises(ShipError):
        run_job(release, repo_root=repo)


def test_release_json_invalid_fields(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, _ = ship_job(job, repo)
    (release / "RELEASE.json").write_text(
        json.dumps({"name": "demo"}, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ShipError, match="Invalid RELEASE.json"):
        verify_release(release)


def test_dev_job_unchanged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    record = run_job(job, repo_root=repo)
    assert record.status == "succeeded"
    assert record.release is False
    assert record.content_hash is None
    data = json.loads(Path(record.run_path).joinpath("run.json").read_text(encoding="utf-8"))
    assert data["release"] is False
    assert data["content_hash"] is None


def test_ship_and_run_with_inputs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(
        tmp_path,
        name="greetish",
        inputs="""
[inputs.name]
type = "string"
required = true
""",
        entry_body=(
            "import os\n"
            "from pathlib import Path\n"
            "name = os.environ['COREME_INPUT_name']\n"
            "Path(os.environ['COREME_ARTIFACTS_DIR'], 'hi.txt')"
            ".write_text(name, encoding='utf-8')\n"
        ),
    )
    release, _ = ship_job(job, repo)
    record = run_job(release, repo_root=repo, input_pairs=[("name", "Ada")])
    assert record.status == "succeeded"
    assert record.release is True
    out = Path(record.run_path) / "artifacts" / "hi.txt"
    assert out.read_text(encoding="utf-8") == "Ada"


def test_unsafe_version_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path, version="1.0-beta")
    with pytest.raises(ShipError, match="version"):
        ship_job(job, repo)
    assert not (repo / "releases").exists() or list((repo / "releases").iterdir()) == []


def test_cli_ship_and_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    monkeypatch.chdir(repo)
    # ship resolves repo from cwd via find_repo_root; job is outside repo
    code = main(["ship", str(job)])
    assert code == 0
    release = repo / "releases" / "demo-0.1.0"
    assert release.is_dir()
    code = main(["ship", str(job)])
    assert code == 2


def _try_symlink(target: Path, link: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError:
        pytest.skip("symlinks not available on this platform/user")


def _try_directory_link(target: Path, link: Path) -> None:
    if os.name != "nt":
        _try_symlink(target, link)
        return
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.skip("directory junctions not available on this platform/user")


def test_symlink_file_in_tree_refused(tmp_path: Path) -> None:
    job = _write_job(tmp_path)
    target = tmp_path / "outside.txt"
    target.write_text("x", encoding="utf-8")
    _try_symlink(target, job / "link.txt")
    with pytest.raises(ShipError, match="link|reparse"):
        hash_job_tree(job)


def test_excluded_directory_link_refused_for_hash_and_release(tmp_path: Path) -> None:
    job = _write_job(tmp_path)
    target = tmp_path / "cache"
    target.mkdir()
    _try_directory_link(target, job / "__pycache__")
    with pytest.raises(ShipError, match="link|reparse"):
        hash_job_tree(job)

    repo = _repo(tmp_path)
    clean_job = _write_job(tmp_path, name="clean")
    release, _ = ship_job(clean_job, repo)
    _try_directory_link(target, release / "__pycache__")
    with pytest.raises(ShipError, match="link|reparse"):
        verify_release(release)


@pytest.mark.parametrize("name", ["ignored.pyc", "RELEASE.json"])
def test_excluded_linked_file_refused(tmp_path: Path, name: str) -> None:
    job = _write_job(tmp_path)
    target = tmp_path / "outside"
    target.write_text("x", encoding="utf-8")
    _try_symlink(target, job / name)
    with pytest.raises(ShipError, match="link|reparse"):
        hash_job_tree(job)


def test_unreadable_walk_error_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _write_job(tmp_path)

    def broken_walk(*args: object, **kwargs: object):
        onerror = kwargs["onerror"]
        assert callable(onerror)
        onerror(OSError("denied"))
        return iter(())

    monkeypatch.setattr(ship_module.os, "walk", broken_walk)
    with pytest.raises(ShipError, match="Cannot walk"):
        hash_job_tree(job)


def test_purge_refuses_linked_cache_before_removal(tmp_path: Path) -> None:
    job = _write_job(tmp_path)
    target = tmp_path / "cache"
    target.mkdir()
    _try_directory_link(target, job / "__pycache__")
    with pytest.raises(ShipError, match="link|reparse"):
        ship_module._purge_excluded(job)


def test_purge_junction_keeps_external_cache_files(tmp_path: Path) -> None:
    job = _write_job(tmp_path)
    target = tmp_path / "cache"
    victim = target / "nested" / "victim.pyc"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(b"do not delete")
    _try_directory_link(target, job / "__pycache__")
    with pytest.raises(ShipError, match="link|reparse"):
        ship_module._purge_excluded(job)
    assert victim.exists()


def test_linked_job_toml_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    manifest = job / "JOB.toml"
    payload = manifest.read_text(encoding="utf-8")
    manifest.unlink()
    external = tmp_path / "manifest.toml"
    external.write_text(payload, encoding="utf-8")
    _try_symlink(external, manifest)
    with pytest.raises(JobPathError, match="link|reparse"):
        run_job(job, repo_root=repo)


def test_symlink_job_root_refused_on_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    link = tmp_path / "job-link"
    _try_symlink(job, link)
    with pytest.raises(JobPathError, match="link|reparse"):
        run_job(link, repo_root=repo)


def test_linked_release_json_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, _ = ship_job(job, repo)
    real = release / "RELEASE.json"
    payload = real.read_text(encoding="utf-8")
    real.unlink()
    external = tmp_path / "env.json"
    external.write_text(payload, encoding="utf-8")
    _try_symlink(external, real)
    with pytest.raises(ShipError, match="link|reparse"):
        run_job(release, repo_root=repo)
    assert not (repo / "runs").exists() or list((repo / "runs").iterdir()) == []


def test_linked_release_root_and_destination_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, _ = ship_job(job, repo)
    root_link = tmp_path / "release-link"
    _try_directory_link(release, root_link)
    with pytest.raises(JobPathError, match="link|reparse"):
        verify_release(root_link)

    second = _write_job(tmp_path, name="other")
    destination = repo / "releases" / "other-0.1.0"
    _try_directory_link(release, destination)
    with pytest.raises(ShipError, match="already exists"):
        ship_job(second, repo)


def test_linked_releases_dir_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    target = tmp_path / "release-target"
    target.mkdir()
    _try_directory_link(target, repo / "releases")
    with pytest.raises(ShipError, match="link|reparse"):
        ship_job(job, repo)


def test_dangling_release_destination_link_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    releases = repo / "releases"
    releases.mkdir()
    _try_symlink(tmp_path / "missing", releases / "demo-0.1.0")
    with pytest.raises(ShipError, match="already exists|escapes releases"):
        ship_job(job, repo)


@pytest.mark.parametrize("failure", ["copy", "proof", "envelope"])
def test_ship_failure_cleans_temp_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    with monkeypatch.context() as patch:
        if failure == "copy":
            patch.setattr(
                ship_module,
                "_copy_tree",
                lambda *args: (_ for _ in ()).throw(ShipError("copy")),
            )
        elif failure == "proof":
            patch.setattr(ship_module, "test_job", lambda *args: 1)
        else:
            write_text = Path.write_text

            def fail_envelope(path: Path, data: str, *args: object, **kwargs: object) -> int:
                if path.name == "RELEASE.json":
                    raise OSError("envelope")
                return write_text(path, data, *args, **kwargs)

            patch.setattr(Path, "write_text", fail_envelope)
        with pytest.raises(ShipError):
            ship_job(job, repo)
    releases = repo / "releases"
    assert list(releases.iterdir()) == []
    assert ship_job(job, repo)[0].is_dir()


def test_ship_stops_timed_out_proof_tree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    marker = tmp_path / "late.txt"
    job = _write_job(
        tmp_path,
        timeout_sec=1,
        proof_py=(
            "import time\n"
            "from pathlib import Path\n"
            "time.sleep(2)\n"
            f"Path({str(marker)!r}).write_text('late', encoding='utf-8')\n"
        ),
    )

    with pytest.raises(ShipError, match="Offline proof failed"):
        ship_job(job, repo)

    time.sleep(2.5)
    assert not marker.exists()
    assert list((repo / "releases").iterdir()) == []


def test_ship_reports_temp_cleanup_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    releases = repo / "releases"
    real_rmtree = ship_module.shutil.rmtree

    with monkeypatch.context() as patch:
        patch.setattr(
            ship_module,
            "_copy_tree",
            lambda *args: (_ for _ in ()).throw(ShipError("copy")),
        )
        patch.setattr(
            ship_module.shutil,
            "rmtree",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("locked")),
        )
        with pytest.raises(ShipError, match="Cannot clean temporary release"):
            ship_job(job, repo)

    for path in releases.iterdir():
        real_rmtree(path)


def test_verify_matches_shipped_hash(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    job = _write_job(tmp_path)
    release, content_hash = ship_job(job, repo)
    assert verify_release(release) == content_hash

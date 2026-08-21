"""Hub: exclusive claim (F2) plus hash pull and evidence (F3)."""

from __future__ import annotations

import io
import json
import os
import threading
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import make_repo, write_job

from coreme_agent.cli import main as agent_main
from coreme_agent.hub import HubClient, HubClientError, enroll_machine
from coreme_hub.blobs import hash_hex
from coreme_hub.db import Pool, StoreError, connect, hash_token, migrate
from coreme_hub.http import parse_bind, serve
from coreme_hub.store import (
    STATUS_CLAIMED,
    STATUS_LEASE_LOST,
    STATUS_PENDING,
    STATUS_SUCCEEDED,
    claim,
    complete,
    create_assignment,
    create_enroll_token,
    create_schedule,
    enqueue,
    fire_due_schedules,
    get_assignment,
    heartbeat,
    hub_stats,
    list_attempts,
    prune_old,
    put_evidence,
    renew,
    set_machine_drained,
    set_schedule_enabled,
    upsert_release,
)

OPS = "ops-secret"
_DUMMY_HASH = "sha256:" + "ab" * 32
_DUMMY_BLOB = f"/v1/releases/{'ab' * 32}/blob"


def _enqueue(conn: object, **kwargs: object) -> object:
    kwargs.setdefault("release_name", "greet")
    kwargs.setdefault("release_version", "1.0.0")
    kwargs.setdefault("content_hash", _DUMMY_HASH)
    kwargs.setdefault("blob_url", _DUMMY_BLOB)
    return create_assignment(conn, **kwargs)  # type: ignore[arg-type]


def test_hash_token_is_sha256() -> None:
    assert hash_token("x") == ("2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881")


def test_parse_bind() -> None:
    assert parse_bind("127.0.0.1:8787") == ("127.0.0.1", 8787)


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    env = os.environ.get("COREME_TEST_PG_DSN")
    if env:
        try:
            with connect(env) as conn:
                conn.execute("SELECT 1")
        except Exception as exc:
            pytest.skip(f"COREME_TEST_PG_DSN is not reachable: {exc}")
        yield env
        return
    if not (
        Path(r"\\.\pipe\dockerDesktopLinuxEngine").exists()
        or Path(r"\\.\pipe\docker_engine").exists()
    ):
        pytest.skip("docker engine pipe is not available")
    postgres = pytest.importorskip("testcontainers.postgres")
    try:
        container = postgres.PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"postgres container unavailable: {exc}")
    url = container.get_connection_url()
    for old in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        url = url.replace(old, "postgresql://")
    try:
        yield url
    finally:
        container.stop()


@pytest.fixture
def schema(pg_dsn: str) -> str:
    name = f"t_{uuid.uuid4().hex[:12]}"
    migrate(pg_dsn, schema=name)
    return name


def test_pool_reuse_keeps_search_path(pg_dsn: str, schema: str) -> None:
    """A rolled-back idle connection must not fall back to public."""
    pool = Pool(pg_dsn, schema=schema, max_size=2)
    try:
        with pool.connection():
            pass  # checkin rolls this connection back
        with pool.connection() as conn:
            row = conn.execute("SHOW search_path").fetchone()
            assert row is not None and schema in str(row["search_path"])
    finally:
        pool.close()


def _register(conn: object, machine_id: str, token: str, tags: list[str]) -> None:
    heartbeat(
        conn,  # type: ignore[arg-type]
        machine_id=machine_id,
        token=token,
        tags=tags,
        status="idle",
        agent_version="test",
    )


def test_two_machines_do_not_double_claim(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", ["site=lab"])
        _register(conn, "m2", "tok-b", ["site=lab"])
        _enqueue(conn, assignment_id="a1")
        conn.commit()

    def _one(mid: str) -> str | None:
        with connect(pg_dsn, schema) as c:
            row = claim(c, machine_id=mid)
            c.commit()
            return None if row is None else str(row["claimed_by"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_one, ["m1", "m2"]))
    won = [r for r in results if r is not None]
    assert len(won) == 1
    assert results.count(None) == 1
    with connect(pg_dsn, schema) as conn:
        row = get_assignment(conn, "a1")
    assert row is not None
    assert row["status"] == STATUS_CLAIMED
    assert row["claimed_by"] == won[0]


def test_expired_lease_is_reclaimed_by_second_machine(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", ["role=invoice"])
        _register(conn, "m2", "tok-b", ["role=invoice"])
        _enqueue(
            conn,
            assignment_id="a2",
            lease_seconds=1,
            required_tags=["role=invoice"],
        )
        first = claim(conn, machine_id="m1")
        assert first is not None
        assert first["claimed_by"] == "m1"
        conn.execute(
            "UPDATE assignments SET lease_until = now() - interval '1 second' WHERE id = %s",
            ("a2",),
        )
        second = claim(conn, machine_id="m2")
        assert second is not None
        assert second["claimed_by"] == "m2"
        assert second["attempt_id"] != first["attempt_id"]
        attempts = list_attempts(conn, "a2")
        statuses = {t["status"] for t in attempts}
        assert STATUS_LEASE_LOST in statuses
        assert "running" in statuses


def test_tag_mismatch_is_not_claimed(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", ["site=lab"])
        _enqueue(conn, required_tags=["site=prod"])
        assert claim(conn, machine_id="m1") is None


def test_renew_and_complete(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", [])
        _enqueue(conn, assignment_id="a3")
        claimed = claim(conn, machine_id="m1")
        assert claimed is not None
        renewed = renew(
            conn,
            assignment_id="a3",
            machine_id="m1",
            attempt_id=str(claimed["attempt_id"]),
        )
        assert renewed["lease_until"] >= claimed["lease_until"]
        done = complete(
            conn,
            assignment_id="a3",
            machine_id="m1",
            attempt_id=str(claimed["attempt_id"]),
            status=STATUS_SUCCEEDED,
            run_id="/runs/x",
            exit_code=0,
        )
        assert done["status"] == STATUS_SUCCEEDED
        assert done["run_id"] == "/runs/x"


def test_complete_accepts_api_sketch_status_alias(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", [])
        _enqueue(conn, assignment_id="a-alias")
        claimed = claim(conn, machine_id="m1")
        assert claimed is not None
        done = complete(
            conn,
            assignment_id="a-alias",
            machine_id="m1",
            attempt_id=str(claimed["attempt_id"]),
            status="success",
            exit_code=0,
        )
        assert done["status"] == STATUS_SUCCEEDED


def test_stale_attempt_cannot_complete_after_reclaim(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", [])
        _enqueue(conn, assignment_id="a4", lease_seconds=1)
        first = claim(conn, machine_id="m1")
        assert first is not None
        conn.execute(
            "UPDATE assignments SET lease_until = now() - interval '1 second' WHERE id = %s",
            ("a4",),
        )
        second = claim(conn, machine_id="m1")
        assert second is not None
        assert second["attempt_id"] != first["attempt_id"]
        with pytest.raises(StoreError) as exc:
            complete(
                conn,
                assignment_id="a4",
                machine_id="m1",
                attempt_id=str(first["attempt_id"]),
                status=STATUS_SUCCEEDED,
                exit_code=0,
            )
        assert exc.value.kind == "conflict"
        done = complete(
            conn,
            assignment_id="a4",
            machine_id="m1",
            attempt_id=str(second["attempt_id"]),
            status=STATUS_SUCCEEDED,
            exit_code=0,
        )
        assert done["status"] == STATUS_SUCCEEDED


def test_stale_attempt_cannot_put_evidence_after_reclaim(
    pg_dsn: str, schema: str, tmp_path: Path
) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", [])
        _enqueue(conn, assignment_id="a-ev", lease_seconds=1)
        first = claim(conn, machine_id="m1")
        assert first is not None
        conn.execute(
            "UPDATE assignments SET lease_until = now() - interval '1 second' WHERE id = %s",
            ("a-ev",),
        )
        second = claim(conn, machine_id="m1")
        assert second is not None
        with pytest.raises(StoreError) as exc:
            put_evidence(
                conn,
                data_dir=tmp_path,
                assignment_id="a-ev",
                attempt_id=str(first["attempt_id"]),
                machine_id="m1",
                payload=b"PK\x03\x04fake",
            )
        assert exc.value.kind == "conflict"
        row = put_evidence(
            conn,
            data_dir=tmp_path,
            assignment_id="a-ev",
            attempt_id=str(second["attempt_id"]),
            machine_id="m1",
            payload=b"PK\x03\x04fake",
        )
        assert row["evidence_bytes"] == 8


def test_enqueue_uses_catalog(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        upsert_release(
            conn,
            content_hash=_DUMMY_HASH,
            name="greet",
            version="1.0.0",
            blob_url=_DUMMY_BLOB,
            size_bytes=1,
        )
        row = enqueue(conn, name="greet", version="1.0.0")
        assert row["status"] == STATUS_PENDING
        assert row["content_hash"] == _DUMMY_HASH
        assert row["blob_url"] == _DUMMY_BLOB


def test_wrong_token_rejected(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", [])
        with pytest.raises(StoreError) as exc:
            heartbeat(conn, machine_id="m1", token="other", tags=[])
        assert exc.value.kind == "forbidden"


@pytest.fixture
def hub(pg_dsn: str, schema: str, tmp_path: Path) -> Iterator[SimpleNamespace]:
    data = tmp_path / "hub-data"
    httpd = serve(
        pg_dsn,
        bind="127.0.0.1:0",
        ops_token=OPS,
        schema=schema,
        data_dir=data,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    try:
        yield SimpleNamespace(url=f"http://{host}:{port}", data=data)
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def hub_url(hub: SimpleNamespace) -> str:
    return str(hub.url)


def _ops(hub_url: str, method: str, path: str, body: dict | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        hub_url + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {OPS}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        if not raw:
            return None
        return json.loads(raw)


def _zip_tree(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return buf.getvalue()


def _register_job(hub_url: str, job: Path, *, name: str | None = None) -> dict:
    req = urllib.request.Request(
        hub_url + "/v1/releases",
        data=_zip_tree(job),
        method="POST",
        headers={
            "Authorization": f"Bearer {OPS}",
            "Content-Type": "application/zip",
            "X-Coreme-Name": name or job.name,
            "X-Coreme-Version": "1.0.0",
        },
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _ops_bytes(hub_url: str, path: str) -> bytes:
    req = urllib.request.Request(
        hub_url + path,
        method="GET",
        headers={"Authorization": f"Bearer {OPS}"},
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def test_http_two_machines_one_assignment(hub_url: str) -> None:
    created = _ops(
        hub_url,
        "POST",
        "/v1/assignments",
        {
            "id": "http-a1",
            "release": {
                "name": "hub-demo",
                "version": "1.0.0",
                "content_hash": _DUMMY_HASH,
                "blob_url": _DUMMY_BLOB,
            },
        },
    )
    assert isinstance(created, dict)
    assert created["status"] == STATUS_PENDING

    a = HubClient(hub_url, "tok-a", "pc-a")
    b = HubClient(hub_url, "tok-b", "pc-b")
    a.heartbeat(tags=["site=lab"], status="idle")
    b.heartbeat(tags=["site=lab"], status="idle")

    first = a.claim()
    second = b.claim()
    assert first is not None
    assert first.id == "http-a1"
    assert second is None

    a.complete(
        "http-a1",
        attempt_id=first.attempt_id,
        status="succeeded",
        exit_code=0,
        run_id="runs/demo",
    )
    listed = _ops(hub_url, "GET", "/v1/assignments?status=succeeded")
    assert isinstance(listed, list)
    assert listed[0]["id"] == "http-a1"


def test_agent_once_against_hub(hub_url: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    job = write_job(repo / "jobs" / "hello", name="hello", version="1.0.0")
    registered = _register_job(hub_url, job)
    created = _ops(
        hub_url,
        "POST",
        "/v1/assignments",
        {"release": {"name": "hello", "version": "1.0.0"}},
    )
    assert isinstance(created, dict)
    assert created["status"] == STATUS_PENDING
    assert created["release"]["content_hash"] == registered["content_hash"]

    code = agent_main(
        [
            "once",
            "--hub",
            hub_url,
            "--machine-id",
            "win-1",
            "--machine-token",
            "machine-tok",
            "--tag",
            "site=lab",
            "--workspace",
            str(repo),
        ]
    )
    assert code == 0
    shown = _ops(hub_url, "GET", f"/v1/assignments/{created['id']}")
    assert isinstance(shown, dict)
    assert shown["status"] == STATUS_SUCCEEDED
    assert isinstance(shown.get("summary"), dict)
    assert shown["summary"]["status"] == "succeeded"


def test_wrong_hash_refuses_run_and_fails_attempt(hub_url: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    job = write_job(repo / "jobs" / "hello", name="hello", version="1.0.0")
    registered = _register_job(hub_url, job)
    wrong = "sha256:" + "cd" * 32
    created = _ops(
        hub_url,
        "POST",
        "/v1/assignments",
        {
            "release": {
                "name": "hello",
                "version": "1.0.0",
                "content_hash": wrong,
                "blob_url": registered["blob_url"],
                "size_bytes": registered["size_bytes"],
            }
        },
    )
    assert isinstance(created, dict)
    code = agent_main(
        [
            "once",
            "--hub",
            hub_url,
            "--machine-id",
            "win-hash",
            "--machine-token",
            "tok-hash",
            "--workspace",
            str(repo),
        ]
    )
    assert code == 1
    shown = _ops(hub_url, "GET", f"/v1/assignments/{created['id']}")
    assert isinstance(shown, dict)
    assert shown["status"] == "failed"
    assert shown["fail"]["kind"] == "release-hash"
    assert "mismatch" in shown["fail"]["message"]
    assert shown["summary"]["message"]
    runs = list((repo / "runs").glob("*")) if (repo / "runs").exists() else []
    assert runs == []


def test_fail_run_uploads_full_tree(hub_url: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        repo / "jobs" / "boom",
        name="boom",
        version="1.0.0",
        entry_content="import sys\nsys.exit(1)\n",
    )
    _register_job(hub_url, job, name="boom")
    created = _ops(
        hub_url,
        "POST",
        "/v1/assignments",
        {"release": {"name": "boom", "version": "1.0.0"}},
    )
    assert isinstance(created, dict)
    code = agent_main(
        [
            "once",
            "--hub",
            hub_url,
            "--machine-id",
            "win-fail",
            "--machine-token",
            "tok-fail",
            "--workspace",
            str(repo),
        ]
    )
    assert code == 1
    shown = _ops(hub_url, "GET", f"/v1/assignments/{created['id']}")
    assert isinstance(shown, dict)
    assert shown["status"] == "failed"
    assert shown["evidence"] is not None
    assert shown["evidence"]["size_bytes"] > 0
    blob = _ops_bytes(hub_url, f"/v1/assignments/{created['id']}/evidence")
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert "fail.json" in names
    assert "run.json" in names


def test_cache_hit_does_not_need_blob(hub: SimpleNamespace, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    job = write_job(repo / "jobs" / "hello", name="hello", version="1.0.0")
    registered = _register_job(hub.url, job)
    _ops(
        hub.url,
        "POST",
        "/v1/assignments",
        {"id": "cache-1", "release": {"name": "hello", "version": "1.0.0"}},
    )
    first = agent_main(
        [
            "once",
            "--hub",
            hub.url,
            "--machine-id",
            "win-cache",
            "--machine-token",
            "tok-cache",
            "--workspace",
            str(repo),
        ]
    )
    assert first == 0
    blob = Path(hub.data) / "blobs" / f"{hash_hex(registered['content_hash'])}.zip"
    assert blob.is_file()
    blob.unlink()
    _ops(
        hub.url,
        "POST",
        "/v1/assignments",
        {"id": "cache-2", "release": {"name": "hello", "version": "1.0.0"}},
    )
    second = agent_main(
        [
            "once",
            "--hub",
            hub.url,
            "--machine-id",
            "win-cache",
            "--machine-token",
            "tok-cache",
            "--workspace",
            str(repo),
        ]
    )
    assert second == 0


def test_secret_values_stay_out_of_index(hub_url: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    job = write_job(repo / "jobs" / "hello", name="hello", version="1.0.0")
    _register_job(hub_url, job)
    secret = "super-secret-value-xyz"
    created = _ops(
        hub_url,
        "POST",
        "/v1/assignments",
        {
            "release": {"name": "hello", "version": "1.0.0"},
            "secret_names": ["API_KEY"],
        },
    )
    assert isinstance(created, dict)
    dumped = json.dumps(created)
    assert "API_KEY" in dumped
    assert secret not in dumped
    assert created["inputs"] == {}
    os.environ["API_KEY"] = secret
    try:
        code = agent_main(
            [
                "once",
                "--hub",
                hub_url,
                "--machine-id",
                "win-sec",
                "--machine-token",
                "tok-sec",
                "--workspace",
                str(repo),
            ]
        )
        assert code == 0
    finally:
        os.environ.pop("API_KEY", None)
    shown = _ops(hub_url, "GET", f"/v1/assignments/{created['id']}")
    assert isinstance(shown, dict)
    text = json.dumps(shown)
    assert secret not in text
    assert "API_KEY" in text


def test_enroll_token_flow(hub_url: str, pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        minted = create_enroll_token(conn, tags=["site=lab"], ttl_hours=1.0)
        conn.commit()
    token = str(minted["token"])

    result = enroll_machine(hub_url, token, tags=["site=lab"], agent_version="test")
    assert result.machine_id
    assert result.machine_token
    assert result.tags == ["site=lab"]

    # The returned credentials are a fully working machine identity.
    client = HubClient(hub_url, result.machine_token, result.machine_id)
    client.heartbeat(tags=["site=lab"], status="idle", agent_version="test")

    # A one-time token cannot be redeemed twice.
    with pytest.raises(HubClientError) as exc:
        enroll_machine(hub_url, token)
    assert exc.value.status == 409

    # Unknown tokens are rejected.
    with pytest.raises(HubClientError) as exc_unknown:
        enroll_machine(hub_url, "no-such-token")
    assert exc_unknown.value.status == 401


def test_health_ready_version_and_metrics(hub_url: str) -> None:
    def _get(path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(hub_url + path, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    status, body = _get("/healthz")
    assert status == 200 and '"ok"' in body
    status, body = _get("/readyz")
    assert status == 200 and '"ready"' in body
    status, body = _get("/version")
    assert status == 200 and '"version"' in body
    status, body = _get("/metrics")
    assert status == 200
    assert "coreme_machines_total 0" in body
    assert "coreme_assignments" in body


def test_drained_machine_does_not_claim(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", ["site=lab"])
        _enqueue(conn, assignment_id="a-drain", required_tags=["site=lab"])
        conn.commit()

        row = set_machine_drained(conn, machine_id="m1", drained=True)
        assert row is not None
        conn.commit()
        assert claim(conn, machine_id="m1") is None

        set_machine_drained(conn, machine_id="m1", drained=False)
        conn.commit()
        claimed = claim(conn, machine_id="m1")
        assert claimed is not None
        conn.commit()


def test_schedule_fires_then_advances(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        upsert_release(
            conn,
            content_hash=_DUMMY_HASH,
            name="greet",
            version="1.0.0",
            blob_url=_DUMMY_BLOB,
            size_bytes=1,
        )
        create_schedule(
            conn,
            name="nightly",
            release_name="greet",
            release_version="1.0.0",
            interval_seconds=3600,
            required_tags=["site=lab"],
        )
        conn.commit()

        fired = fire_due_schedules(conn)
        conn.commit()
        assert len(fired) == 1
        item = fired[0]
        assert item["schedule"] == "nightly"
        created = get_assignment(conn, str(item["assignment_id"]))
        assert created is not None
        assert str(created["batch_id"]).startswith("sched:nightly:")
        assert created["status"] == STATUS_PENDING

        # next_run_at advanced: an immediate second tick fires nothing.
        assert fire_due_schedules(conn) == []
        conn.commit()


def test_disabled_schedule_does_not_fire(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        upsert_release(
            conn,
            content_hash=_DUMMY_HASH,
            name="greet",
            version="1.0.0",
            blob_url=_DUMMY_BLOB,
            size_bytes=1,
        )
        create_schedule(conn, name="off", release_name="greet", interval_seconds=60)
        set_schedule_enabled(conn, name="off", enabled=False)
        conn.commit()
        assert fire_due_schedules(conn) == []
        conn.commit()


def test_prune_old_removes_terminal_assignments(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", [])
        _enqueue(conn, assignment_id="a-old")
        claimed = claim(conn, machine_id="m1")
        assert claimed is not None
        complete(
            conn,
            assignment_id="a-old",
            machine_id="m1",
            attempt_id=str(claimed["attempt_id"]),
            status=STATUS_SUCCEEDED,
            exit_code=0,
        )
        conn.execute(
            "UPDATE assignments SET finished_at = now() - interval '10 days' WHERE id = 'a-old'"
        )
        _enqueue(conn, assignment_id="a-new")
        fresh = claim(conn, machine_id="m1")
        assert fresh is not None
        complete(
            conn,
            assignment_id="a-new",
            machine_id="m1",
            attempt_id=str(fresh["attempt_id"]),
            status=STATUS_SUCCEEDED,
            exit_code=0,
        )
        conn.commit()

        dry = prune_old(conn, days=5, dry_run=True)
        assert dry["assignments"] == 1
        assert dry["attempts"] >= 1

        counts = prune_old(conn, days=5)
        conn.commit()
        assert counts["assignments"] == 1
        assert counts["attempts"] >= 1
        assert get_assignment(conn, "a-old") is None
        assert get_assignment(conn, "a-new") is not None


def test_hub_stats_counts(pg_dsn: str, schema: str) -> None:
    with connect(pg_dsn, schema) as conn:
        _register(conn, "m1", "tok-a", [])
        _enqueue(conn, assignment_id="a-stats")
        stats = hub_stats(conn)
    assert stats["machines_total"] == 1
    assert stats["assignments_by_status"].get(STATUS_PENDING) == 1


def test_schedules_http_route_create_list_validate(hub_url: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    job = write_job(
        repo / "jobs" / "greetjob",
        name="greetjob",
        version="1.0.0",
        inputs_toml='\n[inputs.name]\ntype = "string"\nrequired = true\n',
    )
    _register_job(hub_url, job)

    def _post(path: str, body: dict) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            hub_url + path,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {OPS}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    good = {
        "name": "nightly",
        "release": {"name": "greetjob", "version": "1.0.0"},
        "inputs": {"name": "Fleet"},
        "required_tags": ["site=lab"],
        "interval_seconds": 3600,
    }
    status, created = _post("/v1/schedules", good)
    assert status == 200
    assert created["name"] == "nightly"
    assert created["release"]["name"] == "greetjob"
    assert created["enabled"] is True
    assert created["inputs"] == {"name": "Fleet"}

    status, listed = _get_json(hub_url, "/v1/schedules")
    assert status == 200
    assert any(s["name"] == "nightly" for s in listed)

    unknown = dict(good, name="bad-unknown", inputs={"nope": "x"})
    status, err = _post("/v1/schedules", unknown)
    assert status == 400 and "unknown inputs" in err["error"]

    missing = dict(good, name="bad-missing", inputs={})
    status, err = _post("/v1/schedules", missing)
    assert status == 400 and "missing required inputs" in err["error"]

    ghost = dict(good, name="bad-release", release={"name": "ghost", "version": "9.9.9"})
    status, err = _post("/v1/schedules", ghost)
    assert status == 404


def _get_json(hub_url: str, path: str) -> tuple[int, object]:
    req = urllib.request.Request(hub_url + path, headers={"Authorization": f"Bearer {OPS}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))

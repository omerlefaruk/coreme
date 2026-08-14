"""F1 local agent: SQLite queue + drain with fake coreme."""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from contextlib import suppress
from pathlib import Path

import pytest
from helpers import make_repo, write_job

import coreme_agent.executor as executor_module
from coreme._process import ProcessError
from coreme_agent.cli import main as agent_main
from coreme_agent.executor import (
    RESULT_SCHEMA,
    RESULT_VERSION,
    build_run_argv,
    execute_assignment,
)
from coreme_agent.store import (
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SUCCEEDED,
    STATUS_TIMEOUT,
    LocalQueue,
    QueueError,
)
from coreme_agent.worker import drain, process_one


def _fake_coreme(
    path: Path,
    *,
    exit_code: int = 0,
    run_path: str | None = None,
    fail_message: str | None = None,
) -> list[str]:
    """Write a tiny script with a valid result frame and plain footer."""
    rp = run_path or str(path.parent / "fake-run")
    status = "succeeded" if exit_code == 0 else "failed"
    result = {
        "schema": RESULT_SCHEMA,
        "version": RESULT_VERSION,
        "status": status,
        "exit_code": exit_code,
        "run_path": rp,
        "job": "fake",
        "job_version": "1.0.0",
    }
    if fail_message:
        result["fail_message"] = fail_message
    lines = [
        "import json, os, sys",
        *_write_frame_lines(result),
        f"print({status!r} and f'status={status} exit_code={exit_code}')",
        f"print('run_path=' + {rp!r})",
    ]
    if fail_message:
        lines.append(f"print('fail_message=' + {fail_message!r})")
    lines.append(f"raise SystemExit({exit_code})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [sys.executable, str(path)]


def _fake_coreme_with_result(
    path: Path,
    *,
    exit_code: int,
    result: dict,
    footer_run_path: str,
) -> list[str]:
    """Fake coreme that writes one result frame plus a plain footer."""
    footer_status = "succeeded" if exit_code == 0 else "failed"
    lines = [
        "import json, os, sys",
        *_write_frame_lines(result),
        f"print({footer_status!r} + f' exit_code={exit_code}')",
        f"print('run_path=' + {footer_run_path!r})",
        f"raise SystemExit({exit_code})",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [sys.executable, str(path)]


def _write_frame_lines(result: dict) -> list[str]:
    result_text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    return [
        f"body = {result_text!r}.encode('utf-8')",
        "frame = len(body).to_bytes(4, 'big') + body",
        "locator = os.environ['COREME_RESULT_CHANNEL']",
        "if locator.startswith('handle:'):",
        "    import msvcrt",
        "    fd = msvcrt.open_osfhandle(int(locator[7:]), os.O_WRONLY)",
        "else:",
        "    fd = int(locator)",
        "os.write(fd, frame)",
        "os.close(fd)",
    ]


def test_enqueue_claim_complete(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    release = tmp_path / "job"
    release.mkdir()
    with LocalQueue(db) as q:
        a = q.enqueue(release, inputs={"name": "Ada"}, assignment_id="a1")
        assert a.status == STATUS_PENDING
        assert a.inputs == {"name": "Ada"}
        claimed = q.claim_next()
        assert claimed is not None
        assert claimed.id == "a1"
        assert claimed.status == "running"
        assert claimed.attempt_id
        assert q.claim_next() is None
        done = q.complete(
            "a1",
            status=STATUS_SUCCEEDED,
            exit_code=0,
            run_path=str(tmp_path / "runs" / "x"),
        )
        assert done.status == STATUS_SUCCEEDED
        assert done.run_path
        attempts = q.attempts_for("a1")
        assert len(attempts) == 1
        assert attempts[0].status == STATUS_SUCCEEDED


def test_claim_fifo(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    r = tmp_path / "job"
    r.mkdir()
    with LocalQueue(db) as q:
        q.enqueue(r, assignment_id="first")
        q.enqueue(r, assignment_id="second")
        c1 = q.claim_next()
        c2 = q.claim_next()
        assert c1 is not None and c1.id == "first"
        assert c2 is not None and c2.id == "second"


def test_duplicate_id_raises(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    r = tmp_path / "job"
    r.mkdir()
    with LocalQueue(db) as q:
        q.enqueue(r, assignment_id="same")
        with pytest.raises(QueueError):
            q.enqueue(r, assignment_id="same")


def test_process_one_success_with_fake_coreme(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    fake_run = tmp_path / "runs" / "demo-1"
    fake_run.mkdir(parents=True)
    script = tmp_path / "fake_coreme.py"
    cmd = _fake_coreme(script, exit_code=0, run_path=str(fake_run))
    release = tmp_path / "rel"
    release.mkdir()
    with LocalQueue(db) as q:
        q.enqueue(release, inputs={"k": "v"}, assignment_id="ok1")
        finished = process_one(q, workspace=tmp_path, coreme_cmd=cmd)
    assert finished is not None
    assert finished.status == STATUS_SUCCEEDED
    assert finished.exit_code == 0
    assert finished.run_path == str(fake_run)


def test_process_one_fail_with_fake_coreme(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    fake_run = tmp_path / "runs" / "demo-fail"
    fake_run.mkdir(parents=True)
    script = tmp_path / "fake_coreme.py"
    cmd = _fake_coreme(
        script,
        exit_code=1,
        run_path=str(fake_run),
        fail_message="boom",
    )
    release = tmp_path / "rel"
    release.mkdir()
    with LocalQueue(db) as q:
        q.enqueue(release, assignment_id="bad1")
        finished = process_one(q, workspace=tmp_path, coreme_cmd=cmd)
    assert finished is not None
    assert finished.status == STATUS_FAILED
    assert finished.exit_code == 1
    assert finished.message == "boom"


def test_drain_two(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    script = tmp_path / "fake_coreme.py"
    cmd = _fake_coreme(script, exit_code=0, run_path=str(tmp_path / "r"))
    rel = tmp_path / "rel"
    rel.mkdir()
    with LocalQueue(db) as q:
        q.enqueue(rel, assignment_id="d1")
        q.enqueue(rel, assignment_id="d2")
        done = drain(q, workspace=tmp_path, coreme_cmd=cmd)
    assert len(done) == 2
    assert all(a.status == STATUS_SUCCEEDED for a in done)


def test_idle_once(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    with LocalQueue(db) as q:
        assert process_one(q) is None


def test_build_run_argv_sorted_inputs() -> None:
    from coreme_agent.store import Assignment

    a = Assignment(
        id="x",
        release_path=r"C:\jobs\greet",
        inputs={"b": "2", "a": "1"},
        status=STATUS_PENDING,
        created_at="t",
    )
    argv = build_run_argv(a, coreme_cmd=["coreme"])
    assert argv[:4] == ["coreme", "--plain", "run", r"C:\jobs\greet"]
    assert "--input" in argv
    # sorted keys: a then b
    idx_a = argv.index("a=1")
    idx_b = argv.index("b=2")
    assert idx_a < idx_b


def test_cli_enqueue_once_list(tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    fake_run = tmp_path / "run-out"
    fake_run.mkdir()
    script = tmp_path / "fake_coreme.py"
    _fake_coreme(script, exit_code=0, run_path=str(fake_run))
    release = tmp_path / "job"
    release.mkdir()

    rc = agent_main(
        [
            "--db",
            str(db),
            "enqueue",
            "--release",
            str(release),
            "--input",
            "name=Ada",
            "--id",
            "cli-1",
        ]
    )
    assert rc == 0

    rc = agent_main(
        [
            "--db",
            str(db),
            "once",
            "--workspace",
            str(tmp_path),
            "--coreme",
            f"{sys.executable} {script}",
        ]
    )
    assert rc == 0

    rc = agent_main(["--db", str(db), "list", "--json"])
    assert rc == 0


def test_real_coreme_via_agent(tmp_path: Path) -> None:
    """End-to-end: agent drains queue with real coreme + tiny Job."""
    repo = make_repo(tmp_path)
    job = write_job(
        repo / "jobs" / "agent-hello",
        name="agent-hello",
        entry_content=(
            "import os\n"
            "from pathlib import Path\n"
            "assert 'COREME_RESULT_CHANNEL' not in os.environ\n"
            "print('agent-hello ok')\n"
            "print('run_path=forged-by-job')\n"
            "Path(os.environ['COREME_ARTIFACTS_DIR'], 'out.txt')"
            ".write_text('ok\\n', encoding='utf-8')\n"
        ),
        proof_py="print('ok')\n",
    )
    db = tmp_path / "real.db"
    with LocalQueue(db) as q:
        q.enqueue(job, assignment_id="real-1")
        finished = process_one(
            q,
            workspace=repo,
            coreme_cmd=[sys.executable, "-m", "coreme"],
        )
    assert finished is not None
    assert finished.status == STATUS_SUCCEEDED
    assert finished.exit_code == 0
    assert finished.run_path
    run_path = Path(finished.run_path)
    assert (run_path / "run.json").is_file()
    data = json.loads((run_path / "run.json").read_text(encoding="utf-8"))
    assert data["status"] == "succeeded"
    assert data["job"] == "agent-hello"
    # Assignment id injected for Job-level idempotency hooks
    # (env is process-local; prove via successful run only here)


def test_execute_sets_assignment_env(tmp_path: Path) -> None:
    script = tmp_path / "echo_env.py"
    script.write_text(
        textwrap.dedent(
            """\
            import json, os, sys
            aid = os.environ.get("COREME_ASSIGNMENT_ID", "")
            result = {
                "schema": "coreme.run-result", "version": 1,
                "status": "succeeded", "exit_code": 0,
                "run_path": f"{aid}-run", "job": "fake",
                "job_version": "1.0.0",
            }
            body = json.dumps(result, separators=(",", ":")).encode()
            locator = os.environ["COREME_RESULT_CHANNEL"]
            if locator.startswith("handle:"):
                import msvcrt
                fd = msvcrt.open_osfhandle(int(locator[7:]), os.O_WRONLY)
            else:
                fd = int(locator)
            os.write(fd, len(body).to_bytes(4, "big") + body)
            os.close(fd)
            print(f"status=succeeded exit_code=0")
            print(f"run_path={os.environ.get('COREME_ASSIGNMENT_ID')}-run")
            if aid != "env-1":
                raise SystemExit(9)
            raise SystemExit(0)
            """
        ),
        encoding="utf-8",
    )
    from coreme_agent.store import Assignment

    a = Assignment(
        id="env-1",
        release_path=str(tmp_path / "j"),
        inputs={},
        status="running",
        created_at="t",
        attempt_id="att-1",
        batch_id="batch-9",
    )
    result = execute_assignment(
        a,
        workspace=tmp_path,
        coreme_cmd=[sys.executable, str(script)],
    )
    assert result.status == STATUS_SUCCEEDED
    assert result.run_path == "env-1-run"


def test_result_channel_contract_is_authoritative(tmp_path: Path) -> None:
    """Structured pipe result wins over the --plain footer lines."""
    db = tmp_path / "q.db"
    fake_run = tmp_path / "runs" / "demo-json"
    fake_run.mkdir(parents=True)
    script = tmp_path / "fake_coreme_result.py"
    result = {
        "schema": RESULT_SCHEMA,
        "version": RESULT_VERSION,
        "status": "failed",
        "exit_code": 3,
        "run_path": str(fake_run),
        "job": "demo",
        "job_version": "0.1.0",
        "fail_path": str(fake_run / "fail.json"),
        "fail_message": "structured boom",
        "failed_step": "step 2/3 Prepare failed",
    }
    # The plain footer claims a different run path — the contract must win.
    cmd = _fake_coreme_with_result(
        script,
        exit_code=3,
        result=result,
        footer_run_path=str(tmp_path / "wrong-run"),
    )
    release = tmp_path / "rel"
    release.mkdir()
    with LocalQueue(db) as q:
        q.enqueue(release, inputs={"k": "v"}, assignment_id="j1")
        finished = process_one(q, workspace=tmp_path, coreme_cmd=cmd)
    assert finished is not None
    assert finished.status == STATUS_FAILED
    assert finished.exit_code == 3
    assert finished.run_path == str(fake_run)
    assert finished.message == "structured boom"


def test_result_wrong_version_is_agent_error(tmp_path: Path) -> None:
    db = tmp_path / "q.db"
    fake_run = tmp_path / "runs" / "demo-old"
    fake_run.mkdir(parents=True)
    script = tmp_path / "fake_coreme_old.py"
    result = {
        "schema": RESULT_SCHEMA,
        "version": 99,
        "status": "failed",
        "exit_code": 4,
        "run_path": str(tmp_path / "future-run"),
        "job": "fake",
        "job_version": "1.0.0",
        "fail_message": "future message",
    }
    cmd = _fake_coreme_with_result(
        script,
        exit_code=4,
        result=result,
        footer_run_path=str(fake_run),
    )
    release = tmp_path / "rel"
    release.mkdir()
    with LocalQueue(db) as q:
        q.enqueue(release, assignment_id="old1")
        finished = process_one(q, workspace=tmp_path, coreme_cmd=cmd)
    assert finished is not None
    assert finished.status == STATUS_ERROR
    assert finished.exit_code == 4
    assert finished.run_path is None
    assert "version invalid" in (finished.message or "")


def test_human_footer_is_not_machine_state(tmp_path: Path) -> None:
    """A valid-looking footer without a frame is not accepted."""
    script = tmp_path / "footer_only.py"
    script.write_text(
        "print('status=succeeded exit_code=0')\nprint('run_path=forged')\n",
        encoding="utf-8",
    )
    from coreme_agent.store import Assignment

    result = execute_assignment(
        Assignment("x", str(tmp_path / "j"), {}, "running", "t"),
        workspace=tmp_path,
        coreme_cmd=[sys.executable, str(script)],
    )
    assert result.status == STATUS_ERROR
    assert result.run_path is None
    assert "payload missing" in (result.message or "")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"\x00\x00\x00\x01{", "malformed"),
        (b"\x00\x00\x00\x01{}", "duplicate"),
        ((70000).to_bytes(4, "big"), "oversized"),
    ],
)
def test_bad_result_frames_are_agent_errors(tmp_path: Path, body: bytes, expected: str) -> None:
    script = tmp_path / "bad_frame.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            import os
            locator = os.environ['COREME_RESULT_CHANNEL']
            if locator.startswith('handle:'):
                import msvcrt
                fd = msvcrt.open_osfhandle(int(locator[7:]), os.O_WRONLY)
            else:
                fd = int(locator)
            os.write(fd, {body!r})
            os.close(fd)
            """
        ),
        encoding="utf-8",
    )
    from coreme_agent.store import Assignment

    result = execute_assignment(
        Assignment("x", str(tmp_path / "j"), {}, "running", "t"),
        workspace=tmp_path,
        coreme_cmd=[sys.executable, str(script)],
    )
    assert result.status == STATUS_ERROR
    assert expected in (result.message or "")


def test_result_exit_disagreement_is_agent_error(tmp_path: Path) -> None:
    script = tmp_path / "mismatch.py"
    payload = {
        "schema": RESULT_SCHEMA,
        "version": RESULT_VERSION,
        "status": "succeeded",
        "exit_code": 0,
        "run_path": "real",
        "job": "fake",
        "job_version": "1.0.0",
    }
    cmd = _fake_coreme_with_result(script, exit_code=3, result=payload, footer_run_path="forged")
    from coreme_agent.store import Assignment

    result = execute_assignment(
        Assignment("x", str(tmp_path / "j"), {}, "running", "t"),
        workspace=tmp_path,
        coreme_cmd=cmd,
    )
    assert result.status == STATUS_ERROR
    assert result.run_path is None
    assert "disagrees" in (result.message or "")


def test_result_status_disagreement_is_agent_error(tmp_path: Path) -> None:
    script = tmp_path / "status_mismatch.py"
    payload = {
        "schema": RESULT_SCHEMA,
        "version": RESULT_VERSION,
        "status": "failed",
        "exit_code": 0,
        "run_path": "real",
        "job": "fake",
        "job_version": "1.0.0",
    }
    cmd = _fake_coreme_with_result(script, exit_code=0, result=payload, footer_run_path="forged")
    from coreme_agent.store import Assignment

    result = execute_assignment(
        Assignment("x", str(tmp_path / "j"), {}, "running", "t"),
        workspace=tmp_path,
        coreme_cmd=cmd,
    )
    assert result.status == STATUS_ERROR
    assert "status disagrees" in (result.message or "")


def test_agent_timeout_kills_process_tree_posix(tmp_path: Path) -> None:
    """On POSIX, agent-level timeout must kill the whole coreme process group."""
    if os.name != "posix":
        pytest.skip("process-group kill is POSIX-only")
    child_pid_file = tmp_path / "child.pid"
    script = tmp_path / "hang_coreme.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            import os, subprocess, sys, time
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(300)"]
            )
            open({str(child_pid_file)!r}, "w", encoding="utf-8").write(
                str(child.pid)
            )
            sys.stdout.flush()
            time.sleep(300)
            """
        ),
        encoding="utf-8",
    )
    from coreme_agent.store import Assignment

    a = Assignment(
        id="t1",
        release_path=str(tmp_path / "j"),
        inputs={},
        status="running",
        created_at="t",
    )
    result = execute_assignment(
        a,
        workspace=tmp_path,
        coreme_cmd=[sys.executable, str(script)],
        timeout_sec=1,
    )
    assert result.status == STATUS_TIMEOUT
    assert result.exit_code == 124
    assert "agent-level timeout" in (result.message or "")
    # The grandchild (same process group) must not survive the timeout.
    pid = int(child_pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail(f"child {pid} survived agent-level timeout")


@pytest.mark.skipif(os.name != "posix", reason="POSIX detached descendant behavior")
def test_agent_timeout_is_bounded_with_detached_pipe_holder(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "detached.pid"
    script = tmp_path / "detached.py"
    payload = {
        "schema": RESULT_SCHEMA,
        "version": RESULT_VERSION,
        "status": "succeeded",
        "exit_code": 0,
        "run_path": "untrusted",
        "job": "fake",
        "job_version": "1.0.0",
    }
    frame_lines = "\n".join(_write_frame_lines(payload))
    script.write_text(
        "import json, os, sys\n"
        + frame_lines
        + "\n"
        + textwrap.dedent(
            f"""\
            import subprocess, time
            child = subprocess.Popen(
                [sys.executable, '-c', 'import time; time.sleep(300)'],
                start_new_session=True,
            )
            open({str(child_pid_file)!r}, 'w').write(str(child.pid))
            time.sleep(300)
            """
        ),
        encoding="utf-8",
    )
    from coreme_agent.store import Assignment

    started = time.monotonic()
    result = execute_assignment(
        Assignment("x", str(tmp_path / "j"), {}, "running", "t"),
        workspace=tmp_path,
        coreme_cmd=[sys.executable, str(script)],
        timeout_sec=0.5,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 4
    assert result.status == STATUS_TIMEOUT
    assert result.exit_code == 124
    assert result.run_path is None
    pid = int(child_pid_file.read_text().strip())
    with suppress(ProcessLookupError):
        os.kill(pid, 9)


def test_output_reader_is_the_only_close_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    read_fd, write_fd = os.pipe()
    pipe = os.fdopen(read_fd, "rb", buffering=0)
    reader = executor_module._BoundedOutput(pipe)
    tracked_fd = reader.fd
    real_close = os.close
    closes: list[tuple[int, int | None]] = []

    def recording_close(fd: int) -> None:
        if fd == tracked_fd:
            closes.append((fd, executor_module.threading.current_thread().ident))
        real_close(fd)

    monkeypatch.setattr(executor_module.os, "close", recording_close)
    reader.thread.start()
    reader.stop_bounded()

    assert not reader.thread.is_alive()
    assert closes == [(tracked_fd, reader.thread.ident)]

    # Reuse the released descriptor and prove no late reader close can hit it.
    replacement_read, replacement_write = os.pipe()
    assert tracked_fd in {replacement_read, replacement_write}
    os.write(replacement_write, b"x")
    assert os.read(replacement_read, 1) == b"x"
    real_close(replacement_read)
    real_close(replacement_write)
    real_close(write_fd)


@pytest.mark.parametrize(
    ("operation", "detail"),
    [
        ("create", "Cannot create Windows Job Object"),
        ("assign", "Cannot contain process tree"),
        ("resume", "Cannot resume contained process"),
        ("terminate", "Cannot stop process tree"),
    ],
)
def test_windows_job_process_error_completes_assignment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    detail: str,
) -> None:
    def fail_job_operation(*args: object, **kwargs: object) -> tuple[str, str, int, bool]:
        raise ProcessError(detail)

    monkeypatch.setattr(executor_module, "_run_coreme", fail_job_operation)
    release = tmp_path / "rel"
    release.mkdir()
    with LocalQueue(tmp_path / "q.db") as queue:
        queue.enqueue(release, assignment_id=f"job-{operation}")
        finished = process_one(queue, workspace=tmp_path)
        attempts = queue.attempts_for(f"job-{operation}")

    assert finished is not None
    assert finished.status == STATUS_ERROR
    assert finished.exit_code is None
    assert finished.run_path is None
    assert detail in (finished.message or "")
    assert len(attempts) == 1
    assert attempts[0].status == STATUS_ERROR


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
def test_agent_timeout_contains_windows_process_tree(tmp_path: Path) -> None:
    marker = tmp_path / "late.txt"
    script = tmp_path / "windows_tree.py"
    child_code = (
        "import time; from pathlib import Path; time.sleep(2); "
        f"Path({str(marker)!r}).write_text('late')"
    )
    script.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    from coreme_agent.store import Assignment

    result = execute_assignment(
        Assignment("x", str(tmp_path / "j"), {}, "running", "t"),
        workspace=tmp_path,
        coreme_cmd=[sys.executable, str(script)],
        timeout_sec=0.5,
    )
    assert result.status == STATUS_TIMEOUT
    time.sleep(2.5)
    assert not marker.exists()

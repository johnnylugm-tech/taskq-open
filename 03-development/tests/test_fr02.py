"""FR-02 — Task run endpoint (`/v1/tasks/{id}/run`, `/v1/tasks/{id}/runs`).

Covers TEST_SPEC.md FR-02 rows 1-11 (AC-2.1 .. AC-2.5, SEC T-06, SEC T-11).

Test harness contract:
- HTTP cases drive `taskq_api.app.create_app()` in-process through FastAPI's
  TestClient; each test points `TASKQ_DB_URL` at a fresh SQLite file
  (state_mode="isolate_per_test"). A submitted run executes in the background
  of the app's event loop; tests poll the database until it is terminal.
- `POST /v1/tasks/{id}/run` returns 202 `{"run_id": <str>, ...}`.
- `GET /v1/tasks/{id}/runs` returns `{"items": [...]}`; each item carries
  `run_id` and the `task_results` columns (`exit_code`, `stdout_tail`,
  `stderr_tail`, `duration_ms`, `finished_at`), newest first.
- In-process runner cases (subprocess_mode="in_process") use
  `taskq_api.service.runner`:
    * `TaskStateMachine()` starts in `pending`; `.state`, `.history`
      (every state entered, starting with `pending`), `.transition(to)` which
      raises `InvalidTransition` for an illegal move.
    * `async run_command(command, machine=...)` executes
      `asyncio.create_subprocess_exec(*shlex.split(command))` with the
      `TASKQ_TASK_TIMEOUT` (seconds) read from the environment, drives the
      machine and returns an outcome with `status`, `exit_code`,
      `stdout_tail`, `stderr_tail`, `duration_ms`, `finished_at`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shlex
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.api import routes_runs  # noqa: E402,F401
from taskq_api.app import create_app  # noqa: E402
from taskq_api.models.base import Base  # noqa: E402
from taskq_api.repository import results  # noqa: E402,F401
from taskq_api.service import runner, runs  # noqa: E402,F401

PROBLEM_JSON = "application/problem+json"
KEYS = {
    "read": "sk-test-read-0123456789",
    "write": "sk-test-write-0123456789",
    "admin": "sk-test-admin-0123456789",
}
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
TERMINAL_STATES = ("done", "failed", "timeout")
WAIT_SECONDS = 15.0


def _headers(scope: str) -> dict[str, str]:
    return {"X-API-Key": KEYS[scope]}


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Env:
    """Per-test application + raw SQLite handle for seeding/inspection."""

    def __init__(self, db_file: Path, client: TestClient) -> None:
        self.db_file = db_file
        self.client = client

    def sql(self, statement: str, params: tuple = ()) -> list[tuple]:
        conn = sqlite3.connect(self.db_file)
        try:
            rows = conn.execute(statement, params).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def seed_task(self, command: str, status: str = "pending") -> str:
        """Insert a task directly, bypassing FR-01 create-time validation."""
        task_id = str(uuid.uuid4())
        self.sql(
            "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, command, f"task-{task_id[:8]}", status, BASE_TIME.isoformat()),
        )
        return task_id

    def run(self, task_id: str):
        return self.client.post(f"/v1/tasks/{task_id}/run", headers=_headers("write"))

    def wait_finished(self, task_id: str) -> list[tuple]:
        """Poll until the task is terminal and its result row is finished."""
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            status_rows = self.sql("SELECT status FROM tasks WHERE id = ?", (task_id,))
            result_rows = self.sql(
                "SELECT id, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at "
                "FROM task_results WHERE task_id = ? AND finished_at IS NOT NULL",
                (task_id,),
            )
            if status_rows and status_rows[0][0] in TERMINAL_STATES and result_rows:
                return result_rows
            time.sleep(0.05)
        pytest.fail(f"run of task {task_id} did not finish within {WAIT_SECONDS}s")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_file = tmp_path / "taskq.db"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "10")
    # Rate limiting (FR-05) must not interfere with FR-02 behaviour.
    monkeypatch.setenv("TASKQ_RATE_BURST", "100000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "100000")

    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    engine.dispose()

    conn = sqlite3.connect(db_file)
    for scope, plaintext in KEYS.items():
        conn.execute(
            "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
            (
                str(uuid.uuid4()),
                hashlib.sha256(plaintext.encode()).hexdigest(),
                scope,
                BASE_TIME.isoformat(),
            ),
        )
    conn.commit()
    conn.close()

    with TestClient(create_app()) as client:
        yield Env(db_file, client)


@pytest.fixture
def spawn_spy(monkeypatch):
    """Record every subprocess spawn while still running the real process."""
    calls: list[dict] = []
    real_exec = asyncio.create_subprocess_exec

    async def spy_exec(*argv, **kwargs):
        calls.append({"argv": list(argv), "kwargs": dict(kwargs), "api": "exec"})
        return await real_exec(*argv, **kwargs)

    async def forbidden_shell(cmd, **kwargs):
        calls.append({"argv": [cmd], "kwargs": dict(kwargs), "api": "shell"})
        raise AssertionError("create_subprocess_shell must never be used (AC-2.2)")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_shell)
    # Also intercept `from asyncio import create_subprocess_exec` style imports.
    monkeypatch.setattr(runner, "create_subprocess_exec", spy_exec, raising=False)
    monkeypatch.setattr(runner, "create_subprocess_shell", forbidden_shell, raising=False)
    return calls


def _run_in_process(command: str):
    machine = runner.TaskStateMachine()
    outcome = asyncio.run(runner.run_command(command, machine=machine))
    return machine, outcome


# --- AC-2.1 -----------------------------------------------------------------

def test_fr02_run_returns_202_with_run_id(env):
    expected_status = "202"
    task_id = env.seed_task("echo ok")
    resp = env.run(task_id)
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    result_run_id = resp.json()["run_id"]
    assert isinstance(result_run_id, str)
    assert len(result_run_id) > 0

    env.wait_finished(task_id)
    history = env.client.get(f"/v1/tasks/{task_id}/runs", headers=_headers("read"))
    assert history.status_code == 200, history.text
    assert [item["run_id"] for item in history.json()["items"]] == [result_run_id]


def test_fr02_run_unknown_task_returns_404(env):
    expected_status = "404"
    unknown_id = "00000000-0000-0000-0000-000000000000"
    resp = env.run(unknown_id)
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    assert resp.headers["content-type"].startswith(PROBLEM_JSON)
    body = resp.json()
    assert body["status"] == 404
    assert body["type"].endswith("/errors/not-found")
    assert env.sql("SELECT COUNT(*) FROM task_results") == [(0,)]


# --- AC-2.2 -----------------------------------------------------------------

# GREEN TODO: taskq_api.service.runner must spawn via
# asyncio.create_subprocess_exec(*shlex.split(command)) (never the shell
# variant, never shell=True) and honour TASKQ_TASK_TIMEOUT from the env.
# NFR-02
def test_fr02_run_uses_exec_without_shell_and_times_out(monkeypatch, spawn_spy):
    task_command = "sleep 30"
    expected_final_status = "timeout"
    expected_shell_flag = "False"
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.5")

    started = time.monotonic()
    _machine, outcome = _run_in_process(task_command)
    elapsed = time.monotonic() - started

    result_final_status = outcome.status
    assert result_final_status == expected_final_status
    assert len(spawn_spy) == 1, spawn_spy
    spawn = spawn_spy[0]
    assert spawn["api"] == "exec"
    result_used_shell_text = str(bool(spawn["kwargs"].get("shell", False)))
    assert result_used_shell_text == expected_shell_flag
    result_spawn_argv = spawn["argv"]
    result_shlex_split_command = shlex.split(task_command)
    assert result_spawn_argv == result_shlex_split_command
    # The 30 s process was killed at the 0.5 s timeout, not awaited to completion.
    assert elapsed < 10, elapsed


# --- AC-2.3 -----------------------------------------------------------------

def test_fr02_run_lifecycle_state_machine():
    task_command = "true"
    expected_transitions = "pending,running,done"
    machine, outcome = _run_in_process(task_command)
    result_transitions = list(machine.history)
    assert result_transitions == expected_transitions.split(",")
    assert machine.state == "done"
    assert outcome.status == "done"
    assert outcome.exit_code == 0


def test_fr02_run_lifecycle_failed_on_nonzero_exit():
    task_command = "false"
    expected_transitions = "pending,running,failed"
    machine, outcome = _run_in_process(task_command)
    result_transitions = list(machine.history)
    assert result_transitions == expected_transitions.split(",")
    assert machine.state == "failed"
    assert outcome.status == "failed"
    assert outcome.exit_code != 0


# NFR-03
def test_fr02_run_lifecycle_timeout(monkeypatch):
    task_command = "sleep 30"
    expected_transitions = "pending,running,timeout"
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.5")
    machine, outcome = _run_in_process(task_command)
    result_transitions = list(machine.history)
    assert result_transitions == expected_transitions.split(",")
    assert machine.state == "timeout"
    assert outcome.status == "timeout"


@pytest.mark.parametrize(
    "task_command",
    ["   ", "echo 'unterminated", "taskq-no-such-binary-xyz --flag"],
    ids=["empty", "unparsable", "not_found"],
)
def test_fr02_run_unspawnable_command_ends_failed(task_command):
    machine, outcome = _run_in_process(task_command)
    assert list(machine.history) == ["pending", "running", "failed"]
    assert outcome.status == "failed"
    assert outcome.exit_code is None
    assert outcome.stdout_tail == ""
    assert outcome.stderr_tail != ""


def test_fr02_state_machine_rejects_backward_transition():
    from_state = "done"
    to_state = "running"
    machine = runner.TaskStateMachine()
    machine.transition("running")
    machine.transition(from_state)
    assert machine.state == from_state

    try:
        machine.transition(to_state)
        result_transition_accepted = True
    except runner.InvalidTransition:
        result_transition_accepted = False
    assert not result_transition_accepted
    assert machine.state == from_state
    assert list(machine.history) == ["pending", "running", "done"]


# --- AC-2.4 -----------------------------------------------------------------

def test_fr02_results_persisted_in_task_results(env):
    task_command = "echo out"
    expected_columns = "exit_code,stdout_tail,stderr_tail,duration_ms,finished_at"
    expected_exit_code = "0"
    expected_stdout = "out"

    task_id = env.seed_task(task_command)
    resp = env.run(task_id)
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    rows = env.wait_finished(task_id)
    assert len(rows) == 1

    table_columns = [row[1] for row in env.sql("PRAGMA table_info(task_results)")]
    result_columns = [c for c in table_columns if c not in ("id", "task_id")]
    assert sorted(result_columns) == sorted(expected_columns.split(","))

    _row_id, result_exit_code, result_stdout_tail, stderr_tail, duration_ms, finished_at = rows[0]
    assert result_exit_code == int(expected_exit_code)
    assert result_stdout_tail.strip() == expected_stdout
    assert stderr_tail is not None and stderr_tail.strip() == ""
    assert isinstance(duration_ms, int) and duration_ms >= 0
    assert _parse_ts(finished_at).tzinfo is not None
    assert env.sql("SELECT status FROM tasks WHERE id = ?", (task_id,)) == [("done",)]

    history = env.client.get(f"/v1/tasks/{task_id}/runs", headers=_headers("read"))
    assert history.status_code == 200, history.text
    item = history.json()["items"][0]
    assert item["run_id"] == run_id
    assert item["exit_code"] == 0
    assert item["stdout_tail"].strip() == expected_stdout


# --- AC-2.5 -----------------------------------------------------------------

def test_fr02_runs_history_newest_first(env):
    seeded_runs = "3"
    expected_order = "newest_first"
    task_id = env.seed_task("echo hist", status="done")
    run_ids_by_age = [str(uuid.uuid4()) for _ in range(int(seeded_runs))]  # oldest first
    # Insert out of chronological order so insertion order cannot pass the test.
    for offset in (1, 0, 2):
        finished = BASE_TIME + timedelta(minutes=offset)
        env.sql(
            "INSERT INTO task_results (id, task_id, exit_code, stdout_tail, stderr_tail, "
            "duration_ms, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_ids_by_age[offset], task_id, 0, f"run-{offset}", "", 10, finished.isoformat()),
        )
    other_task = env.seed_task("echo other", status="done")
    env.sql(
        "INSERT INTO task_results (id, task_id, exit_code, stdout_tail, stderr_tail, "
        "duration_ms, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), other_task, 0, "other", "", 10, (BASE_TIME + timedelta(hours=1)).isoformat()),
    )

    resp = env.client.get(f"/v1/tasks/{task_id}/runs", headers=_headers("read"))
    assert resp.status_code == 200, resp.text
    result_runs = resp.json()["items"]
    assert len(result_runs) == int(seeded_runs)
    finished_list = [_parse_ts(item["finished_at"]) for item in result_runs]
    ids_newest_first = list(reversed(run_ids_by_age))
    result_run_order = (
        "newest_first"
        if finished_list == sorted(finished_list, reverse=True)
        and [item["run_id"] for item in result_runs] == ids_newest_first
        else "other"
    )
    assert result_run_order == expected_order


# --- SEC T-06 ---------------------------------------------------------------

def test_sec_t06_shell_metacharacters_not_interpreted(env):
    # SPEC_AMBIGUITY: TEST_SPEC precondition says `$` is accepted at create, but
    # the FR-01 injection blacklist rejects it; the task is seeded directly so
    # this case exercises only the run path (no shell expansion at exec time).
    task_command = "echo $HOME"
    expected_stdout_tail = "$HOME"
    task_id = env.seed_task(task_command)
    resp = env.run(task_id)
    assert resp.status_code == 202, resp.text
    rows = env.wait_finished(task_id)
    result_stdout_tail = rows[0][2]
    assert result_stdout_tail.strip() == expected_stdout_tail


# --- SEC T-11 ---------------------------------------------------------------

# NFR-04
def test_sec_t11_secrets_redacted_in_output_and_logs(env, caplog):
    task_command = "echo sk-abcdefgh12345678"
    secret_literal = "sk-abcdefgh12345678"
    expected_stdout_tail = "[REDACTED]"
    caplog.set_level(logging.DEBUG)

    task_id = env.seed_task(task_command)
    resp = env.run(task_id)
    assert resp.status_code == 202, resp.text
    rows = env.wait_finished(task_id)
    result_stdout_tail = rows[0][2]
    assert result_stdout_tail.strip() == expected_stdout_tail
    assert secret_literal not in result_stdout_tail

    history = env.client.get(f"/v1/tasks/{task_id}/runs", headers=_headers("read"))
    assert history.status_code == 200, history.text
    assert secret_literal not in history.text

    result_log_text = caplog.text
    assert secret_literal not in result_log_text

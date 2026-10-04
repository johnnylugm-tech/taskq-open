"""FR-08 — Async executor (TaskGroup, concurrency cap, timeout kill, drain).

Covers TEST_SPEC.md FR-08 rows 1-7 (AC-8.1 .. AC-8.4, NP-13, NP-15, SEC T-07).

Test harness contract:
- `taskq_api.service.executor.Executor()` reads `TASKQ_MAX_CONCURRENT` from the
  environment (through `load_settings()`) and is an async context manager that
  owns an `asyncio.TaskGroup`:
    * `ex.enqueue(job)` (sync) accepts a zero-argument callable returning an
      awaitable. The callable is invoked only when a concurrency slot is free,
      so excess jobs wait in a queue and no coroutine is created for them
      ("不得無限制生成 coroutine").
    * `await ex.drain()` waits for queued and in-flight jobs for at most
      `TASKQ_DRAIN_TIMEOUT` seconds; jobs still unfinished are cancelled.
  `asyncio.CancelledError` is never swallowed: cancelling the task that owns
  the executor raises `CancelledError` in that task.
- `taskq_api.service.runner.run_command` kills (`process.kill()`) and reaps
  (`await process.wait()`) its subprocess on timeout AND on cancellation, then
  lets `CancelledError` propagate.
- `taskq_api.app.create_app()` submits runs through the executor; on shutdown
  the lifespan drains it with `TASKQ_DRAIN_TIMEOUT` and runs still unfinished
  end with task status `interrupted` (NFR-99.4) and leave no orphan process.

subprocess_mode="in_process": every case runs the service code in this
interpreter (TestClient or asyncio.run) so pytest-cov measures it; only the
task command itself (`sleep ...`) is a child process, observed through a spy
on `asyncio.create_subprocess_exec` (mocking only at the OS-process boundary).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.app import create_app  # noqa: E402
from taskq_api.models.base import Base  # noqa: E402
from taskq_api.service import executor, runner  # noqa: E402

WRITE_KEY = "sk-test-write-0123456789"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
WAIT_SECONDS = 10.0
ORPHAN_GRACE_SECONDS = 1.0


# --- helpers ----------------------------------------------------------------

class ProcessSpy:
    """Record every spawned child and the kill/wait calls made on it."""

    def __init__(self) -> None:
        self.pids: list[int] = []
        self.events: dict[int, list[str]] = {}

    def waited_after_kill(self) -> bool:
        """Every killed process had `wait()` complete after its last `kill()`."""
        killed = [pid for pid, seen in self.events.items() if "kill" in seen]
        if not killed:
            return False
        for pid in killed:
            seen = self.events[pid]
            last_kill = max(i for i, name in enumerate(seen) if name == "kill")
            if "wait_done" not in seen[last_kill + 1:]:
                return False
        return True

    def orphan_pids(self) -> list[int]:
        """Spawned children still present (running or unreaped zombie)."""
        deadline = time.monotonic() + ORPHAN_GRACE_SECONDS
        alive = list(self.pids)
        while alive and time.monotonic() < deadline:
            alive = [pid for pid in alive if _pid_exists(pid)]
            if alive:
                time.sleep(0.05)
        return [pid for pid in alive if _pid_exists(pid)]

    def kill_leftovers(self) -> None:
        for pid in self.pids:
            if _pid_exists(pid):
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.fixture
def process_spy(monkeypatch):
    """Wrap asyncio.create_subprocess_exec; the real process still runs."""
    spy = ProcessSpy()
    real_exec = asyncio.create_subprocess_exec

    async def spy_exec(*argv, **kwargs):
        process = await real_exec(*argv, **kwargs)
        pid = process.pid
        spy.pids.append(pid)
        spy.events[pid] = []
        real_kill = process.kill
        real_wait = process.wait

        def kill():
            spy.events[pid].append("kill")
            return real_kill()

        async def wait():
            spy.events[pid].append("wait")
            code = await real_wait()
            spy.events[pid].append("wait_done")
            return code

        process.kill = kill
        process.wait = wait
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    monkeypatch.setattr(runner, "create_subprocess_exec", spy_exec, raising=False)
    yield spy
    spy.kill_leftovers()


class Env:
    """Per-test application, unstarted TestClient and raw SQLite handle."""

    def __init__(self, db_file: Path) -> None:
        self.db_file = db_file
        self.client: TestClient | None = None

    def sql(self, statement: str, params: tuple = ()) -> list[tuple]:
        conn = sqlite3.connect(self.db_file)
        try:
            rows = conn.execute(statement, params).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def start(self) -> TestClient:
        self.client = TestClient(create_app())
        self.client.__enter__()
        return self.client

    def shutdown(self) -> float:
        """Run the lifespan shutdown (graceful drain); return its duration."""
        assert self.client is not None
        started = time.monotonic()
        self.client.__exit__(None, None, None)
        elapsed = time.monotonic() - started
        self.client = None
        return elapsed

    def seed_task(self, command: str) -> str:
        task_id = str(uuid.uuid4())
        self.sql(
            "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, command, f"task-{task_id[:8]}", "pending", BASE_TIME.isoformat()),
        )
        return task_id

    def run(self, task_id: str) -> str:
        assert self.client is not None
        resp = self.client.post(f"/v1/tasks/{task_id}/run", headers={"X-API-Key": WRITE_KEY})
        assert resp.status_code == 202, resp.text
        return resp.json()["run_id"]

    def status(self, task_id: str) -> str:
        return self.sql("SELECT status FROM tasks WHERE id = ?", (task_id,))[0][0]


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_file = tmp_path / "taskq.db"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "60")
    # Rate limiting (FR-05) must not interfere with FR-08 behaviour.
    monkeypatch.setenv("TASKQ_RATE_BURST", "100000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "100000")

    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    engine.dispose()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
        (str(uuid.uuid4()), hashlib.sha256(WRITE_KEY.encode()).hexdigest(), "write", BASE_TIME.isoformat()),
    )
    conn.commit()
    conn.close()

    state = Env(db_file)
    yield state
    if state.client is not None:
        state.shutdown()


class Tracker:
    """Measure how many jobs exist at once; a job counts from creation."""

    def __init__(self, duration: float) -> None:
        self.duration = duration
        self.running = 0
        self.peak = 0
        self.completed = 0
        self.intervals: list[tuple[float, float]] = []

    def job(self):
        # Called by the executor only when a slot is free: creating the
        # coroutine is what counts as "running" (no unbounded coroutines).
        self.running += 1
        self.peak = max(self.peak, self.running)
        return self._body()

    async def _body(self) -> None:
        started = time.monotonic()
        try:
            await asyncio.sleep(self.duration)
        finally:
            self.running -= 1
        self.completed += 1
        self.intervals.append((started, time.monotonic()))


async def _run_tracked(submitted: int, duration: float) -> tuple[Tracker, int, float]:
    tracker = Tracker(duration)
    started = time.monotonic()
    async with executor.Executor() as ex:
        for _ in range(submitted):
            ex.enqueue(tracker.job)
        await asyncio.sleep(duration / 2)
        in_flight_early = tracker.running
        await ex.drain()
    return tracker, in_flight_early, time.monotonic() - started


def _wait_until(predicate, what: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail(f"timed out waiting for {what}")


# --- AC-8.1 -----------------------------------------------------------------

# GREEN TODO: create_app() must submit runs via service.executor and its
# lifespan must drain with TASKQ_DRAIN_TIMEOUT, marking stragglers `interrupted`.
# NFR-03
def test_fr08_graceful_drain_marks_interrupted(env, process_spy, monkeypatch):
    TASKQ_DRAIN_TIMEOUT = "0.5"
    inflight_command = "sleep 30"
    expected_final_status = "interrupted"
    monkeypatch.setenv("TASKQ_DRAIN_TIMEOUT", TASKQ_DRAIN_TIMEOUT)

    env.start()
    task_id = env.seed_task(inflight_command)
    env.run(task_id)
    _wait_until(lambda: process_spy.pids and env.status(task_id) == "running", "the run to start")

    result_drain_elapsed_s = env.shutdown()
    result_final_status = env.status(task_id)

    # rule_id: AC8.1-status
    assert result_final_status == expected_final_status
    # rule_id: AC8.1-drain-bounded
    assert result_drain_elapsed_s <= float(TASKQ_DRAIN_TIMEOUT) + 1.0, result_drain_elapsed_s
    # SPEC §8 #25: the interrupted run leaves no orphan process.
    assert process_spy.orphan_pids() == []


def test_fr08_drain_waits_for_short_task_until_done(env, process_spy, monkeypatch):
    TASKQ_DRAIN_TIMEOUT = "5.0"
    inflight_command = "sleep 0.2"
    expected_final_status = "done"
    monkeypatch.setenv("TASKQ_DRAIN_TIMEOUT", TASKQ_DRAIN_TIMEOUT)

    env.start()
    task_id = env.seed_task(inflight_command)
    run_id = env.run(task_id)
    # Shut down immediately: the drain, not the test, must wait for the run.
    result_drain_elapsed_s = env.shutdown()
    result_final_status = env.status(task_id)

    # rule_id: AC8.1-status
    assert result_final_status == expected_final_status
    # rule_id: AC8.1-drain-bounded
    assert result_drain_elapsed_s <= float(TASKQ_DRAIN_TIMEOUT) + 1.0, result_drain_elapsed_s
    finished = env.sql("SELECT exit_code, finished_at FROM task_results WHERE id = ?", (run_id,))
    assert finished and finished[0][0] == 0 and finished[0][1] is not None, finished
    assert process_spy.orphan_pids() == []


# --- AC-8.2 -----------------------------------------------------------------

# NFR-03
def test_fr08_concurrency_cap_queues_excess(monkeypatch):
    TASKQ_MAX_CONCURRENT = "2"
    submitted_tasks = "5"
    task_duration_s = "0.1"
    monkeypatch.setenv("TASKQ_MAX_CONCURRENT", TASKQ_MAX_CONCURRENT)
    monkeypatch.setenv("TASKQ_DRAIN_TIMEOUT", "10")

    tracker, in_flight_early, elapsed = asyncio.run(
        _run_tracked(int(submitted_tasks), float(task_duration_s))
    )
    result_peak_running = tracker.peak
    result_completed_count = tracker.completed

    # rule_id: AC8.2-peak
    assert result_peak_running <= int(TASKQ_MAX_CONCURRENT)
    # rule_id: AC8.2-all-complete
    assert result_completed_count == int(submitted_tasks)
    # The cap is used (2 at once) while the other 3 wait in the queue.
    assert in_flight_early == int(TASKQ_MAX_CONCURRENT)
    # 5 jobs at 2 at a time need 3 waves of 0.1 s.
    assert elapsed >= 3 * float(task_duration_s) * 0.9, elapsed


def test_fr08_max_concurrent_1_serializes_tasks(monkeypatch):
    TASKQ_MAX_CONCURRENT = "1"
    submitted_tasks = "3"
    task_duration_s = "0.1"
    monkeypatch.setenv("TASKQ_MAX_CONCURRENT", TASKQ_MAX_CONCURRENT)
    monkeypatch.setenv("TASKQ_DRAIN_TIMEOUT", "10")

    tracker, in_flight_early, _elapsed = asyncio.run(
        _run_tracked(int(submitted_tasks), float(task_duration_s))
    )
    result_peak_running = tracker.peak
    result_completed_count = tracker.completed

    # rule_id: AC8.2-peak
    assert result_peak_running <= int(TASKQ_MAX_CONCURRENT)
    # rule_id: AC8.2-all-complete
    assert result_completed_count == int(submitted_tasks)
    assert in_flight_early == 1
    ordered = sorted(tracker.intervals)
    for (_s1, end_prev), (start_next, _e2) in zip(ordered, ordered[1:]):
        assert start_next >= end_prev, ordered


# --- AC-8.3 -----------------------------------------------------------------

# NFR-03
def test_fr08_timeout_kills_process_no_orphan(process_spy, monkeypatch):
    TASKQ_TASK_TIMEOUT = "0.5"
    task_command = "sleep 30"
    expected_orphans = "0"
    expected_final_status = "timeout"
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", TASKQ_TASK_TIMEOUT)
    monkeypatch.setenv("TASKQ_MAX_CONCURRENT", "2")
    monkeypatch.setenv("TASKQ_DRAIN_TIMEOUT", "10")
    outcomes: list[runner.RunOutcome] = []

    async def scenario() -> None:
        async def job() -> None:
            outcomes.append(await runner.run_command(task_command, machine=runner.TaskStateMachine()))

        async with executor.Executor() as ex:
            ex.enqueue(job)
            await ex.drain()

    asyncio.run(scenario())
    assert len(outcomes) == 1
    result_final_status = outcomes[0].status
    result_orphan_pids = process_spy.orphan_pids()
    result_process_waited_after_kill = process_spy.waited_after_kill()

    # rule_id: AC8.1-status
    assert result_final_status == expected_final_status
    # rule_id: AC8.3-no-orphan
    assert len(result_orphan_pids) == int(expected_orphans), result_orphan_pids
    # rule_id: AC8.3-waited
    assert result_process_waited_after_kill


# NFR-03
def test_sec_t07_timeout_kills_subprocess_no_orphan(process_spy, monkeypatch):
    TASKQ_TASK_TIMEOUT = "0.5"
    task_command = "sleep 30"
    expected_orphans = "0"
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", TASKQ_TASK_TIMEOUT)

    started = time.monotonic()
    outcome = asyncio.run(runner.run_command(task_command, machine=runner.TaskStateMachine()))
    elapsed = time.monotonic() - started
    result_orphan_pids = process_spy.orphan_pids()
    result_process_waited_after_kill = process_spy.waited_after_kill()

    assert outcome.status == "timeout"
    assert len(process_spy.pids) == 1
    # rule_id: AC8.3-no-orphan
    assert len(result_orphan_pids) == int(expected_orphans), result_orphan_pids
    # rule_id: AC8.3-waited
    assert result_process_waited_after_kill
    assert elapsed < 5, elapsed


# --- AC-8.4 -----------------------------------------------------------------

# NFR-03
def test_fr08_cancelled_error_propagates(process_spy, monkeypatch):
    scenario = "cancel_runner_task"
    expected_propagated = "True"
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "60")
    monkeypatch.setenv("TASKQ_MAX_CONCURRENT", "2")
    monkeypatch.setenv("TASKQ_DRAIN_TIMEOUT", "60")
    assert scenario == "cancel_runner_task"

    async def cancel_runner() -> bool:
        machine = runner.TaskStateMachine()
        job = asyncio.create_task(runner.run_command("sleep 30", machine=machine))
        while not process_spy.pids:
            await asyncio.sleep(0.01)
        job.cancel()
        try:
            await job
        except asyncio.CancelledError:
            return job.cancelled()
        return False

    async def cancel_executor_owner() -> bool:
        async def owner() -> None:
            async with executor.Executor() as ex:
                ex.enqueue(lambda: runner.run_command("sleep 30", machine=runner.TaskStateMachine()))
                await ex.drain()

        task = asyncio.create_task(owner())
        while len(process_spy.pids) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await asyncio.wait_for(task, 5)
        except asyncio.CancelledError:
            return task.cancelled()
        return False

    runner_propagated = asyncio.run(cancel_runner())
    executor_propagated = asyncio.run(cancel_executor_owner())
    result_cancelled_error_propagated = runner_propagated and executor_propagated

    # rule_id: AC8.4-propagated
    assert result_cancelled_error_propagated, (
        runner_propagated,
        executor_propagated,
    )
    assert str(result_cancelled_error_propagated) == expected_propagated
    # The cancelled runs killed and reaped their children (AC-8.3).
    assert process_spy.orphan_pids() == []
    assert process_spy.waited_after_kill()


# --- coverage: edge branches -------------------------------------------------

def test_fr08_run_command_unspawnable_fails(monkeypatch):
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "5")
    for command in ("", "/nonexistent/definitely-not-a-binary"):
        machine = runner.TaskStateMachine()
        outcome = asyncio.run(runner.run_command(command, machine=machine))
        assert machine.state == "failed"
        assert outcome.exit_code is None


def test_fr08_invalid_transition_raises():
    machine = runner.TaskStateMachine()
    with pytest.raises(runner.InvalidTransition):
        machine.transition("done")


def test_fr08_drop_queued_notifies_on_dropped(monkeypatch):
    monkeypatch.setenv("TASKQ_MAX_CONCURRENT", "1")
    monkeypatch.setenv("TASKQ_DRAIN_TIMEOUT", "0.2")
    dropped: list[int] = []

    async def scenario() -> None:
        async with executor.Executor() as ex:
            ex.enqueue(lambda: asyncio.sleep(30))
            ex.enqueue(lambda: asyncio.sleep(30), on_dropped=lambda: dropped.append(1))
            ex.enqueue(lambda: asyncio.sleep(30))
            await ex.drain()

    asyncio.run(scenario())
    assert dropped == [1]

"""NFR-08 — behavioural tests that pin values mutation testing found unguarded.

Each test asserts an observable contract (error detail, constant, boundary,
default argument, immutability) of the ``service`` / ``repository`` layers.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.config import Settings  # noqa: E402
from taskq_api.errors import Conflict, NotFound, Unauthenticated, ValidationFailed  # noqa: E402
from taskq_api.models.api_key import ApiKey  # noqa: E402
from taskq_api.repository import migration_state, tasks as task_repo  # noqa: E402
from taskq_api.repository.session import build_engine, uow_factory  # noqa: E402
from taskq_api.service import auth, health, ratelimit, redact, runner, runs, tasks  # noqa: E402


@pytest.fixture
def db_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path / 'kills.db'}"
    monkeypatch.setenv("TASKQ_DB_URL", url)
    migration_state.upgrade(url)
    return url


@pytest.fixture
def factory(db_url):
    settings = Settings(
        db_url=db_url, db_pool_size=5, task_timeout=5.0, rate_burst=5, rate_per_sec=1.0,
        max_concurrent=2, drain_timeout=1.0,
    )
    engine = build_engine(settings)
    yield uow_factory(engine)
    engine.dispose()


@pytest.fixture
def uow(factory):
    with factory() as unit:
        yield unit


# --- service.tasks ------------------------------------------------------------

def test_nfr08_task_validation_messages_and_constants():
    assert tasks.INITIAL_STATUS == "pending"
    assert tasks.INJECTION_CHARS == frozenset(";&|`$<>\n\r")
    cases = [
        (tasks.validate_command, "  ", "command must not be empty"),
        (tasks.validate_command, "x" * (tasks.MAX_COMMAND_LENGTH + 1),
         f"command must be at most {tasks.MAX_COMMAND_LENGTH} characters"),
        (tasks.validate_command, "echo a;b", "command contains forbidden characters"),
        (tasks.validate_name, " ", "name must not be empty"),
        (tasks.validate_name, "n" * (tasks.MAX_NAME_LENGTH + 1),
         f"name must be at most {tasks.MAX_NAME_LENGTH} characters"),
    ]
    for validate, value, detail in cases:
        with pytest.raises(ValidationFailed) as caught:
            validate(value)
        assert caught.value.detail == detail


def test_nfr08_each_injection_char_is_rejected():
    for char in tasks.INJECTION_CHARS:
        with pytest.raises(ValidationFailed):
            tasks.validate_command(f"echo a{char}b")


def test_nfr08_get_task_unknown_detail_and_new_task_status(uow):
    with pytest.raises(NotFound) as caught:
        tasks.get_task(uow, str(uuid.uuid4()))
    assert caught.value.detail == "task not found"
    created = tasks.create_task(uow, "fresh", "echo ok")
    assert created.status == "pending"


# --- repository.tasks ---------------------------------------------------------

def test_nfr08_invalid_cursor_detail():
    with pytest.raises(ValidationFailed) as caught:
        task_repo.decode_cursor("not-a-cursor")
    assert caught.value.detail == "cursor is invalid"


def test_nfr08_duplicate_name_conflict_detail(factory):
    with factory() as first:
        tasks.create_task(first, "same", "echo 1")
    with pytest.raises(Conflict) as caught, factory() as second:
        tasks.create_task(second, "same", "echo 2")
    assert caught.value.detail == "task name already exists"


def test_nfr08_page_of_exactly_limit_has_no_next_cursor(uow):
    for index in range(4):
        tasks.create_task(uow, f"t{index}", "echo x")
    first, cursor = tasks.list_tasks(uow, None, 2, None)
    assert len(first) == 2 and cursor is not None
    second, cursor = tasks.list_tasks(uow, None, 2, cursor)
    assert len(second) == 2
    assert cursor is None


# --- repository.session / migration_state -------------------------------------

def test_nfr08_sqlite_connections_use_driver_autocommit_mode(db_url):
    settings = Settings(
        db_url=db_url, db_pool_size=5, task_timeout=5.0, rate_burst=5, rate_per_sec=1.0,
        max_concurrent=2, drain_timeout=1.0,
    )
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.connection.driver_connection.isolation_level is None
    finally:
        engine.dispose()


def test_nfr08_upgrade_defaults_to_head_and_script_location_exists(tmp_path):
    url = f"sqlite:///{tmp_path / 'default.db'}"
    assert migration_state._SCRIPT_LOCATION.is_dir()
    migration_state.upgrade(url)
    assert migration_state.current_revision(url) == migration_state.head_revision(url) == "v3"


def test_nfr08_offline_sql_defaults_render_full_history(tmp_path):
    url = f"sqlite:///{tmp_path / 'offline.db'}"
    default = migration_state.offline_sql(url)
    assert default == migration_state.offline_sql(url, "base", "head")
    assert "CREATE TABLE task_results" in default
    assert "CREATE TABLE tasks" in default


def test_nfr08_migration_probe_is_immutable_and_defaults_to_no_schema():
    probe = migration_state.MigrationProbe(reachable=True, current="v3", head="v3")
    assert probe.has_schema is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        probe.reachable = False  # type: ignore[misc]


# --- service.auth -------------------------------------------------------------

def test_nfr08_auth_constants_and_plaintext_shape(uow):
    assert auth.SCOPES == ("read", "write", "admin")
    plaintext = auth.create_key(uow, "read")
    assert plaintext.startswith("tq_")
    assert len(plaintext) == len("tq_") + 43  # token_urlsafe(32) -> 43 chars


def test_nfr08_auth_rejection_details(uow):
    with pytest.raises(Unauthenticated) as missing:
        auth.verify(uow, None)
    assert missing.value.detail == "missing API key"
    with pytest.raises(Unauthenticated) as invalid:
        auth.verify(uow, "tq_unknown")
    assert invalid.value.detail == "invalid API key"


def test_nfr08_scope_hierarchy():
    assert auth.scope_includes("admin", "read") and auth.scope_includes("write", "write")
    assert not auth.scope_includes("read", "write") and not auth.scope_includes("write", "admin")
    assert isinstance(ApiKey.__table__.c.scope.type.length, int)


# --- service.health -----------------------------------------------------------

def test_nfr08_readiness_details_and_immutability():
    assert health.DETAIL_DB_UNAVAILABLE == "database unavailable"
    assert health.DETAIL_MIGRATION_BEHIND == "migration not at head"
    ready = health.Readiness(True, "ready")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ready.ready = False  # type: ignore[misc]


def test_nfr08_readiness_ready_detail(db_url):
    verdict = health.readiness(db_url)
    assert verdict.ready is True
    assert verdict.detail == "ready"


def test_nfr08_rejection_counter_counts_one_per_increment():
    counter = health.RejectionCounter()
    assert counter.value == 0
    counter.increment()
    assert counter.value == 1
    counter.increment()
    assert counter.value == 2


def test_nfr08_percentile_nearest_rank():
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert health._percentile(values, 50) == 50
    assert health._percentile(values, 95) == 100
    assert health._percentile(values, 99) == 100
    assert health._percentile([7], 50) == 7
    assert health._percentile([], 50) is None
    assert health._percentile([1, 2, 3, 4], 25) == 1
    assert health._percentile([1, 2, 3, 4], 75) == 3


# --- service.ratelimit --------------------------------------------------------

def test_nfr08_allowed_decision_has_zero_retry_and_decision_is_frozen():
    decision = ratelimit.RateDecision(allowed=True, retry_after_s=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.allowed = False  # type: ignore[misc]


def test_nfr08_consume_allowed_returns_zero_retry_after(uow):
    key = ApiKey(id=str(uuid.uuid4()), key_hash="h" * 64, scope="read", created_at=datetime.now(timezone.utc))
    uow.api_keys.add(key)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decision = ratelimit.consume(uow, key.id, capacity=3, rate_per_sec=1.0, now=now)
    assert decision.allowed is True
    assert decision.retry_after_s == 0


def test_nfr08_seconds_until_token_uses_missing_fraction():
    assert ratelimit._seconds_until_token(0.5, 0.1) == 5
    assert ratelimit._seconds_until_token(0.0, 0.25) == 4
    assert ratelimit._seconds_until_token(0.99, 100.0) == 1


# --- service.redact -----------------------------------------------------------

def test_nfr08_redact_preserves_line_endings_and_plain_lines():
    assert redact.SECRET_PATTERN is not None
    assert redact.redact("ok\nkey sk-abcdefgh1234\nend\n") == "ok\n[REDACTED]\nend\n"
    assert redact.redact("key sk-abcdefgh1234\r\nnext\r\n") == "[REDACTED]\r\nnext\r\n"
    assert redact.redact("a\nb") == "a\nb"
    assert redact.redact("Bearer abc.def\ntoken=xyz") == "[REDACTED]\n[REDACTED]"


# --- service.runner -----------------------------------------------------------

def test_nfr08_tail_keeps_last_chars_and_replaces_bad_bytes():
    assert runner.TAIL_CHARS == 4096
    assert runner.tail(b"a" * 4096) == "a" * 4096
    assert runner.tail(b"b" + b"a" * 5000) == "a" * 4096
    assert runner.tail(b"\xff") == "�"


def test_nfr08_state_machine_initial_state_and_error_text():
    machine = runner.TaskStateMachine()
    assert machine.state == runner.PENDING == "pending"
    assert machine.history == ["pending"]
    with pytest.raises(runner.InvalidTransition) as caught:
        machine.transition(runner.DONE)
    assert str(caught.value) == "pending -> done"
    machine.transition(runner.RUNNING)
    machine.transition(runner.DONE)
    assert machine.state == "done"
    assert machine.history == ["pending", "running", "done"]
    assert runner.RUNNING == "running" and runner.DONE == "done"
    assert runner.TRANSITIONS[runner.RUNNING] == frozenset({"done", "failed", "timeout"})
    with pytest.raises(runner.InvalidTransition):
        machine.transition(runner.RUNNING)


def test_nfr08_run_outcome_is_immutable():
    outcome = runner.RunOutcome("done", 0, "", "", 1, datetime.now(timezone.utc))
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.status = "failed"  # type: ignore[misc]


def test_nfr08_run_command_empty_unspawnable_and_timeout(monkeypatch):
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.3")
    empty = asyncio.run(runner.run_command("   ", runner.TaskStateMachine()))
    assert (empty.status, empty.exit_code, empty.stdout_tail) == ("failed", None, "")
    assert empty.stderr_tail == "empty command"
    missing = asyncio.run(runner.run_command("definitely-not-a-binary-xyz", runner.TaskStateMachine()))
    assert missing.status == "failed" and missing.exit_code is None
    slow = asyncio.run(runner.run_command("sleep 30", runner.TaskStateMachine()))
    assert slow.status == "timeout"
    assert slow.stdout_tail == "" and slow.stderr_tail == ""
    assert 250 <= slow.duration_ms < 5000


def test_nfr08_run_command_duration_reflects_elapsed_time(monkeypatch):
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "10")
    outcome = asyncio.run(runner.run_command("sleep 0.4", runner.TaskStateMachine()))
    assert outcome.status == "done" and outcome.exit_code == 0
    assert 350 <= outcome.duration_ms < 3000


# --- service.runs -------------------------------------------------------------

def test_nfr08_execute_without_submitted_run_fails_with_clear_message(factory):
    with factory() as unit:
        task_id = tasks.create_task(unit, "orphan", "echo hi").id
    missing_run = str(uuid.uuid4())
    with pytest.raises(AssertionError) as caught:
        asyncio.run(runs.execute(factory, task_id, missing_run, "echo hi"))
    assert str(caught.value) == f"run {missing_run} was not created by submit()"

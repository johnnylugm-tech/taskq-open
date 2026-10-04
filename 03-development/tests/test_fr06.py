"""FR-06 — Persistence layer and transaction boundaries.

Covers TEST_SPEC.md FR-06 rows 1-7 (AC-6.1 .. AC-6.5, NP-08).

Test harness contract:
- `taskq_api.repository.session.uow_factory(engine)` returns a zero-arg factory
  of `UnitOfWork` context managers; `taskq_api.service.uow.UnitOfWork` is the
  type the business layer sees. Commit on normal exit, rollback on any
  exception including `asyncio.CancelledError`, which must propagate.
- `build_engine(load_settings())` honours `TASKQ_DB_POOL_SIZE` and sets
  `pool_pre_ping=True`.
- `Task.tags` is a mapped relationship (via `task_tags`) and
  `TaskRepository.list_page` loads it explicitly with `selectinload` /
  `joinedload`, so touching `task.tags` after the page query issues no SQL.
- The service layer never references `Session`; no module under
  `taskq_api` builds SQL text with f-strings, `%` or `+`.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.app import create_app  # noqa: E402
from taskq_api.config import load_settings  # noqa: E402
from taskq_api.models.base import Base  # noqa: E402
from taskq_api.models.task import Task  # noqa: E402
from taskq_api.repository.session import build_engine, uow_factory  # noqa: E402
from taskq_api.service.uow import UnitOfWork  # noqa: E402

PKG_ROOT = SRC_ROOT / "taskq_api"
KEY_ID = "22222222-2222-2222-2222-222222222222"
KEY = "sk-test-fr06-0123456789abcdef"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)

# SQL keywords that mark a string literal as SQL text (uppercase, whole word).
SQL_KEYWORD = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|LIMIT|OFFSET|ORDER BY|VALUES|BEGIN|JOIN)\b"
)


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _sql(db_file: Path, statement: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _make_db(tmp_path: Path, monkeypatch, pool_size: str = "5") -> Path:
    path = tmp_path / "taskq.db"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{path}")
    monkeypatch.setenv("TASKQ_DB_POOL_SIZE", pool_size)
    # Keep the rate limiter out of the way of statement counting.
    monkeypatch.setenv("TASKQ_RATE_BURST", "1000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "1000.0")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


def _seed_key(db_file: Path) -> None:
    _sql(
        db_file,
        "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
        (KEY_ID, hashlib.sha256(KEY.encode()).hexdigest(), "admin", BASE_TIME.isoformat(), None),
    )


def _seed_tasks_with_tags(db_file: Path, rows: int) -> None:
    tag_ids = [str(uuid.uuid4()) for _ in range(3)]
    conn = sqlite3.connect(db_file)
    try:
        conn.executemany(
            "INSERT INTO tags (id, label) VALUES (?, ?)",
            [(tag_id, f"tag-{n}") for n, tag_id in enumerate(tag_ids)],
        )
        for n in range(rows):
            task_id = str(uuid.uuid4())
            created = (BASE_TIME + timedelta(seconds=n)).isoformat()
            conn.execute(
                "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, "echo hi", f"task-{n}", "pending", created),
            )
            conn.executemany(
                "INSERT INTO task_tags (task_id, tag_id) VALUES (?, ?)",
                [(task_id, tag_id) for tag_id in tag_ids[: 1 + n % 3]],
            )
        conn.commit()
    finally:
        conn.close()


class _TxCounter:
    """Counts real commits / rollbacks of every ORM ``Session``."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def on_commit(self, session) -> None:
        self.commits += 1

    def on_rollback(self, session) -> None:
        self.rollbacks += 1


@pytest.fixture
def tx_counter():
    counter = _TxCounter()
    event.listen(Session, "after_commit", counter.on_commit)
    event.listen(Session, "after_rollback", counter.on_rollback)
    yield counter
    event.remove(Session, "after_commit", counter.on_commit)
    event.remove(Session, "after_rollback", counter.on_rollback)


@pytest.fixture
def make_uow(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch)
    engine = build_engine(load_settings())
    yield uow_factory(engine)
    engine.dispose()


def _new_task() -> Task:
    return Task(
        id=str(uuid.uuid4()),
        command="echo hi",
        name=f"fr06-{uuid.uuid4().hex[:8]}",
        status="pending",
        created_at=BASE_TIME,
    )


# --- AC-6.1 -----------------------------------------------------------------

# NFR-06
def test_fr06_service_layer_holds_no_session():
    scan_root = "03-development/src/taskq_api/service"
    forbidden_symbol = "Session"
    expected_hits = "0"
    root = Path(__file__).resolve().parents[2] / scan_root
    files = _py_files(root)
    result_scanned_file_count = len(files)
    result_offending_files = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.Attribute):
                names.append(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.extend(alias.name.rsplit(".", 1)[-1] for alias in node.names)
            if forbidden_symbol in names:
                result_offending_files.append(str(path.relative_to(root)))
                break
    # The business layer's transaction handle is the UnitOfWork, not a Session.
    assert not issubclass(UnitOfWork, Session)
    # AC6.1-no-session
    assert len(result_offending_files) == int(expected_hits), result_offending_files
    # AC6.1-scanned
    assert result_scanned_file_count > 0


# --- AC-6.2 -----------------------------------------------------------------

# NFR-03
def test_fr06_session_commit_on_success_rollback_on_error(make_uow, tx_counter):
    scenario = "success"
    expected_commits = "1"
    expected_rollbacks = "0"
    task = _new_task()
    with make_uow() as uow:
        uow.tasks.add(task)
    result_commit_count = tx_counter.commits
    result_rollback_count = tx_counter.rollbacks
    with make_uow() as uow:
        persisted = uow.tasks.get(task.id)
    assert persisted is not None, scenario
    # AC6.2-commits
    assert result_commit_count == int(expected_commits)
    # AC6.2-rollbacks
    assert result_rollback_count == int(expected_rollbacks)


def test_fr06_session_rollback_on_exception(make_uow, tx_counter):
    scenario = "exception"
    expected_commits = "0"
    expected_rollbacks = "1"
    task = _new_task()
    with pytest.raises(RuntimeError):
        with make_uow() as uow:
            uow.tasks.add(task)
            raise RuntimeError(scenario)
    result_commit_count = tx_counter.commits
    result_rollback_count = tx_counter.rollbacks
    with make_uow() as uow:
        persisted = uow.tasks.get(task.id)
    assert persisted is None
    # AC6.2-commits
    assert result_commit_count == int(expected_commits)
    # AC6.2-rollbacks
    assert result_rollback_count == int(expected_rollbacks)


def test_fr06_session_rollback_on_cancelled_error(make_uow, tx_counter):
    scenario = "cancelled"
    expected_commits = "0"
    expected_rollbacks = "1"
    task = _new_task()
    result_cancelled_error_reraised = False
    try:
        with make_uow() as uow:
            uow.tasks.add(task)
            raise asyncio.CancelledError(scenario)
    except asyncio.CancelledError:
        result_cancelled_error_reraised = True
    result_commit_count = tx_counter.commits
    result_rollback_count = tx_counter.rollbacks
    with make_uow() as uow:
        persisted = uow.tasks.get(task.id)
    assert persisted is None
    # AC6.2-commits
    assert result_commit_count == int(expected_commits)
    # AC6.2-rollbacks
    assert result_rollback_count == int(expected_rollbacks)
    # AC6.2-cancel-reraised
    assert result_cancelled_error_reraised


# --- AC-6.3 / NP-08 ---------------------------------------------------------

def _sql_concat_hits(path: Path, patterns: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []

    def literal_is_sql(node: ast.AST) -> bool:
        return any(
            isinstance(sub, ast.Constant)
            and isinstance(sub.value, str)
            and SQL_KEYWORD.search(sub.value)
            for sub in ast.walk(node)
        )

    for node in ast.walk(tree):
        kind = None
        if (
            "f-string" in patterns
            and isinstance(node, ast.JoinedStr)
            and any(isinstance(v, ast.FormattedValue) for v in node.values)
            and literal_is_sql(node)
        ):
            kind = "f-string"
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and "percent" in patterns:
            if isinstance(node.left, ast.Constant) and literal_is_sql(node.left):
                kind = "percent"
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.op, ast.Add)
            and "plus" in patterns
            and literal_is_sql(node.value)
        ):
            kind = "plus"
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and "plus" in patterns:
            if literal_is_sql(node.left) or literal_is_sql(node.right):
                kind = "plus"
        elif (
            "plus" in patterns
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and literal_is_sql(node.func.value)
        ):
            kind = "format"
        if kind is not None:
            hits.append(f"{path.name}:{node.lineno}:{kind}")
    return hits


# NFR-02
def test_fr06_no_string_built_sql():
    scan_root = "03-development/src/taskq_api"
    patterns = "f-string,percent,plus"
    expected_hits = "0"
    root = Path(__file__).resolve().parents[2] / scan_root
    files = _py_files(root)
    result_scanned_file_count = len(files)
    result_sql_concat_hits: list[str] = []
    for path in files:
        result_sql_concat_hits.extend(_sql_concat_hits(path, set(patterns.split(","))))
    # AC6.3-no-concat
    assert len(result_sql_concat_hits) == int(expected_hits), result_sql_concat_hits
    # AC6.3-scanned
    assert result_scanned_file_count > 0


# --- AC-6.4 -----------------------------------------------------------------

def _count_list_statements(tmp_path: Path, monkeypatch, rows: int, query_limit: int) -> tuple[int, int]:
    """Statements for GET /v1/tasks and for list_page + touching every task's tags."""
    db_file = _make_db(tmp_path, monkeypatch)
    _seed_key(db_file)
    _seed_tasks_with_tags(db_file, rows)

    statements: list[str] = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", on_execute)
    try:
        with TestClient(create_app()) as client:
            statements.clear()
            response = client.get(
                "/v1/tasks", params={"limit": query_limit}, headers={"X-API-Key": KEY}
            )
            endpoint_count = len(statements)
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == min(rows, query_limit)

        engine = build_engine(load_settings())
        try:
            with uow_factory(engine)() as uow:
                statements.clear()
                page, _ = uow.tasks.list_page(None, query_limit, None)
                tag_total = sum(len(task.tags) for task in page)
                repo_count = len(statements)
        finally:
            engine.dispose()
        assert tag_total > 0
    finally:
        event.remove(Engine, "before_cursor_execute", on_execute)
    return endpoint_count, repo_count


# NFR-01
def test_fr06_list_query_count_constant(tmp_path, monkeypatch):
    endpoint = "/v1/tasks"
    query_limit = "50"
    rows_small = "10"
    rows_large = "100"
    small_dir = tmp_path / "small"
    large_dir = tmp_path / "large"
    small_dir.mkdir()
    large_dir.mkdir()
    small_endpoint, small_repo = _count_list_statements(
        small_dir, monkeypatch, int(rows_small), int(query_limit)
    )
    large_endpoint, large_repo = _count_list_statements(
        large_dir, monkeypatch, int(rows_large), int(query_limit)
    )
    result_stmt_count_small = small_endpoint + small_repo
    result_stmt_count_large = large_endpoint + large_repo
    # AC6.4-constant
    assert result_stmt_count_large == result_stmt_count_small, (
        endpoint,
        (small_endpoint, small_repo),
        (large_endpoint, large_repo),
    )
    # Explicit eager load: the page query plus at most one relationship statement.
    assert large_repo <= 2, large_repo


# --- AC-6.5 -----------------------------------------------------------------

def test_fr06_engine_pool_size_and_pre_ping(tmp_path, monkeypatch):
    TASKQ_DB_POOL_SIZE = "5"
    _make_db(tmp_path, monkeypatch, pool_size=TASKQ_DB_POOL_SIZE)
    engine = build_engine(load_settings())
    try:
        result_pool_size = engine.pool.size()
        result_pool_pre_ping = engine.pool._pre_ping
    finally:
        engine.dispose()
    # AC6.5-pool
    assert result_pool_size == int(TASKQ_DB_POOL_SIZE)
    # AC6.5-pre-ping
    assert result_pool_pre_ping


def test_fr06_engine_pool_size_honours_non_default_setting(tmp_path, monkeypatch):
    """[FR-06] A non-default TASKQ_DB_POOL_SIZE must reach the engine pool."""
    _make_db(tmp_path, monkeypatch, pool_size="7")
    engine = build_engine(load_settings())
    try:
        assert engine.pool.size() == 7
    finally:
        engine.dispose()


def test_fr06_limit_with_offset_uses_default_rendering(tmp_path, monkeypatch):
    from sqlalchemy import select

    _make_db(tmp_path, monkeypatch, pool_size="5")
    engine = build_engine(load_settings())
    try:
        sql = str(
            select(Task.id).limit(5).offset(10).compile(engine)
        )
    finally:
        engine.dispose()
    assert "LIMIT" in sql and "OFFSET" in sql

"""FR-01 — Task resource CRUD API (`/v1/tasks`).

Covers TEST_SPEC.md FR-01 rows 1-16 (AC-1.1 .. AC-1.8, SEC T-05, SEC T-08).

Test harness contract (in-process, via FastAPI TestClient / httpx):
- `taskq_api.app.create_app()` builds the app, reading settings from the
  `TASKQ_*` environment variables (SPEC 5.1). Each test points
  `TASKQ_DB_URL` at a fresh SQLite file (state_mode="isolate_per_test").
- The schema is created from `taskq_api.models.base.Base.metadata` (the ORM
  mapping of the SPEC 5.2 head schema); importing `taskq_api.app` must
  register every model on that metadata.
- API keys are seeded straight into `api_keys` as SHA-256 hex digests of the
  plaintext (SPEC FR-03); primary keys are uuid strings.
- The list endpoint returns `{"items": [...], "next_cursor": <str|null>}`.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.app import create_app  # noqa: E402
from taskq_api.errors import ValidationFailed  # noqa: E402
from taskq_api.models.base import Base  # noqa: E402

PROBLEM_JSON = "application/problem+json"
KEYS = {
    "read": "sk-test-read-0123456789",
    "write": "sk-test-write-0123456789",
    "admin": "sk-test-admin-0123456789",
}
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _headers(scope: str) -> dict[str, str]:
    return {"X-API-Key": KEYS[scope]}


def _assert_problem(resp, status_code: int, error_type: str) -> None:
    assert resp.status_code == status_code, resp.text
    assert resp.headers["content-type"].startswith(PROBLEM_JSON)
    body = resp.json()
    assert body["status"] == status_code
    assert body["type"].endswith(f"/errors/{error_type}")


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

    def seed_tasks(self, count: int, status: str = "pending", prefix: str = "seed") -> list[str]:
        ids = []
        conn = sqlite3.connect(self.db_file)
        try:
            for i in range(count):
                task_id = str(uuid.uuid4())
                created = (BASE_TIME + timedelta(seconds=len(ids) + i)).isoformat()
                conn.execute(
                    "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (task_id, "echo seed", f"{prefix}-{i}", status, created),
                )
                ids.append(task_id)
            conn.commit()
        finally:
            conn.close()
        return ids

    def create(self, name: str, command: str):
        return self.client.post(
            "/v1/tasks", json={"name": name, "command": command}, headers=_headers("write")
        )

    def list_all(self, **params) -> list[list[dict]]:
        pages = []
        query = {k: v for k, v in params.items() if v is not None}
        while True:
            resp = self.client.get("/v1/tasks", params=query, headers=_headers("read"))
            assert resp.status_code == 200, resp.text
            body = resp.json()
            pages.append(body["items"])
            if not body["next_cursor"]:
                return pages
            query["cursor"] = body["next_cursor"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_file = tmp_path / "taskq.db"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{db_file}")
    # Rate limiting (FR-05) must not interfere with FR-01 behaviour.
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


# --- AC-1.1 -----------------------------------------------------------------

def test_fr01_create_task_returns_201(env):
    expected_status = "201"
    resp = env.create("build-app", "echo hello")
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    result_task_id = resp.json()["id"]
    assert len(result_task_id) > 0
    assert str(uuid.UUID(result_task_id)) == result_task_id
    assert env.sql("SELECT name, command FROM tasks WHERE id = ?", (result_task_id,)) == [
        ("build-app", "echo hello")
    ]


# --- AC-1.2 -----------------------------------------------------------------

def test_fr01_get_task_returns_all_fields(env):
    expected_status = "200"
    expected_fields = "id,command,name,status,created_at"
    task_id = env.create("get-me", "echo hello").json()["id"]
    resp = env.client.get(f"/v1/tasks/{task_id}", headers=_headers("read"))
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    body = resp.json()
    result_fields = list(body)
    assert sorted(result_fields) == sorted(expected_fields.split(","))
    assert body["id"] == task_id
    assert body["command"] == "echo hello"
    assert body["name"] == "get-me"
    assert body["status"] == "pending"
    datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))


# --- AC-1.3 -----------------------------------------------------------------

def test_fr01_list_tasks_filters_and_cursor(env):
    expected_status = "200"
    expected_page_size = "2"
    query_status = "done"
    env.seed_tasks(2, status="pending", prefix="pend")
    done_ids = set(env.seed_tasks(3, status="done", prefix="done"))

    page1 = env.client.get(
        "/v1/tasks", params={"status": query_status, "limit": 2}, headers=_headers("read")
    )
    result_status = page1.status_code
    assert result_status == int(expected_status), page1.text
    body1 = page1.json()
    result_items = body1["items"]
    result_item_statuses = [item["status"] for item in result_items]
    assert len(result_items) == int(expected_page_size)
    assert all(s == query_status for s in result_item_statuses)
    assert body1["next_cursor"]

    result_next_cursor_followed_count = 0
    page2 = env.client.get(
        "/v1/tasks",
        params={"status": query_status, "limit": 2, "cursor": body1["next_cursor"]},
        headers=_headers("read"),
    )
    result_next_cursor_followed_count += 1
    assert page2.status_code == 200, page2.text
    body2 = page2.json()
    assert result_next_cursor_followed_count == 1
    assert len(body2["items"]) == 1
    assert body2["items"][0]["status"] == query_status
    assert body2["next_cursor"] is None

    seen = {item["id"] for item in body1["items"] + body2["items"]}
    assert seen == done_ids


# --- AC-1.4 -----------------------------------------------------------------

def test_fr01_delete_task_removes_results_same_txn(env):
    expected_status_class = "2"
    task_id = env.create("to-delete", "echo bye").json()["id"]
    for i in range(2):
        env.sql(
            "INSERT INTO task_results (id, task_id, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), task_id, 0, "bye", "", 5 + i, BASE_TIME.isoformat()),
        )
    assert env.sql("SELECT COUNT(*) FROM task_results WHERE task_id = ?", (task_id,)) == [(2,)]

    resp = env.client.delete(f"/v1/tasks/{task_id}", headers=_headers("admin"))
    result_status = resp.status_code
    assert result_status // 100 == int(expected_status_class), resp.text

    assert env.sql("SELECT COUNT(*) FROM tasks WHERE id = ?", (task_id,)) == [(0,)]
    result_remaining_result_rows = env.sql(
        "SELECT COUNT(*) FROM task_results WHERE task_id = ?", (task_id,)
    )[0][0]
    assert result_remaining_result_rows == 0
    gone = env.client.get(f"/v1/tasks/{task_id}", headers=_headers("read"))
    result_get_after_delete_status = gone.status_code
    assert result_get_after_delete_status == 404
    _assert_problem(gone, 404, "not-found")


# --- AC-1.5 -----------------------------------------------------------------

# NFR-10
def test_fr01_invalid_body_returns_422(env):
    expected_status = "422"
    resp = env.create("empty-cmd", "")
    result_status = resp.status_code
    result_content_type = resp.headers["content-type"]
    assert result_status == int(expected_status), resp.text
    assert result_content_type.startswith("application/problem+json")
    _assert_problem(resp, 422, "validation")
    assert env.sql("SELECT COUNT(*) FROM tasks") == [(0,)]


# --- AC-1.6 -----------------------------------------------------------------

# NFR-10
def test_fr01_unknown_id_returns_404(env):
    expected_status = "404"
    resp = env.client.get(
        "/v1/tasks/00000000-0000-0000-0000-000000000000", headers=_headers("read")
    )
    result_status = resp.status_code
    result_content_type = resp.headers["content-type"]
    assert result_status == int(expected_status), resp.text
    assert result_content_type.startswith("application/problem+json")
    _assert_problem(resp, 404, "not-found")


# --- AC-1.7 -----------------------------------------------------------------

# NFR-01
def test_fr01_pagination_is_cursor_based(env):
    expected_pages = "3"
    seeded = set(env.seed_tasks(120))
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        pages = env.list_all(limit=50)
    finally:
        event.remove(Engine, "before_cursor_execute", _record)
    result_page_count = len(pages)
    assert result_page_count == int(expected_pages)
    assert [len(p) for p in pages] == [50, 50, 20]
    result_all_ids = [item["id"] for page in pages for item in page]
    assert len(result_all_ids) == len(set(result_all_ids))
    assert set(result_all_ids) == seeded
    result_sql_uses_offset = any(" offset " in f" {stmt.lower()} " for stmt in statements)
    assert statements, "no SQL captured"
    assert not result_sql_uses_offset

    first = env.client.get("/v1/tasks", params={"limit": 50}, headers=_headers("read")).json()
    # An opaque cursor, not a numeric offset in disguise.
    assert not first["next_cursor"].isdigit()
    # `offset` is not a pagination mechanism: it does not shift the page.
    with_offset = env.client.get(
        "/v1/tasks", params={"limit": 50, "offset": 50}, headers=_headers("read")
    )
    if with_offset.status_code == 200:
        assert [i["id"] for i in with_offset.json()["items"]] == [i["id"] for i in first["items"]]
    else:
        _assert_problem(with_offset, 422, "validation")


# --- AC-1.8 -----------------------------------------------------------------

# NFR-01
def test_fr01_list_limit_default_50_max_200(env):
    expected_page_size = "50"
    env.seed_tasks(60)
    resp = env.client.get("/v1/tasks", headers=_headers("read"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    result_items = body["items"]
    assert len(result_items) == int(expected_page_size)
    assert body["next_cursor"]


def test_fr01_list_limit_200_accepted(env):
    expected_status = "200"
    expected_page_size = "200"
    env.seed_tasks(210)
    resp = env.client.get("/v1/tasks", params={"limit": 200}, headers=_headers("read"))
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    result_items = resp.json()["items"]
    assert len(result_items) == int(expected_page_size)


def test_fr01_list_limit_201_returns_422(env):
    expected_status = "422"
    resp = env.client.get("/v1/tasks", params={"limit": 201}, headers=_headers("read"))
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    _assert_problem(resp, 422, "validation")


# --- AC-1.5 boundaries / blacklist / uniqueness -----------------------------

def test_fr01_command_over_1000_chars_returns_422(env):
    expected_status = "422"
    command = "echo " + "a" * 996
    assert len(command) == 1001
    resp = env.create("long-cmd", command)
    result_status = resp.status_code
    result_content_type = resp.headers["content-type"]
    assert result_status == int(expected_status), resp.text
    assert result_content_type.startswith("application/problem+json")
    _assert_problem(resp, 422, "validation")
    assert env.sql("SELECT COUNT(*) FROM tasks") == [(0,)]


def test_fr01_command_exactly_1000_chars_accepted(env):
    expected_status = "201"
    command = "echo " + "a" * 995
    assert len(command) == 1000
    resp = env.create("max-cmd", command)
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    assert env.sql("SELECT command FROM tasks WHERE id = ?", (resp.json()["id"],)) == [(command,)]


def test_fr01_injection_chars_in_command_returns_422(env):
    # `;` is in the injection blacklist; membership beyond `;` is open decision NFR-99.2.
    expected_status = "422"
    resp = env.create("inj", "echo hi; cat /etc/passwd")
    result_status = resp.status_code
    result_content_type = resp.headers["content-type"]
    assert result_status == int(expected_status), resp.text
    assert result_content_type.startswith("application/problem+json")
    _assert_problem(resp, 422, "validation")
    result_task_count = env.sql("SELECT COUNT(*) FROM tasks")[0][0]
    assert result_task_count == 0


def test_fr01_duplicate_name_returns_409(env):
    # NFR-99.3 resolved to 409 per SPEC section 7.
    expected_status = "409"
    first = env.create("dup-name", "echo one")
    assert first.status_code == 201, first.text
    resp = env.create("dup-name", "echo two")
    result_status = resp.status_code
    result_content_type = resp.headers["content-type"]
    result_problem_type = "/errors/" + resp.json()["type"].rsplit("/errors/", 1)[-1]
    assert result_status == int(expected_status), resp.text
    assert result_content_type.startswith("application/problem+json")
    assert result_problem_type == "/errors/conflict"
    assert env.sql("SELECT COUNT(*) FROM tasks WHERE name = ?", ("dup-name",)) == [(1,)]


# --- SEC T-05 / T-08 --------------------------------------------------------

# NFR-02
def test_sec_t05_injection_chars_rejected_422(env):
    expected_status = "422"
    resp = env.create("t05", "echo a; echo b")
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    _assert_problem(resp, 422, "validation")
    result_task_count = env.sql("SELECT COUNT(*) FROM tasks")[0][0]
    assert result_task_count == 0


# NFR-02
def test_sec_t08_sql_metacharacters_treated_as_data(env):
    expected_status = "201"
    task_name = "x' OR '1'='1"
    resp = env.create(task_name, "echo sql")
    result_status = resp.status_code
    assert result_status == int(expected_status), resp.text
    task_id = resp.json()["id"]

    assert env.sql("SELECT COUNT(*) FROM tasks") == [(1,)]
    got = env.client.get(f"/v1/tasks/{task_id}", headers=_headers("read"))
    assert got.status_code == 200, got.text
    result_stored_name = env.sql("SELECT name FROM tasks WHERE id = ?", (task_id,))[0][0]
    assert result_stored_name == task_name
    assert got.json()["name"] == task_name
    tables = {row[0] for row in env.sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    result_tables_intact = {"tasks", "task_results", "api_keys"} <= tables
    assert result_tables_intact


# --- Coverage: validation edge cases -----------------------------------------

# NFR-10
def test_fr01_invalid_cursor_returns_422(env):
    resp = env.client.get("/v1/tasks", params={"cursor": "not-a-cursor!"}, headers=_headers("read"))
    assert resp.status_code == 422, resp.text
    _assert_problem(resp, 422, "validation")


@pytest.mark.parametrize("name", ["   ", "n" * 256])
def test_fr01_validate_name_rejects_blank_or_too_long(name):
    from taskq_api.service.tasks import validate_name

    with pytest.raises(ValidationFailed):
        validate_name(name)


def test_fr01_validate_name_accepts_max_length():
    from taskq_api.service.tasks import MAX_NAME_LENGTH, validate_name

    assert validate_name("n" * MAX_NAME_LENGTH) is None

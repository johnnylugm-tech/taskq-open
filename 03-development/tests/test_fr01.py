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
from sqlalchemy import create_engine

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.app import create_app  # noqa: E402
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
    resp = env.create("build-app", "echo hello")
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]
    assert str(uuid.UUID(task_id)) == task_id
    assert env.sql("SELECT name, command FROM tasks WHERE id = ?", (task_id,)) == [
        ("build-app", "echo hello")
    ]


# --- AC-1.2 -----------------------------------------------------------------

def test_fr01_get_task_returns_all_fields(env):
    task_id = env.create("get-me", "echo hello").json()["id"]
    resp = env.client.get(f"/v1/tasks/{task_id}", headers=_headers("read"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for field in ("id", "command", "name", "status", "created_at"):
        assert field in body
    assert body["id"] == task_id
    assert body["command"] == "echo hello"
    assert body["name"] == "get-me"
    assert body["status"] == "pending"
    datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))


# --- AC-1.3 -----------------------------------------------------------------

def test_fr01_list_tasks_filters_and_cursor(env):
    env.seed_tasks(2, status="pending", prefix="pend")
    done_ids = set(env.seed_tasks(3, status="done", prefix="done"))

    page1 = env.client.get(
        "/v1/tasks", params={"status": "done", "limit": 2}, headers=_headers("read")
    )
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert all(item["status"] == "done" for item in body1["items"])
    assert body1["next_cursor"]

    page2 = env.client.get(
        "/v1/tasks",
        params={"status": "done", "limit": 2, "cursor": body1["next_cursor"]},
        headers=_headers("read"),
    )
    assert page2.status_code == 200, page2.text
    body2 = page2.json()
    assert len(body2["items"]) == 1
    assert body2["items"][0]["status"] == "done"
    assert body2["next_cursor"] is None

    seen = {item["id"] for item in body1["items"] + body2["items"]}
    assert seen == done_ids


# --- AC-1.4 -----------------------------------------------------------------

def test_fr01_delete_task_removes_results_same_txn(env):
    task_id = env.create("to-delete", "echo bye").json()["id"]
    for i in range(2):
        env.sql(
            "INSERT INTO task_results (id, task_id, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), task_id, 0, "bye", "", 5 + i, BASE_TIME.isoformat()),
        )
    assert env.sql("SELECT COUNT(*) FROM task_results WHERE task_id = ?", (task_id,)) == [(2,)]

    resp = env.client.delete(f"/v1/tasks/{task_id}", headers=_headers("admin"))
    assert 200 <= resp.status_code < 300, resp.text

    assert env.sql("SELECT COUNT(*) FROM tasks WHERE id = ?", (task_id,)) == [(0,)]
    assert env.sql("SELECT COUNT(*) FROM task_results WHERE task_id = ?", (task_id,)) == [(0,)]
    _assert_problem(
        env.client.get(f"/v1/tasks/{task_id}", headers=_headers("read")), 404, "not-found"
    )


# --- AC-1.5 -----------------------------------------------------------------

def test_fr01_invalid_body_returns_422(env):
    _assert_problem(env.create("empty-cmd", ""), 422, "validation")
    assert env.sql("SELECT COUNT(*) FROM tasks") == [(0,)]


# --- AC-1.6 -----------------------------------------------------------------

def test_fr01_unknown_id_returns_404(env):
    resp = env.client.get(
        "/v1/tasks/00000000-0000-0000-0000-000000000000", headers=_headers("read")
    )
    _assert_problem(resp, 404, "not-found")


# --- AC-1.7 -----------------------------------------------------------------

def test_fr01_pagination_is_cursor_based(env):
    seeded = set(env.seed_tasks(120))
    pages = env.list_all(limit=50)
    assert [len(p) for p in pages] == [50, 50, 20]
    ids = [item["id"] for page in pages for item in page]
    assert len(ids) == len(set(ids)) == 120
    assert set(ids) == seeded

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

def test_fr01_list_limit_default_50_max_200(env):
    env.seed_tasks(60)
    resp = env.client.get("/v1/tasks", headers=_headers("read"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 50
    assert body["next_cursor"]


def test_fr01_list_limit_200_accepted(env):
    env.seed_tasks(210)
    resp = env.client.get("/v1/tasks", params={"limit": 200}, headers=_headers("read"))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 200


def test_fr01_list_limit_201_returns_422(env):
    resp = env.client.get("/v1/tasks", params={"limit": 201}, headers=_headers("read"))
    _assert_problem(resp, 422, "validation")


# --- AC-1.5 boundaries / blacklist / uniqueness -----------------------------

def test_fr01_command_over_1000_chars_returns_422(env):
    command = "echo " + "a" * 996
    assert len(command) == 1001
    _assert_problem(env.create("long-cmd", command), 422, "validation")
    assert env.sql("SELECT COUNT(*) FROM tasks") == [(0,)]


def test_fr01_command_exactly_1000_chars_accepted(env):
    command = "echo " + "a" * 995
    assert len(command) == 1000
    resp = env.create("max-cmd", command)
    assert resp.status_code == 201, resp.text
    assert env.sql("SELECT command FROM tasks WHERE id = ?", (resp.json()["id"],)) == [(command,)]


def test_fr01_injection_chars_in_command_returns_422(env):
    # `;` is in the injection blacklist; membership beyond `;` is open decision NFR-99.2.
    _assert_problem(env.create("inj", "echo hi; cat /etc/passwd"), 422, "validation")
    assert env.sql("SELECT COUNT(*) FROM tasks") == [(0,)]


def test_fr01_duplicate_name_returns_409(env):
    # NFR-99.3 resolved to 409 per SPEC section 7.
    first = env.create("dup-name", "echo one")
    assert first.status_code == 201, first.text
    _assert_problem(env.create("dup-name", "echo two"), 409, "conflict")
    assert env.sql("SELECT COUNT(*) FROM tasks WHERE name = ?", ("dup-name",)) == [(1,)]


# --- SEC T-05 / T-08 --------------------------------------------------------

def test_sec_t05_injection_chars_rejected_422(env):
    resp = env.create("t05", "echo a; echo b")
    _assert_problem(resp, 422, "validation")
    assert env.sql("SELECT COUNT(*) FROM tasks") == [(0,)]


def test_sec_t08_sql_metacharacters_treated_as_data(env):
    name = "x' OR '1'='1"
    resp = env.create(name, "echo sql")
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]

    assert env.sql("SELECT COUNT(*) FROM tasks") == [(1,)]
    got = env.client.get(f"/v1/tasks/{task_id}", headers=_headers("read"))
    assert got.status_code == 200, got.text
    assert got.json()["name"] == name
    assert env.sql("SELECT name FROM tasks WHERE id = ?", (task_id,)) == [(name,)]

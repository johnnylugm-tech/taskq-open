"""FR-09 — Health checks and observability.

Covers TEST_SPEC.md FR-09 rows 1-6 (AC-9.1 .. AC-9.5, NP-01, NP-02, NP-07).

Test harness contract:
- HTTP cases run in-process via FastAPI TestClient against
  `taskq_api.app.create_app()`, with `TASKQ_DB_URL` pointing at a fresh SQLite
  *file* per test (state_mode="isolate_per_test").
- The schema is built by the real Alembic migrations
  (`taskq_api.repository.migration_state.upgrade`), so `alembic current` is a
  real stamped revision: "v3" is head, "v2" is one revision behind.
- `GET /readyz` is decided by `taskq_api.service.health` (readiness) and
  answered by `taskq_api.api.routes_health`; when not ready it returns an
  RFC 7807 body with `type` "/errors/not-ready" and a `detail` naming the
  failing check ("database" unavailable / "migration" not at head).
- DB-down fault injection: `TASKQ_DB_URL` names a SQLite file inside a
  directory that does not exist, so every connection attempt fails.
- `GET /v1/metrics` is served by `taskq_api.api.routes_metrics` (scope
  `admin`), aggregated in `taskq_api.service.health` from
  `taskq_api.repository.stats`. Its JSON body carries three sections:
    "tasks_by_status"        -> {status: count}
    "latency_percentiles"    -> {"p50": ms, "p95": ms, "p99": ms}
    "rate_limit_rejections"  -> int (429 responses served so far)
  and never contains the DB URL (NFR-04).
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.api import routes_health, routes_metrics  # noqa: E402
from taskq_api.app import create_app  # noqa: E402
from taskq_api.repository import migration_state, stats  # noqa: E402
from taskq_api.service import health  # noqa: E402

PROBLEM_JSON = "application/problem+json"
ADMIN_KEY = "sk-test-admin-0123456789"
WRITE_KEY = "sk-test-write-0123456789"
READ_KEY = "sk-test-read-0123456789"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
SECTION_KEYS = {
    "task counts by status": "tasks_by_status",
    "latency percentiles": "latency_percentiles",
    "rate-limit rejections": "rate_limit_rejections",
}


def _sql(db_file: Path, statement: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _seed_key(db_file: Path, plaintext: str, scope: str) -> None:
    _sql(
        db_file,
        "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), hashlib.sha256(plaintext.encode()).hexdigest(), scope, BASE_TIME.isoformat(), None),
    )


def _seed_task(db_file: Path, name: str, status: str, duration_ms: int | None) -> None:
    task_id = str(uuid.uuid4())
    _sql(
        db_file,
        "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, "echo hi", name, status, BASE_TIME.isoformat()),
    )
    if duration_ms is not None:
        _sql(
            db_file,
            "INSERT INTO task_results (id, task_id, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), task_id, 0, "hi", "", duration_ms, BASE_TIME.isoformat()),
        )


def _migrated_db(tmp_path: Path, monkeypatch, revision: str) -> tuple[Path, str]:
    db_file = tmp_path / "taskq.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("TASKQ_DB_URL", db_url)
    migration_state.upgrade(db_url, revision)
    return db_file, db_url


@pytest.fixture
def head_db(tmp_path, monkeypatch) -> tuple[Path, str]:
    """Fresh SQLite file migrated to head ("v3"); rate limit out of the way."""
    monkeypatch.setenv("TASKQ_RATE_BURST", "100000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "100000")
    return _migrated_db(tmp_path, monkeypatch, "head")


def _problem_fields(resp) -> tuple[str, str]:
    body = resp.json()
    return str(body.get("detail", "")), str(body.get("type", ""))


# --- AC-9.1 -----------------------------------------------------------------

def test_fr09_healthz_returns_ok(head_db):
    endpoint = "/healthz"
    expected_status = "200"
    expected_body_status = "ok"
    with TestClient(create_app()) as client:
        resp = client.get(endpoint)  # x_api_key_header="absent"
    result_status = resp.status_code
    result_body_status = resp.json().get("status")
    # AC9.1-status
    assert result_status == int(expected_status), resp.text
    # AC9.1-body
    assert result_body_status == expected_body_status
    assert resp.json() == {"status": "ok"}


# --- AC-9.2 -----------------------------------------------------------------

def test_fr09_readyz_ok_when_db_up_and_at_head(head_db):
    endpoint = "/readyz"
    db_revision = "v3"
    alembic_head = "v3"
    expected_status = "200"
    _, db_url = head_db
    assert migration_state.current_revision(db_url) == db_revision == alembic_head
    with TestClient(create_app()) as client:
        resp = client.get(endpoint)
    result_status = resp.status_code
    # AC9.1-status
    assert result_status == int(expected_status), resp.text
    readiness = health.readiness(db_url)
    assert readiness.ready is True


# --- AC-9.3 (SPEC §8 #10, NP-07) --------------------------------------------

def test_fr09_readyz_503_when_db_down(tmp_path, monkeypatch):
    endpoint = "/readyz"
    fault_type = "db_unavailable"
    expected_status = "503"
    expected_detail_token = "database"
    # fault_type="db_unavailable": the DB file's directory does not exist, so
    # SQLite cannot open (or create) it and every connect attempt fails.
    missing_dir = tmp_path / "db-stopped"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{missing_dir / 'taskq.db'}")
    assert fault_type == "db_unavailable" and not missing_dir.exists()
    with TestClient(create_app()) as client:
        resp = client.get(endpoint)
        liveness = client.get("/healthz")
    result_status = resp.status_code
    result_detail, result_problem_type = _problem_fields(resp)
    # AC9.1-status
    assert result_status == int(expected_status), resp.text
    assert resp.headers.get("content-type", "").startswith(PROBLEM_JSON)
    # AC9.3-detail
    assert expected_detail_token in result_detail.lower()
    # AC9.3-problem
    assert result_problem_type.endswith("/errors/not-ready")
    assert result_problem_type == "/errors/not-ready"
    # Liveness is independent of the DB.
    assert liveness.status_code == 200


# --- AC-9.4 (SPEC §8 #11) ---------------------------------------------------

def test_fr09_readyz_503_when_migration_behind(tmp_path, monkeypatch):
    endpoint = "/readyz"
    db_revision = "v2"
    alembic_head = "v3"
    expected_status = "503"
    expected_detail_token = "migration"
    _, db_url = _migrated_db(tmp_path, monkeypatch, "head")
    # `alembic downgrade -1` from head lands one revision behind.
    migration_state.downgrade(db_url, "-1")
    assert migration_state.current_revision(db_url) == db_revision != alembic_head
    with TestClient(create_app()) as client:
        resp = client.get(endpoint)
    result_status = resp.status_code
    result_detail, result_problem_type = _problem_fields(resp)
    # AC9.1-status
    assert result_status == int(expected_status), resp.text
    assert resp.headers.get("content-type", "").startswith(PROBLEM_JSON)
    # AC9.3-detail
    assert expected_detail_token in result_detail.lower()
    # AC9.3-problem
    assert result_problem_type == "/errors/not-ready"


# --- AC-9.5 -----------------------------------------------------------------

def test_fr09_metrics_admin_payload(tmp_path, monkeypatch):
    endpoint = "/v1/metrics"
    key_scope = "admin"
    expected_status = "200"
    expected_sections = "task counts by status,latency percentiles,rate-limit rejections"
    # One token per key and no refill: a second request with READ_KEY is a 429.
    monkeypatch.setenv("TASKQ_RATE_BURST", "1")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "0.0001")
    db_file, db_url = _migrated_db(tmp_path, monkeypatch, "head")
    _seed_key(db_file, ADMIN_KEY, key_scope)
    _seed_key(db_file, READ_KEY, "read")
    _seed_task(db_file, "t-pending", "pending", None)
    _seed_task(db_file, "t-done-1", "done", 100)
    _seed_task(db_file, "t-done-2", "done", 200)
    _seed_task(db_file, "t-failed", "failed", 300)
    with TestClient(create_app()) as client:
        assert client.get("/v1/tasks", headers={"X-API-Key": READ_KEY}).status_code == 200
        assert client.get("/v1/tasks", headers={"X-API-Key": READ_KEY}).status_code == 429
        resp = client.get(endpoint, headers={"X-API-Key": ADMIN_KEY})
    result_status = resp.status_code
    result_body_text = resp.text
    payload = resp.json()
    result_missing_sections = [
        label for label in expected_sections.split(",") if SECTION_KEYS[label] not in payload
    ]
    result_db_url_fragment = str(db_file)
    # AC9.1-status
    assert result_status == int(expected_status), resp.text
    # AC9.5-sections
    assert len(result_missing_sections) == 0, result_missing_sections
    assert payload["tasks_by_status"].get("done") == 2
    assert payload["tasks_by_status"].get("pending") == 1
    assert payload["tasks_by_status"].get("failed") == 1
    assert {"p50", "p95", "p99"} <= set(payload["latency_percentiles"])
    assert 100 <= payload["latency_percentiles"]["p50"] <= 300
    assert payload["latency_percentiles"]["p50"] <= payload["latency_percentiles"]["p99"] <= 300
    assert payload["rate_limit_rejections"] >= 1
    # AC9.5-no-db-url
    assert result_db_url_fragment not in result_body_text
    assert db_url not in result_body_text
    assert stats.task_counts_by_status is not None
    assert routes_metrics.router is not None and routes_health.router is not None


# --- AC-9.5 / NP-02 ---------------------------------------------------------

def test_fr09_metrics_requires_admin_scope(head_db):
    endpoint = "/v1/metrics"
    key_scope = "write"
    expected_status = "403"
    db_file, _ = head_db
    _seed_key(db_file, WRITE_KEY, key_scope)
    with TestClient(create_app()) as client:
        resp = client.get(endpoint, headers={"X-API-Key": WRITE_KEY})
    result_status = resp.status_code
    # AC9.1-status
    assert result_status == int(expected_status), resp.text
    assert resp.headers.get("content-type", "").startswith(PROBLEM_JSON)
    assert resp.json()["type"].endswith("/errors/forbidden")

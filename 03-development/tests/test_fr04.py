"""FR-04 — Scope authorization.

Covers TEST_SPEC.md FR-04 rows 1-7 (AC-4.1 .. AC-4.4, SEC T-02, SEC T-03).

Test harness contract:
- HTTP cases run in-process via FastAPI TestClient against
  `taskq_api.app.create_app()`, with `TASKQ_DB_URL` pointing at a fresh SQLite
  file per test (state_mode="isolate_per_test").
- Keys are seeded into `api_keys` as SHA-256 hex digests of the plaintext.
- AC-4.4 inspects the FastAPI dependency tree of every `/v1` route: each must
  reach the single `taskq_api.api.deps.require_scope` dependency.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.api import deps  # noqa: E402
from taskq_api.app import create_app  # noqa: E402
from taskq_api.models.base import Base  # noqa: E402
from taskq_api.service.auth import hash_key  # noqa: E402

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
KEYS = {
    "read": "sk-test-read-0123456789",
    "write": "sk-test-write-0123456789",
    "admin": "sk-test-admin-0123456789",
}
NEW_TASK = {"name": "fr04-task", "command": "echo hi"}


def _seed_key(db_file: Path, plaintext: str, scope: str) -> None:
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
            (str(uuid.uuid4()), hash_key(plaintext), scope, BASE_TIME.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "taskq.db"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{path}")
    # Rate limiting (FR-05) must not interfere with FR-04 behaviour.
    monkeypatch.setenv("TASKQ_RATE_BURST", "100000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "100000")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    for scope, plaintext in KEYS.items():
        _seed_key(path, plaintext, scope)
    with TestClient(create_app()) as test_client:
        yield test_client


def _h(scope: str) -> dict[str, str]:
    return {"X-API-Key": KEYS[scope]}


def _create_task(client: TestClient, name: str = NEW_TASK["name"]) -> str:
    response = client.post("/v1/tasks", json={**NEW_TASK, "name": name}, headers=_h("admin"))
    assert response.status_code == 201
    return response.json()["id"]


def _delete_probe(client: TestClient, task_id: str):
    return client.delete(f"/v1/tasks/{task_id}", headers=_h("write"))


def _problem_type(response) -> str:
    return urlparse(response.json()["type"]).path


def test_fr04_scope_hierarchy_matrix(client):
    # admin >= write, so POST /v1/tasks -> 201.
    expected_status = "201"
    resp = client.post("/v1/tasks", json=NEW_TASK, headers=_h("admin"))
    result_status = resp.status_code
    # AC4.1-allowed
    assert result_status == int(expected_status), resp.text
    # Full matrix: allowed iff scope rank >= required rank.
    write_task = {**NEW_TASK, "name": "fr04-write-task"}
    assert client.post("/v1/tasks", json=write_task, headers=_h("write")).status_code == 201
    assert client.post("/v1/tasks", json=NEW_TASK, headers=_h("read")).status_code == 403
    task_id = _create_task(client, "fr04-delete-target")
    assert client.delete(f"/v1/tasks/{task_id}", headers=_h("read")).status_code == 403
    assert client.delete(f"/v1/tasks/{task_id}", headers=_h("write")).status_code == 403
    assert client.delete(f"/v1/tasks/{task_id}", headers=_h("admin")).status_code == 204


def test_fr04_write_key_can_read(client):
    expected_status = "200"
    resp = client.get("/v1/tasks", headers=_h("write"))
    result_status = resp.status_code
    # AC4.1-allowed: write includes read.
    assert result_status == int(expected_status), resp.text


def test_fr04_insufficient_scope_returns_403(client):
    expected_status = "403"
    resp = client.post("/v1/tasks", json=NEW_TASK, headers=_h("read"))
    result_status = resp.status_code
    result_problem_type = _problem_type(resp)
    # AC4.2-denied
    assert result_status == int(expected_status), resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    # AC4.2-problem
    assert result_problem_type == "/errors/forbidden"


# NFR-02
def test_fr04_403_does_not_leak_existence(client):
    expected_status = "403"
    existing_id = _create_task(client)
    unknown_id = str(uuid.uuid4())
    existing = _delete_probe(client, existing_id)
    unknown = _delete_probe(client, unknown_id)
    result_status = existing.status_code
    result_status_existing = existing.status_code
    result_status_unknown = unknown.status_code
    result_problem_type_existing = _problem_type(existing)
    result_problem_type_unknown = _problem_type(unknown)
    result_detail_existing = existing.json()["detail"]
    result_detail_unknown = unknown.json()["detail"]
    # AC4.2-denied
    assert result_status == int(expected_status)
    # AC4.3-same-status
    assert result_status_existing == result_status_unknown
    # AC4.3-same-type
    assert result_problem_type_existing == result_problem_type_unknown
    # AC4.3-same-detail
    assert result_detail_existing == result_detail_unknown
    assert existing_id not in existing.text
    assert unknown_id not in unknown.text


def test_fr04_every_v1_route_uses_scope_dependency(client):
    expected_unguarded_routes = "0"
    app = client.app

    def calls(dependant) -> list:
        found = []
        for sub in dependant.dependencies:
            found.append(sub.call)
            found.extend(calls(sub))
        return found

    v1_routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/v1")]
    result_checked_route_count = len(v1_routes)
    result_unguarded_routes = [
        f"{sorted(r.methods)} {r.path}"
        for r in v1_routes
        if not any(
            getattr(c, "__module__", "") == deps.__name__
            and getattr(c, "__qualname__", "").startswith("require_scope.")
            for c in calls(r.dependant)
        )
    ]
    # AC4.4-routes-seen
    assert result_checked_route_count > 0
    # AC4.4-all-guarded
    assert len(result_unguarded_routes) == int(expected_unguarded_routes), result_unguarded_routes


def test_sec_t02_insufficient_scope_returns_403(client):
    expected_status = "403"
    resp = client.post("/v1/tasks", json=NEW_TASK, headers=_h("read"))
    result_status = resp.status_code
    result_problem_type = _problem_type(resp)
    # AC4.2-denied
    assert result_status == int(expected_status), resp.text
    # AC4.2-problem
    assert result_problem_type == "/errors/forbidden"


# NFR-02
def test_sec_t03_forbidden_body_does_not_reveal_existence(client):
    existing_id = _create_task(client)
    unknown_id = str(uuid.uuid4())
    existing = _delete_probe(client, existing_id)
    unknown = _delete_probe(client, unknown_id)
    result_status_existing = existing.status_code
    result_status_unknown = unknown.status_code
    result_problem_type_existing = _problem_type(existing)
    result_problem_type_unknown = _problem_type(unknown)
    result_detail_existing = existing.json()["detail"]
    result_detail_unknown = unknown.json()["detail"]
    # AC4.3-same-status
    assert result_status_existing == result_status_unknown == 403
    # AC4.3-same-type
    assert result_problem_type_existing == result_problem_type_unknown
    # AC4.3-same-detail
    assert result_detail_existing == result_detail_unknown


def test_fr04_require_scope_rejects_unknown_scope():
    """[FR-04] Misconfigured route scope fails at import time, not per request."""
    with pytest.raises(ValueError):
        deps.require_scope("superuser")


def test_fr04_over_limit_key_is_rejected_before_scope_check(client):
    """[FR-04] Rate-limit rejection (FR-05) applies ahead of scope authorization."""
    client.app.state.settings = dataclasses.replace(
        client.app.state.settings, rate_burst=1, rate_per_sec=0.001
    )
    first = client.get("/v1/tasks", headers=_h("read"))
    second = client.get("/v1/tasks", headers=_h("read"))
    assert first.status_code == 200
    assert second.status_code == 429


def test_fr04_get_executor_returns_app_executor(client):
    """[FR-04] The executor dependency resolves the app-lifespan executor."""
    request = type("R", (), {"app": client.app})()
    assert deps.get_executor(request) is client.app.state.executor  # type: ignore[arg-type]

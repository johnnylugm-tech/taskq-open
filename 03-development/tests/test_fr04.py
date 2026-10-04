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

import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

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


def _create_task(client: TestClient) -> str:
    response = client.post("/v1/tasks", json=NEW_TASK, headers=_h("admin"))
    assert response.status_code == 201
    return response.json()["id"]


def _delete_probe(client: TestClient, task_id: str):
    return client.delete(f"/v1/tasks/{task_id}", headers=_h("write"))


def test_fr04_scope_hierarchy_matrix(client):
    # AC4.1-allowed: admin >= write, so POST /v1/tasks -> 201.
    # Full matrix: (scope, method) -> allowed iff scope rank >= required rank.
    assert client.post("/v1/tasks", json=NEW_TASK, headers=_h("admin")).status_code == 201
    assert client.post("/v1/tasks", json=NEW_TASK, headers=_h("write")).status_code == 201
    assert client.post("/v1/tasks", json=NEW_TASK, headers=_h("read")).status_code == 403
    task_id = _create_task(client)
    assert client.delete(f"/v1/tasks/{task_id}", headers=_h("read")).status_code == 403
    assert client.delete(f"/v1/tasks/{task_id}", headers=_h("write")).status_code == 403
    assert client.delete(f"/v1/tasks/{task_id}", headers=_h("admin")).status_code == 204


def test_fr04_write_key_can_read(client):
    # AC4.1-allowed: write includes read.
    response = client.get("/v1/tasks", headers=_h("write"))
    assert response.status_code == 200


def test_fr04_insufficient_scope_returns_403(client):
    response = client.post("/v1/tasks", json=NEW_TASK, headers=_h("read"))
    assert response.status_code == 403  # AC4.2-denied
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("/errors/forbidden")  # AC4.2-problem


def test_fr04_403_does_not_leak_existence(client):
    existing_id = _create_task(client)
    unknown_id = str(uuid.uuid4())
    existing = _delete_probe(client, existing_id)
    unknown = _delete_probe(client, unknown_id)
    assert existing.status_code == 403  # AC4.2-denied
    assert existing.status_code == unknown.status_code  # AC4.3-same-status
    assert existing.json()["type"] == unknown.json()["type"]  # AC4.3-same-type
    assert existing.json()["detail"] == unknown.json()["detail"]  # AC4.3-same-detail
    assert existing_id not in existing.text
    assert unknown_id not in unknown.text


def test_fr04_every_v1_route_uses_scope_dependency(client):
    app = client.app

    def calls(dependant) -> list:
        found = []
        for sub in dependant.dependencies:
            found.append(sub.call)
            found.extend(calls(sub))
        return found

    v1_routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/v1")]
    assert v1_routes
    unguarded = [
        f"{sorted(r.methods)} {r.path}"
        for r in v1_routes
        if not any(
            getattr(c, "__module__", "") == deps.__name__
            and getattr(c, "__qualname__", "").startswith("require_scope.")
            for c in calls(r.dependant)
        )
    ]
    assert len(unguarded) == 0, unguarded  # AC4.4-all-guarded


def test_sec_t02_insufficient_scope_returns_403(client):
    response = client.post("/v1/tasks", json=NEW_TASK, headers=_h("read"))
    assert response.status_code == 403  # AC4.2-denied
    assert response.json()["type"].endswith("/errors/forbidden")  # AC4.2-problem


def test_sec_t03_forbidden_body_does_not_reveal_existence(client):
    existing_id = _create_task(client)
    unknown_id = str(uuid.uuid4())
    existing = _delete_probe(client, existing_id)
    unknown = _delete_probe(client, unknown_id)
    assert existing.status_code == unknown.status_code == 403  # AC4.3-same-status
    assert existing.json()["type"] == unknown.json()["type"]  # AC4.3-same-type
    assert existing.json()["detail"] == unknown.json()["detail"]  # AC4.3-same-detail

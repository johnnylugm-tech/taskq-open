"""Runtime NFR checks driven through the real app, real SQLite files and real processes.

Covers the cross-cutting rows of TEST_SPEC.md: NFR-01 (latency, query count),
NFR-02 (key hashing, 403 leak, error body, CORS), NFR-03 (DB failure, timeout
orphans, migration rollback), NFR-04 (secret masking), NFR-05 (OpenAPI docs)
and the deployment smoke test.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.app import create_app  # noqa: E402
from taskq_api.repository import migration_state  # noqa: E402
from taskq_api.service import auth, runner  # noqa: E402

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
KEYS = {"read": "sk-test-nfr-read-0123456789", "write": "sk-test-nfr-write-0123456789",
        "admin": "sk-test-nfr-admin-0123456789"}


def _headers(scope: str) -> dict[str, str]:
    return {"X-API-Key": KEYS[scope]}


def _seed_keys(db_file: Path) -> None:
    conn = sqlite3.connect(db_file)
    for scope, plaintext in KEYS.items():
        conn.execute(
            "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
            (str(uuid.uuid4()), hashlib.sha256(plaintext.encode()).hexdigest(), scope, BASE_TIME.isoformat()),
        )
    conn.commit()
    conn.close()


def _seed_tasks(db_file: Path, rows: int) -> list[str]:
    ids = [str(uuid.uuid4()) for _ in range(rows)]
    conn = sqlite3.connect(db_file)
    conn.executemany(
        "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, 'echo seed', ?, 'pending', ?)",
        [(task_id, f"seed-{index}", (BASE_TIME + timedelta(seconds=index)).isoformat())
         for index, task_id in enumerate(ids)],
    )
    conn.commit()
    conn.close()
    return ids


def _migrated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "taskq.db") -> Path:
    db_file = tmp_path / name
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("TASKQ_RATE_BURST", "1000000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "1000000")
    migration_state.upgrade(f"sqlite:///{db_file}")
    _seed_keys(db_file)
    return db_file


@pytest.fixture
def db_file(tmp_path, monkeypatch) -> Path:
    return _migrated_db(tmp_path, monkeypatch)


@pytest.fixture
def client(db_file):
    with TestClient(create_app()) as test_client:
        yield test_client


# --- NFR-01 -------------------------------------------------------------------

def _p95_ms(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


async def _bench(app, path: str, rounds: int, params: dict | None = None) -> list[float]:
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            samples = []
            for _ in range(rounds):
                started = time.perf_counter()
                resp = await http.get(path, params=params, headers=_headers("read"))
                samples.append((time.perf_counter() - started) * 1000)
                assert resp.status_code == 200
            return samples


@pytest.fixture(scope="module")
def big_db(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp_path = tmp_path_factory.mktemp("nfr01")
    db_file = _migrated_db(tmp_path, mp, "big.db")
    ids = _seed_tasks(db_file, 10000)
    yield db_file, ids
    mp.undo()


def test_nfr01_get_task_p95_under_30ms(big_db):
    db_file, ids = big_db
    p95_budget_ms = 30
    result_seeded_rows = sqlite3.connect(db_file).execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    samples = asyncio.run(_bench(create_app(), f"/v1/tasks/{ids[5000]}", rounds=100))
    result_p95_ms = _p95_ms(samples)
    assert result_seeded_rows == 10000  # ACN1.1-rows
    assert result_p95_ms < p95_budget_ms, result_p95_ms  # ACN1.1-p95 (NFR-01)


def test_nfr01_list_p95_under_80ms(big_db):
    p95_budget_ms = 80
    samples = asyncio.run(_bench(create_app(), "/v1/tasks", rounds=100, params={"limit": 50}))
    result_p95_ms = _p95_ms(samples)
    assert result_p95_ms < p95_budget_ms, result_p95_ms  # ACN1.1-p95 (NFR-01)


def _count_statements(db_file: Path) -> int:
    counted: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        counted.append(statement)

    event.listen(Engine, "before_cursor_execute", before)
    try:
        with TestClient(create_app()) as test_client:
            resp = test_client.get("/v1/tasks", params={"limit": 50}, headers=_headers("read"))
            assert resp.status_code == 200
            assert len(resp.json()["items"]) == 50
    finally:
        event.remove(Engine, "before_cursor_execute", before)
    return len(counted)


def test_nfr01_sql_statement_count_constant(tmp_path, monkeypatch):
    small = _migrated_db(tmp_path, monkeypatch, "small.db")
    _seed_tasks(small, 60)
    result_stmt_count_small = _count_statements(small)
    large = _migrated_db(tmp_path, monkeypatch, "large.db")
    _seed_tasks(large, 10000)
    result_stmt_count_large = _count_statements(large)
    assert result_stmt_count_small > 0
    assert result_stmt_count_large == result_stmt_count_small  # ACN1.3-constant (NFR-01)


# --- NFR-02 -------------------------------------------------------------------

def test_nfr02_api_key_hashed_compare_digest(client, db_file, monkeypatch):
    expected_hash_len = 64
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    resp = client.get("/v1/tasks", headers=_headers("read"))
    stored = [row[0] for row in sqlite3.connect(db_file).execute("SELECT key_hash FROM api_keys")]
    assert resp.status_code == 200
    assert all(len(result_key_hash) == expected_hash_len for result_key_hash in stored)  # ACN2.3-hash-len
    assert KEYS["read"] not in stored
    assert calls and len(calls[0][0]) == expected_hash_len  # ACN2.3-compare-digest (NFR-02)


def test_nfr02_403_no_existence_leak(client):
    existing = client.post("/v1/tasks", json={"name": "keep", "command": "echo"}, headers=_headers("write")).json()["id"]
    unknown = str(uuid.uuid4())
    seen_existing = client.delete(f"/v1/tasks/{existing}", headers=_headers("write"))
    seen_unknown = client.delete(f"/v1/tasks/{unknown}", headers=_headers("write"))
    assert seen_existing.status_code == seen_unknown.status_code == 403  # ACN2.4-same-status
    assert seen_existing.json()["detail"] == seen_unknown.json()["detail"]  # ACN2.4-same-body (NFR-02)
    assert existing not in seen_existing.text


def test_nfr02_error_body_no_internals(db_file):
    forbidden_tokens = "SELECT,Traceback,.py,/Users"
    app = create_app()

    async def boom():
        raise RuntimeError("SELECT * FROM api_keys failed in /Users/dev/app/secret.py Traceback (most recent call)")

    app.add_api_route("/__fault", boom, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as test_client:
        resp = test_client.get("/__fault")
    assert resp.status_code == 500
    assert all(tok not in resp.text for tok in forbidden_tokens.split(","))  # ACN2.5-no-internals (NFR-02)


def test_nfr02_cors_default_deny(client):
    result_acao_header = client.get("/healthz", headers={"Origin": "https://evil.example"}).headers.get(
        "access-control-allow-origin", ""
    )
    assert result_acao_header == ""  # ACN2.6-deny (NFR-02)


# --- NFR-03 -------------------------------------------------------------------

def test_nfr03_db_failure_readyz_503_no_infinite_retry(tmp_path, monkeypatch):
    response_deadline_s = 5
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{tmp_path / 'missing-dir' / 'taskq.db'}")
    with TestClient(create_app()) as test_client:
        started = time.monotonic()
        resp = test_client.get("/readyz")
        result_elapsed_s = time.monotonic() - started
    assert resp.status_code == 503  # ACN3.4-status (NFR-03)
    assert result_elapsed_s < response_deadline_s  # ACN3.4-bounded
    assert len(resp.json()["detail"]) > 0  # ACN3.4-detail


def test_nfr03_timeout_leaves_no_orphan(monkeypatch):
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.5")
    pids: list[int] = []
    real_exec = asyncio.create_subprocess_exec

    async def spy_exec(*argv, **kwargs):
        process = await real_exec(*argv, **kwargs)
        pids.append(process.pid)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    outcome = asyncio.run(runner.run_command("sleep 30", runner.TaskStateMachine()))

    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    result_orphan_pids = [pid for pid in pids if alive(pid)]
    assert outcome.status == "timeout"  # NFR-03
    assert len(pids) == 1
    assert len(result_orphan_pids) == 0  # ACN3.5-no-orphan


def test_nfr03_failed_migration_rolls_back(tmp_path, monkeypatch):
    import alembic.op

    db_url = f"sqlite:///{tmp_path / 'rollback.db'}"
    migration_state.upgrade(db_url, "v2")
    conn = sqlite3.connect(tmp_path / "rollback.db")
    conn.execute(
        "INSERT INTO tasks (id, command, name, status, created_at, result_json) "
        "VALUES ('t1', 'echo', 'n', 'done', '2026-01-01T00:00:00', '{\"exit_code\": 0}')"
    )
    conn.commit()
    conn.close()

    def failing_drop_column(*args, **kwargs):
        raise RuntimeError("fault injected after the data move")

    monkeypatch.setattr(alembic.op, "drop_column", failing_drop_column)
    with pytest.raises(RuntimeError, match="fault injected"):
        migration_state.upgrade(db_url)
    monkeypatch.undo()

    result_revision_after = migration_state.current_revision(db_url)
    tables = {row[0] for row in sqlite3.connect(tmp_path / "rollback.db").execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    result_partial_tables = tables & {"task_results"}
    assert result_revision_after == "v2"  # ACN3.6-revision (NFR-03)
    assert len(result_partial_tables) == 0  # ACN3.6-no-partial


# --- NFR-04 -------------------------------------------------------------------

def test_nfr04_db_url_absent_from_logs_errors_metrics(tmp_path, monkeypatch, caplog):
    secret_fragment = "s3cretPw"
    caplog.set_level(logging.DEBUG)
    db_file = _migrated_db(tmp_path, monkeypatch, f"nfr04-{secret_fragment}.db")
    assert secret_fragment in os.environ["TASKQ_DB_URL"]
    app = create_app()

    async def boom():
        raise RuntimeError("unexpected failure")

    app.add_api_route("/__fault", boom, methods=["GET"])
    bodies = []
    with TestClient(app, raise_server_exceptions=False) as test_client:
        bodies.append(test_client.get(f"/v1/tasks/{uuid.uuid4()}", headers=_headers("read")).text)
        bodies.append(test_client.get("/v1/tasks").text)
        bodies.append(test_client.get("/__fault").text)
        bodies.append(test_client.get("/readyz").text)
        result_metrics_text = test_client.get("/v1/metrics", headers=_headers("admin")).text
    missing_dir_url = f"sqlite:///{tmp_path / f'absent-{secret_fragment}' / 'x.db'}"
    monkeypatch.setenv("TASKQ_DB_URL", missing_dir_url)
    with TestClient(create_app()) as unreachable:
        bodies.append(unreachable.get("/readyz").text)
    result_logs_text = "\n".join(f"{r.getMessage()} {r.exc_text or ''}" for r in caplog.records)
    assert db_file.exists()
    assert secret_fragment not in result_logs_text  # ACN4.2-logs
    assert secret_fragment not in "\n".join(bodies)  # ACN4.2-errors
    assert secret_fragment not in result_metrics_text  # ACN4.2-metrics (NFR-04)


def test_nfr04_key_plaintext_never_persisted(tmp_path, monkeypatch):
    db_file = tmp_path / "plain.db"
    db_url = f"sqlite:///{db_file}"
    migration_state.upgrade(db_url)
    env = {**os.environ, "TASKQ_DB_URL": db_url, "PYTHONPATH": str(SRC_ROOT)}
    proc = subprocess.run(
        [sys.executable, "-m", "taskq_api", "key", "create", "--scope", "read"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    plaintext = proc.stdout.strip()
    result_plaintext_occurrences_in_stdout = proc.stdout.count(plaintext)
    conn = sqlite3.connect(db_file)
    rows = conn.execute("SELECT id, key_hash, scope FROM api_keys").fetchall()
    result_plaintext_in_db = any(plaintext in str(value) for row in rows for value in row)
    result_files_with_plaintext = [
        str(path) for path in tmp_path.rglob("*")
        if path.is_file() and plaintext.encode() in path.read_bytes()
    ]
    assert proc.returncode == 0 and plaintext  # NFR-04
    assert not result_plaintext_in_db  # ACN4.3-db
    assert len(result_files_with_plaintext) == 0  # ACN4.3-files
    assert result_plaintext_occurrences_in_stdout == 1  # ACN4.3-printed-once
    assert rows[0][1] == hashlib.sha256(plaintext.encode()).hexdigest()


# --- NFR-05 -------------------------------------------------------------------

def test_nfr05_openapi_summary_description_per_operation(client):
    expected_missing_operations = 0
    schema = client.get("/openapi.json").json()
    operations = [(path, method, op) for path, item in schema["paths"].items() for method, op in item.items()]
    result_operations_missing_summary = [(p, m) for p, m, op in operations if not op.get("summary")]
    result_operations_missing_description = [(p, m) for p, m, op in operations if not op.get("description")]
    assert len(operations) > 0  # ACN5.2-nonempty (NFR-05)
    assert len(result_operations_missing_summary) == expected_missing_operations  # ACN5.2-summary
    assert len(result_operations_missing_description) == expected_missing_operations  # ACN5.2-description


# --- Deployment smoke ---------------------------------------------------------

def test_app_starts_and_health_endpoint_returns_200(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

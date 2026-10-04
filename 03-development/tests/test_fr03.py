"""FR-03 — API key authentication.

Covers TEST_SPEC.md FR-03 rows 1-8 (AC-3.1 .. AC-3.5, SEC T-01).

Test harness contract:
- HTTP cases run in-process via FastAPI TestClient against
  `taskq_api.app.create_app()`, with `TASKQ_DB_URL` pointing at a fresh SQLite
  file per test (state_mode="isolate_per_test"); the schema comes from
  `taskq_api.models.base.Base.metadata`.
- Keys are seeded into `api_keys` as SHA-256 hex digests of the plaintext.
- `taskq_api.service.auth.hash_key(plaintext) -> str` returns the 64-hex
  SHA-256 digest stored in `api_keys.key_hash`.
- `taskq_api.cli.main(argv) -> int` is the CLI entry (`python -m taskq_api`
  delegates to it); `key create --scope <scope>` inserts one `api_keys` row
  into the database named by `TASKQ_DB_URL` and prints the plaintext key
  exactly once on stdout.
- The CLI cases marked subprocess_mode="out_of_process" run the real
  `python -m taskq_api` entry point; the child shares the parent's
  `TASKQ_DB_URL` (shared_TASKQ_HOME="true") and gets `03-development/src`
  on PYTHONPATH.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api import cli  # noqa: E402
from taskq_api.app import create_app  # noqa: E402
from taskq_api.models.base import Base  # noqa: E402
from taskq_api.service.auth import hash_key  # noqa: E402

PROBLEM_JSON = "application/problem+json"
VALID_KEY = "sk-test-read-0123456789"
REVOKED_KEY = "sk-test-revoked-0123456789"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
TOKEN_RE = re.compile(r"[A-Za-z0-9_\-\.]{16,}")


def _sql(db_file: Path, statement: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _seed_key(db_file: Path, plaintext: str, scope: str, revoked: bool) -> None:
    _sql(
        db_file,
        "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            hashlib.sha256(plaintext.encode()).hexdigest(),
            scope,
            BASE_TIME.isoformat(),
            BASE_TIME.isoformat() if revoked else None,
        ),
    )


@pytest.fixture
def db_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "taskq.db"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{path}")
    # Rate limiting (FR-05) must not interfere with FR-03 behaviour.
    monkeypatch.setenv("TASKQ_RATE_BURST", "100000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "100000")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


@pytest.fixture
def client(db_file):
    _seed_key(db_file, VALID_KEY, "read", revoked=False)
    _seed_key(db_file, REVOKED_KEY, "admin", revoked=True)
    with TestClient(create_app()) as test_client:
        yield test_client


def _child_env(db_file: Path) -> dict[str, str]:
    # Out-of-process: pytest's pythonpath setting does not reach the child.
    env = os.environ.copy()
    env["TASKQ_DB_URL"] = f"sqlite:///{db_file}"
    env["PYTHONPATH"] = str(SRC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_cli(db_file: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "taskq_api", *args],
        env=_child_env(db_file),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _issued_plaintext(output: str, key_hash: str) -> str:
    """Return the printed token whose SHA-256 equals the stored hash."""
    for token in TOKEN_RE.findall(output):
        if hashlib.sha256(token.encode()).hexdigest() == key_hash:
            return token
    raise AssertionError("no printed token hashes to the stored key_hash")


# --- AC-3.1 -----------------------------------------------------------------

def test_fr03_missing_or_invalid_key_returns_401(client):
    endpoint = "/v1/tasks"
    expected_status = "401"
    resp = client.get(endpoint)
    result_status = resp.status_code
    result_content_type = resp.headers.get("content-type", "")
    # AC3.1-status
    assert result_status == int(expected_status), resp.text
    # AC3.1-problem
    assert result_content_type.startswith("application/problem+json")
    assert resp.json()["type"].endswith("/errors/unauthenticated")


def test_fr03_invalid_key_returns_401(client):
    endpoint = "/v1/tasks"
    x_api_key_header = "tq_not_a_real_key"
    expected_status = "401"
    resp = client.get(endpoint, headers={"X-API-Key": x_api_key_header})
    result_status = resp.status_code
    result_content_type = resp.headers.get("content-type", "")
    # AC3.1-status
    assert result_status == int(expected_status), resp.text
    # AC3.1-problem
    assert result_content_type.startswith("application/problem+json")
    assert resp.json()["type"].endswith("/errors/unauthenticated")
    # The seeded valid key is accepted on the same endpoint (auth is real, not deny-all).
    assert client.get(endpoint, headers={"X-API-Key": VALID_KEY}).status_code == 200


# --- AC-3.2 -----------------------------------------------------------------

# NFR-02
def test_fr03_key_stored_as_sha256_hash_only(db_file):
    key_scope = "read"
    # In-process CLI call so the key-creation path is measured by coverage.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exit_code = cli.main(["key", "create", "--scope", key_scope])
    assert exit_code == 0
    rows = _sql(db_file, "SELECT key_hash, scope, revoked_at FROM api_keys")
    assert len(rows) == 1
    result_key_hash, stored_scope, revoked_at = rows[0]
    assert stored_scope == key_scope
    assert revoked_at is None
    issued_key = _issued_plaintext(buf.getvalue(), result_key_hash)
    result_sha256_of_issued_key = hashlib.sha256(issued_key.encode()).hexdigest()
    dump = "\n".join(sqlite3.connect(db_file).iterdump())
    result_plaintext_in_db = issued_key in dump or issued_key.encode() in db_file.read_bytes()
    # AC3.2-hash-len
    assert len(result_key_hash) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", result_key_hash)
    # AC3.2-digest-matches
    assert result_key_hash == result_sha256_of_issued_key
    assert hash_key(issued_key) == result_key_hash
    # AC3.2-no-plaintext
    assert not result_plaintext_in_db
    # comparison must be constant-time (SPEC L104)
    auth_source = (SRC_ROOT / "taskq_api" / "service" / "auth.py")
    if not auth_source.exists():
        auth_source = SRC_ROOT / "taskq_api" / "service" / "auth" / "__init__.py"
    assert "hmac.compare_digest" in auth_source.read_text()


# --- AC-3.3 -----------------------------------------------------------------

def test_fr03_key_create_cli_prints_plaintext_once(db_file):
    expected_plaintext_occurrences = "1"
    proc = _run_cli(db_file, "key", "create", "--scope", "read")
    result_exit_code = proc.returncode
    # AC3.3-exit-ok
    assert result_exit_code == 0, proc.stderr
    rows = _sql(db_file, "SELECT key_hash FROM api_keys")
    assert len(rows) == 1
    issued_key = _issued_plaintext(proc.stdout, rows[0][0])
    result_plaintext_occurrences = (proc.stdout + proc.stderr).count(issued_key)
    # AC3.3-once
    assert result_plaintext_occurrences == int(expected_plaintext_occurrences)
    # The issued key authenticates against the API.
    with TestClient(create_app()) as test_client:
        assert test_client.get("/v1/tasks", headers={"X-API-Key": issued_key}).status_code == 200


def test_fr03_key_create_rejects_unknown_scope(db_file):
    proc = _run_cli(db_file, "key", "create", "--scope", "superuser")
    result_exit_code = proc.returncode
    result_new_key_rows = _sql(db_file, "SELECT COUNT(*) FROM api_keys")[0][0]
    # AC3.3-exit-bad
    assert result_exit_code != 0
    # AC3.3-no-row
    assert result_new_key_rows == 0


# --- AC-3.4 -----------------------------------------------------------------

def test_fr03_revoked_key_returns_401(client):
    endpoint = "/v1/tasks"
    expected_status = "401"
    resp = client.get(endpoint, headers={"X-API-Key": REVOKED_KEY})
    result_status = resp.status_code
    # AC3.1-status
    assert result_status == int(expected_status), resp.text
    assert resp.headers.get("content-type", "").startswith(PROBLEM_JSON)


# --- AC-3.5 -----------------------------------------------------------------

def test_fr03_health_endpoints_need_no_key(client):
    expected_healthz_status = "200"
    healthz = client.get("/healthz")
    readyz = client.get("/readyz")
    result_healthz_status = healthz.status_code
    result_readyz_status = readyz.status_code
    # AC3.5-healthz
    assert result_healthz_status == int(expected_healthz_status), healthz.text
    assert healthz.json() == {"status": "ok"}
    # AC3.5-readyz-open
    assert result_readyz_status != 401
    assert result_readyz_status != 404


# --- SEC T-01 ---------------------------------------------------------------

def test_sec_t01_invalid_or_revoked_key_rejected(client):
    endpoint = "/v1/tasks"
    expected_status = "401"
    resp = client.post(
        endpoint, json={"name": "t01", "command": "echo hi"}, headers={"X-API-Key": REVOKED_KEY}
    )
    result_status = resp.status_code
    result_problem_type = resp.json()["type"]
    # AC3.1-status
    assert result_status == int(expected_status), resp.text
    # T01-body
    assert result_problem_type == "/errors/unauthenticated"

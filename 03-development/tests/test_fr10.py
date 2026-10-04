"""FR-10 — Error contract (RFC 7807).

Covers TEST_SPEC.md FR-10 rows 1-17 (AC-10.1 .. AC-10.6, SEC T-10/T-12/T-13).

Test harness contract:
- HTTP cases run in-process against `taskq_api.app.create_app()` with
  `TASKQ_DB_URL` pointing at a fresh SQLite *file* per test
  (state_mode="isolate_per_test"); the schema is built by the real Alembic
  migrations (`taskq_api.repository.migration_state.upgrade`).
- Every non-2xx response is `application/problem+json` with the fields
  type/title/status/detail/instance/correlation_id, rendered by
  `taskq_api.api.error_handlers`; unhandled exceptions become 500
  `/errors/internal` with a fixed, generic `detail` (no SQL, traceback,
  file path or schema text).
- `taskq_api.api.middleware` assigns each request a correlation id, echoes it
  in the `X-Correlation-Id` response header (`middleware.CORRELATION_HEADER`)
  and in the problem body, and logs the error with a `LogRecord` attribute
  `correlation_id` equal to that id.
- `asyncio.CancelledError` is not an error-table row: it must propagate out
  of the app, never be converted into a 500 response.
- CORS: no origin is allowed unless listed in `TASKQ_CORS_ORIGINS`
  (comma-separated); the default is empty -> deny all.
- Fault injection for 500 / cancel: an extra route is added to the app under
  test that raises the exception directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api import errors  # noqa: E402
from taskq_api.api import error_handlers, middleware  # noqa: E402
from taskq_api.app import create_app  # noqa: E402
from taskq_api.repository import migration_state  # noqa: E402

PROBLEM_JSON = "application/problem+json"
KEYS = {
    "read": "sk-test-read-0123456789",
    "write": "sk-test-write-0123456789",
    "admin": "sk-test-admin-0123456789",
}
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
LEAKY_MESSAGE = (
    "SELECT * FROM tasks WHERE id = 1 failed in "
    "/Users/dev/taskq/03-development/src/taskq_api/repository/tasks.py line 42"
)
TERMINAL_STATES = ("done", "failed", "timeout")
WAIT_SECONDS = 15.0


def _headers(scope: str) -> dict[str, str]:
    return {"X-API-Key": KEYS[scope]}


def _sql(db_file: Path, statement: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _prepare_db(tmp_path: Path, monkeypatch, burst: str = "100000") -> Path:
    db_file = tmp_path / "taskq.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("TASKQ_DB_URL", db_url)
    monkeypatch.setenv("TASKQ_RATE_BURST", burst)
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "0.001" if burst != "100000" else "100000")
    monkeypatch.setenv("TASKQ_CORS_ORIGINS", "")
    migration_state.upgrade(db_url, "head")
    for scope, plaintext in KEYS.items():
        _sql(
            db_file,
            "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
            (str(uuid.uuid4()), hashlib.sha256(plaintext.encode()).hexdigest(), scope, BASE_TIME.isoformat()),
        )
    return db_file


@pytest.fixture
def db_file(tmp_path, monkeypatch) -> Path:
    return _prepare_db(tmp_path, monkeypatch)


@pytest.fixture
def client(db_file):
    with TestClient(create_app()) as test_client:
        yield test_client


def _app_raising(exc_factory):
    """App under test with an extra route raising ``exc_factory()``."""
    app = create_app()

    async def boom():
        raise exc_factory()

    app.add_api_route("/__fault", boom, methods=["GET"])
    return app


def _get_500():
    app = _app_raising(lambda: RuntimeError(LEAKY_MESSAGE))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        return test_client.get("/__fault")


def _problem(resp) -> tuple[str, str]:
    body = resp.json()
    return str(body.get("type", "")), str(body.get("detail", ""))


def _logged_correlation_ids(caplog) -> list[str]:
    return [str(rec.correlation_id) for rec in caplog.records if getattr(rec, "correlation_id", None)]


def _assert_mapping(resp, expected_status: str, expected_type: str) -> None:
    result_status = resp.status_code
    result_content_type = resp.headers.get("content-type", "")
    result_problem_type, _ = _problem(resp)
    # AC10.1-status
    assert result_status == int(expected_status), resp.text
    # AC10.5-type
    assert result_problem_type == expected_type, resp.text
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == int(expected_status)
    assert body.get("correlation_id")
    assert resp.headers.get(middleware.CORRELATION_HEADER) == body["correlation_id"]


# --- AC-10.1 ----------------------------------------------------------------

# NFR-10
def test_fr10_non_2xx_content_type_problem_json(client):
    expected_status = "404"
    expected_content_type = "application/problem+json"
    resp = client.get(f"/v1/tasks/{uuid.uuid4()}", headers=_headers("read"))  # trigger="unknown task id"
    result_status = resp.status_code
    result_content_type = resp.headers.get("content-type", "")
    # AC10.1-status
    assert result_status == int(expected_status), resp.text
    # AC10.1-content-type
    assert result_content_type.startswith(expected_content_type)
    assert error_handlers.PROBLEM_JSON == expected_content_type


# --- AC-10.2 ----------------------------------------------------------------

# NFR-10
def test_fr10_problem_body_required_fields(client):
    expected_fields = "type,title,status,detail,instance,correlation_id"
    missing_id = str(uuid.uuid4())
    resp = client.get(f"/v1/tasks/{missing_id}", headers=_headers("read"))  # trigger="unknown task id"
    body = resp.json()
    result_fields = set(body)
    # AC10.2-fields
    assert all(f in result_fields for f in expected_fields.split(",")), body
    assert body["type"].startswith("/errors/")
    assert isinstance(body["title"], str) and body["title"]
    assert body["status"] == 404
    assert isinstance(body["detail"], str)
    assert body["instance"] == f"/v1/tasks/{missing_id}"
    assert isinstance(body["correlation_id"], str) and body["correlation_id"]


# --- AC-10.3 ----------------------------------------------------------------

# NFR-02
def test_fr10_500_body_leaks_no_internals(db_file):
    forbidden_tokens = "SELECT,Traceback,.py,/Users"
    expected_status = "500"
    resp = _get_500()
    result_status = resp.status_code
    _, result_detail = _problem(resp)
    # AC10.1-status
    assert result_status == int(expected_status), resp.text
    # AC10.3-no-internals
    assert all(tok not in result_detail for tok in forbidden_tokens.split(",")), result_detail
    assert all(tok not in resp.text for tok in forbidden_tokens.split(",")), resp.text
    assert resp.headers.get("content-type", "").startswith(PROBLEM_JSON)


# --- AC-10.4 ----------------------------------------------------------------

# NFR-10
def test_fr10_correlation_id_header_matches_log(client, caplog):
    expected_header = "X-Correlation-Id"
    caplog.set_level(logging.DEBUG)
    resp = client.get(f"/v1/tasks/{uuid.uuid4()}", headers=_headers("read"))  # trigger="unknown task id"
    assert middleware.CORRELATION_HEADER == expected_header
    result_header_value = resp.headers.get(expected_header)
    assert result_header_value, dict(resp.headers)
    logged = _logged_correlation_ids(caplog)
    result_logged_id = result_header_value if result_header_value in logged else (logged[-1] if logged else None)
    result_body_correlation_id = resp.json().get("correlation_id")
    # AC10.4-header-eq-log
    assert result_header_value == result_logged_id
    # AC10.4-body-eq-header
    assert result_body_correlation_id == result_header_value


# --- AC-10.5 (8 sub-rows) ---------------------------------------------------

# NFR-10
def test_fr10_status_to_problem_type_mapping(client):
    expected_status = "422"
    expected_type = "/errors/validation"
    resp = client.post("/v1/tasks", json={}, headers=_headers("write"))  # trigger="invalid body"
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")
    assert errors.ValidationFailed("x").type_uri == expected_type


def test_fr10_mapping_401_unauthenticated(client):
    expected_status = "401"
    expected_type = "/errors/unauthenticated"
    resp = client.get("/v1/tasks")  # trigger="missing X-API-Key"
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")


def test_fr10_mapping_403_forbidden(client):
    expected_status = "403"
    expected_type = "/errors/forbidden"
    resp = client.post(
        "/v1/tasks", json={"name": "t-403", "command": "echo hi"}, headers=_headers("read")
    )  # trigger="read key on POST /v1/tasks"
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")


def test_fr10_mapping_404_not_found(client):
    expected_status = "404"
    expected_type = "/errors/not-found"
    resp = client.get(f"/v1/tasks/{uuid.uuid4()}", headers=_headers("read"))  # trigger="unknown task id"
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")


def test_fr10_mapping_409_conflict(client):
    expected_status = "409"
    expected_type = "/errors/conflict"
    payload = {"name": "dup-name", "command": "echo hi"}
    first = client.post("/v1/tasks", json=payload, headers=_headers("write"))
    assert first.status_code == 201, first.text
    resp = client.post("/v1/tasks", json=payload, headers=_headers("write"))  # trigger="duplicate task name"
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")


def test_fr10_mapping_429_rate_limited(tmp_path, monkeypatch):
    expected_status = "429"
    expected_type = "/errors/rate-limited"
    _prepare_db(tmp_path, monkeypatch, burst="1")
    with TestClient(create_app()) as test_client:
        first = test_client.get("/v1/tasks", headers=_headers("read"))
        assert first.status_code == 200, first.text
        resp = test_client.get("/v1/tasks", headers=_headers("read"))  # trigger="burst exceeded"
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")
    assert resp.headers.get("Retry-After")


def test_fr10_mapping_503_not_ready(tmp_path, monkeypatch):
    expected_status = "503"
    expected_type = "/errors/not-ready"
    # trigger="database unavailable on /readyz": SQLite file in a missing directory.
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{tmp_path / 'missing-dir' / 'taskq.db'}")
    with TestClient(create_app()) as test_client:
        resp = test_client.get("/readyz")
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")


def test_fr10_mapping_500_internal(db_file):
    expected_status = "500"
    expected_type = "/errors/internal"
    app = _app_raising(lambda: RuntimeError("boom"))  # trigger="injected unhandled RuntimeError"
    with TestClient(app, raise_server_exceptions=False) as test_client:
        resp = test_client.get("/__fault")
    _assert_mapping(resp, expected_status, expected_type)
    result_problem_type, _ = _problem(resp)
    result_content_type = resp.headers.get("content-type", "")
    # AC10.5-type
    assert result_problem_type == expected_type
    # AC10.5-ctype
    assert result_content_type.startswith("application/problem+json")


# --- AC-10.6 ----------------------------------------------------------------

# NFR-03
def test_fr10_timeout_is_200_and_cancel_not_500(tmp_path, monkeypatch):
    expected_http_status = "200"
    expected_task_status = "timeout"
    # subprocess_mode="in_process": the app runs in this process via TestClient.
    db = _prepare_db(tmp_path, monkeypatch)
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.5")
    task_id = str(uuid.uuid4())
    _sql(
        db,
        "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, "sleep 30", "t-timeout", "pending", BASE_TIME.isoformat()),
    )
    with TestClient(create_app()) as test_client:
        run = test_client.post(f"/v1/tasks/{task_id}/run", headers=_headers("write"))
        assert run.status_code == 202, run.text
        deadline = time.monotonic() + WAIT_SECONDS
        resp = test_client.get(f"/v1/tasks/{task_id}", headers=_headers("read"))
        while resp.json().get("status") not in TERMINAL_STATES and time.monotonic() < deadline:
            time.sleep(0.05)
            resp = test_client.get(f"/v1/tasks/{task_id}", headers=_headers("read"))
    result_http_status = resp.status_code
    result_task_status = resp.json().get("status")
    # AC10.6-http
    assert result_http_status == int(expected_http_status), resp.text
    # AC10.6-task
    assert result_task_status == expected_task_status
    assert not resp.headers.get("content-type", "").startswith(PROBLEM_JSON)


# NFR-03
def test_fr10_cancelled_error_not_converted_to_500(db_file):
    expected_converted_to_500 = "False"
    app = _app_raising(asyncio.CancelledError)  # trigger="CancelledError raised inside handler"

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            return await async_client.get("/__fault")

    try:
        resp = asyncio.run(call())
    except asyncio.CancelledError:
        result_converted_to_500_text = "False"
    else:
        result_converted_to_500_text = str(resp.status_code == 500)
    # AC10.6-cancel
    assert result_converted_to_500_text == expected_converted_to_500


# --- SEC T-10 / T-12 / T-13 -------------------------------------------------

def test_sec_t10_correlation_id_in_header_body_and_log(client, caplog):
    expected_header = "X-Correlation-Id"
    caplog.set_level(logging.DEBUG)
    resp = client.get(f"/v1/tasks/{uuid.uuid4()}", headers=_headers("read"))  # trigger="unknown task id"
    result_header_value = resp.headers.get(expected_header)
    assert result_header_value, dict(resp.headers)
    result_body_correlation_id = resp.json().get("correlation_id")
    logged = _logged_correlation_ids(caplog)
    result_logged_id = result_header_value if result_header_value in logged else (logged[-1] if logged else None)
    # AC10.4-header-eq-log
    assert result_header_value == result_logged_id
    # AC10.4-body-eq-header
    assert result_body_correlation_id == result_header_value
    # Distinct requests get distinct correlation ids.
    second = client.get(f"/v1/tasks/{uuid.uuid4()}", headers=_headers("read"))
    assert second.headers.get(expected_header) not in (None, result_header_value)


# NFR-02
def test_sec_t12_500_body_has_no_internal_details(db_file, caplog):
    forbidden_tokens = "SELECT,Traceback,.py,/Users"
    expected_status = "500"
    caplog.set_level(logging.DEBUG)
    resp = _get_500()
    result_status = resp.status_code
    _, result_detail = _problem(resp)
    # AC10.1-status
    assert result_status == int(expected_status), resp.text
    # AC10.3-no-internals
    assert all(tok not in result_detail for tok in forbidden_tokens.split(",")), result_detail
    body = resp.json()
    assert body.get("type") == "/errors/internal"
    for field_value in body.values():
        assert all(tok not in str(field_value) for tok in forbidden_tokens.split(",")), body
    # The failure is still recorded server-side, tagged with the correlation id.
    assert body.get("correlation_id") in _logged_correlation_ids(caplog)


def test_sec_t13_cors_default_denies_all_origins(tmp_path, monkeypatch):
    request_origin = "https://evil.example"
    endpoint = "/healthz"
    _prepare_db(tmp_path, monkeypatch)
    monkeypatch.setenv("TASKQ_CORS_ORIGINS", "")
    with TestClient(create_app()) as test_client:
        resp = test_client.get(endpoint, headers={"Origin": request_origin})
        preflight = test_client.options(
            endpoint, headers={"Origin": request_origin, "Access-Control-Request-Method": "GET"}
        )
    result_acao_header = resp.headers.get("access-control-allow-origin", "")
    # T13-no-acao
    assert result_acao_header == ""
    assert preflight.headers.get("access-control-allow-origin", "") == ""

    # Positive control: an origin listed in TASKQ_CORS_ORIGINS is allowed, so the
    # denial above is a decision of the CORS policy, not a missing middleware.
    allowed_origin = "https://ok.example"
    monkeypatch.setenv("TASKQ_CORS_ORIGINS", allowed_origin)
    with TestClient(create_app()) as test_client:
        allowed = test_client.get(endpoint, headers={"Origin": allowed_origin})
        denied = test_client.get(endpoint, headers={"Origin": request_origin})
    assert allowed.headers.get("access-control-allow-origin", "") == allowed_origin
    assert denied.headers.get("access-control-allow-origin", "") == ""

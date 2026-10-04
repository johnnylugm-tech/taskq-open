"""NFR-10 — integration suite driven through ``httpx.AsyncClient`` + ``ASGITransport``.

Every case talks to the real ASGI app over HTTP (no handler is called
directly), against a SQLite file built by the real Alembic migrations, with
API keys issued through the real ``key create`` CLI (SPEC.md L259-264).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import io
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api import cli  # noqa: E402
from taskq_api.app import create_app  # noqa: E402
from taskq_api.repository import migration_state  # noqa: E402

PROBLEM_JSON = "application/problem+json"


def async_test(test):
    """Run an ``async def`` test on its own event loop.

    Needs no pytest plugin, so the suite also runs with plugin autoload off
    (the mutation-testing sandbox sets ``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1``).
    """

    @functools.wraps(test)
    def runner(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))

    return runner


class FakeClock:
    """Manually advanced clock for deterministic rate-limit recovery."""

    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current


def _issue_key(scope: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["key", "create", "--scope", scope]) == 0
    return out.getvalue().strip()


class Service:
    """A running app, its database file and one issued key per scope."""

    def __init__(self, db_file: Path, client: httpx.AsyncClient, keys: dict[str, str], clock: FakeClock) -> None:
        self.db_file = db_file
        self.client = client
        self.keys = keys
        self.clock = clock

    def headers(self, scope: str) -> dict[str, str]:
        return {"X-API-Key": self.keys[scope]}

    async def create(self, name: str, command: str = "echo hi") -> httpx.Response:
        return await self.client.post(
            "/v1/tasks", json={"name": name, "command": command}, headers=self.headers("write")
        )

    def sql(self, statement: str) -> list[tuple]:
        conn = sqlite3.connect(self.db_file)
        try:
            return conn.execute(statement).fetchall()
        finally:
            conn.close()


@contextlib.asynccontextmanager
async def _running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str):
    db_file = tmp_path / "taskq.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("TASKQ_DB_URL", db_url)
    monkeypatch.setenv("TASKQ_RATE_BURST", "100000")
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", "100000")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    migration_state.upgrade(db_url)
    keys = {scope: _issue_key(scope) for scope in ("read", "write", "admin")}
    app = create_app()
    clock = FakeClock()
    app.state.clock = clock
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield Service(db_file, client, keys, clock)


@pytest.fixture
def running(tmp_path, monkeypatch):
    return lambda **env: _running(tmp_path, monkeypatch, **env)


def _assert_problem(resp: httpx.Response, status: int, error_type: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith(PROBLEM_JSON)
    body = resp.json()
    assert body["status"] == status
    assert body["type"].endswith(f"/errors/{error_type}")


async def _wait_for_status(svc: Service, task_id: str, expected: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        resp = await svc.client.get(f"/v1/tasks/{task_id}", headers=svc.headers("read"))
        body = resp.json()
        if body["status"] == expected:
            return body
        assert time.monotonic() < deadline, body
        await asyncio.sleep(0.05)


@async_test
async def test_nfr10_crud_chain_create_get_list_delete(running):
    async with running() as svc:
        created = await svc.create("alpha")
        assert created.status_code == 201
        task_id = created.json()["id"]

        got = await svc.client.get(f"/v1/tasks/{task_id}", headers=svc.headers("read"))
        assert got.status_code == 200
        assert got.json()["name"] == "alpha"
        assert got.json()["status"] == "pending"

        await svc.create("beta")
        listed = await svc.client.get("/v1/tasks", headers=svc.headers("read"))
        assert listed.status_code == 200
        assert sorted(item["name"] for item in listed.json()["items"]) == ["alpha", "beta"]

        deleted = await svc.client.delete(f"/v1/tasks/{task_id}", headers=svc.headers("admin"))
        assert deleted.status_code == 204
        gone = await svc.client.get(f"/v1/tasks/{task_id}", headers=svc.headers("read"))
        _assert_problem(gone, 404, "not-found")


@async_test
async def test_nfr10_pagination_walks_every_task(running):
    async with running() as svc:
        for index in range(5):
            assert (await svc.create(f"page-{index}")).status_code == 201
        seen: list[str] = []
        params: dict[str, str] = {"limit": "2"}
        while True:
            body = (await svc.client.get("/v1/tasks", params=params, headers=svc.headers("read"))).json()
            seen.extend(item["name"] for item in body["items"])
            if not body["next_cursor"]:
                break
            params["cursor"] = body["next_cursor"]
        assert sorted(seen) == [f"page-{index}" for index in range(5)]


@async_test
async def test_nfr10_error_401_without_key_and_with_unknown_key(running):
    async with running() as svc:
        missing = await svc.client.get("/v1/tasks")
        assert missing.status_code == 401
        _assert_problem(missing, 401, "unauthenticated")
        unknown = await svc.client.get("/v1/tasks", headers={"X-API-Key": "sk-not-a-real-key"})
        assert unknown.status_code == 401
        _assert_problem(unknown, 401, "unauthenticated")


@async_test
async def test_nfr10_error_403_when_scope_is_too_low(running):
    async with running() as svc:
        task_id = (await svc.create("protected")).json()["id"]
        denied = await svc.client.delete(f"/v1/tasks/{task_id}", headers=svc.headers("write"))
        _assert_problem(denied, 403, "forbidden")
        assert task_id not in denied.text
        still_there = await svc.client.get(f"/v1/tasks/{task_id}", headers=svc.headers("read"))
        assert still_there.status_code == 200
        read_cannot_create = await svc.client.post(
            "/v1/tasks", json={"name": "x", "command": "echo"}, headers=svc.headers("read")
        )
        _assert_problem(read_cannot_create, 403, "forbidden")


@async_test
async def test_nfr10_error_404_for_unknown_task_and_run_history(running):
    async with running() as svc:
        unknown = "00000000-0000-0000-0000-000000000000"
        got = await svc.client.get(f"/v1/tasks/{unknown}", headers=svc.headers("read"))
        history = await svc.client.get(f"/v1/tasks/{unknown}/runs", headers=svc.headers("read"))
        started = await svc.client.post(f"/v1/tasks/{unknown}/run", headers=svc.headers("write"))
        assert [got.status_code, history.status_code, started.status_code] == [404, 404, 404]
        for resp in (got, history, started):
            _assert_problem(resp, 404, "not-found")


@async_test
async def test_nfr10_error_409_on_duplicate_name(running):
    async with running() as svc:
        assert (await svc.create("dup")).status_code == 201
        _assert_problem(await svc.create("dup"), 409, "conflict")
        assert len(svc.sql("SELECT id FROM tasks WHERE name = 'dup'")) == 1


@async_test
async def test_nfr10_error_422_on_invalid_body(running):
    async with running() as svc:
        resp = await svc.client.post("/v1/tasks", json={"name": "only-name"}, headers=svc.headers("write"))
        _assert_problem(resp, 422, "validation")
        assert svc.sql("SELECT id FROM tasks") == []


@async_test
async def test_nfr10_error_429_then_recovery_after_refill(running):
    async with running(TASKQ_RATE_BURST="2", TASKQ_RATE_PER_SEC="1") as svc:
        headers = svc.headers("read")
        assert (await svc.client.get("/v1/tasks", headers=headers)).status_code == 200
        assert (await svc.client.get("/v1/tasks", headers=headers)).status_code == 200
        limited = await svc.client.get("/v1/tasks", headers=headers)
        _assert_problem(limited, 429, "rate-limited")
        assert int(limited.headers["Retry-After"]) >= 1
        health = await svc.client.get("/healthz")
        assert health.status_code == 200

        svc.clock.current += timedelta(seconds=5)
        recovered = await svc.client.get("/v1/tasks", headers=headers)
        assert recovered.status_code == 200

        metrics = await svc.client.get("/v1/metrics", headers=svc.headers("admin"))
        assert metrics.status_code == 200
        assert metrics.json()["rate_limit_rejections"] >= 1


@async_test
async def test_nfr10_error_503_when_migration_is_behind(running):
    async with running() as svc:
        assert (await svc.client.get("/readyz")).status_code == 200
        migration_state.downgrade(f"sqlite:///{svc.db_file}", "base")
        not_ready = await svc.client.get("/readyz")
        _assert_problem(not_ready, 503, "not-ready")
        assert "sqlite" not in not_ready.text


@async_test
async def test_nfr10_migration_round_trip_keeps_results(running):
    async with running() as svc:
        db_url = f"sqlite:///{svc.db_file}"
        task_id = (await svc.create("migrate-me", "echo round-trip")).json()["id"]
        assert (await svc.client.post(f"/v1/tasks/{task_id}/run", headers=svc.headers("write"))).status_code == 202
        await _wait_for_status(svc, task_id, "done")
        before = svc.sql("SELECT exit_code, stdout_tail, duration_ms IS NOT NULL FROM task_results")
        assert before and before[0][0] == 0 and "round-trip" in before[0][1]

        migration_state.downgrade(db_url, "v2")
        assert svc.sql("SELECT result_json FROM tasks WHERE id = '%s'" % task_id)[0][0]
        migration_state.upgrade(db_url)
        after = svc.sql("SELECT exit_code, stdout_tail, duration_ms IS NOT NULL FROM task_results")
        assert after == before
        assert migration_state.current_revision(db_url) == "v3"


@async_test
async def test_nfr10_run_lifecycle_and_history(running):
    async with running() as svc:
        task_id = (await svc.create("runner", "echo from-run")).json()["id"]
        accepted = await svc.client.post(f"/v1/tasks/{task_id}/run", headers=svc.headers("write"))
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]
        await _wait_for_status(svc, task_id, "done")
        runs = (await svc.client.get(f"/v1/tasks/{task_id}/runs", headers=svc.headers("read"))).json()["items"]
        assert [run["run_id"] for run in runs] == [run_id]
        assert runs[0]["exit_code"] == 0
        assert "from-run" in runs[0]["stdout_tail"]


@async_test
async def test_nfr10_failed_run_and_timeout_run(running):
    async with running(TASKQ_TASK_TIMEOUT="0.5") as svc:
        failing = (await svc.create("fails", "sh -c 'exit 3'")).json()["id"]
        await svc.client.post(f"/v1/tasks/{failing}/run", headers=svc.headers("write"))
        await _wait_for_status(svc, failing, "failed")
        runs = (await svc.client.get(f"/v1/tasks/{failing}/runs", headers=svc.headers("read"))).json()["items"]
        assert runs[0]["exit_code"] == 3

        slow = (await svc.create("slow", "sleep 30")).json()["id"]
        await svc.client.post(f"/v1/tasks/{slow}/run", headers=svc.headers("write"))
        await _wait_for_status(svc, slow, "timeout")


@async_test
async def test_nfr10_graceful_drain_marks_unfinished_run_interrupted(tmp_path, monkeypatch):
    async with _running(tmp_path, monkeypatch, TASKQ_DRAIN_TIMEOUT="0.3", TASKQ_TASK_TIMEOUT="60") as svc:
        task_id = (await svc.create("drained", "sleep 30")).json()["id"]
        assert (await svc.client.post(f"/v1/tasks/{task_id}/run", headers=svc.headers("write"))).status_code == 202
        await _wait_for_status(svc, task_id, "running")
        started = time.monotonic()
    assert time.monotonic() - started < 10
    assert svc.sql(f"SELECT status FROM tasks WHERE id = '{task_id}'") == [("interrupted",)]


@async_test
async def test_nfr10_metrics_reports_counts_without_db_url(running):
    async with running() as svc:
        await svc.create("counted")
        resp = await svc.client.get("/v1/metrics", headers=svc.headers("admin"))
        assert resp.status_code == 200
        assert "sqlite" not in resp.text
        assert "taskq.db" not in resp.text
        denied = await svc.client.get("/v1/metrics", headers=svc.headers("read"))
        _assert_problem(denied, 403, "forbidden")


@async_test
async def test_nfr10_health_endpoints_need_no_key(running):
    async with running() as svc:
        assert (await svc.client.get("/healthz")).json() == {"status": "ok"}
        assert (await svc.client.get("/readyz")).json() == {"status": "ready"}


@async_test
async def test_nfr10_cors_allows_only_configured_origin(running):
    async with running(TASKQ_CORS_ORIGINS="https://ok.example") as svc:
        allowed = await svc.client.get("/healthz", headers={"Origin": "https://ok.example"})
        assert allowed.headers.get("access-control-allow-origin") == "https://ok.example"
        denied = await svc.client.get("/healthz", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in denied.headers


@async_test
async def test_nfr10_concurrency_cap_queues_and_drain_interrupts_queued_run(tmp_path, monkeypatch):
    async with _running(
        tmp_path, monkeypatch, TASKQ_MAX_CONCURRENT="1", TASKQ_DRAIN_TIMEOUT="0.3", TASKQ_TASK_TIMEOUT="60"
    ) as svc:
        first = (await svc.create("first", "sleep 30")).json()["id"]
        second = (await svc.create("second", "sleep 30")).json()["id"]
        for task_id in (first, second):
            accepted = await svc.client.post(f"/v1/tasks/{task_id}/run", headers=svc.headers("write"))
            assert accepted.status_code == 202
        await _wait_for_status(svc, first, "running")
        await asyncio.sleep(0.3)
        queued = await svc.client.get(f"/v1/tasks/{second}", headers=svc.headers("read"))
        assert queued.json()["status"] == "pending"
    statuses = dict(svc.sql("SELECT id, status FROM tasks"))
    assert statuses[first] == "interrupted"
    assert statuses[second] == "interrupted"

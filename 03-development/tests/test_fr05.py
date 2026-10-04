"""FR-05 — Rate limiting (per-token token bucket).

Covers TEST_SPEC.md FR-05 rows 1-7 (AC-5.1 .. AC-5.4, NP-03, NP-13, SEC T-04).

Test harness contract:
- HTTP cases run in-process against `taskq_api.app.create_app()` with
  `TASKQ_DB_URL` pointing at a fresh SQLite file per test
  (state_mode="isolate_per_test"); the schema comes from
  `taskq_api.models.base.Base.metadata` (which must include `rate_buckets`:
  `key_id` FK -> api_keys.id, `tokens`, `updated_at`).
- `create_app()` reads `TASKQ_RATE_BURST` / `TASKQ_RATE_PER_SEC` and stores
  the rate-limit clock on `app.state.clock`; the clock is any object with
  `now() -> datetime` (the `taskq_api.service.ratelimit.Clock` protocol).
  Tests replace it with a frozen `FakeClock` (clock_mode="fake"; SAD 7.2 allows
  mocking the clock only), so refill happens solely through `advance()`.
- `taskq_api.service.ratelimit.consume(uow, key_id, *, capacity, rate_per_sec,
  now) -> RateDecision` performs one read-modify-write of the caller's bucket
  through `uow.rate_buckets` (`taskq_api.repository.rate_buckets`);
  `RateDecision.allowed: bool`, `RateDecision.retry_after_s: int`.
- Over-limit `/v1` requests get 429 application/problem+json with
  type `/errors/rate-limited` and an integer-seconds `Retry-After` header.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Delete, Insert, Select, Update, create_engine, event
from sqlalchemy.dialects import postgresql

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taskq_api.app import create_app  # noqa: E402
from taskq_api.config import load_settings  # noqa: E402
from taskq_api.models.base import Base  # noqa: E402
from taskq_api.repository import rate_buckets  # noqa: E402,F401
from taskq_api.repository.session import build_engine, uow_factory  # noqa: E402
from taskq_api.service import ratelimit  # noqa: E402

PROBLEM_JSON = "application/problem+json"
KEY_ID = "11111111-1111-1111-1111-111111111111"
KEY = "sk-test-ratelimit-0123456789"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
LIMITED_ENDPOINT = "/v1/tasks"


class FakeClock:
    """Frozen clock; time moves only through ``advance``."""

    def __init__(self, start: datetime = BASE_TIME) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _sql(db_file: Path, statement: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _seed_key(db_file: Path, key_id: str, plaintext: str, scope: str) -> None:
    _sql(
        db_file,
        "INSERT INTO api_keys (id, key_hash, scope, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
        (key_id, hashlib.sha256(plaintext.encode()).hexdigest(), scope, BASE_TIME.isoformat(), None),
    )


def _make_db(tmp_path: Path, monkeypatch, burst: str, per_sec: str) -> Path:
    path = tmp_path / "taskq.db"
    monkeypatch.setenv("TASKQ_DB_URL", f"sqlite:///{path}")
    monkeypatch.setenv("TASKQ_RATE_BURST", burst)
    monkeypatch.setenv("TASKQ_RATE_PER_SEC", per_sec)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    _seed_key(path, KEY_ID, KEY, "admin")
    return path


def _client(clock: FakeClock) -> TestClient:
    app = create_app()
    app.state.clock = clock
    return TestClient(app)


def _send(client: TestClient, endpoint: str = LIMITED_ENDPOINT) -> httpx.Response:
    return client.get(endpoint, headers={"X-API-Key": KEY})


def _burst_then_one_more(client: TestClient, requests_sent: int) -> tuple[list[int], httpx.Response]:
    statuses = [_send(client).status_code for _ in range(requests_sent - 1)]
    return statuses, _send(client)


# --- AC-5.1 -----------------------------------------------------------------

def test_fr05_bucket_trigger_and_recovery(tmp_path, monkeypatch):
    TASKQ_RATE_BURST = "20"
    TASKQ_RATE_PER_SEC = "5.0"
    requests_sent = "21"
    advance_seconds = "1"
    _make_db(tmp_path, monkeypatch, TASKQ_RATE_BURST, TASKQ_RATE_PER_SEC)
    clock = FakeClock()
    with _client(clock) as client:
        statuses, after_burst = _burst_then_one_more(client, int(requests_sent))
        result_ok_count = statuses.count(200)
        result_status_after_burst = after_burst.status_code
        clock.advance(float(advance_seconds))
        result_status_after_refill = _send(client).status_code
    # AC5.1-burst-ok
    assert result_ok_count == int(TASKQ_RATE_BURST), statuses
    # AC5.1-then-429
    assert result_status_after_burst == 429
    # AC5.1-recovers
    assert result_status_after_refill == 200


def test_fr05_exactly_burst_requests_all_succeed(tmp_path, monkeypatch):
    TASKQ_RATE_BURST = "20"
    requests_sent = "20"
    _make_db(tmp_path, monkeypatch, TASKQ_RATE_BURST, "5.0")
    with _client(FakeClock()) as client:
        statuses = [_send(client).status_code for _ in range(int(requests_sent))]
        # The bucket is now empty: the limiter is active, not merely absent.
        next_status = _send(client).status_code
    result_ok_count = statuses.count(200)
    # AC5.1-exact
    assert result_ok_count == int(requests_sent), statuses
    assert next_status == 429


# --- AC-5.2 -----------------------------------------------------------------

def test_fr05_over_limit_returns_429_retry_after(tmp_path, monkeypatch):
    TASKQ_RATE_BURST = "20"
    requests_sent = "21"
    expected_status = "429"
    # Frozen clock: no refill can sneak in while the 21 requests are sent.
    _make_db(tmp_path, monkeypatch, TASKQ_RATE_BURST, "5.0")
    with _client(FakeClock()) as client:
        _, after_burst = _burst_then_one_more(client, int(requests_sent))
    result_status_after_burst = after_burst.status_code
    result_retry_after_s = int(after_burst.headers["Retry-After"])
    assert after_burst.headers.get("content-type", "").startswith(PROBLEM_JSON)
    result_problem_type = after_burst.json()["type"]
    # AC5.2-status
    assert result_status_after_burst == int(expected_status), after_burst.text
    # AC5.2-retry-after
    assert result_retry_after_s >= 1
    # AC5.2-problem
    assert result_problem_type == "/errors/rate-limited"


# --- AC-5.1 / AC-5.2 (per-token isolation, refill rate) ----------------------

def test_fr05_bucket_is_per_token(tmp_path, monkeypatch):
    other_key_id = "22222222-2222-2222-2222-222222222222"
    other_key = "sk-test-ratelimit-other-0123456789"
    db_file = _make_db(tmp_path, monkeypatch, "3", "1.0")
    _seed_key(db_file, other_key_id, other_key, "admin")
    with _client(FakeClock()) as client:
        drained = [_send(client).status_code for _ in range(3)]
        exhausted = _send(client).status_code
        other = client.get(LIMITED_ENDPOINT, headers={"X-API-Key": other_key}).status_code
    assert drained == [200, 200, 200]
    assert exhausted == 429
    # A bucket shared by all tokens would answer 429 here.
    assert other == 200


def test_fr05_refill_rate_and_retry_after_follow_rate_per_sec(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch, "4", "2.0")
    clock = FakeClock()
    with _client(clock) as client:
        assert [_send(client).status_code for _ in range(4)] == [200] * 4
        empty = _send(client)
        clock.advance(1.0)  # 1s * 2.0/s = exactly 2 tokens
        after = [_send(client).status_code for _ in range(3)]
    # one token needs 1 / 2.0s = 0.5s, rounded up to whole seconds
    assert empty.status_code == 429
    assert int(empty.headers["Retry-After"]) == 1
    assert after == [200, 200, 429]


# NFR-02
def test_sec_t04_burst_exceeded_returns_429(tmp_path, monkeypatch):
    TASKQ_RATE_BURST = "20"
    requests_sent = "21"
    expected_status = "429"
    _make_db(tmp_path, monkeypatch, TASKQ_RATE_BURST, "5.0")
    with _client(FakeClock()) as client:
        _, after_burst = _burst_then_one_more(client, int(requests_sent))
    result_status_after_burst = after_burst.status_code
    result_retry_after_s = int(after_burst.headers["Retry-After"])
    # AC5.2-status
    assert result_status_after_burst == int(expected_status), after_burst.text
    # AC5.2-retry-after
    assert result_retry_after_s >= 1


# --- AC-5.3 -----------------------------------------------------------------

def test_fr05_bucket_update_single_txn_row_lock(tmp_path, monkeypatch):
    dialect = "postgresql"
    expected_for_update = "True"
    _make_db(tmp_path, monkeypatch, "20", "5.0")
    engine = build_engine(load_settings())
    make_uow = uow_factory(engine)
    try:
        # First consume creates the bucket row; the measured one updates it.
        with make_uow() as uow:
            ratelimit.consume(uow, KEY_ID, capacity=20, rate_per_sec=5.0, now=BASE_TIME)

        trace: list[tuple[str, object]] = []

        def on_begin(conn):
            trace.append(("begin", None))

        def on_commit(conn):
            trace.append(("commit", None))

        def on_execute(conn, clauseelement, multiparams, params, execution_options):
            trace.append(("exec", clauseelement))

        event.listen(engine, "begin", on_begin)
        event.listen(engine, "commit", on_commit)
        event.listen(engine, "before_execute", on_execute)
        with make_uow() as uow:
            decision = ratelimit.consume(
                uow, KEY_ID, capacity=20, rate_per_sec=5.0, now=BASE_TIME + timedelta(seconds=1)
            )
        event.remove(engine, "begin", on_begin)
        event.remove(engine, "commit", on_commit)
        event.remove(engine, "before_execute", on_execute)
    finally:
        engine.dispose()

    assert decision.allowed is True

    def touches_buckets(clause: object) -> bool:
        return "rate_buckets" in str(clause)

    bucket_reads = [i for i, (kind, c) in enumerate(trace) if kind == "exec" and isinstance(c, Select) and touches_buckets(c)]
    bucket_writes = [
        i for i, (kind, c) in enumerate(trace)
        if kind == "exec" and isinstance(c, (Update, Insert, Delete)) and touches_buckets(c)
    ]
    begins = [i for i, (kind, _) in enumerate(trace) if kind == "begin"]
    commits = [i for i, (kind, _) in enumerate(trace) if kind == "commit"]
    assert bucket_reads, trace
    assert bucket_writes, trace

    pg = postgresql.dialect() if dialect == "postgresql" else None
    result_select_has_for_update = all(
        "FOR UPDATE" in str(trace[i][1].compile(dialect=pg)) for i in bucket_reads
    )
    result_read_and_write_in_one_txn = (
        len(begins) == 1
        and len(commits) == 1
        and begins[0] < min(bucket_reads) < max(bucket_writes) < commits[0]
    )
    # AC5.3-for-update
    assert expected_for_update == "True"
    assert result_select_has_for_update, trace
    # AC5.3-one-txn
    assert result_read_and_write_in_one_txn, trace


# NP-13 forced integration case (SAD: repository.rate_buckets): 40 concurrent
# requests through the ASGI app (httpx.AsyncClient + ASGITransport, NFR-10);
# sync dependencies run in the threadpool, so bucket updates really race.
# NFR-10
def test_fr05_concurrent_requests_never_overdraw_bucket(tmp_path, monkeypatch):
    TASKQ_RATE_BURST = "20"
    TASKQ_RATE_PER_SEC = "5.0"
    concurrent_requests = "40"
    expected_ok_count = "20"
    db_file = _make_db(tmp_path, monkeypatch, TASKQ_RATE_BURST, TASKQ_RATE_PER_SEC)
    app = create_app()
    app.state.clock = FakeClock()

    async def fire() -> list[int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *(client.get(LIMITED_ENDPOINT, headers={"X-API-Key": KEY}) for _ in range(int(concurrent_requests)))
            )
        return [r.status_code for r in responses]

    statuses = asyncio.run(fire())
    result_ok_count = statuses.count(200)
    # Every request is decided (admitted or limited); none crashes on the race.
    assert set(statuses) <= {200, 429}, statuses
    tokens_rows = _sql(db_file, "SELECT tokens FROM rate_buckets WHERE key_id = ?", (KEY_ID,))
    assert len(tokens_rows) == 1, tokens_rows
    result_tokens_after = float(tokens_rows[0][0])
    # NP13-no-overdraw
    assert result_ok_count == int(expected_ok_count), statuses
    # NP13-tokens-nonneg
    assert result_tokens_after >= 0


# --- AC-5.4 -----------------------------------------------------------------

def test_fr05_health_endpoints_not_rate_limited(tmp_path, monkeypatch):
    TASKQ_RATE_BURST = "20"
    endpoints = "/healthz,/readyz"
    requests_sent = "50"
    _make_db(tmp_path, monkeypatch, TASKQ_RATE_BURST, "5.0")
    with _client(FakeClock()) as client:
        # Exhaust the caller's bucket first so the limiter is demonstrably active.
        drained = [_send(client).status_code for _ in range(int(TASKQ_RATE_BURST) + 1)]
        assert drained[-1] == 429, drained
        health_statuses = [
            _send(client, endpoint).status_code
            for endpoint in endpoints.split(",")
            for _ in range(int(requests_sent))
        ]
    result_non_200_count = sum(1 for s in health_statuses if s != 200)
    # AC5.4-never-limited
    assert result_non_200_count == 0, health_statuses

# Specification Tracking Matrix — `taskq-api`

> Human-readable view only, not the SSOT. Canonical spec source: `SPEC.md` (project root). Requirements baseline: `01-requirements/SRS.md` (APPROVED). Authoritative status and scores: `build_traceability` scan / `quality_manifest.json`.

## Project Info
- Project Name: taskq-api
- Version: v1.0.0
- Created: 2026-10-04

## Specification Status

> **The Status column is machine-refreshed** — `advance-phase` overwrites each
> FR's Status from `build_traceability`'s live code/test scan (IN_PROGRESS once
> code/module exists, VERIFIED once code+test exist). The authoritative status is
> that scan / `quality_manifest.json`, NOT this hand-filled cell. Fill the
> semantic columns (Spec Description / Intent Class / Decision Framework / Notes);
> leave Status to refresh itself (a hand-edit is overwritten on the next advance).

| FR ID | Spec Description | Intent Class | Decision Framework | Status | Notes |
|-------|-----------------|--------------|-------------------|--------|-------|
| FR-01 | Task resource CRUD API under `/v1/tasks` (POST/GET/list/DELETE); cursor pagination, default limit 50 / max 200; 422 and 404 problem+json | Functional (API) | Integration tests via httpx ASGITransport (CRUD chain, 404, 422) | DRAFT | SPEC.md L79-91; SRS AC-1.1..1.8 |
| FR-02 | Task execution endpoint: `POST /v1/tasks/{id}/run` returns 202 + `run_id`; `create_subprocess_exec` without `shell=True`; state machine pending→running→done/failed/timeout; `task_results`; runs history newest first | Functional (execution) | Run-lifecycle and runs-history integration tests; grep gate for `shell=True` | DRAFT | SPEC.md L93-99; SRS AC-2.1..2.5 |
| FR-03 | API Key authentication via `X-API-Key`; SHA-256 hashed storage; `hmac.compare_digest`; `key create` CLI prints plaintext once; revoked keys invalid; health endpoints exempt | Security | 401 integration test; DB inspection test; CLI test | DRAFT | SPEC.md L101-107; SRS AC-3.1..3.5 |
| FR-04 | Scope authorization read<write<admin; 403 without existence leak; single dependency for every `/v1` route | Security | 403 integration test; route-dependency assertion test | DRAFT | SPEC.md L109-113; SRS AC-4.1..4.4 |
| FR-05 | Per-token token bucket in DB with row-level lock in one transaction; 429 + `Retry-After`; health endpoints not limited | Reliability (traffic control) | Rate-limit trigger and recovery integration test; repository-level test | DRAFT | SPEC.md L115-120; SRS AC-5.1..5.4 |
| FR-06 | Persistence layer and transaction boundary: repository-only data access; one Session per request with commit/rollback; no string-built SQL; no N+1; pool config | Data integrity | `lint-imports`; transaction-boundary test; SQL statement-count test; SQL concatenation scan | DRAFT | SPEC.md L122-128; SRS AC-6.1..6.5 |
| FR-07 | Alembic v1/v2/v3 migrations, each with real downgrade; v3 moves `tasks.result_json` to `task_results` reversibly; offline SQL tested | Data integrity (migration) | Real SQLite-file round-trip test with per-column comparison; offline SQL test | DRAFT | SPEC.md L130-143; SRS AC-7.1..7.5 |
| FR-08 | Async executor: `asyncio.TaskGroup`, graceful drain to `TASKQ_DRAIN_TIMEOUT` marking `interrupted`, `TASKQ_MAX_CONCURRENT` cap, `wait_for` timeout with kill + wait, `CancelledError` propagates | Reliability (concurrency) | Graceful-drain, orphan-process, cancellation-propagation and concurrency tests | DRAFT | SPEC.md L145-150; SRS AC-8.1..8.4; see SRS Open Issue NFR-99.4 |
| FR-09 | Health and observability: `/healthz`; `/readyz` 200 only when DB up and migration at head, else 503; `/v1/metrics` (admin) | Operability | Health, readiness (DB down, migration behind head) and metrics integration tests | DRAFT | SPEC.md L152-160; SRS AC-9.1..9.5 |
| FR-10 | RFC 7807 error contract: all non-2xx as `application/problem+json` with required fields; no internal leakage; `correlation_id` in header and log; status mapping | Functional (error contract) | Per-error-code integration tests; 500 body leak inspection | DRAFT | SPEC.md L162-168, L331-347; SRS AC-10.1..10.6 |

## Update log

| Date | Change | By |
|------|--------|----|
| 2026-10-04 | Initial creation from SRS.md FR-01..FR-10 | Agent A |

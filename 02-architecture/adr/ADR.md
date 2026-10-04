# Architecture Decision Records (ADR) — taskq-api

Source of truth: `02-architecture/SAD.md` (section references below point to it). Python runtime verified from `.venv/bin/python --version`: 3.11.15.

Scope note (Requires Verification): the dispatch brief mentioned "Python stdlib-only", ThreadPoolExecutor, atomic write and circuit breaker. SAD.md specifies none of these. It specifies FastAPI, SQLAlchemy 2.x, Alembic, `asyncio.TaskGroup` and DB transactions. This ADR records what the SAD decides and does not invent decisions absent from it. See ADR-011.

## ADR-001: Python 3.11 with FastAPI and pydantic v2 as the service stack

### Status
Accepted

### Context
SPEC requires a REST task queue with automatic OpenAPI documentation (NFR-05) and request validation mapped to 422 (FR-01). Runtime in this repo is Python 3.11.15 (verified). `asyncio.TaskGroup` requires 3.11+. (SAD §1, §4)

### Decision
Single-process ASGI service on Python 3.11 using FastAPI and pydantic v2. This is not stdlib-only. FastAPI, pydantic, SQLAlchemy, Alembic and import-linter are third-party dependencies, pinned in `requirements.txt` and `requirements.lock` (NFR-07).

### Rationale
FastAPI gives async endpoints and generated OpenAPI; pydantic v2 gives validation that yields 422.

### Consequences
- Positive: OpenAPI for free; async fits subprocess orchestration.
- Negative: dependency and licensing surface (allowlist check via `pip-licenses`, SBOM at `08-config/SBOM.json`).

### Alternatives Considered
- Stdlib `http.server`: no OpenAPI, no validation, hand-rolled routing; rejected.
- Flask or Django: sync-first or heavier; weaker fit for TaskGroup-based execution.

## ADR-002: Strict four-layer architecture enforced by import-linter

### Status
Accepted

### Context
NFR-06 demands layering that is machine-checkable. NFR-11 limits directories to 15 files, files to 400 lines, handlers to 40 lines. (SAD §1, §2.1, §4)

### Decision
Layers `api > service > repository > models`, plus independence modules `config` and `errors`, `entry` as composition root (`app`, `__main__`, `cli`), and `migrations` standalone. Dependencies point downward only. `.importlinter` encodes the layers contract, independence of `config`/`errors`, and a forbidden contract that bars `sqlalchemy` from `api`, `service`, `config`, `errors`. `lint-imports` must exit 0.

### Rationale
A machine-checked DAG prevents god modules and cycles; business logic sinks into `service/`.

### Consequences
- Positive: layering regressions fail the build; small, separately testable communities.
- Negative: more files and indirection (UoW re-export through `service.uow`).
- Open item (Requires Verification): SPEC says "repository 以外的任何層" but `models` and `migrations` must import `sqlalchemy`; the forbidden contract therefore names `api`, `service`, `config`, `errors` as sources. To be confirmed with the SPEC owner.

### Alternatives Considered
- Convention only (code review): not verifiable; rejected.
- Flat package: violates NFR-11 and fails the god-module constraint.

## ADR-003: UnitOfWork as the only persistence handle visible to the business layer

### Status
Accepted

### Context
FR-06 requires per-request transactions with commit on success and rollback on failure; `service` must not import SQLAlchemy. (SAD §1, §2.4)

### Decision
`repository.session` defines a `UnitOfWork` context manager exposing `tasks`, `results`, `api_keys`, `rate_buckets`, `tags`, `stats`. `service.uow` re-exports the type. It commits on normal exit and rolls back on any exception including `CancelledError`, which is re-raised. Background tasks open their own UoW and never reuse a request session. `pool_size=TASKQ_DB_POOL_SIZE`, `pool_pre_ping=True`.

### Rationale
Transaction scope is explicit and testable, and the service layer stays ORM-agnostic.

### Consequences
- Positive: atomic request-level writes; no session leakage into `service`.
- Negative: `repository.session` is a high-risk module needing mutation and real-DB tests.

### Alternatives Considered
- Passing `Session` to services: breaks NFR-06 forbidden contract.
- Autocommit per statement: no atomicity across multi-row operations.

## ADR-004: SQLAlchemy 2.x with SQLite (dev/test) and PostgreSQL (production)

### Status
Accepted

### Context
Persistence must work on both engines (SPEC section 2). NFR-01 needs constant statement counts and indexed lookups. (SAD §1, §4)

### Decision
SQLAlchemy 2.x ORM for both engines. Relationship loading via `selectinload`/`joinedload`. Cursor pagination, no offset. Indexes on `tasks.name`, `tasks.status/created_at`. SQL statement count asserted constant by an event listener in tests.

### Rationale
One mapping for both engines, explicit transaction control.

### Consequences
- Positive: avoids N+1 queries; p95 targets (30 ms get, 80 ms list at 10k rows) measurable.
- Negative: row-lock clause is a no-op on SQLite, so rate-bucket correctness there relies on single-writer semantics (SAD §2.4 Logical Constraints).

### Alternatives Considered
- Raw `sqlite3`/`psycopg` SQL: duplicate dialect handling, higher injection risk.
- SQLite only: does not meet the production target.

## ADR-005: Alembic with three reversible revisions, including a data-moving v3

### Status
Accepted

### Context
FR-07 requires reversible migrations; v3 moves `result_json` into `task_results`. NFR-09 requires real-DB verification. (SAD §2.2, §3.4, §6 T-09)

### Decision
Revisions `v1_initial`, `v2_tags`, `v3_split_results`, each with a real `downgrade`. Revisions use `op` and lightweight table constructs and import nothing from `taskq_api` layers, so a revision's meaning never changes when models evolve. A failed revision rolls back its transaction. Tested by round-trip on a real SQLite file comparing every column.

### Rationale
Migrations must be frozen snapshots, independent of current ORM models.

### Consequences
- Positive: safe upgrade and downgrade; failure leaves DB at the previous revision.
- Negative: some table duplication in revisions; v3 is a high-risk module.

### Alternatives Considered
- `Base.metadata.create_all`: no history, no downgrade.
- Revisions importing ORM models: semantics drift as models change.

## ADR-006: Authorization decided in one dependency, before resource lookup

### Status
Accepted

### Context
FR-03, FR-04, FR-05; threats T-01, T-02, T-03. A 403 versus 404 difference would reveal task existence. (SAD §3.1, §6)

### Decision
Fixed pipeline order: authenticate (`X-API-Key`, SHA-256 hash compared with `hmac.compare_digest`, `revoked_at` honored; 401), authorize scope `read < write < admin` (403), rate-limit (429 with `Retry-After`), then touch the resource. Only `api.deps.require_scope` decides authorization; a test iterates `app.routes` to assert every `/v1` route declares it. 403 body is identical regardless of resource existence.

### Rationale
One enforcement point is auditable; ordering prevents existence leaks.

### Consequences
- Positive: 404 reachable only by callers with sufficient scope.
- Negative: authentication cost on every request (one indexed single-row statement).

### Alternatives Considered
- Per-handler checks: drift and omission risk.
- Authorize after lookup: leaks existence.

## ADR-007: Database-backed token-bucket rate limiting

### Status
Accepted

### Context
FR-05 and T-04 require per-token rate limiting with `Retry-After`. (SAD §2.4, §3.1, §6)

### Decision
Bucket state in the `rate_buckets` table, read-modify-write in one transaction under a row lock (`repository.rate_buckets`); arithmetic in `service.ratelimit`.

### Rationale
Shared durable state keeps limits correct across restarts without an external service (no new infrastructure).

### Consequences
- Positive: no extra component; consistent with transactional model.
- Negative: one extra DB write per request; on SQLite correctness depends on single-writer locking.

### Alternatives Considered
- In-memory counter: lost on restart, wrong with multiple processes.
- Redis: new external dependency, contradicts "no external services".

## ADR-008: Subprocess execution via asyncio.TaskGroup with bounded concurrency

### Status
Accepted

### Context
FR-02/FR-08 run user-supplied commands; T-06 (shell interpretation), T-07 (orphan processes), NFR-03 (cancellation correctness). (SAD §3.2, §6)

### Decision
`service.executor` runs workers inside an `asyncio.TaskGroup`, bounded by `TASKQ_MAX_CONCURRENT`, excess work queued. `service.runner` uses `shlex.split` into `asyncio.create_subprocess_exec`; `shell=True` is forbidden and grep-gated. Timeout via `asyncio.wait_for(TASKQ_TASK_TIMEOUT)`, then `process.kill()` followed by `await process.wait()`. State machine `pending -> running -> done | failed | timeout`, plus `interrupted` when the lifespan drain (`TASKQ_DRAIN_TIMEOUT`) expires. A task timeout is a task state, not an HTTP error. `CancelledError` is never swallowed; no bare `except:`.

### Rationale
Structured concurrency gives cancellable, leak-free execution without threads.

### Consequences
- Positive: no orphan processes; graceful shutdown with defined end state.
- Negative: `service.runner` is high risk; in-process queue is lost on crash (stragglers become `interrupted` only on graceful drain).

### Alternatives Considered
- `ThreadPoolExecutor` with `subprocess.run`: blocking threads, harder cancellation and kill-then-wait semantics. Not adopted by the SAD.
- External worker (Celery): new infrastructure, out of scope.
- `shell=True`: command-chaining risk; forbidden.

## ADR-009: Single error-rendering point using RFC 7807 problem+json with correlation id

### Status
Accepted

### Context
FR-10, T-10, T-12. (SAD §3.4)

### Decision
All non-2xx responses come from `api.error_handlers` as `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`, `correlation_id`; header `X-Correlation-Id` matches the logged id (set in `api.middleware`). `detail` is chosen from a whitelist and passed through `service.redact`. Unexpected exceptions are caught only there, logged server-side, and returned as 500 `/errors/internal` with generic text. Domain errors (`errors.*`) map to 422/401/403/404/409/429/503.

### Rationale
One rendering point guarantees a uniform contract and prevents stack-trace or SQL leakage.

### Consequences
- Positive: traceability across client, response and log.
- Negative: every new error type must be registered in the whitelist.

### Alternatives Considered
- Per-route error handling: inconsistent shape, leak risk.
- Plain `{"detail": ...}` default: no correlation id, no stable type URIs.

## ADR-010: Central redaction, readiness fail-closed, and secret handling

### Status
Accepted

### Context
NFR-04, T-11, FR-09. (SAD §3.3, §4, §6)

### Decision
A single `service.redact` regex pass (sk-, token=, Bearer, postgres URL) applies to stored output tails, log records and error details; matching lines become `[REDACTED]`. DB URL is excluded from `Settings.__repr__`, logs and metrics. API key plaintext is printed only by `key create`. `/readyz` returns 200 only when the DB is reachable and `alembic current == head`; otherwise 503 problem+json naming the failing check, with no unbounded retry.

### Rationale
One pass is testable once and applied everywhere; failing closed prevents serving on a stale schema.

### Consequences
- Positive: consistent masking; deploy safety.
- Negative: regex-based redaction can miss novel secret formats.

### Alternatives Considered
- Per-call-site masking: inconsistent.
- Ready when DB reachable only: may serve with the wrong schema.

## ADR-011: Resilience and file-write patterns not adopted (circuit breaker, atomic file write)

### Status
Proposed (Requires Verification)

### Context
The dispatch brief listed "atomic write" and "circuit breaker" as patterns to cover. SAD.md contains neither. The service has no outbound dependencies other than its database and local subprocesses ("no external services", SAD §4), and all persistence is transactional through the UnitOfWork.

### Decision
No circuit breaker and no file-level atomic-write component are introduced. The equivalent guarantees come from existing decisions: atomicity from UoW transactions and Alembic transactional revisions (ADR-003, ADR-005); failure containment from bounded concurrency, timeouts, kill-then-wait, drain timeout and no unbounded retry (ADR-008, ADR-010). If SPEC owners intend either pattern, the SAD must be amended first.

### Rationale
Adding patterns not required by SPEC or SAD would be speculative design.

### Consequences
- Positive: smaller surface.
- Negative: no automatic back-off if the database degrades; `/readyz` 503 is the only signal.

### Alternatives Considered
- Circuit breaker around DB access: no outbound-service failure mode in the SAD justifies it.
- Write-temp-then-rename for files: no persisted files besides the SQLite database, which is managed by the engine.

## Traceability Matrix (ADR to SRS requirements)

This traceability matrix links each decision to the SRS requirements (`01-requirements/SRS.md`, FR-01 to FR-10 and NFR-01 to NFR-12) and to the originating specification (`SPEC.md`) that it serves. Requirement IDs are cited only where an ADR above or `SAD.md` already names them. "Served" means the decision is the architectural mechanism the SAD uses for that requirement; verification of the requirement itself, including its acceptance criteria (AC-IDs in SRS.md), is owned by `TEST_SPEC.md`, not by this ADR.

| ADR | Decision | FR served | NFR served | Source specification |
|-----|----------|-----------|------------|----------------------|
| ADR-001 | Python 3.11, FastAPI, pydantic v2 | FR-01 | NFR-05, NFR-07 | SPEC section 2; SAD section 1, 4 |
| ADR-002 | Four-layer architecture checked by import-linter | (cross-cutting) | NFR-06, NFR-11 | SAD section 1, 2.1, 4 |
| ADR-003 | UnitOfWork as the sole persistence handle | FR-06 | NFR-03 | SAD section 1, 2.4 |
| ADR-004 | SQLAlchemy 2.x on SQLite and PostgreSQL | FR-06 | NFR-01 | SPEC section 2; SAD section 1, 4 |
| ADR-005 | Alembic, three reversible revisions | FR-07 | NFR-03, NFR-09 | SAD section 2.2, 3.4, 6 T-09 |
| ADR-006 | Authorization in one dependency before lookup | FR-03, FR-04, FR-05 | NFR-02 | SAD section 3.1, 6 T-01 to T-03 |
| ADR-007 | Database-backed token-bucket rate limit | FR-05 | (none beyond FR-05) | SAD section 2.4, 3.1, 6 T-04 |
| ADR-008 | Subprocess execution under asyncio.TaskGroup | FR-02, FR-08 | NFR-03, NFR-02 | SAD section 3.2, 6 T-06, T-07 |
| ADR-009 | RFC 7807 problem+json single rendering point | FR-10 | NFR-02 | SAD section 3.4, 6 T-10, T-12 |
| ADR-010 | Central redaction and readiness fail-closed | FR-09 | NFR-04, NFR-03 | SAD section 3.3, 4, 6 T-11 |
| ADR-011 | Circuit breaker and atomic file write not adopted | (none) | (none) | SAD section 4 |
| (cross-cutting) | No single owning decision: verification-only requirements, see below | (none) | NFR-08, NFR-10, NFR-12 | SRS.md section 4 |

### Requirements without a single owning decision

- NFR-08 (mutation testing), NFR-09 (zero-skip verification honesty, other than the real-database migration clause served by ADR-005), NFR-10 (integration coverage) and NFR-12 (`verify-system` target) constrain how the implementation is verified, not how it is structured. They are cross-cutting verification requirements with no single owning architectural decision; SRS.md section 4 defines them and TEST_SPEC.md owns their verification.
- NFR-01 is served structurally by ADR-004 (eager loading, cursor pagination, indexes); the p95 latency figures are measured by tests, not guaranteed by the decision.
- NFR-07 beyond the pinned stack (license allowlist, lock file, SBOM) is named in ADR-001 only as a consequence; no separate decision was needed.

## Quality and Security Notes Across Decisions

### Specification and test linkage

Each decision above implements the specification in SRS.md and SPEC.md, and the traceability matrix is the completeness check that no requirement lacks an owner. Verification follows the test plan in TEST_SPEC.md: a unit test for pure service logic, an integration test through the ASGI app for every HTTP-visible rule, and a regression test for each fixed defect. Persistence is never replaced by a mock (ADR-004, ADR-005); a mock is limited to the clock and the OS-process boundary of ADR-008. A pytest fixture builds a migrated temporary database. Test coverage is reported by `pytest --cov` and mutation score applies to `service/` and `repository/`. Monitoring relies on the readiness probe of ADR-010 and the correlation id of ADR-009, and audit records of key use rely on the same log fields.

### Code-structure conventions implied by the decisions

- Interface boundaries (ADR-002, ADR-003): the UnitOfWork and the executor are declared as an `ABC` or Protocol `interface`, implemented by a concrete `class`, so layers depend on abstractions.
- Records crossing layers are frozen `dataclass` objects or pydantic models; each public function has a type hint on every parameter and return value and a `docstring` citing its FR or NFR id.
- Naming follows snake_case for functions and modules, PascalCase for classes.

### Security consequences across decisions

- Security posture: the decisions in ADR-006, ADR-007, ADR-009 and ADR-010 form the security design of SAD section 6.
- Input sanitizer: ADR-001 adopts pydantic validation as the input sanitizer; the request is sanitized before any persistence (SAD T-05).
- RBAC and permission: ADR-006 defines role-based access over the scopes read, write and admin, with a single permission check ahead of resource lookup.
- PII and secrets: ADR-010 redacts secrets and PII-like tokens from outputs; keys are stored only as hashes (ADR-006).
- Encrypt and TLS: transport encryption is delegated to the reverse proxy, which must terminate TLS; the service does not encrypt payloads itself (Requires Verification at deployment).
- Signature: no request signature scheme is adopted; the API key is the only credential.
- Vulnerability mitigation and monitoring: `bandit`, pinned dependencies and the license and SBOM checks of NFR-07 supply the vulnerability mitigation baseline.

## Architecture Amendment — `taskq_api.__main__` declared in layer `entry`

- **When**: 2026-10-04T12:08:12.060906+00:00
- **Amended**: layer 'entry'
- **Reason**: python -m taskq_api is the CLI entry point and delegates to taskq_api.cli, matching SAD section 2.2
- **Recorded by**: `harness_cli.py amend-sab --declare` (Gate 1 Architecture Amendment Protocol)

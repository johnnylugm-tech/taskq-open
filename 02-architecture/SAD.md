# Software Architecture Document (SAD) — taskq-api

## 1. Architecture Overview

`taskq-api` is a single-process ASGI service (FastAPI, Python 3.11) that exposes a task queue over REST. State lives in a relational database (SQLite for dev/test, PostgreSQL for production) behind SQLAlchemy 2.x; the schema evolves through three Alembic revisions; background execution uses `asyncio.TaskGroup` and `asyncio.create_subprocess_exec`.

The architecture is a strict four-layer stack plus two independence modules (SPEC NFR-06):

```
            entry   (app.py, __main__.py, cli.py)   composition root
              |
   api  >  service  >  repository  >  models         layers contract
   config, errors                                     independence modules
   migrations/versions/*                              Alembic revisions (no import of taskq_api layers)
```

Rules that shape every later section:

- Only `repository` (and `models`, which declares the ORM mapping, plus `migrations`) imports `sqlalchemy`. `api` and `service` never do (NFR-06 forbidden contract).
- The business layer never holds a `Session`. It holds a `UnitOfWork` object (defined in `repository.session`, re-exported through `service.uow`) that exposes repository objects (FR-06).
- Authorization is decided in exactly one FastAPI dependency (`api.deps.require_scope`) (FR-04).
- All non-2xx responses are produced by one exception-handler module (`api.error_handlers`) (FR-10).

Note on SPEC: SPEC.md jumps from section 5 to section 7; there is no section 6 (directory structure). The module tree below is therefore derived from SPEC section 2 (stack), NFR-06 (layers), NFR-11 (size limits) and SPEC section 10 (high-risk modules). This is flagged as an Unknown to be confirmed against the SPEC owner.

### 1.1 System Verification Target

**Makefile target**: `verify-system`

**Exercises**: (1) `alembic upgrade head` against a real SQLite file; (2) the full pytest suite (including the real-DB migration round trip, FR-07/NFR-09); (3) starts the real service (`python -m taskq_api serve` / `uvicorn taskq_api.app:app`) and smoke-tests `/healthz` and `/readyz`; (4) `alembic downgrade base` then `upgrade head`; then prints `verify-system: PASS`. High-risk modules executed for real by this target: `taskq_api.service.runner` (a real subprocess is run through the live service), `taskq_api.service.auth` (a key is created with the CLI and used), `taskq_api.repository.session` (real transactions), `migrations.versions.v3_split_results` (real data migration). Every step uses `set -e` semantics; there is no `|| true`.

## 2. Module Design

### 2.1 Directory Structure Design Principles

- One responsibility per directory; every directory holds at most 15 files (NFR-11); every file at most 400 lines; handlers at most 40 lines (business logic sinks to `service/`).
- Each directory is its own graph community and is expected to stay well under 50 nodes: no flat 10+ file directory, no god module.
- Dependencies point downward only. No cycles: the import graph is the DAG `entry -> api -> service -> repository -> models`, with `config`/`errors` as leaves that import nothing from the package (and not from each other).

### 2.2 Module tree (package `taskq_api`, under `03-development/src/`)

```
03-development/src/taskq_api/
  __init__.py
  __main__.py          entry: python -m taskq_api  (delegates to cli.py)
  app.py               entry: FastAPI app factory, lifespan (runner start / drain)
  cli.py               entry: serve / migrate / key create / seed / healthcheck
  config.py            independence: env settings (12 TASKQ_* vars)
  errors.py            independence: domain exception types + problem type URIs
  api/                 (9 files)
    __init__.py
    deps.py            auth dependency, scope check, rate-limit dependency, UoW dependency
    schemas.py         pydantic v2 request/response models (TaskCreate, ...)
    routes_tasks.py    FR-01 CRUD
    routes_runs.py     FR-02 run / runs
    routes_health.py   FR-09 /healthz /readyz
    routes_metrics.py  FR-09 /v1/metrics
    error_handlers.py  FR-10 RFC 7807 rendering
    middleware.py      correlation id, CORS (default deny)
  service/             (10 files)
    __init__.py
    uow.py             UnitOfWork type + factory seen by api
    tasks.py           FR-01 validation rules, create/get/list/delete
    runs.py            FR-02 run submission and history
    runner.py          FR-02/FR-08 subprocess execution, timeout kill, state machine   [high risk]
    executor.py        FR-08 TaskGroup, concurrency limit, queue, graceful drain
    auth.py            FR-03/FR-04 key hash/verify, scope hierarchy                    [high risk]
    ratelimit.py       FR-05 token-bucket arithmetic
    redact.py          NFR-04 redaction of output, logs, error bodies
    health.py          FR-09 readiness decision, metrics aggregation
  repository/          (9 files)
    __init__.py
    session.py         engine, pool, request-scoped UnitOfWork, commit/rollback    [high risk]
    tasks.py           task queries (cursor pagination, selectinload)
    results.py         task_results queries
    api_keys.py        api_keys queries
    rate_buckets.py    row-level-lock bucket update
    tags.py            tags / task_tags
    stats.py           counts and latency quantile queries (metrics)
    migration_state.py alembic current vs head, upgrade/downgrade helpers
  models/              (7 files)
    __init__.py
    base.py            declarative base
    task.py  api_key.py  tag.py  result.py  rate_bucket.py
migrations/             (project root, with alembic.ini)
  env.py
  versions/
    v1_initial.py            tasks, api_keys, rate_buckets
    v2_tags.py               tags, task_tags, unique index on tasks.name
    v3_split_results.py      result_json -> task_results (data move, reversible)   [high risk]
```

### 2.3 FR to module mapping

| FR | Primary modules | Notes |
|----|-----------------|-------|
| FR-01 Task CRUD | `api.routes_tasks`, `api.schemas`, `service.tasks`, `repository.tasks`, `repository.tags`, `models.task`, `models.tag` | validation rules (non-empty, <=1000 chars, injection blacklist, unique name) live in `service.tasks`; cursor pagination in `repository.tasks` |
| FR-02 Run endpoint | `api.routes_runs`, `service.runs`, `service.runner`, `repository.results`, `models.result` | 202 + `run_id`; `GET /runs` newest first |
| FR-03 API key auth | `service.auth`, `repository.api_keys`, `models.api_key`, `api.deps`, `cli` (key create) | SHA-256 stored, `hmac.compare_digest`, `revoked_at` honored |
| FR-04 Scope authz | `api.deps` (single dependency), `service.auth` (scope hierarchy) | check precedes resource lookup so 403 does not leak existence |
| FR-05 Rate limit | `service.ratelimit`, `repository.rate_buckets`, `models.rate_bucket`, `api.deps` | bucket in DB, one transaction, row lock |
| FR-06 Persistence / tx | `repository.session`, `repository.*`, `models.*`, `service.uow` | per-request UoW; commit on success, rollback on exception |
| FR-07 Migrations | `migrations/versions/v1_initial`, `v2_tags`, `v3_split_results`, `migrations/env.py`, `repository.migration_state` | every revision has a real `downgrade` |
| FR-08 Async executor | `service.executor`, `service.runner`, `app` (lifespan drain) | TaskGroup, `TASKQ_MAX_CONCURRENT`, `wait_for`, `kill()` + `await wait()` |
| FR-09 Health / metrics | `api.routes_health`, `api.routes_metrics`, `service.health`, `repository.migration_state`, `repository.stats` | `/readyz` fails closed when not at head |
| FR-10 Error contract | `api.error_handlers`, `api.middleware`, `errors`, `service.redact` | single rendering point; whitelisted `detail` |

### 2.4 Module detail

| Attribute | Value |
|-----------|-------|
| **api** | |
| Responsibility | HTTP translation only: parse, authenticate via dependency, call one service function, serialize |
| External Interface | `/v1/tasks`, `/v1/tasks/{id}`, `/v1/tasks/{id}/run`, `/v1/tasks/{id}/runs`, `/v1/metrics`, `/healthz`, `/readyz`, `/openapi.json` |
| Dependencies | `service`, `config`, `errors` |

- Handlers are at most 40 lines; no business rules, no ORM types.
- Every `/v1` route declares `Depends(require_scope(...))` and nothing else decides authorization (a test iterates `app.routes` to assert it).

| Attribute | Value |
|-----------|-------|
| **service** | |
| Responsibility | Business rules, state machine, auth decisions, rate arithmetic, redaction, async orchestration |
| External Interface | plain functions/classes taking a `UnitOfWork`; no HTTP or SQLAlchemy types |
| Dependencies | `repository`, `models`, `config`, `errors` |

- `service.runner` never uses `shell=True`; command is `shlex.split` into `create_subprocess_exec`.
- `except asyncio.CancelledError` is either not caught or re-raised; no bare `except:` and no `except Exception: pass`.

| Attribute | Value |
|-----------|-------|
| **repository** | |
| Responsibility | All SQL via ORM or parameterized statements; sessions, pooling, transactions; migration-state inspection |
| External Interface | `UnitOfWork` context manager exposing `tasks`, `results`, `api_keys`, `rate_buckets`, `tags`, `stats` |
| Dependencies | `models`, `config`, `errors` |

- Relationship loads use `selectinload`/`joinedload`; list queries issue a constant number of statements.
- `pool_size=TASKQ_DB_POOL_SIZE`, `pool_pre_ping=True`.

| Attribute | Value |
|-----------|-------|
| **models** | |
| Responsibility | SQLAlchemy declarative mapping for the tables of SPEC 5.2 (current head = v3) |
| External Interface | ORM classes |
| Dependencies | none inside the package |

| Attribute | Value |
|-----------|-------|
| **config / errors** | |
| Responsibility | `config`: typed settings from the 12 `TASKQ_*` variables (DB URL never rendered in repr/logs). `errors`: exception classes and `/errors/*` type URIs |
| External Interface | `Settings`, `TaskqError` hierarchy |
| Dependencies | none (independence modules; they do not import each other) |

| Attribute | Value |
|-----------|-------|
| **migrations** | |
| Responsibility | Three reversible revisions; v3 moves data both ways |
| External Interface | `alembic upgrade|downgrade` |
| Dependencies | none from `taskq_api` layers (uses `op`/lightweight table constructs so a revision never changes meaning when models evolve) |

#### Logical Constraints
- No import from a lower layer to a higher layer; no cycles.
- `sqlalchemy` imported only in `repository`, `models`, `migrations`.
- The authorization check runs before any resource lookup (403 must not reveal existence).
- Rate-limit bucket read-modify-write happens in one transaction with a row lock (on SQLite, write serialization via the database lock; the row-lock clause is a no-op there, so correctness on SQLite relies on single-writer semantics).
- `UnitOfWork` commits on normal exit and rolls back on any exception, including `CancelledError` (which is then re-raised).
- Background tasks open their own `UnitOfWork`; they never reuse a request session.

## 3. Interfaces & Data Flows

### 3.1 Request pipeline (authenticated `/v1` call)

```
Client
  -> middleware (correlation id, CORS)
  -> api.deps: X-API-Key -> service.auth.verify -> repository.api_keys     (401)
  -> api.deps: scope check (read < write < admin)                          (403)
  -> api.deps: service.ratelimit.consume -> repository.rate_buckets        (429 + Retry-After)
  -> api.routes_*: handler -> service.* -> repository.* -> DB
  -> response (2xx) | error_handlers -> application/problem+json
```

Order is fixed: authenticate, authorize, rate-limit, then touch the resource. 404 can therefore only be reached by a caller already holding sufficient scope.

### 3.2 Run flow (FR-02 / FR-08)

```
POST /v1/tasks/{id}/run
  -> service.runs.submit: UoW { task.status = pending; create run } commit
  -> service.executor.enqueue(run_id)   (bounded by TASKQ_MAX_CONCURRENT, queued otherwise)
  <- 202 {run_id}

executor worker (inside TaskGroup, own UoW):
  status running -> service.runner.exec (create_subprocess_exec, wait_for TASKQ_TASK_TIMEOUT)
     timeout -> process.kill(); await process.wait(); status timeout
  -> service.redact(stdout_tail, stderr_tail) -> repository.results (task_results row)
  -> status done | failed | timeout
shutdown (lifespan): executor.drain(TASKQ_DRAIN_TIMEOUT); stragglers -> status interrupted
```

State machine: `pending -> running -> done | failed | timeout` (+ `interrupted` on drain expiry). A task timeout is a task state, not an HTTP error.

### 3.3 Readiness (FR-09)

```
GET /readyz -> service.health.readiness -> repository.migration_state
   DB reachable?  alembic current == head?
   both yes -> 200 ; otherwise 503 problem+json naming the failing check (fail closed)
```

### 3.4 Error handling

| Level | Handling Strategy |
|-------|------------------|
| Domain error (`errors.*`) | Raised in service/repository; `api.error_handlers` maps to 422/401/403/404/409/429/503 problem+json |
| Unexpected exception | Caught only in `api.error_handlers`; logged with `correlation_id`; client gets 500 `/errors/internal` with a fixed generic `detail` |
| `asyncio.CancelledError` | Never mapped to a response; propagates (NFR-03) |
| Migration failure | Revision transaction rolls back; DB stays at previous revision |
| DB unavailable | `/readyz` 503 with explicit detail; no unbounded retry |

Problem body fields: `type`, `title`, `status`, `detail`, `instance`, `correlation_id`; header `X-Correlation-Id` matches the logged id. `detail` is chosen from a whitelist of per-error messages and passes through `service.redact`.

### 3.5 Dependency diagram

```
entry (app, __main__, cli)
   |-------------------------> repository.migration_state   (migrate/healthcheck commands)
   v
  api ---------> service ---------> repository ---------> models
   |                |                   |                    |
   +----------------+-------------------+--------------------+--> config, errors (leaves)
migrations/versions : standalone (alembic op only)
```

No arrow points upward; `config` and `errors` have no outgoing arrows.

## 4. NFR Handling

| NFR | Approach | Modules |
|-----|----------|---------|
| NFR-01 Performance | Cursor pagination (no offset); eager loading; indexes on `tasks.name`, `tasks.status/created_at`; SQL statement count asserted constant via SQLAlchemy event listener; pytest-benchmark for p95 targets (30 ms get, 80 ms list at 10k rows) | `repository.tasks`, `repository.session` |
| NFR-02 Security | No `shell=True`/`eval`/`exec`; parameterized/ORM only; hashed keys with `hmac.compare_digest`; uniform 403; CORS default deny via `TASKQ_CORS_ORIGINS`; bandit 0 HIGH / 0 MEDIUM | `service.auth`, `api.middleware`, `service.runner` |
| NFR-03 Error handling | Context-manager transactions; no bare/swallowing excepts; `CancelledError` re-raised; kill-then-wait on timeout; migration rollback | `repository.session`, `service.executor`, `service.runner` |
| NFR-04 Sensitive data masking | Single `service.redact` regex pass (sk-, token=, Bearer, postgres URL) applied to output tails, log records and error details; DB URL excluded from `Settings.__repr__`, logs and metrics; API key plaintext only printed by `key create` | `service.redact`, `config`, `cli` |
| NFR-05 Documentation | Docstrings with `[FR-XX]`/`[NFR-XX]` on all public symbols; `summary` + `description` on every route | all modules, `api.routes_*` |
| NFR-06 Layering | `.importlinter`: layers `api > service > repository > models`, independence of `config`/`errors`, forbidden `sqlalchemy` for `api`/`service`/`config`/`errors`; `lint-imports` exit 0 | project root |
| NFR-07 Licensing | Pinned `requirements.txt`, full `requirements.lock`, allowlist check with `pip-licenses`, SBOM at `08-config/SBOM.json` | build config |
| NFR-08 Mutation | mutmut limited to `service/` and `repository/`, score target 70 per SPEC, rationale recorded in `.methodology/harness_config.json` | `service`, `repository` |
| NFR-09 Verification authenticity | Zero skip/xfail; real SQLite file for migration tests; every test asserts | tests (Phase 3) |
| NFR-10 Integration coverage | `httpx.AsyncClient(transport=ASGITransport(app))`, one case per error code, migration round trip, rate limit trigger/recover, graceful drain | tests/integration |
| NFR-11 Readability | Directories <= 15 files, files <= 400 lines, handler <= 40 lines, CC <= 10; logic sunk into `service/` | all |
| NFR-12 System verification | `make verify-system` as in 1.1 | `Makefile` |

Latency budget: auth lookup and bucket update each cost one indexed single-row statement; the list endpoint adds one `selectinload` statement for tags, so statement count is constant (about 4 per request). Cost: no external services; single process; connection pool bounded by `TASKQ_DB_POOL_SIZE`.

Technology choices

| Technology | Rationale |
|------------|----------|
| FastAPI / pydantic v2 | ASGI async endpoints, automatic OpenAPI for NFR-05, validation to 422 |
| SQLAlchemy 2.x | One ORM model for SQLite and PostgreSQL; explicit transaction control |
| Alembic | Required reversible, data-moving migrations (FR-07) |
| asyncio TaskGroup + subprocess_exec | Structured concurrency, no shell, cancellable |
| import-linter | Machine-checkable layering (NFR-06) |

---

## 5. SAB Block (machine-readable — BINDING CONTRACT)

> Field names must match `core/quality_gate/sab_parser.py:render_canonical_sab_template()`. The real block is generated/validated in the SAB Generation phase; the YAML below is the draft derived from this SAD.

<!-- SAB:START -->
```yaml
sab:
  version: "1.0"
  created_at: "2026-10-04"
  phase: 2
  project: "taskq-api"

  layers:
    - name: api
      modules:
        - "taskq_api.api.deps"
        - "taskq_api.api.schemas"
        - "taskq_api.api.routes_tasks"
        - "taskq_api.api.routes_runs"
        - "taskq_api.api.routes_health"
        - "taskq_api.api.routes_metrics"
        - "taskq_api.api.error_handlers"
        - "taskq_api.api.middleware"
      allowed_dependencies: ["service", "shared"]
    - name: service
      modules:
        - "taskq_api.service.uow"
        - "taskq_api.service.tasks"
        - "taskq_api.service.runs"
        - "taskq_api.service.runner"
        - "taskq_api.service.executor"
        - "taskq_api.service.auth"
        - "taskq_api.service.ratelimit"
        - "taskq_api.service.redact"
        - "taskq_api.service.health"
      allowed_dependencies: ["repository", "models", "shared"]
    - name: repository
      modules:
        - "taskq_api.repository.session"
        - "taskq_api.repository.tasks"
        - "taskq_api.repository.results"
        - "taskq_api.repository.api_keys"
        - "taskq_api.repository.rate_buckets"
        - "taskq_api.repository.tags"
        - "taskq_api.repository.stats"
        - "taskq_api.repository.migration_state"
      allowed_dependencies: ["models", "shared"]
    - name: models
      modules:
        - "taskq_api.models.base"
        - "taskq_api.models.task"
        - "taskq_api.models.api_key"
        - "taskq_api.models.tag"
        - "taskq_api.models.result"
        - "taskq_api.models.rate_bucket"
      allowed_dependencies: []
    - name: shared
      modules:
        - "taskq_api.config"
        - "taskq_api.errors"
      allowed_dependencies: []
    - name: entry
      modules:
        - "taskq_api.app"
        - "taskq_api.cli"
      allowed_dependencies: ["api", "service", "repository", "shared"]
    - name: migrations
      modules:
        - "migrations.versions.v1_initial"
        - "migrations.versions.v2_tags"
        - "migrations.versions.v3_split_results"
      allowed_dependencies: []

  allowed_dependencies:
    - from: api
      to: service
    - from: api
      to: shared
    - from: service
      to: repository
    - from: service
      to: models
    - from: service
      to: shared
    - from: repository
      to: models
    - from: repository
      to: shared
    - from: entry
      to: api
    - from: entry
      to: service
    - from: entry
      to: repository
    - from: entry
      to: shared

  quality_targets:
    max_complexity: 10
    min_coverage: 100
    max_coupling: 0.3

  nfr_dimension_mapping: {}

  nfr_traceability:
    NFR-01:
      type: performance
      dimension: performance
      target: "p95 get < 30ms, list < 80ms at 10k rows; constant SQL statement count"
      module: taskq_api.repository.tasks
    NFR-02:
      type: security
      dimension: security
      target: "bandit 0 HIGH / 0 MEDIUM; no shell=True, eval, exec, string-built SQL"
      module: taskq_api.service.auth
    NFR-03:
      type: reliability
      dimension: error_handling
      target: "no swallowed exceptions; CancelledError re-raised; no orphan processes"
      module: taskq_api.service.executor
    NFR-04:
      type: security
      dimension: security
      target: "redaction regex applied; DB URL absent from logs and metrics"
      module: taskq_api.service.redact
    NFR-05:
      type: documentation
      dimension: documentation
      target: "all public symbols documented with FR/NFR reference"
      module: taskq_api.api.routes_tasks
    NFR-06:
      type: layering
      dimension: architecture_constraints
      target: "lint-imports exit 0; sqlalchemy forbidden outside repository"
      module: taskq_api.repository.session
    NFR-07:
      type: licensing
      dimension: license_compliance
      target: "all dependencies in license allowlist incl. transitive"
      module: taskq_api.config
    NFR-08:
      type: mutation
      dimension: mutation_testing
      target: "mutation score threshold per SPEC NFR-08 on service and repository"
      scope_layers: [service, repository]
      module: taskq_api.service.tasks
    NFR-09:
      type: testability
      dimension: test_assertion_quality
      target: "zero skipped tests; zero assertion-free tests"
      module: taskq_api.repository.migration_state
    NFR-10:
      type: integration
      dimension: integration_coverage
      target: "integration line coverage threshold per SPEC NFR-10"
      module: taskq_api.app
    NFR-11:
      type: maintainability
      dimension: readability
      target: "CC <= 10; file <= 400 lines; directory <= 15 files"
      module: taskq_api.service.tasks
    NFR-12:
      type: verifiability
      dimension: execute_verification_target
      target: "make verify-system exits 0 and prints verify-system: PASS"
      module: taskq_api.app

  advisory_only: []

  gate_score_overrides: {}

  fr_module_traceability:
    FR-01: ["taskq_api.api.routes_tasks", "taskq_api.api.schemas", "taskq_api.service.tasks", "taskq_api.repository.tasks", "taskq_api.repository.tags"]
    FR-02: ["taskq_api.api.routes_runs", "taskq_api.service.runs", "taskq_api.service.runner", "taskq_api.repository.results"]
    FR-03: ["taskq_api.service.auth", "taskq_api.repository.api_keys", "taskq_api.cli"]
    FR-04: ["taskq_api.api.deps", "taskq_api.service.auth"]
    FR-05: ["taskq_api.service.ratelimit", "taskq_api.repository.rate_buckets"]
    FR-06: ["taskq_api.repository.session", "taskq_api.service.uow"]
    FR-07: ["migrations.versions.v1_initial", "migrations.versions.v2_tags", "migrations.versions.v3_split_results", "taskq_api.repository.migration_state"]
    FR-08: ["taskq_api.service.executor", "taskq_api.service.runner", "taskq_api.app"]
    FR-09: ["taskq_api.api.routes_health", "taskq_api.api.routes_metrics", "taskq_api.service.health", "taskq_api.repository.stats"]
    FR-10: ["taskq_api.api.error_handlers", "taskq_api.api.middleware", "taskq_api.errors"]

  architecture_constraints:
    - id: "NFR-06-layers"
      executor: import-linter
      contract_type: layers
      contract_name: "taskq_api layers"
      source_modules: ["taskq_api.app", "taskq_api.api", "taskq_api.service", "taskq_api.repository", "taskq_api.models"]
    - id: "NFR-06-independence"
      executor: import-linter
      contract_type: independence
      contract_name: "taskq_api independence"
      source_modules: ["taskq_api.config", "taskq_api.errors"]
    - id: "NFR-06-no-sqlalchemy-outside-repository"
      executor: import-linter
      contract_type: forbidden
      contract_name: "no sqlalchemy outside repository"
      source_modules: ["taskq_api.app", "taskq_api.api", "taskq_api.service", "taskq_api.config", "taskq_api.errors"]
      forbidden_modules: ["sqlalchemy"]
  decision_issues:
    - {id: "NFR-99.1", status: resolved, blocks_phase: 3, resolution_ref: "02-architecture/SAD.md:491"}
    - {id: "NFR-99.2", status: resolved, blocks_phase: 3, resolution_ref: "02-architecture/SAD.md:492"}
    - {id: "NFR-99.3", status: resolved, blocks_phase: 3, resolution_ref: "02-architecture/SAD.md:493"}
    - {id: "NFR-99.4", status: resolved, blocks_phase: 3, resolution_ref: "02-architecture/SAD.md:494"}

  high_risk_modules:
    - "taskq_api.service.runner"
    - "taskq_api.service.auth"
    - "taskq_api.repository.session"
    - "migrations.versions.v3_split_results"

  required_artifacts:
    - {path: ".importlinter", required_by_phase: 3}
    - {path: "requirements.txt", required_by_phase: 3}
    - {path: ".env.example", required_by_phase: 3}
    - {path: "alembic.ini", required_by_phase: 3}
    - {path: "Makefile", required_by_phase: 3}
```
<!-- SAB:END -->

Decision resolutions referenced by `decision_issues` (each line is the resolution record):

NFR-99.1: resolved — p95 is computed from the raw benchmark round timings, not from pytest-benchmark's mean/median.
NFR-99.2: resolved — `;` is in the injection blacklist and `$` is accepted at task create (blacklist beyond `;` is implementation-defined and documented in `service.tasks`).
NFR-99.3: resolved — a duplicate task name returns 409 `/errors/conflict` (SPEC section 7 and section 8 #8 take precedence over the SPEC L88 wording).
NFR-99.4: resolved — `interrupted` is an additional terminal state set only by drain expiry; the FR-02 happy-path machine is unchanged.

Note: `architecture_constraints` carries typed import-linter mappings above. Open item: `models` and `migrations` import `sqlalchemy` by necessity, so the NFR-06 forbidden contract must name `api`, `service`, `config`, `errors` as sources rather than "every layer other than repository" literally (SPEC wording says "repository 以外的任何層"; this is a Requires Verification point).

---

## 6. Security Design (STRIDE-lite — machine-readable, BINDING CONTRACT)

Attack surface is real (authenticated HTTP API, database, subprocess execution), so `applicability: full`. Boundaries: TB-01 HTTP clients to API; TB-02 service to subprocess; TB-03 service/repository to database; TB-04 service to logs/error bodies.

<!-- SEC:START -->
```yaml
security_design:
  version: "1.0"
  applicability: full   # full | none — none REQUIRES justification and skips the rest
  justification: ""     # required (>=20 chars) when applicability: none
  trust_boundaries:
    - id: TB-01
      name: "external HTTP input"
      description: "requests crossing from unauthenticated clients into the API layer (X-API-Key, JSON bodies, query params)"
    - id: TB-02
      name: "task command execution"
      description: "user-supplied task command strings crossing from the service layer into an OS subprocess"
    - id: TB-03
      name: "database access"
      description: "service and repository code crossing into the relational database holding keys, tasks and rate buckets"
    - id: TB-04
      name: "outbound diagnostics"
      description: "logs, error bodies, metrics and stored output tails leaving the service toward operators and clients"
  threats:
    - id: T-01
      boundary: TB-01
      category: spoofing
      description: "caller forges or guesses an API key, or uses a revoked key, to act as another principal"
      mitigation: "SHA-256 hashed keys compared with hmac.compare_digest; revoked_at rejects; missing or invalid key returns 401"
      owner_module: "taskq_api.service.auth"
      nfr: NFR-02
      verified_by: "test_sec_t01_invalid_or_revoked_key_rejected"
    - id: T-02
      boundary: TB-01
      category: elevation_of_privilege
      description: "a read or write key calls an endpoint that requires a higher scope"
      mitigation: "single scope dependency applied to every /v1 route, evaluated before resource lookup"
      owner_module: "taskq_api.api.deps"
      nfr: NFR-02
      verified_by: "test_sec_t02_insufficient_scope_returns_403"
    - id: T-03
      boundary: TB-01
      category: information_disclosure
      description: "403 versus 404 responses reveal whether a task id exists to a caller lacking scope"
      mitigation: "authorization decided before lookup; 403 body is identical regardless of resource existence"
      owner_module: "taskq_api.api.deps"
      nfr: NFR-02
      verified_by: "test_sec_t03_forbidden_body_does_not_reveal_existence"
    - id: T-04
      boundary: TB-01
      category: denial_of_service
      description: "a token floods the API to exhaust workers or the connection pool"
      mitigation: "per-token DB-backed token bucket under row lock; 429 with Retry-After; bounded concurrency and pool"
      owner_module: "taskq_api.service.ratelimit"
      nfr: NFR-03
      verified_by: "test_sec_t04_burst_exceeded_returns_429"
    - id: T-05
      boundary: TB-01
      category: tampering
      description: "malformed or injection-laden task payload is persisted or later executed"
      mitigation: "pydantic validation, length cap, injection-character blacklist, uniqueness check; 422 on violation"
      owner_module: "taskq_api.service.tasks"
      nfr: NFR-02
      verified_by: "test_sec_t05_injection_chars_rejected_422"
    - id: T-06
      boundary: TB-02
      category: elevation_of_privilege
      description: "task command is interpreted by a shell, allowing command chaining beyond the intended program"
      mitigation: "shlex.split into create_subprocess_exec; shell=True forbidden and grep-gated"
      owner_module: "taskq_api.service.runner"
      nfr: NFR-02
      verified_by: "test_sec_t06_shell_metacharacters_not_interpreted"
    - id: T-07
      boundary: TB-02
      category: denial_of_service
      description: "a long-running or hung task leaves an orphan process and holds resources"
      mitigation: "asyncio.wait_for timeout; process.kill() then await process.wait(); drain timeout marks interrupted"
      owner_module: "taskq_api.service.executor"
      nfr: NFR-03
      verified_by: "test_sec_t07_timeout_kills_subprocess_no_orphan"
    - id: T-08
      boundary: TB-03
      category: tampering
      description: "SQL injection through string-built queries alters or reads other rows"
      mitigation: "ORM or parameterized statements only; no f-string or concatenated SQL; grep gate"
      owner_module: "taskq_api.repository.tasks"
      nfr: NFR-02
      verified_by: "test_sec_t08_sql_metacharacters_treated_as_data"
    - id: T-09
      boundary: TB-03
      category: tampering
      description: "v3 data migration loses or corrupts result data on upgrade or downgrade"
      mitigation: "reversible real downgrade; round-trip test comparing every column on a real SQLite file"
      owner_module: "migrations.versions.v3_split_results"
      nfr: NFR-03
      verified_by: "test_sec_t09_v3_roundtrip_preserves_data"
    - id: T-10
      boundary: TB-03
      category: repudiation
      description: "a failed request cannot be traced to its actor or cause across client and server"
      mitigation: "correlation_id in X-Correlation-Id header, problem body and server log"
      owner_module: "taskq_api.api.middleware"
      nfr: NFR-03
      verified_by: "test_sec_t10_correlation_id_in_header_body_and_log"
    - id: T-11
      boundary: TB-04
      category: information_disclosure
      description: "secrets (sk- keys, tokens, Bearer values, DB URL with password) leak via stored output tails, logs or metrics"
      mitigation: "single redaction pass replaces matching lines with [REDACTED]; DB URL excluded from repr, logs and metrics"
      owner_module: "taskq_api.service.redact"
      nfr: NFR-04
      verified_by: "test_sec_t11_secrets_redacted_in_output_and_logs"
    - id: T-12
      boundary: TB-04
      category: information_disclosure
      description: "500 or other error bodies expose stack traces, SQL or file paths"
      mitigation: "whitelisted generic detail text; unexpected exceptions logged server-side only"
      owner_module: "taskq_api.api.error_handlers"
      nfr: NFR-02
      verified_by: "test_sec_t12_500_body_has_no_internal_details"
    - id: T-13
      boundary: TB-01
      category: spoofing
      description: "cross-origin web page drives the API using a victim's browser"
      mitigation: "CORS allows no origin unless listed in TASKQ_CORS_ORIGINS"
      owner_module: "taskq_api.api.middleware"
      nfr: NFR-02
      verified_by: "test_sec_t13_cors_default_denies_all_origins"
```
<!-- SEC:END -->

Note: every `owner_module` above is declared in the §5 SAB block; `verified_by` names are the single test each mitigation must be proven by (to be created in Phase 3/4).

---

## 7. Specification Traceability and Quality Plan

### 7.1 Traceability matrix (SRS to SAD to verification)

This matrix links each SRS requirement to the SAD section that designs it and to the test level that proves it. The SRS (`01-requirements/SRS.md`) and SPEC.md are the specification baseline; TEST_SPEC.md holds the detailed cases.

| SRS requirement | SAD design location | Verification level |
|-----------------|--------------------|--------------------|
| FR-01, FR-02 | 2.3, 2.4, 3.2 | integration test (CRUD chain, run lifecycle) |
| FR-03, FR-04, FR-05 | 3.1, 6 (T-01 to T-04) | unit test for scope hierarchy, integration test for 401/403/429 |
| FR-06, FR-07 | 2.2, 3.4, 6 (T-09) | integration test on a real SQLite file, migration round trip |
| FR-08 | 3.2, 6 (T-06, T-07) | integration test (timeout, graceful drain), unit test for cancellation |
| FR-09, FR-10 | 3.3, 3.4 | integration test (one case per error code) |
| NFR-01 to NFR-12 | 4 | per-row approach in section 4 |

### 7.2 Test plan, test coverage and regression

- Test plan: unit test cases cover pure service logic (scope ordering, token-bucket arithmetic, redaction); integration test cases drive the ASGI app through `httpx.AsyncClient`. TEST_SPEC.md is the authoritative test plan.
- Mock policy: a mock is allowed only at the OS-process boundary of the subprocess executor and for the clock; persistence is never mocked because NFR-09 requires a real database.
- Fixture design: a pytest fixture builds a temporary SQLite file, applies the Alembic revisions, and yields a request-scoped UnitOfWork; a second fixture seeds API keys for each scope.
- Test coverage target: statement coverage is measured by `pytest --cov`, and a coverage report is emitted by `make verify-system`. Mutation score (NFR-08) complements it for `service/` and `repository/`.
- Regression: every fixed defect gets a regression test named after its threat or requirement id, and the full suite runs on every change.
- Monitoring: `/healthz` and `/readyz` (FR-09) plus the correlation id in logs give operators the runtime signals; metrics never include the DB URL (NFR-04).
- Audit: key creation, revocation and 401/403 outcomes are logged with the correlation id, giving an audit trail without recording secrets.
- Completeness: the traceability matrix above, the FR to module mapping in 2.3 and the `verified_by` field of each threat must together leave no SRS requirement without a design owner and a test.

### 7.3 Code conventions (maintainability)

- Type hint rule: every public function and method carries full type hints, checked in CI.
- Data carriers between layers are frozen `dataclass` objects or pydantic models, so the API layer never receives ORM entities.
- Extension points (executor, clock, rate-limit store) are declared as an `ABC` or `Protocol` in the service layer so tests can substitute them.
- Naming: modules, functions and variables use snake_case; classes and pydantic models use PascalCase.

### 7.4 Additional security measures

- Input sanitizer: all request text passes the pydantic validators (length cap, injection-character blacklist) acting as the input sanitizer; the same step sanitize rules apply to the `name` and `command` fields before persistence (T-05).
- RBAC: authorization is role-based on three ordered scopes (read < write < admin); a permission check runs in `api.deps.require_scope` only.
- PII: the service stores no personal data beyond task text supplied by callers; PII-like tokens in output tails are removed by `service.redact` (NFR-04).
- Encrypt and TLS: the service does not encrypt traffic in-process. TLS is terminated by the deployment reverse proxy (assumption, Requires Verification at deployment); API keys are stored only as SHA-256 hashes, so the database holds no recoverable key.
- Signature: no request signature scheme is adopted; the API key in `X-API-Key` is the only credential (see ADR-006).
- Vulnerability management: `bandit` (0 HIGH, 0 MEDIUM), `pip-licenses` and dependency pinning in `requirements.lock` provide the vulnerability scan baseline.

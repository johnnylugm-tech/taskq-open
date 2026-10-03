# Software Requirements Specification (SRS) — `taskq-api`

> Source of truth: `/SPEC.md` (v1.0.0, 10 FR / 12 NFR / 12 env). Citations use `SPEC L<line>` or `SPEC §<n>`. Canonical phrases are kept verbatim (zh-TW) inside quotes.

## 1. Introduction

- **Project**: `taskq-api` — HTTP-serviced task queue: submit, query and execute tasks over REST; data persisted in a relational DB; schema evolves via Alembic; API-key authentication, per-token scope authorization, rate limiting (SPEC L49-54).
- **Language / form**: Python 3.11; ASGI service started by `uvicorn taskq_api.app:app`; plus `python -m taskq_api` admin entry (migrate / seed / healthcheck) (SPEC L53-54).
- **Role**: second-round progressive validation test bed (HTTP layer, real DB, real schema migration, async) (SPEC L3-6, L26-39).
- **Technical architecture** (SPEC L58-73): FastAPI (ASGI); pydantic v2; SQLAlchemy 2.x (declarative + `Session` explicit transaction boundary); SQLite (dev/test) and PostgreSQL (prod) with one ORM model set; Alembic v1 → v2 → v3 each with `downgrade`; `async def` endpoints + `asyncio.TaskGroup` background executor; `X-API-Key` header with hashed comparison; scopes `read` / `write` / `admin`; per-token token bucket; RFC 7807 `application/problem+json`; `asyncio.create_subprocess_exec` (no `shell=True`); `import-linter` layers contract.
- **Config parameters (SPEC §5.1)**: 12 `TASKQ_*` environment variables read by `config.py` and fully declared in `.env.example`:

| Variable | Default | Meaning |
|---|---|---|
| `TASKQ_DB_URL` | `sqlite:///./taskq.db` | DB connection string (must not appear in logs — NFR-04) |
| `TASKQ_DB_POOL_SIZE` | `5` | pool size (FR-06) |
| `TASKQ_TASK_TIMEOUT` | `10.0` | per-task subprocess timeout (s) |
| `TASKQ_MAX_CONCURRENT` | `8` | background concurrency cap (FR-08) |
| `TASKQ_DRAIN_TIMEOUT` | `30.0` | graceful drain limit on shutdown (s) |
| `TASKQ_RATE_BURST` | `20` | token bucket capacity (FR-05) |
| `TASKQ_RATE_PER_SEC` | `5.0` | token refill rate (FR-05) |
| `TASKQ_CORS_ORIGINS` | (empty string) | comma-separated allowed origins; empty = deny all (NFR-02) |
| `TASKQ_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `TASKQ_LOG_FORMAT` | `json` | `json` / `text` |
| `TASKQ_HOST` | `127.0.0.1` | listen address (default not externally exposed) |
| `TASKQ_PORT` | `8000` | listen port |

- **Database schema (SPEC §5.2)**, defined by FR-07 Alembic revisions: `tasks` (v1: `id` uuid, `command`, `name`, `status`, `created_at`); `api_keys` (v1: `id`, `key_hash` sha256, `scope`, `created_at`, `revoked_at`); `tags` (v2: `id`, `label`); `task_tags` (v2: `task_id`, `tag_id`, composite PK); `task_results` (v3: `id`, `task_id` FK, `exit_code`, `stdout_tail`, `stderr_tail`, `duration_ms`, `finished_at`); `rate_buckets` (v1: `key_id` FK, `tokens`, `updated_at`). `tasks.result_json` is created in v1 and removed in v3 (data moved to `task_results`) (SPEC L315).

## 2. Constraints

- **C-1** Language Python 3.11 (SPEC L53).
- **C-2** Required project-side files, not optional (SPEC §5.3, L317-327): `.importlinter` (NFR-06); `requirements.txt` + `requirements.lock` (NFR-07); `requirements-dev.txt` containing `import-linter` / `pip-licenses` / `mutmut` / `pytest-benchmark` / `httpx` (NFR-06/07/08/10); `alembic.ini` + `migrations/versions/` with three revisions (FR-07); `.env.example` declaring all 12 `TASKQ_*` with comments (§5.1); `.methodology/harness_config.json` with `features.mutation_testing: true`, `crg_cohesion_healthy` not lowered (NFR-08); `Makefile` with `verify-system` including migration round trip (NFR-12).
- **C-3** Source tree `03-development/src/`, tests `03-development/tests/` (SPEC §8 commands).
- **C-4** CRG calibration: "`crg_cohesion_healthy` 保持預設值,不得為了讓專案通過而調降" (SPEC L425).
- **C-5** High-risk modules requiring per-module TDD coverage: `taskq_api.service.runner`, `taskq_api.service.auth`, `taskq_api.repository.session`, `migrations/versions/v3_split_results.py` (SPEC L427).
- **C-6** Async scanner findings: "若它們在 async 語法上出現誤判或漏判,那本身就是本輪測床要交付的發現 —— 應記入 Phase 4 的 bug hunt,不得靜默繞過" (SPEC L429).

## 3. Functional Requirements

### FR-01: 任務資源 CRUD API

Citation: SPEC L79-91.

| Method | Path | scope | Behavior |
|---|---|---|---|
| `POST` | `/v1/tasks` | `write` | 建立任務;body 由 `TaskCreate` pydantic 模型驗證 |
| `GET` | `/v1/tasks/{id}` | `read` | 取得單一任務全欄位 |
| `GET` | `/v1/tasks` | `read` | 分頁列表,支援 `?status=`、`?limit=`、`?cursor=` |
| `DELETE` | `/v1/tasks/{id}` | `admin` | 刪除任務(連同結果列,同一交易) |

**Acceptance criteria (FR-01)**
- **AC-1.1** `POST /v1/tasks` with a valid `write` key returns 201 + task id — decided by the integration test for SPEC §8 #4 (`pytest 03-development/tests`), per SPEC L83, L361.
- **AC-1.2** `GET /v1/tasks/{id}` (scope `read`) returns the single task with all fields — decided by the CRUD-chain integration test (NFR-10), per SPEC L84.
- **AC-1.3** `GET /v1/tasks` supports `?status=`, `?limit=`, `?cursor=` — decided by the CRUD-chain integration test, per SPEC L85.
- **AC-1.4** `DELETE /v1/tasks/{id}` (scope `admin`) deletes the task together with its result rows in the same transaction — decided by the CRUD-chain integration test, per SPEC L86.
- **AC-1.5** "驗證規則同第 1 輪 FR-01(非空 / ≤1000 字元 / 注入字元黑名單 / 名稱唯一);違反 → **HTTP 422** + problem+json" — decided by the validation-error integration test (422 case, NFR-10), per SPEC L88. (See Open Issue NFR-99.2 and NFR-99.3.)
- **AC-1.6** Unknown id returns "**HTTP 404** + problem+json" — decided by the 404 integration test (SPEC §8 #7), per SPEC L89.
- **AC-1.7** Pagination is "**cursor-based**(不得用 offset)" — decided by the list-endpoint integration test, per SPEC L90.
- **AC-1.8** List endpoint default `limit` is 50, upper bound 200; exceeding the bound returns 422 — decided by the list-endpoint integration test, per SPEC L91.

### FR-02: 任務執行端點

Citation: SPEC L93-99.

**Acceptance criteria (FR-02)**
- **AC-2.1** `POST /v1/tasks/{id}/run` (scope `write`) returns "**HTTP 202 Accepted**,body 含 `run_id`" — decided by the run-endpoint integration test, per SPEC L95.
- **AC-2.2** Execution uses `asyncio.create_subprocess_exec(*shlex.split(command))`, "**禁 `shell=True`**", timeout is `TASKQ_TASK_TIMEOUT` — decided by the grep gate (SPEC §8 #16) and the timeout integration test, per SPEC L96.
- **AC-2.3** State machine is `pending → running → done | failed | timeout` — decided by the run-lifecycle integration test, per SPEC L97.
- **AC-2.4** Results are written to the `task_results` table (v3 schema) with columns `exit_code` / `stdout_tail` / `stderr_tail` / `duration_ms` / `finished_at` — decided by the run-lifecycle integration test and the migration test (FR-07), per SPEC L98.
- **AC-2.5** `GET /v1/tasks/{id}/runs` (scope `read`) returns the task's run history, "新到舊排序" — decided by the runs-history integration test, per SPEC L99.

### FR-03: API Key 認證

Citation: SPEC L101-107.

**Acceptance criteria (FR-03)**
- **AC-3.1** All `/v1/*` endpoints require the `X-API-Key` header; missing or invalid returns "**HTTP 401** + problem+json" — decided by the 401 integration test (SPEC §8 #5), per SPEC L103.
- **AC-3.2** Keys are "**以 SHA-256 雜湊儲存**於 `api_keys` 表,**不得存明文**"; comparison uses `hmac.compare_digest` — decided by the DB inspection test (SPEC §8 #18: no plaintext key; `key_hash` is 64 hex) and code review/grep for `hmac.compare_digest`, per SPEC L104, L374.
- **AC-3.3** Keys are produced by `python -m taskq_api key create --scope <scope>`; plaintext "只在建立當下印出一次" — decided by a CLI test of `key create`, per SPEC L105.
- **AC-3.4** A key whose `revoked_at` is non-null is always treated as invalid — decided by a revoked-key integration test (401), per SPEC L106.
- **AC-3.5** `/healthz` and `/readyz` do not require authentication — decided by the health-endpoint integration test, per SPEC L107.

### FR-04: Scope 授權

Citation: SPEC L109-113.

**Acceptance criteria (FR-04)**
- **AC-4.1** Each key carries one scope with hierarchy `read` < `write` < `admin` (inclusive) — decided by a scope-matrix integration test, per SPEC L111.
- **AC-4.2** Required scope per endpoint follows the FR-01/FR-02 tables; insufficient scope returns "**HTTP 403** + problem+json" — decided by the 403 integration test (SPEC §8 #6), per SPEC L112.
- **AC-4.3** The 403 "body 不得洩漏該資源是否存在" — decided by the SPEC §8 #6 test (`DELETE /v1/tasks/{id}` with write key, non-admin), per SPEC L112, L362.
- **AC-4.4** Authorization is decided in a "單一中介層(dependency)", "不得散落於各 handler" — decided by a test that asserts "每個 `/v1` 路由都經過同一個 dependency", per SPEC L113.

### FR-05: 流量控制

Citation: SPEC L115-120.

**Acceptance criteria (FR-05)**
- **AC-5.1** Per-token token bucket with capacity `TASKQ_RATE_BURST` and refill rate `TASKQ_RATE_PER_SEC` — decided by the rate-limit integration test (trigger and recovery, NFR-10), per SPEC L117.
- **AC-5.2** Over-limit returns "**HTTP 429** + problem+json + `Retry-After` header(秒)" — decided by the SPEC §8 #9 test (consecutive requests exceeding `TASKQ_RATE_BURST`), per SPEC L118, L365.
- **AC-5.3** Bucket state is stored in the database (consistent across workers); updates occur "在單一交易內以 row-level lock 進行" — decided by a repository-level test and code review of the `rate_buckets` update, per SPEC L119.
- **AC-5.4** `/healthz` and `/readyz` are not rate limited — decided by the health-endpoint integration test, per SPEC L120.

### FR-06: 持久化層與交易邊界

Citation: SPEC L122-128.

**Acceptance criteria (FR-06)**
- **AC-6.1** "全部資料存取經由 `repository/` 層,**業務層不得直接持有 `Session`**" — decided by `lint-imports` (NFR-06 forbidden contract), per SPEC L124.
- **AC-6.2** One `Session` per API request; "成功 commit、例外 rollback(以 context manager 保證)" — decided by a transaction-boundary test of `taskq_api.repository.session`, per SPEC L125.
- **AC-6.3** "**禁止字串拼接 SQL**;一律使用 ORM 或參數化查詢" — decided by the SQL-concatenation scan (SPEC §8 #17, 0 hits), per SPEC L126, L373.
- **AC-6.4** Relationship queries use `selectinload` / `joinedload` explicitly; "**N+1 為驗收失敗條件**" — decided by the SQL statement-count test (SPEC §8 #14), per SPEC L127, L370.
- **AC-6.5** Connection pool uses `pool_size=TASKQ_DB_POOL_SIZE` and `pool_pre_ping=True` — decided by a unit test inspecting the engine configuration, per SPEC L128.

### FR-07: Schema Migration(Alembic 三步演進)

Citation: SPEC L130-143.

| revision | upgrade | downgrade requirement |
|---|---|---|
| **v1** | 建立 `tasks`、`api_keys` 兩表 | drop 兩表 |
| **v2** | 新增 `tags`、`task_tags`(多對多)+ `tasks.name` 唯一索引 | drop 新表與索引,不影響 v1 資料 |
| **v3** | 含資料搬遷:把 `tasks.result_json` 拆為獨立的 `task_results` 表,搬遷既有資料後移除原欄位 | 反向搬遷回 `tasks.result_json` 後 drop `task_results`,資料不得遺失 |

**Acceptance criteria (FR-07)**
- **AC-7.1** Three revisions v1, v2, v3 exist, each with a working `downgrade` per the table above — decided by the real-DB migration tests (SQLite file, NFR-09), per SPEC L132-138.
- **AC-7.2** "`alembic upgrade head` 與 `alembic downgrade base` 必須都成功" — decided by SPEC §8 #13 (`alembic downgrade base` exit 0, no residual tables), per SPEC L140, L369.
- **AC-7.3** Round-trip: `upgrade head` → write sample data → `downgrade -1` → `upgrade head`; "樣本資料的欄位值必須逐欄相同" — decided by the real SQLite-file migration test (SPEC §8 #12), per SPEC L141, L368.
- **AC-7.4** "禁止以 `op.execute("DROP TABLE ...")` 之類的破壞性捷徑取代真正的 downgrade" — decided by the migration test with data comparison (AC-7.3) and code review of `migrations/versions/`, per SPEC L142.
- **AC-7.5** "migration 檔本身納入測試覆蓋(以 `alembic` 的 offline SQL 產生 + 斷言)" — decided by an alembic offline-SQL test, per SPEC L143.

### FR-08: 非同步執行器

Citation: SPEC L145-150.

**Acceptance criteria (FR-08)**
- **AC-8.1** Background execution is managed by `asyncio.TaskGroup`; on service shutdown "graceful drain"(等待進行中的任務至 `TASKQ_DRAIN_TIMEOUT`,逾時則標記 `interrupted`) — decided by the graceful-drain integration test (SPEC §8 #25), per SPEC L147, L381. (See Open Issue NFR-99.4.)
- **AC-8.2** Concurrency cap `TASKQ_MAX_CONCURRENT`; excess tasks queue, "不得無限制生成 coroutine" — decided by a runner concurrency test of `taskq_api.service.runner`, per SPEC L148.
- **AC-8.3** Task timeout is implemented with `asyncio.wait_for`; on timeout the subprocess is terminated (`process.kill()` then `await process.wait()`), "不得留下孤兒進程" — decided by the orphan-process integration test (SPEC §11 "孤兒子進程 0"), per SPEC L149, L453.
- **AC-8.4** "`asyncio.CancelledError` 必須向上傳播,**不得被 `except Exception` 吞掉**" — decided by a cancellation-propagation test (NFR-03), per SPEC L150.

### FR-09: 健康檢查與可觀測性

Citation: SPEC L152-160.

| Endpoint | Auth | Behavior |
|---|---|---|
| `GET /healthz` | 無 | 進程存活 → 200 `{"status":"ok"}` |
| `GET /readyz` | 無 | DB 連線可用 **且** `alembic current` == head → 200;否則 **503** 並在 body 說明哪一項失敗 |
| `GET /v1/metrics` | `admin` | 任務計數(按狀態)、執行延遲分位數、rate-limit 拒絕數 |

**Acceptance criteria (FR-09)**
- **AC-9.1** `GET /healthz` returns 200 `{"status":"ok"}` without authentication — decided by the health-endpoint integration test, per SPEC L156.
- **AC-9.2** `GET /readyz` returns 200 when the DB connection is available and `alembic current` == head — decided by the readiness integration test, per SPEC L157.
- **AC-9.3** With the DB stopped, `GET /readyz` returns "**503**,detail 指明 DB 不可用" — decided by the SPEC §8 #10 test, per SPEC L157, L366.
- **AC-9.4** After `alembic downgrade -1`, `GET /readyz` returns "**503**,detail 指明 migration 未到 head" (fail closed) — decided by the SPEC §8 #11 test, per SPEC L160, L367.
- **AC-9.5** `GET /v1/metrics` (scope `admin`) returns task counts by status, execution latency percentiles, and rate-limit rejection count — decided by the metrics integration test, per SPEC L158.

### FR-10: 錯誤契約(RFC 7807)

Citation: SPEC L162-168, §7 L331-347.

**Acceptance criteria (FR-10)**
- **AC-10.1** "全部非 2xx 回應的 `Content-Type` 為 `application/problem+json`" — decided by the per-error-code integration tests (NFR-10), per SPEC L164.
- **AC-10.2** Body fields: `type`(URI)、`title`、`status`、`detail`、`instance`、`correlation_id` — decided by the per-error-code integration tests, per SPEC L165.
- **AC-10.3** "`detail` 不得洩漏內部細節":不得含 SQL 陳述、堆疊追蹤、檔案路徑、資料庫結構描述 — decided by the 500-body inspection test (SPEC §8 #19) and the integration test behind SPEC §11 "錯誤 body 洩漏內部細節 0", per SPEC L166, L375, L451.
- **AC-10.4** `correlation_id` appears in both the `X-Correlation-Id` response header and the server log — decided by an integration test with log capture, per SPEC L167.
- **AC-10.5** Error mapping: 422 驗證 / 401 未認證 / 403 scope 不足 / 404 未知資源 / 409 名稱衝突 / 429 超限 / 503 未就緒 / 500 其他, with `type` values from SPEC §7: `/errors/validation`, `/errors/unauthenticated`, `/errors/forbidden`, `/errors/not-found`, `/errors/conflict`, `/errors/rate-limited`, `/errors/not-ready`, `/errors/internal` — decided by the per-error-code integration tests, per SPEC L168, L335-345.
- **AC-10.6** "任務 timeout" yields HTTP 200 with task status `timeout`; "`asyncio.CancelledError` **不屬於**上表任何一列 —— 它必須向上傳播,不得轉成 500" — decided by the timeout integration test and the cancellation test (AC-N3.3), per SPEC L344, L347.

## 4. Non-Functional Requirements

Dimension roster check: all dimensions below were verified present as `### <dimension>` headers in `harness/harness/ssi/prompts/evaluate_dimension.md`. No canonical dimension name is missing from the roster.

### NFR-01: 效能與查詢效率

Citation: SPEC L177-183. dimension: `performance`.

**Acceptance criteria (NFR-01)**
- **AC-N1.1** "`GET /v1/tasks/{id}` 在 10,000 筆資料下 **p95 < 30ms**(不含網路,以 ASGI transport 量測)" — decided by the `pytest-benchmark` test (SPEC §8 #15), per SPEC L179, L371.
- **AC-N1.2** "`GET /v1/tasks?limit=50` 在 10,000 筆資料下 **p95 < 80ms**" — decided by the `pytest-benchmark` test, per SPEC L180.
- **AC-N1.3** "N+1 為失敗條件:列表端點回應一次請求所發出的 SQL 陳述數必須是 **常數**(與回傳筆數無關),以 SQLAlchemy event listener 計數斷言" — decided by the SQL-statement-count test (SPEC §8 #14), per SPEC L182, L370.
  - **Coverage note**: the `performance` section of evaluate_dimension.md scores only mean latency from `benchmark_report.json` (penalty only at mean > 1000 ms / 3000 ms) and does not check p95 < 30/80 ms or the SQL statement count; AC-N1.1 to AC-N1.3 need dedicated test tasks. (See Open Issue NFR-99.1.)

### NFR-02: HTTP 與資料層安全

Citation: SPEC L185-194. dimension: `security`.

**Acceptance criteria (NFR-02)**
- **AC-N2.1** "全 codebase 禁用 `shell=True`、`eval(`、`exec(`(grep 0 命中)" — decided by `grep -rn "shell=True\|eval(\|exec(" 03-development/src/` (SPEC §8 #16), per SPEC L187-188, L372.
- **AC-N2.2** "禁止字串拼接 SQL:不得出現 f-string / `%` / `+` 組成的 SQL;一律 ORM 或參數化(以 grep + code review 雙重驗證)" — decided by the SQL-concatenation scan (SPEC §8 #17) plus code review, per SPEC L189, L373.
- **AC-N2.3** API key stored hashed; comparison uses `hmac.compare_digest` (FR-03) — decided by the SPEC §8 #18 DB inspection test, per SPEC L190.
- **AC-N2.4** 403 responses must not leak resource existence (FR-04) — decided by the SPEC §8 #6 test, per SPEC L191.
- **AC-N2.5** Error bodies must not contain stack/SQL/paths (FR-10) — decided by the SPEC §8 #19 test, per SPEC L192.
- **AC-N2.6** "CORS 預設**拒絕所有來源**;允許清單由 `TASKQ_CORS_ORIGINS` 明示" — decided by a CORS integration test, per SPEC L193.
- **AC-N2.7** "`bandit -r 03-development/src/`:**0 HIGH、0 MEDIUM**" — decided by `bandit -r 03-development/src/` (SPEC §8 #23), per SPEC L194, L379.
  - **Coverage note**: the `security` section of evaluate_dimension.md runs only bandit (`bandit -r src/`, score `100 - HIGH×10 - MEDIUM×3 - LOW×1`); AC-N2.1 to AC-N2.6 (grep gates, hashing, CORS, leakage) are not verified by that dimension and need dedicated implementation tasks.

### NFR-03: 錯誤處理、交易與非同步正確性

Citation: SPEC L196-204. dimension: `error_handling`.

**Acceptance criteria (NFR-03)**
- **AC-N3.1** "每個請求的交易邊界明確:成功 commit、例外 rollback,以 context manager 保證(FR-06)" — decided by the `taskq_api.repository.session` transaction test, per SPEC L199.
- **AC-N3.2** "**不得**出現裸 `except:`、`except Exception: pass`" — decided by the framework `ast-error-handling` scan (anti-patterns `bare_except`, `broad_swallow`), per SPEC L200.
- **AC-N3.3** "**`asyncio.CancelledError` 不得被吞掉** —— 必須重新拋出" — decided by a cancellation-propagation test of `taskq_api.service.runner`, per SPEC L201.
- **AC-N3.4** "資料庫連線失敗 → `/readyz` 503 + 明確 detail;不得靜默重試至無限" — decided by the SPEC §8 #10 test, per SPEC L202.
- **AC-N3.5** "任務 timeout 必須確實終止子進程,不留孤兒(FR-08)" — decided by the orphan-process integration test, per SPEC L203.
- **AC-N3.6** "migration 失敗 → 交易 rollback,資料庫維持在前一個 revision(FR-07)" — decided by a failing-migration test against a real SQLite file, per SPEC L204.
  - **Coverage note**: the `error_handling` section scores file-level handler presence and anti-patterns (`except_base_exception`, `bare_except`, `broad_swallow`); it does not verify `CancelledError` re-raise (it flags `except BaseException` only), commit/rollback, orphan processes, or migration rollback. AC-N3.1, N3.3 to N3.6 need dedicated implementation tasks.

### NFR-04: 敏感資料遮蔽

Citation: SPEC L206-212. dimension: `security`.

**Acceptance criteria (NFR-04)**
- **AC-N4.1** Before `stdout_tail` / `stderr_tail` / logs / error bodies are persisted or sent, lines matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+|Bearer\s+\S+|postgres(ql)?://[^\s]+)` are replaced whole-line with `[REDACTED]` — decided by a redaction unit test, per SPEC L209-210.
- **AC-N4.2** "資料庫連線字串(含密碼)不得出現在任何日誌、錯誤訊息或 `/v1/metrics` 回應中" — decided by the unit test behind SPEC §8 #20 / §11 "DB 連線字串出現於日誌 0", per SPEC L211, L376, L452.
- **AC-N4.3** "API key 明文只在 `key create` 當下輸出一次,不得寫入任何持久化位置" — decided by the `key create` test plus the DB inspection test (SPEC §8 #18), per SPEC L212.
  - **Coverage note**: the `security` section runs only bandit; redaction and secret-leak behavior are not verified by it and need dedicated implementation tasks.

### NFR-05: 文件覆蓋

Citation: SPEC L214-218. dimension: `documentation`.

**Acceptance criteria (NFR-05)**
- **AC-N5.1** "全部公開函式/類別有 docstring 且含 `[FR-XX]` 或 `[NFR-XX]` 引用,覆蓋率 **100%**" — decided by the framework `ast-docstrings` scan (docstring presence) for presence, per SPEC L217.
- **AC-N5.2** "每個 API 端點在 OpenAPI schema 中有 `summary` 與 `description`(FastAPI 自動產生的 `/openapi.json` 以測試斷言)" — decided by an OpenAPI-schema test asserting `summary` and `description` per operation, per SPEC L218.
  - **Coverage note**: the `documentation` section scores only docstring presence on public defs/classes; it does not check for the `[FR-XX]`/`[NFR-XX]` reference (AC-N5.1 part) nor OpenAPI summary/description (AC-N5.2); these need dedicated implementation tasks.

### NFR-06: 架構分層契約

Citation: SPEC L220-232. dimension: `architecture_constraints`.

**Acceptance criteria (NFR-06)**
- **AC-N6.1** "專案根目錄**必須存在 `.importlinter`**,宣告 layers contract: `api > service > repository > models`";上層可 import 下層,下層不得 import 上層;`config` 與 `errors` 為 independence 模組 — decided by `lint-imports` (SPEC §8 #21), per SPEC L223-229.
- **AC-N6.2** Forbidden contract: "`repository` 以外的任何層**不得 import `sqlalchemy`**" — decided by `lint-imports`, with a test that a `service`/`api` import of `sqlalchemy` is blocked (SPEC §8 #21), per SPEC L230, L377.
- **AC-N6.3** "`lint-imports` 必須 **exit 0**" — decided by `lint-imports` exit code (SPEC §8 #21), per SPEC L231.
- **AC-N6.4** "禁止以刪除 `.importlinter`、萬用字元 `ignore_imports`、或降級 contract 的方式取得通過" — decided by code review of `.importlinter` in Agent B review and the Gate 1 `architecture_constraints` run, per SPEC L232.
  - **Coverage note**: the `architecture_constraints` section checks only `lint-imports` exit code (no `.importlinter` makes it unscoreable); it does not inspect contract content, so AC-N6.1, N6.2, N6.4 (layers, `sqlalchemy` forbidden contract, no wildcard ignores) need a dedicated task to author and verify the contract.

### NFR-07: 依賴與授權合規

Citation: SPEC L234-240. dimension: `license_compliance`.

**Acceptance criteria (NFR-07)**
- **AC-N7.1** "全部 runtime 依賴在 `requirements.txt` 以 `==` 釘版;**transitive 依賴以 lock 檔(`requirements.lock`)完整鎖定**" — decided by a test parsing `requirements.txt` and `requirements.lock`, per SPEC L237.
- **AC-N7.2** Allowed licenses are MIT / BSD-2-Clause / BSD-3-Clause / Apache-2.0 / PSF; others not allowed — decided by `pip-licenses --format=json --with-system` (SPEC §8 #22), per SPEC L238, L378.
- **AC-N7.3** "掃描範圍必須包含完整依賴樹(直接 + transitive),證據命令:`pip-licenses --format=json --with-system`" — decided by `pip-licenses --format=json --with-system`, per SPEC L239.
- **AC-N7.4** SBOM at `08-config/SBOM.json` containing per dependency `name` / `version` / `license` / `direct|transitive` — decided by an SBOM-content test, per SPEC L240.
  - **Coverage note**: the `license_compliance` section runs `scancode --license` on `src/` only; it does not scan the dependency tree, apply the allowlist, check pins/lock, or produce an SBOM. AC-N7.1 to N7.4 need dedicated implementation tasks.

### NFR-08: 變異測試

Citation: SPEC L242-247. dimension: `mutation_testing`.

**Acceptance criteria (NFR-08)**
- **AC-N8.1** "`.methodology/harness_config.json` 設 `features.mutation_testing: true`" — decided by a config-content test, per SPEC L245.
- **AC-N8.2** "**mutation score ≥ 70**" — decided by `mutmut run` then `mutmut results` (SPEC §8 #24), via `harness_cli.py mutation-test-score`, per SPEC L246, L380.
- **AC-N8.3** "範圍限定於 `service/` 與 `repository/` 兩層,並在 `harness_config.json` 註記限定理由(執行時間預算)" — decided by a config-content test checking the scope and the recorded rationale, per SPEC L247.
  - **Coverage note**: the `mutation_testing` section produces the score through the framework `compute_mutation_score`; it does not verify the `service/` + `repository/` scope restriction or the recorded rationale (AC-N8.3); that needs a dedicated task.

### NFR-09: 驗證真實性(零 skip 鐵律)

Citation: SPEC L249-257. dimension: `test_assertion_quality`.

**Acceptance criteria (NFR-09)**
- **AC-N9.1** "任何 FR / NFR 的驗證測試不得是 `pytest.skip` / `skipif` / `xfail` / 無斷言的 stub" — decided by `pytest 03-development/tests -q` output and the `ast-assertions` scan, per SPEC L252.
- **AC-N9.2** "`pytest 03-development/tests -q` 的 **skipped 計數必須為 0**" — decided by `pytest 03-development/tests -q` (SPEC §8 #1), per SPEC L253, L357.
- **AC-N9.3** "每個測試函式至少一個 `assert`(`zero_assert == 0`)" — decided by the framework `ast-assertions` scan, per SPEC L254.
- **AC-N9.4** "不得以 `--ignore` / `-k` / `--deselect` / `collect_ignore` / 從 `testpaths` 移除目錄的方式排除測試" — decided by code review of pytest configuration in Agent B review, per SPEC L255.
- **AC-N9.5** "`FR-07` 的三步 migration 必須以**真實資料庫**測試(SQLite 檔案,非 in-memory mock),往返可逆性以實際資料比對驗證" — decided by the FR-07 migration tests (AC-7.3), per SPEC L256.
- **AC-N9.6** "`TRACEABILITY_MATRIX.md` 的 `VERIFIED` 只能在測試實際執行並通過時給出" — decided by `TRACEABILITY_MATRIX.md` consistency check against pytest results in a downstream phase, per SPEC L257.
  - **Coverage note**: the `test_assertion_quality` section scores only the share of tests with at least one assertion; skipped count 0 (AC-N9.2), exclusion bans (AC-N9.4), real-DB migration tests (AC-N9.5) and VERIFIED honesty (AC-N9.6) are not verified by it and need dedicated implementation tasks.

### NFR-10: 整合覆蓋

Citation: SPEC L259-264. dimension: `integration_coverage`.

**Acceptance criteria (NFR-10)**
- **AC-N10.1** "`03-development/tests/integration/` 行覆蓋 **≥ 80%**" — decided by `pytest 03-development/tests/integration --cov=03-development/src --cov-report=term` (SPEC §8 #3), per SPEC L262, L359.
- **AC-N10.2** "整合測試以 `httpx.AsyncClient(transport=ASGITransport(app))` 驅動,**不得直接呼叫 handler 函式**" — decided by code review of `03-development/tests/integration/` in Agent B review, per SPEC L263.
- **AC-N10.3** Coverage includes "CRUD 全鏈、401/403/404/409/422/429/503 每個錯誤碼各一例、migration 往返、rate limit 觸發與恢復、graceful drain" — decided by the TEST_SPEC.md coverage check against the integration test list, per SPEC L264.
  - **Coverage note**: the `integration_coverage` section measures line coverage only; it does not verify ASGITransport usage (AC-N10.2) or the enumerated scenarios (AC-N10.3), which need dedicated tasks.

### NFR-11: 可讀性

Citation: SPEC L266-271. dimension: `readability`.

**Acceptance criteria (NFR-11)**
- **AC-N11.1** "專案 MI(LLOC 加權)**≥ 80**" — decided by `radon mi` via the framework `readability` scoring, per SPEC L269.
- **AC-N11.2** "單一函式 CC **≤ 10**" — decided by `radon cc`, per SPEC L269.
- **AC-N11.3** "單一檔案 ≤ 400 行;單一目錄 ≤ 15 檔" — decided by a file/directory size test, per SPEC L270.
- **AC-N11.4** "每個 API handler ≤ 40 行(業務邏輯必須下沉到 `service/`)" — decided by an AST handler-length test, per SPEC L271.
  - **Coverage note**: the `readability` section averages per-file MI only (unweighted by LLOC); CC, file/directory size and handler length are not verified. AC-N11.1 (LLOC weighting) to AC-N11.4 need dedicated tasks.

### NFR-12: 系統驗證目標

Citation: SPEC L273-281. dimension: `execute_verification_target`.

**Acceptance criteria (NFR-12)**
- **AC-N12.1** "`Makefile` 的 `verify-system` target 必須串接:1. `alembic upgrade head` 2. 全套測試 3. 服務啟動 + `/healthz`、`/readyz` 冒煙 4. `alembic downgrade base` 後再 `upgrade head`(往返驗證)" — decided by a Makefile-content test (`# NFR-12`), per SPEC L276-280.
- **AC-N12.2** "`make verify-system` 必須 **exit 0** 並在 stdout 印出 `verify-system: PASS`" — decided by `make verify-system` (SPEC §8 #27), per SPEC L281, L383.
- **AC-N12.3** DERIVED: SPEC L382 — §8 #26 has no owning NFR; attached to NFR-12 as the nearest system-level verification. `grep -c "^TASKQ_" .env.example` returns "**12**(§5.1 全部宣告)" — decided by that grep command (SPEC §8 #26), per SPEC L325, L382.
  - **Coverage note**: the `execute_verification_target` section checks only that `make verify-system` exits 0; it does not read the target's steps (AC-N12.1) or the `verify-system: PASS` string (AC-N12.2), which need a dedicated test.

## 5. Acceptance Criteria Summary

SPEC §8 (L351-383) lists 27 machine-decidable commands. Mapping to this SRS:

| SPEC §8 # | Command / action | Expected | AC |
|---|---|---|---|
| 1 | `pytest 03-development/tests -q` | all green, skipped 0 | AC-N9.2 |
| 2 | `pytest 03-development/tests --cov=03-development/src --cov-report=term` | TOTAL 100% | AC-N9.1 (SPEC L358, §11 L442) |
| 3 | integration `--cov` run | TOTAL ≥ 80% | AC-N10.1 |
| 4 | `POST /v1/tasks` (valid write key) | 201 + task id | AC-1.1 |
| 5 | `POST /v1/tasks` (no `X-API-Key`) | 401 + problem+json | AC-3.1 |
| 6 | `DELETE /v1/tasks/{id}` (write key) | 403, no existence leak | AC-4.2, AC-4.3 |
| 7 | `GET /v1/tasks/{unknown}` | 404 + problem+json | AC-1.6 |
| 8 | `POST /v1/tasks` duplicate name | 409 | AC-10.5 (see NFR-99.3) |
| 9 | requests beyond `TASKQ_RATE_BURST` | 429 + `Retry-After` | AC-5.2 |
| 10 | stop DB, `GET /readyz` | 503, DB unavailable | AC-9.3 |
| 11 | `alembic downgrade -1`, `GET /readyz` | 503, migration not at head | AC-9.4 |
| 12 | upgrade → sample → `downgrade -1` → upgrade | sample identical per column | AC-7.3 |
| 13 | `alembic downgrade base` | exit 0, no residual tables | AC-7.2 |
| 14 | SQL statement count, `GET /v1/tasks?limit=50` (10,000 rows) | constant | AC-N1.3 |
| 15 | `GET /v1/tasks/{id}` p95 (10,000 rows) | < 30ms | AC-N1.1 |
| 16 | `grep -rn "shell=True\|eval(\|exec(" 03-development/src/` | 0 hits | AC-N2.1 |
| 17 | SQL string concatenation scan | 0 hits | AC-N2.2 |
| 18 | inspect `api_keys` | no plaintext; `key_hash` 64 hex | AC-3.2, AC-N2.3 |
| 19 | trigger 500, inspect body | no stack/SQL/path | AC-10.3, AC-N2.5 |
| 20 | logs and `/v1/metrics` full text | no `TASKQ_DB_URL` password fragment | AC-N4.2 |
| 21 | `lint-imports` | exit 0; `service`/`api` `sqlalchemy` import blocked | AC-N6.1, AC-N6.2, AC-N6.3 |
| 22 | `pip-licenses --format=json --with-system` | every license in allowlist | AC-N7.2, AC-N7.3 |
| 23 | `bandit -r 03-development/src/` | 0 HIGH, 0 MEDIUM | AC-N2.7 |
| 24 | `mutmut run` then `mutmut results` | score ≥ 70 | AC-N8.2 |
| 25 | shutdown with in-flight tasks | graceful drain; `interrupted`; no orphans | AC-8.1, AC-8.3 |
| 26 | `grep -c "^TASKQ_" .env.example` | 12 | AC-N12.3 |
| 27 | `make verify-system` | exit 0, `verify-system: PASS` | AC-N12.2 |

Quality gate thresholds (SPEC §11, L433-455) are reproduced by the ACs above: p95 30ms / 80ms, constant SQL count, skips 0, zero-assert 0, line coverage 100%, integration coverage ≥ 80%, migration round-trip 100% per column, mutation ≥ 70, `lint-imports` violations 0, `sqlalchemy` imports outside `repository` 0, non-allowlist licenses 0, SQL concatenation hits 0, bandit 0/0, error-body leaks 0, DB URL in logs 0, orphan subprocesses 0, MI ≥ 80, `make verify-system` exit 0.

Framework dimension alignment (SPEC §10, L406-423) additionally names `linting` (ruff), `type_safety` (pyright), `test_coverage` (pytest-cov; §8 #1/#2), `architecture` (code-review-graph; NFR-06 four layers + FR-07 migrations) and `secrets_scanning` (gitleaks, framework default threshold 100) as framework-default gates; they carry no separate FR/NFR.

## 6. Out-of-Scope

- Behavior defined only in the previous test bed spec (`taskq-plus` SPEC v1.0.0) beyond what SPEC.md restates; see Open Issue NFR-99.2.
- Third-round test bed concerns (SPEC L19 "第 2 輪 / 共 3 輪"); no requirement in SPEC.md describes them.
- SPEC.md has no section numbered 6; nothing was omitted (headings run §5 → §7).

## 7. Open Issues

- **NFR-99.1** Resolve NFR-01 measurement ambiguity — current SPEC phrasing ("p95 < 30ms" with "量測方式:`pytest-benchmark`", SPEC L179, L183) is ambiguous between p95 computed from benchmark rounds and the mean/median statistics that pytest-benchmark reports by default; test harness to confirm with stakeholder. AC-N1.1/N1.2 transcribe the canonical phrase only.
- **NFR-99.2** Resolve FR-01 validation-rule ambiguity — "驗證規則同第 1 輪 FR-01(非空 / ≤1000 字元 / 注入字元黑名單 / 名稱唯一)" (SPEC L88) refers to the previous test bed spec, and the 注入字元黑名單 character set is not stated in SPEC.md; test harness to confirm with stakeholder.
- **NFR-99.3** Resolve name-uniqueness status ambiguity in FR-01 / FR-10 — SPEC L88 says validation violations including 名稱唯一 return 422, while SPEC L168, L341 and §8 #8 say task name conflict returns 409; the current SPEC phrasing is ambiguous between 422 and 409 for a duplicate name; test harness to confirm with stakeholder.
- **NFR-99.4** Resolve FR-02 / FR-08 status vocabulary ambiguity — FR-02 state machine is `pending → running → done | failed | timeout` (SPEC L97), while FR-08 marks drain-timeout tasks `interrupted` (SPEC L147); ambiguous whether `interrupted` is an additional state; test harness to confirm with stakeholder.
- **NFR-99.5** Resolve NFR-05 coverage scope ambiguity — "全部公開函式/類別有 docstring 且含 `[FR-XX]` 或 `[NFR-XX]` 引用,覆蓋率 100%" (SPEC L217) does not define whether this applies to `migrations/versions/` revision functions; test harness to confirm with stakeholder.
- **NFR-99.6** Resolve scope-of-100% ambiguity — SPEC §8 #2 requires TOTAL 100% line coverage (SPEC L358, L442) with no stated exclusions for `config.py`/`__main__` entry code; test harness to confirm with stakeholder.
- Prompt-injection scan of SPEC.md: no hits; no clause deferred (no `FR-XX-deferred` items).
- No TBD / TODO / placeholder markers were found in SPEC.md.

## 8. Risks

Transcribed from SPEC §9 (L387-402):

| ID | Risk | Impact | Likelihood | Mitigation |
|----|------|--------|------------|------------|
| R1 | v3 data migration loses data | High | Medium | real-DB per-column round-trip test (FR-07 / §8 #12) |
| R2 | SQL injection | High | Low | no string-built SQL + ORM/parameterized + grep gate (NFR-02) |
| R3 | API key leakage | High | Medium | hashed storage + constant-time compare + plaintext printed once (FR-03) |
| R4 | 403 leaks resource existence | Medium | Medium | authorization decided before resource lookup (FR-04 / §8 #6) |
| R5 | N+1 queries collapse on large tables | High | High | explicit eager loading + SQL count assertion (NFR-01 / §8 #14) |
| R6 | Error body leaks internal structure | Medium | High | fixed RFC 7807 fields + detail whitelist (FR-10) |
| R7 | `CancelledError` swallowed, shutdown hangs | Medium | Medium | explicit ban + test assertion (NFR-03) |
| R8 | Task timeout leaves orphan process | Medium | Medium | `kill()` + `await wait()` (FR-08 / §8 #25) |
| R9 | Migration forgotten after deploy | High | Medium | `/readyz` fails closed (FR-09 / §8 #11) |
| R10 | Connection pool exhaustion | Medium | Medium | `pool_pre_ping` + concurrency cap (FR-06/08) |
| R11 | Transitive dependency brings incompatible license | Medium | Medium | lock file + full-tree scan (NFR-07) |
| R12 | Rate bucket race causes over-admission | Low | Medium | single transaction + row-level lock (FR-05) |

## 9. Glossary

| Term | Definition |
|------|------------|
| ASGI | Async server gateway interface; FastAPI app is served via `uvicorn` |
| Alembic | DB migration tool; revisions v1, v2, v3 |
| N+1 | Query count growing with returned rows; acceptance failure (NFR-01) |
| Token bucket | Per-token rate limiter with capacity `TASKQ_RATE_BURST` and refill `TASKQ_RATE_PER_SEC` (FR-05) |
| Scope | `read` < `write` < `admin` privilege level on an API key (FR-04) |
| RFC 7807 | `application/problem+json` error format (FR-10) |
| Problem+json | Error body with `type`, `title`, `status`, `detail`, `instance`, `correlation_id` |
| Fail closed | `/readyz` returns 503 when migration is not at head (FR-09) |
| Graceful drain | Waiting for in-flight tasks up to `TASKQ_DRAIN_TIMEOUT` at shutdown (FR-08) |
| Round-trip reversibility | `upgrade head` → sample data → `downgrade -1` → `upgrade head` yields identical column values (FR-07) |
| MI / CC | Maintainability Index / Cyclomatic Complexity (NFR-11) |
| SBOM | Software bill of materials at `08-config/SBOM.json` (NFR-07) |

## FR Block (machine-readable)

<!-- FR:START -->
```json
{
  "version": "1.0",
  "created_at": "2026-10-04",
  "phase": 1,
  "project": "taskq-api",
  "functional_requirements": [
    {
      "id": "FR-01",
      "description": "任務資源 CRUD API: POST/GET/GET list (cursor-based)/DELETE under /v1/tasks with scopes write/read/read/admin; 422 validation, 404 unknown id, default limit 50 max 200",
      "implementation_functions": ["taskq_api.api.tasks", "taskq_api.service.tasks", "taskq_api.repository.tasks"],
      "verification_method": "integration tests via httpx ASGITransport (CRUD chain, 404, 422)"
    },
    {
      "id": "FR-02",
      "description": "任務執行端點: POST /v1/tasks/{id}/run returns 202 with run_id; create_subprocess_exec without shell=True; state machine pending->running->done|failed|timeout; task_results persisted; GET /v1/tasks/{id}/runs newest first",
      "implementation_functions": ["taskq_api.service.runner", "taskq_api.api.runs", "taskq_api.repository.results"],
      "verification_method": "integration tests for run lifecycle and runs history; grep gate for shell=True"
    },
    {
      "id": "FR-03",
      "description": "API Key 認證: X-API-Key required on /v1/*; SHA-256 hashed storage; hmac.compare_digest; key create CLI prints plaintext once; revoked_at keys invalid; /healthz and /readyz exempt",
      "implementation_functions": ["taskq_api.service.auth", "taskq_api.repository.api_keys", "taskq_api.__main__"],
      "verification_method": "401 integration test, DB inspection test, key create CLI test"
    },
    {
      "id": "FR-04",
      "description": "Scope 授權: read<write<admin; 403 problem+json without leaking resource existence; authorization in a single dependency used by every /v1 route",
      "implementation_functions": ["taskq_api.service.auth.require_scope"],
      "verification_method": "403 integration test, route-dependency assertion test"
    },
    {
      "id": "FR-05",
      "description": "流量控制: per-token token bucket (TASKQ_RATE_BURST, TASKQ_RATE_PER_SEC) stored in DB with row-level lock in a single transaction; 429 + Retry-After; health endpoints exempt",
      "implementation_functions": ["taskq_api.service.rate_limit", "taskq_api.repository.rate_buckets"],
      "verification_method": "rate-limit trigger and recovery integration test"
    },
    {
      "id": "FR-06",
      "description": "持久化層與交易邊界: repository layer only; one Session per request with commit/rollback context manager; no string-built SQL; explicit eager loading (no N+1); pool_size and pool_pre_ping",
      "implementation_functions": ["taskq_api.repository.session", "taskq_api.repository"],
      "verification_method": "transaction boundary test, SQL statement count test, lint-imports, SQL concatenation scan"
    },
    {
      "id": "FR-07",
      "description": "Schema Migration (Alembic v1/v2/v3): each revision has working downgrade; v3 migrates tasks.result_json to task_results reversibly; upgrade head and downgrade base succeed; offline SQL tested",
      "implementation_functions": ["migrations/versions/v1", "migrations/versions/v2", "migrations/versions/v3_split_results"],
      "verification_method": "real SQLite-file migration round-trip test with per-column data comparison; alembic offline SQL test"
    },
    {
      "id": "FR-08",
      "description": "非同步執行器: asyncio.TaskGroup, graceful drain up to TASKQ_DRAIN_TIMEOUT marking interrupted, TASKQ_MAX_CONCURRENT queueing, wait_for timeout with kill + await wait, CancelledError propagates",
      "implementation_functions": ["taskq_api.service.runner", "taskq_api.app.lifespan"],
      "verification_method": "graceful drain integration test, orphan process test, cancellation propagation test"
    },
    {
      "id": "FR-09",
      "description": "健康檢查與可觀測性: /healthz 200; /readyz 200 only when DB available and alembic current == head else 503 with failing item; /v1/metrics (admin) task counts, latency percentiles, rate-limit rejections",
      "implementation_functions": ["taskq_api.api.health", "taskq_api.api.metrics", "taskq_api.service.metrics"],
      "verification_method": "integration tests for DB down and migration-behind-head 503"
    },
    {
      "id": "FR-10",
      "description": "錯誤契約 (RFC 7807): all non-2xx as application/problem+json with type/title/status/detail/instance/correlation_id; detail leaks no internals; X-Correlation-Id header matches log; status mapping 422/401/403/404/409/429/503/500",
      "implementation_functions": ["taskq_api.errors", "taskq_api.api.error_handlers"],
      "verification_method": "per-error-code integration tests, 500 body leak inspection"
    }
  ],
  "non_functional_requirements": [
    {
      "id": "NFR-01",
      "type": "performance",
      "description": "p95 < 30ms for GET /v1/tasks/{id} and < 80ms for GET /v1/tasks?limit=50 at 10,000 rows; constant SQL statement count (no N+1)",
      "test_method": "pytest-benchmark; SQLAlchemy event listener statement-count assertion"
    },
    {
      "id": "NFR-02",
      "type": "security",
      "description": "No shell=True/eval(/exec(; no string-built SQL; hashed API keys with hmac.compare_digest; no 403 existence leak; no internals in error body; CORS deny-all by default; bandit 0 HIGH 0 MEDIUM",
      "test_method": "grep gates, bandit -r 03-development/src/, integration tests"
    },
    {
      "id": "NFR-03",
      "type": "reliability",
      "description": "Explicit commit/rollback per request; no bare except or except Exception: pass; CancelledError re-raised; DB failure gives /readyz 503; no orphan subprocess; failed migration rolls back",
      "test_method": "ast-error-handling scan; transaction, cancellation, orphan-process and migration-failure tests"
    },
    {
      "id": "NFR-04",
      "type": "security",
      "description": "Lines matching the secret regex are replaced by [REDACTED] in stdout_tail/stderr_tail/logs/error bodies; DB URL never in logs, errors or /v1/metrics; API key plaintext printed once only",
      "test_method": "redaction unit test; log and metrics inspection test"
    },
    {
      "id": "NFR-05",
      "type": "documentation",
      "description": "100% public functions/classes have docstrings citing [FR-XX]/[NFR-XX]; every endpoint has OpenAPI summary and description",
      "test_method": "ast-docstrings scan; /openapi.json assertion test"
    },
    {
      "id": "NFR-06",
      "type": "layering",
      "description": ".importlinter layers api > service > repository > models, config and errors independent, sqlalchemy forbidden outside repository; lint-imports exit 0; no weakening of the contract",
      "test_method": "lint-imports"
    },
    {
      "id": "NFR-07",
      "type": "licensing",
      "description": "Runtime deps pinned with ==, transitive deps in requirements.lock; allowed licenses MIT/BSD-2-Clause/BSD-3-Clause/Apache-2.0/PSF over the full tree; SBOM at 08-config/SBOM.json",
      "test_method": "pip-licenses --format=json --with-system; SBOM content test"
    },
    {
      "id": "NFR-08",
      "type": "mutation",
      "description": "features.mutation_testing true in harness_config.json; mutation score >= 70 restricted to service/ and repository/ with rationale recorded",
      "test_method": "mutmut run / mutmut results via harness_cli mutation-test-score"
    },
    {
      "id": "NFR-09",
      "type": "testability",
      "description": "Zero skip/skipif/xfail/stub tests; skipped count 0; every test has an assert; no test exclusion mechanisms; FR-07 migrations tested on a real SQLite file; VERIFIED only when tests actually pass",
      "test_method": "pytest 03-development/tests -q; ast-assertions scan; pytest config review"
    },
    {
      "id": "NFR-10",
      "type": "integration",
      "description": "Integration tests line coverage >= 80% driven by httpx AsyncClient ASGITransport; cover CRUD chain, 401/403/404/409/422/429/503, migration round-trip, rate limit trigger/recovery, graceful drain",
      "test_method": "pytest 03-development/tests/integration --cov=03-development/src --cov-report=term"
    },
    {
      "id": "NFR-11",
      "type": "maintainability",
      "description": "Project MI >= 80 (LLOC weighted); function CC <= 10; file <= 400 lines; directory <= 15 files; API handler <= 40 lines",
      "test_method": "radon mi/cc; file and handler size tests"
    },
    {
      "id": "NFR-12",
      "type": "verifiability",
      "description": "make verify-system chains alembic upgrade head, full tests, service smoke on /healthz and /readyz, downgrade base then upgrade head; exits 0 and prints verify-system: PASS; grep -c \"^TASKQ_\" .env.example returns 12",
      "test_method": "make verify-system; Makefile content test; grep -c \"^TASKQ_\" .env.example"
    }
  ]
}
```
<!-- FR:END -->

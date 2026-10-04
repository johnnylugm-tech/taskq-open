# TEST_PLAN — taskq-api (Phase 4)

Source: `01-requirements/SRS.md` (10 FR / 12 NFR), `.methodology/quality_manifest.json` (fr_ids FR-01..FR-10).
Categories: **POS** positive, **NEG** negative, **BND** boundary, **EDG** edge. Priority: P0 (gate-blocking), P1 (required), P2 (nice-to-have).
Conventions: integration tests use `httpx.AsyncClient(transport=ASGITransport(app))` (AC-N10.2); migration tests use a real SQLite file (AC-N9.5); zero skip/xfail (AC-N9.2). Open Issues NFR-99.1..99.6 are flagged where a case depends on them.
Keys: R=read, W=write, A=admin.

## 1. Functional Requirements

### FR-01 Task CRUD (AC-1.1..1.8)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR01-01 | POS | Create task (AC-1.1) | POST /v1/tasks W key, valid command+name | 201, body has id (uuid) | P0 |
| TC-FR01-02 | POS | Get task (AC-1.2) | GET /v1/tasks/{id} R key | 200, all fields (id, command, name, status, created_at) | P0 |
| TC-FR01-03 | POS | List with status filter (AC-1.3) | GET /v1/tasks?status=pending | 200, only pending tasks | P0 |
| TC-FR01-04 | POS | Delete task + results same txn (AC-1.4) | DELETE /v1/tasks/{id} A key after a run | 204/200; task and task_results rows gone | P0 |
| TC-FR01-05 | POS | CRUD chain end to end | create, get, list, delete, get | final get 404 | P0 |
| TC-FR01-06 | NEG | Empty command (AC-1.5) | command="" | 422 problem+json | P0 |
| TC-FR01-07 | NEG | Command contains blacklisted injection char (NFR-99.2) | command with `;`/`|`/backtick | 422 problem+json | P1 |
| TC-FR01-08 | NEG | Duplicate name (NFR-99.3) | POST same name twice | 409 `/errors/conflict` (SPEC §8 #8) | P0 |
| TC-FR01-09 | NEG | Unknown id GET (AC-1.6) | GET random uuid | 404 problem+json `/errors/not-found` | P0 |
| TC-FR01-10 | NEG | Unknown id DELETE | DELETE random uuid, A key | 404 problem+json | P1 |
| TC-FR01-11 | NEG | Malformed id | GET /v1/tasks/not-a-uuid | 422 or 404 problem+json, no internals | P1 |
| TC-FR01-12 | NEG | Missing required field / wrong types | body `{}` / command=123 | 422 | P1 |
| TC-FR01-13 | BND | command length 1000 / 1001 (AC-1.5) | 1000 chars / 1001 chars | 201 / 422 | P0 |
| TC-FR01-14 | BND | command length 1 | "a" | 201 | P2 |
| TC-FR01-15 | BND | limit default (AC-1.8) | GET /v1/tasks, 60 tasks | 50 items | P0 |
| TC-FR01-16 | BND | limit 200 / 201 / 0 / -1 | each | 200 OK / 422 / 422 / 422 | P0 |
| TC-FR01-17 | EDG | Cursor pagination (AC-1.7) | walk pages with cursor, limit=7 over 20 tasks | no dup, no gap, final page has no next cursor; `offset` param not supported | P0 |
| TC-FR01-18 | EDG | Invalid/tampered cursor | cursor=garbage | 422 problem+json | P1 |
| TC-FR01-19 | EDG | Empty list | no tasks | 200, empty items | P1 |
| TC-FR01-20 | EDG | Unicode name/command | CJK + emoji name | 201 round-trips exactly | P2 |
| TC-FR01-21 | EDG | Delete atomicity | force failure mid-delete | task and results both remain (rollback) | P1 |
| TC-FR01-22 | EDG | Name whitespace-only | name="   " | 422 | P1 |

### FR-02 Task execution (AC-2.1..2.5)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR02-01 | POS | Run returns 202 (AC-2.1) | POST /v1/tasks/{id}/run W key | 202, body has run_id | P0 |
| TC-FR02-02 | POS | Lifecycle success (AC-2.3) | command `echo hi` | pending -> running -> done | P0 |
| TC-FR02-03 | POS | Result row persisted (AC-2.4) | after done | task_results: exit_code 0, stdout_tail "hi", stderr_tail "", duration_ms>=0, finished_at set | P0 |
| TC-FR02-04 | POS | Runs history newest first (AC-2.5) | run 3 times, GET /runs R key | 3 entries ordered newest to oldest | P0 |
| TC-FR02-05 | NEG | Non-zero exit | command `false` | status failed, exit_code 1 | P0 |
| TC-FR02-06 | NEG | Timeout (AC-2.2, AC-10.6) | `sleep 30`, TASKQ_TASK_TIMEOUT=0.5 | status timeout; HTTP responses remain 200/202 | P0 |
| TC-FR02-07 | NEG | Run unknown id | random uuid | 404 problem+json | P0 |
| TC-FR02-08 | NEG | Command not found | `nonexistent_bin_xyz` | status failed (no 500, no leak) | P1 |
| TC-FR02-09 | NEG | Read key cannot run | R key | 403 | P0 |
| TC-FR02-10 | BND | Empty runs history | GET /runs on never-run task | 200, empty list | P1 |
| TC-FR02-11 | BND | stdout larger than tail limit | command printing >> tail size | stdout_tail truncated to tail size, ends with last bytes | P1 |
| TC-FR02-12 | EDG | No shell interpretation | command `echo a && echo b` (shlex.split) | stdout is literal `a && echo b`, no second command | P0 |
| TC-FR02-13 | EDG | Quoted args via shlex | `echo "a b"` | one argument | P1 |
| TC-FR02-14 | EDG | Grep gate (SPEC §8 #16) | grep `shell=True` in src | 0 hits | P0 |
| TC-FR02-15 | EDG | Concurrent runs of same task | two POST /run | two distinct run_ids and two result rows | P1 |
| TC-FR02-16 | EDG | Secret in output redacted | command prints `token=abc` | stored tail contains `[REDACTED]` (NFR-04) | P0 |

### FR-03 API key authentication (AC-3.1..3.5)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR03-01 | POS | Valid key accepted | valid key on GET /v1/tasks | 200 | P0 |
| TC-FR03-02 | POS | CLI key create (AC-3.3) | `python -m taskq_api key create --scope read` | plaintext printed exactly once; exit 0 | P0 |
| TC-FR03-03 | POS | Hash storage (AC-3.2, §8 #18) | inspect api_keys | no plaintext anywhere; key_hash matches `^[0-9a-f]{64}$` = sha256(plaintext) | P0 |
| TC-FR03-04 | POS | Health endpoints unauthenticated (AC-3.5) | GET /healthz, /readyz no key | not 401 | P0 |
| TC-FR03-05 | NEG | Missing header (AC-3.1, §8 #5) | POST /v1/tasks no key | 401 problem+json `/errors/unauthenticated` | P0 |
| TC-FR03-06 | NEG | Invalid key | X-API-Key: wrong | 401 | P0 |
| TC-FR03-07 | NEG | Revoked key (AC-3.4) | key with revoked_at set | 401 | P0 |
| TC-FR03-08 | NEG | Every /v1 route 401 without key | iterate routes | all 401 | P0 |
| TC-FR03-09 | BND | Empty header value | `X-API-Key: ` | 401 | P1 |
| TC-FR03-10 | BND | Very long key (10KB) | long value | 401, no crash | P2 |
| TC-FR03-11 | EDG | Key differing by 1 char / case | mutated key | 401 | P1 |
| TC-FR03-12 | EDG | hmac.compare_digest used (AC-3.2) | code inspection/grep | present, no `==` on hashes | P1 |
| TC-FR03-13 | EDG | Key with whitespace padding | " key " | 401 | P2 |
| TC-FR03-14 | EDG | Invalid scope in CLI | `--scope bogus` | non-zero exit, no key persisted | P1 |
| TC-FR03-15 | EDG | Revocation takes effect immediately | revoke mid-session | next request 401 | P1 |

### FR-04 Scope authorization (AC-4.1..4.4)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR04-01 | POS | Scope matrix (AC-4.1) | each of R/W/A against every route | allowed iff key scope >= required; hierarchy inclusive | P0 |
| TC-FR04-02 | POS | Admin can do everything | A key on all routes | no 403 | P0 |
| TC-FR04-03 | NEG | Write key DELETE (AC-4.2, §8 #6) | W key DELETE existing task | 403 `/errors/forbidden` problem+json | P0 |
| TC-FR04-04 | NEG | Read key POST | R key POST /v1/tasks | 403 | P0 |
| TC-FR04-05 | NEG | Non-admin /v1/metrics | W key | 403 | P0 |
| TC-FR04-06 | EDG | No existence leak (AC-4.3) | W key DELETE existing vs unknown id | identical 403 status and body shape (except instance/correlation_id) | P0 |
| TC-FR04-07 | EDG | Single dependency (AC-4.4) | inspect app.routes | every /v1 route depends on the same auth dependency | P0 |
| TC-FR04-08 | EDG | Authz before lookup | R key DELETE unknown id | 403, not 404 | P0 |
| TC-FR04-09 | BND | Lowest/highest scope boundaries | R on read route; A on admin route | 200 | P1 |

### FR-05 Rate limiting (AC-5.1..5.4)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR05-01 | POS | Under burst allowed | BURST requests | all non-429 | P0 |
| TC-FR05-02 | NEG | Over burst (AC-5.2, §8 #9) | BURST+1 consecutive | 429 problem+json `/errors/rate-limited` + Retry-After (integer seconds >= 1) | P0 |
| TC-FR05-03 | POS | Recovery (AC-5.1) | wait ~1/RATE_PER_SEC after 429 | request succeeds | P0 |
| TC-FR05-04 | BND | Exactly BURST vs BURST+1 | with RATE_PER_SEC tiny | BURST ok, next 429 | P0 |
| TC-FR05-05 | BND | Refill cap | idle long time | tokens never exceed BURST | P1 |
| TC-FR05-06 | EDG | Per-token isolation | key A exhausted, key B request | B ok | P0 |
| TC-FR05-07 | EDG | Health exempt (AC-5.4) | flood /healthz, /readyz | never 429 | P0 |
| TC-FR05-08 | EDG | DB-persisted bucket (AC-5.3) | repository test: two app instances share rate_buckets | shared state | P1 |
| TC-FR05-09 | EDG | Row lock single txn | repo test / code review of update | SELECT FOR UPDATE (or equivalent) inside one txn | P1 |
| TC-FR05-10 | EDG | Concurrent burst (R12) | 2x BURST parallel requests | admitted <= BURST (+refill), no over-admission | P1 |
| TC-FR05-11 | EDG | 429 counted in metrics | after 429 | /v1/metrics rate-limit rejections increments | P1 |
| TC-FR05-12 | NEG | Unauthenticated requests not charged to a bucket | no key flood | 401, not 429 | P2 |

### FR-06 Persistence and transactions (AC-6.1..6.5)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR06-01 | POS | Commit on success (AC-6.2) | session ctx mgr, write, exit normally | data visible in new session | P0 |
| TC-FR06-02 | NEG | Rollback on exception | raise inside ctx | data absent | P0 |
| TC-FR06-03 | POS | One Session per request | two requests | distinct sessions; same session within a request | P0 |
| TC-FR06-04 | POS | Engine config (AC-6.5) | inspect engine | pool_size == TASKQ_DB_POOL_SIZE, pool_pre_ping True | P0 |
| TC-FR06-05 | POS | lint-imports (AC-6.1) | `lint-imports` | exit 0 | P0 |
| TC-FR06-06 | NEG | SQL concat scan (AC-6.3, §8 #17) | scan src | 0 hits | P0 |
| TC-FR06-07 | POS | No N+1 (AC-6.4, §8 #14) | count statements for GET /v1/tasks?limit=50 with 5 and 50 rows (tags relation) | equal counts | P0 |
| TC-FR06-08 | BND | pool_size=1 | env set | engine pool_size 1, requests still served sequentially | P2 |
| TC-FR06-09 | EDG | Rollback after commit failure | simulated commit error | exception propagates, session closed | P1 |
| TC-FR06-10 | EDG | Session closed after ctx exit | after exit | no open connection leak | P1 |
| TC-FR06-11 | EDG | Injection payload as data | name `'; DROP TABLE tasks;--` | stored literally (if allowed) or 422; tasks table intact | P0 |
| TC-FR06-12 | EDG | Service layer cannot hold Session | import-linter forbidden contract | no sqlalchemy import outside repository | P0 |

### FR-07 Migrations (AC-7.1..7.5)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR07-01 | POS | Three revisions exist (AC-7.1) | inspect migrations/versions | v1, v2, v3 each define upgrade and downgrade | P0 |
| TC-FR07-02 | POS | upgrade head on empty SQLite file | `alembic upgrade head` | exit 0; tables tasks, api_keys, tags, task_tags, task_results, rate_buckets; tasks.result_json absent | P0 |
| TC-FR07-03 | POS | downgrade base (AC-7.2, §8 #13) | after upgrade head | exit 0; no residual tables except alembic_version | P0 |
| TC-FR07-04 | POS | Round trip with data (AC-7.3, §8 #12) | upgrade head, insert samples, downgrade -1, upgrade head | per-column identical values | P0 |
| TC-FR07-05 | POS | v3 forward data move | seed v2 tasks with result_json, upgrade to v3 | rows in task_results with equal values; result_json column dropped | P0 |
| TC-FR07-06 | POS | v3 reverse data move | downgrade v3->v2 | result_json restored from task_results, then task_results dropped, no data lost | P0 |
| TC-FR07-07 | POS | v2 downgrade keeps v1 data | downgrade v2->v1 | tasks/api_keys rows unchanged; tags, task_tags, name index gone | P0 |
| TC-FR07-08 | POS | Offline SQL (AC-7.5) | `alembic upgrade head --sql` | SQL generated and asserted (CREATE TABLE ...) | P1 |
| TC-FR07-09 | NEG | Failing migration rolls back (AC-N3.6) | inject failure into v3 step | DB remains at v2, data intact | P0 |
| TC-FR07-10 | NEG | No destructive shortcut (AC-7.4) | grep `DROP TABLE` raw op.execute in downgrade bodies | none replacing real downgrade | P1 |
| TC-FR07-11 | BND | Empty tables in round trip | no data | succeeds | P1 |
| TC-FR07-12 | BND | tasks with NULL result_json | v2 rows with NULL | no task_results row created; reverse restores NULL | P0 |
| TC-FR07-13 | EDG | Large result_json (multi-KB, unicode) | row | preserved byte-identical | P1 |
| TC-FR07-14 | EDG | Multiple round trips idempotent | 3 cycles | stable schema and data | P1 |
| TC-FR07-15 | EDG | Real file DB, not :memory: (AC-N9.5) | test uses tmp_path file | file exists on disk | P0 |

### FR-08 Async executor (AC-8.1..8.4)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR08-01 | POS | TaskGroup execution | submit runs | executed via asyncio.TaskGroup | P0 |
| TC-FR08-02 | POS | Graceful drain completes (AC-8.1, §8 #25) | shutdown with short in-flight task, DRAIN_TIMEOUT large | task finishes done before exit | P0 |
| TC-FR08-03 | NEG | Drain timeout -> interrupted | shutdown with long task, small DRAIN_TIMEOUT | status interrupted (NFR-99.4); no orphan subprocess | P0 |
| TC-FR08-04 | POS | Concurrency cap (AC-8.2) | MAX_CONCURRENT=2, submit 6 sleeping tasks | peak running == 2; others queued; all finish | P0 |
| TC-FR08-05 | NEG | Timeout kills process (AC-8.3) | `sleep 60`, short timeout | process killed and awaited; PID not alive | P0 |
| TC-FR08-06 | NEG | CancelledError propagates (AC-8.4) | cancel runner coroutine | CancelledError raised to caller, not swallowed | P0 |
| TC-FR08-07 | BND | MAX_CONCURRENT=1 | 3 tasks | strictly serial | P1 |
| TC-FR08-08 | BND | DRAIN_TIMEOUT=0 | shutdown | in-flight immediately interrupted | P1 |
| TC-FR08-09 | EDG | Bounded coroutine creation | submit 1000 tasks | active coroutines/process count <= cap | P1 |
| TC-FR08-10 | EDG | Cancel during subprocess wait | cancel mid-run | subprocess terminated, no orphan | P0 |
| TC-FR08-11 | EDG | No `except Exception` swallow of cancel | ast scan of runner | CancelledError re-raised | P0 |
| TC-FR08-12 | EDG | Subprocess spawn error | OSError on exec | task failed, runner continues | P1 |

### FR-09 Health and observability (AC-9.1..9.5)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR09-01 | POS | healthz (AC-9.1) | GET /healthz no key | 200 `{"status":"ok"}` | P0 |
| TC-FR09-02 | POS | readyz ready (AC-9.2) | DB up, at head | 200 | P0 |
| TC-FR09-03 | NEG | readyz DB down (AC-9.3, §8 #10) | dispose/stop DB | 503 `/errors/not-ready`, detail names DB unavailable; no connection string | P0 |
| TC-FR09-04 | NEG | readyz behind head (AC-9.4, §8 #11) | `alembic downgrade -1` | 503, detail names migration not at head | P0 |
| TC-FR09-05 | POS | metrics (AC-9.5) | GET /v1/metrics A key | task counts by status, latency percentiles, rate-limit rejections | P0 |
| TC-FR09-06 | NEG | metrics scope | R/W key | 403; no key 401 | P0 |
| TC-FR09-07 | BND | metrics with zero tasks | empty DB | counts 0, percentiles null/0 without error | P1 |
| TC-FR09-08 | EDG | metrics counts accuracy | 2 done, 1 failed, 1 timeout | counts match | P1 |
| TC-FR09-09 | EDG | readyz recovers | DB restored / upgrade head | back to 200 | P1 |
| TC-FR09-10 | EDG | No infinite retry | DB down | readyz returns promptly (< a few seconds) | P1 |
| TC-FR09-11 | EDG | metrics leaks no DB URL (AC-N4.2) | full-text search of body | no password fragment | P0 |

### FR-10 Error contract (AC-10.1..10.6)
| ID | Cat | Description | Input | Expected | Pri |
|---|---|---|---|---|---|
| TC-FR10-01 | POS | Content-Type (AC-10.1) | trigger each error code | `application/problem+json` | P0 |
| TC-FR10-02 | POS | Body fields (AC-10.2) | each error | type(URI), title, status, detail, instance, correlation_id all present; status equals HTTP status | P0 |
| TC-FR10-03 | POS | Mapping (AC-10.5) | 422/401/403/404/409/429/503/500 | type = /errors/validation, unauthenticated, forbidden, not-found, conflict, rate-limited, not-ready, internal respectively | P0 |
| TC-FR10-04 | NEG | 500 leak check (AC-10.3, §8 #19) | force unhandled exception | body has no SQL, stack trace, file path, schema names | P0 |
| TC-FR10-05 | POS | Correlation id (AC-10.4) | any error | X-Correlation-Id header == body correlation_id and appears in captured server log | P0 |
| TC-FR10-06 | POS | Timeout is not an error (AC-10.6) | timed-out task | HTTP 200 on GET, status `timeout` | P0 |
| TC-FR10-07 | NEG | CancelledError not 500 | cancel in handler | propagates, not converted | P0 |
| TC-FR10-08 | NEG | Unknown route / wrong method | GET /nope; PATCH /v1/tasks | 404/405 as problem+json | P1 |
| TC-FR10-09 | NEG | Malformed JSON body | invalid JSON | 422 problem+json | P1 |
| TC-FR10-10 | BND | Client-supplied X-Correlation-Id | provided header | echoed or replaced consistently; never empty | P2 |
| TC-FR10-11 | EDG | 422 detail leaks no internals | validation error | no pydantic internals paths/class names | P1 |
| TC-FR10-12 | EDG | Instance is request path | error on /v1/tasks/x | instance references path | P2 |
| TC-FR10-13 | EDG | Error body redaction | error detail containing `Bearer abc` | `[REDACTED]` (NFR-04) | P1 |

## 2. Non-Functional Requirements

| ID | NFR | Cat | Description | Input / Command | Expected | Pri |
|---|---|---|---|---|---|---|
| TC-NFR01-01 | NFR-01 | BND | GET by id p95 (AC-N1.1, §8 #15) | 10,000 rows, pytest-benchmark, ASGI transport | p95 < 30ms (measurement per NFR-99.1) | P0 |
| TC-NFR01-02 | NFR-01 | BND | List p95 (AC-N1.2) | `GET /v1/tasks?limit=50`, 10,000 rows | p95 < 80ms | P0 |
| TC-NFR01-03 | NFR-01 | POS | Constant SQL count (AC-N1.3, §8 #14) | event listener; limit 5 vs 50 | identical statement counts | P0 |
| TC-NFR02-01 | NFR-02 | NEG | Dangerous-call grep (AC-N2.1, §8 #16) | `grep -rn "shell=True\|eval(\|exec(" 03-development/src/` | 0 hits | P0 |
| TC-NFR02-02 | NFR-02 | NEG | SQL concat scan (AC-N2.2, §8 #17) | grep + review for f-string/%/+ SQL | 0 hits | P0 |
| TC-NFR02-03 | NFR-02 | POS | Hashed key + compare_digest (AC-N2.3) | DB inspection | no plaintext; 64 hex | P0 |
| TC-NFR02-04 | NFR-02 | NEG | 403 no leak (AC-N2.4) | see TC-FR04-06 | pass | P0 |
| TC-NFR02-05 | NFR-02 | NEG | Error body no internals (AC-N2.5) | see TC-FR10-04 | pass | P0 |
| TC-NFR02-06 | NFR-02 | POS | CORS default deny (AC-N2.6) | preflight Origin: https://evil.example, TASKQ_CORS_ORIGINS empty | no Access-Control-Allow-Origin | P0 |
| TC-NFR02-07 | NFR-02 | POS | CORS allowlist | TASKQ_CORS_ORIGINS=https://a.example; Origin a / b | a allowed; b denied | P1 |
| TC-NFR02-08 | NFR-02 | EDG | CORS multi-origin with spaces | "https://a, https://b" | both parsed per spec behavior | P2 |
| TC-NFR02-09 | NFR-02 | POS | bandit (AC-N2.7, §8 #23) | `bandit -r 03-development/src/` | 0 HIGH, 0 MEDIUM | P0 |
| TC-NFR03-01 | NFR-03 | POS | Commit/rollback (AC-N3.1) | see TC-FR06-01/02 | pass | P0 |
| TC-NFR03-02 | NFR-03 | NEG | Anti-pattern scan (AC-N3.2) | ast-error-handling | 0 bare except, 0 `except Exception: pass` | P0 |
| TC-NFR03-03 | NFR-03 | NEG | CancelledError (AC-N3.3) | see TC-FR08-06/11 | pass | P0 |
| TC-NFR03-04 | NFR-03 | NEG | DB failure readyz (AC-N3.4) | see TC-FR09-03/10 | 503 explicit detail, no endless retry | P0 |
| TC-NFR03-05 | NFR-03 | NEG | No orphans (AC-N3.5) | see TC-FR08-05/10 | 0 orphan processes | P0 |
| TC-NFR03-06 | NFR-03 | NEG | Migration failure rollback (AC-N3.6) | see TC-FR07-09 | previous revision retained | P0 |
| TC-NFR04-01 | NFR-04 | POS | Redaction regex (AC-N4.1) | lines with `sk-abcdefgh12`, `token=xyz`, `Bearer abc.def`, `postgresql://u:p@h/db` | whole line replaced with `[REDACTED]` | P0 |
| TC-NFR04-02 | NFR-04 | BND | `sk-` with 7 vs 8 chars | `sk-1234567` / `sk-12345678` | not redacted / redacted | P0 |
| TC-NFR04-03 | NFR-04 | EDG | Multi-line mix; secret mid-line | text with one secret line among clean lines | only matching lines replaced; clean lines kept | P0 |
| TC-NFR04-04 | NFR-04 | EDG | Applied to stdout, stderr, logs, error bodies | each sink | all redacted | P0 |
| TC-NFR04-05 | NFR-04 | NEG | DB URL password absent (AC-N4.2, §8 #20) | set TASKQ_DB_URL with password marker, exercise app, capture logs + /v1/metrics | marker absent | P0 |
| TC-NFR04-06 | NFR-04 | POS | Plaintext once (AC-N4.3) | key create then scan DB, logs, files | plaintext only in CLI stdout | P0 |
| TC-NFR05-01 | NFR-05 | POS | Docstring coverage (AC-N5.1) | ast-docstrings + check for `[FR-XX]`/`[NFR-XX]` | 100% of public defs/classes (NFR-99.5 for migrations) | P1 |
| TC-NFR05-02 | NFR-05 | POS | OpenAPI (AC-N5.2) | GET /openapi.json | every operation has summary and description | P1 |
| TC-NFR06-01 | NFR-06 | POS | lint-imports (AC-N6.1, N6.3, §8 #21) | `lint-imports` | exit 0 | P0 |
| TC-NFR06-02 | NFR-06 | NEG | Forbidden sqlalchemy (AC-N6.2) | temp service module importing sqlalchemy | lint-imports fails | P0 |
| TC-NFR06-03 | NFR-06 | NEG | Layer inversion | temp models importing api | lint-imports fails | P1 |
| TC-NFR06-04 | NFR-06 | EDG | Contract not weakened (AC-N6.4) | parse `.importlinter` | exists; layers + independence + forbidden; no wildcard ignore_imports | P0 |
| TC-NFR07-01 | NFR-07 | POS | Pins and lock (AC-N7.1) | parse requirements.txt / requirements.lock | every runtime dep `==`; lock includes transitive deps | P1 |
| TC-NFR07-02 | NFR-07 | POS | License allowlist (AC-N7.2/7.3, §8 #22) | `pip-licenses --format=json --with-system` | all in MIT/BSD-2/BSD-3/Apache-2.0/PSF | P1 |
| TC-NFR07-03 | NFR-07 | POS | SBOM (AC-N7.4) | read 08-config/SBOM.json | each entry has name, version, license, direct/transitive | P1 |
| TC-NFR08-01 | NFR-08 | POS | Config flag (AC-N8.1) | read harness_config.json | features.mutation_testing true | P1 |
| TC-NFR08-02 | NFR-08 | POS | Mutation score (AC-N8.2, §8 #24) | `mutmut run`; `harness_cli.py mutation-test-score` | >= 70 | P0 |
| TC-NFR08-03 | NFR-08 | POS | Scope and rationale (AC-N8.3) | read config | scope service/ + repository/ and rationale recorded | P1 |
| TC-NFR09-01 | NFR-09 | NEG | Zero skips (AC-N9.1/9.2, §8 #1) | `pytest 03-development/tests -q` | skipped 0, no skip/xfail markers | P0 |
| TC-NFR09-02 | NFR-09 | NEG | Zero zero-assert tests (AC-N9.3) | ast-assertions | zero_assert == 0 | P0 |
| TC-NFR09-03 | NFR-09 | NEG | No exclusion mechanisms (AC-N9.4) | review pytest config | no --ignore/-k/--deselect/collect_ignore; testpaths intact | P1 |
| TC-NFR09-04 | NFR-09 | POS | Real DB migrations (AC-N9.5) | see TC-FR07-15 | pass | P0 |
| TC-NFR09-05 | NFR-09 | POS | Traceability honesty (AC-N9.6) | TRACEABILITY_MATRIX vs pytest results | VERIFIED only for passing tests | P1 |
| TC-NFR09-06 | NFR-09 | POS | Total coverage (§8 #2, NFR-99.6) | `pytest 03-development/tests --cov=03-development/src --cov-report=term` | TOTAL 100% | P0 |
| TC-NFR10-01 | NFR-10 | POS | Integration coverage (AC-N10.1, §8 #3) | `pytest 03-development/tests/integration --cov=03-development/src` | >= 80% | P0 |
| TC-NFR10-02 | NFR-10 | POS | ASGITransport only (AC-N10.2) | grep integration tests | httpx AsyncClient + ASGITransport; no direct handler calls | P1 |
| TC-NFR10-03 | NFR-10 | POS | Scenario coverage (AC-N10.3) | match test list | CRUD chain; 401/403/404/409/422/429/503 one each; migration round trip; rate limit trigger+recovery; graceful drain | P0 |
| TC-NFR11-01 | NFR-11 | POS | MI (AC-N11.1) | radon mi, LLOC weighted | >= 80 | P1 |
| TC-NFR11-02 | NFR-11 | BND | CC (AC-N11.2) | radon cc | every function <= 10 | P1 |
| TC-NFR11-03 | NFR-11 | BND | File/dir size (AC-N11.3) | scan | file <= 400 lines; dir <= 15 files | P1 |
| TC-NFR11-04 | NFR-11 | BND | Handler length (AC-N11.4) | AST | each handler <= 40 lines | P1 |
| TC-NFR12-01 | NFR-12 | POS | Makefile content (AC-N12.1) | parse `verify-system` | chains upgrade head, tests, smoke /healthz+/readyz, downgrade base + upgrade head | P0 |
| TC-NFR12-02 | NFR-12 | POS | verify-system run (AC-N12.2, §8 #27) | `make verify-system` | exit 0 and stdout `verify-system: PASS` | P0 |
| TC-NFR12-03 | NFR-12 | BND | .env.example count (AC-N12.3, §8 #26) | `grep -c "^TASKQ_" .env.example` | 12 | P0 |
| TC-NFR12-04 | NFR-12 | EDG | Defaults per variable | load config with no env | defaults match SRS table (DB_URL, POOL_SIZE 5, TASK_TIMEOUT 10.0, MAX_CONCURRENT 8, RATE_BURST 20, RATE_PER_SEC 5.0, HOST 127.0.0.1, PORT 8000, LOG_FORMAT json) | P1 |
| TC-NFR12-05 | NFR-12 | NEG | Invalid config values | LOG_LEVEL=BOGUS, PORT=abc | rejected with clear error | P2 |

## 3. Constraints and Cross-Cutting
| ID | Description | Expected | Pri |
|---|---|---|---|
| TC-C5-01 | High-risk modules runner, auth, repository.session, v3_split_results each have dedicated TDD coverage | 100% line coverage per module | P0 |
| TC-C6-01 | Async scanner false positive/negative on async syntax (C-6) | any scanner misjudgment recorded in Phase 4 bug hunt, not bypassed | P1 |
| TC-LOG-01 | Logging config (TASKQ_LOG_LEVEL/FORMAT) | json emits parseable JSON lines; text emits plain; level filters | P2 |

## 4. Coverage Matrix (manifest fr_ids)
FR-01..FR-10 each covered above (TC-FR01-xx .. TC-FR10-xx). NFR-01..NFR-12 covered by TC-NFRxx. Each AC in the SRS is referenced by at least one case. SPEC §8 #1-#27 map: #1 NFR09-01, #2 NFR09-06, #3 NFR10-01, #4 FR01-01, #5 FR03-05, #6 FR04-03, #7 FR01-09, #8 FR01-08, #9 FR05-02, #10 FR09-03, #11 FR09-04, #12 FR07-04, #13 FR07-03, #14 NFR01-03, #15 NFR01-01, #16 NFR02-01, #17 NFR02-02, #18 FR03-03, #19 FR10-04, #20 NFR04-05, #21 NFR06-01/02, #22 NFR07-02, #23 NFR02-09, #24 NFR08-02, #25 FR08-02/03, #26 NFR12-03, #27 NFR12-02.

## 5. Open Issues Affecting Cases
NFR-99.1 (p95 measurement: NFR01-01/02), 99.2 (blacklist chars: FR01-07), 99.3 (409 vs 422: FR01-08, expected 409 per §8 #8), 99.4 (`interrupted` state: FR08-03), 99.5 (docstring scope for migrations: NFR05-01), 99.6 (100% coverage exclusions: NFR09-06). Cases pin the SPEC §8 value and are re-confirmed with stakeholder during execution.

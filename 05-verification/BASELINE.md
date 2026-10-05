# BASELINE.md - taskq-open

## 1. Baseline Overview
- Author: Claude (P5 verification author, workflow dispatch)
- Reviewer: Johnny (pending)
- session_id: P5-verification-2026-10-05
- Date: 2026-10-05
- Version: taskq_api (Python 3.11.15), HEAD a904f15, Phase 5, Gate 1 PASS for FR-01..FR-10
- Source modules (03-development/src/): `taskq_api` (api, service, repository, models, app, cli, config, errors, __main__) and `migrations` (env, versions v1_initial, v2_tags, v3_split_results)

## 2. Functional Baseline (maps to SRS FR, 100% complete)

| FR ID | Feature Description | Baseline Status | Notes |
|-------|--------------------|-----------------|-------|
| FR-01 | Task CRUD with cursor pagination and validation | PASS | Gate 1 score 100.0 |
| FR-02 | Task run via subprocess, run history | PASS | Gate 1 score 100.0 |
| FR-03 | API key authentication (SHA-256 stored) | PASS | Gate 1 score 99.01 |
| FR-04 | Scope-based authorization (read/write/admin) | PASS | Gate 1 score 100.0 |
| FR-05 | DB-backed token bucket rate limiting | PASS | Gate 1 score 99.52 |
| FR-06 | Repository layer / session / pool | PASS | Gate 1 score 100.0 |
| FR-07 | Alembic migrations v1-v3 with real downgrade | PASS | Gate 1 score 97.09 |
| FR-08 | Background runner, concurrency cap, graceful drain | PASS | Gate 1 score 99.72 |
| FR-09 | Health, readiness, metrics endpoints | PASS | Gate 1 score 100.0 |
| FR-10 | problem+json error contract | PASS | Gate 1 score 100.0 |

## 3. Quality Baseline

| Metric | Threshold | Actual | Status |
|--------|-----------|--------|--------|
| Gate 3 composite score | >= 85 | 97.88 (open_critical 0, open_high 0) | PASS |
| Coverage (04-testing/COVERAGE_REPORT.md) | >= 80% | 100% (1052 stmts, 0 missed) | PASS |
| Test results, P5 re-run (03-development/tests) | 0 failed | 224 passed, 0 failed, 1 warning | PASS |
| Integration tests (03-development/tests/integration) | 0 failed | 17 passed | PASS |
| bandit -ll | 0 medium/high | 0 high, 0 medium (2 low) | PASS |
| gitleaks | 0 leaks | no leaks found (140 commits) | PASS |

`test_nfr09_verified_only_when_tests_pass` passes after a904f15. Phase 4 TEST_RESULTS.md also recorded 224 passed.

## 4. Performance Baseline (A/B monitoring)

| Metric | Baseline Value |
|--------|---------------|
| GET task by id (NFR-01, budget p95 < 30 ms) | benchmark mean 1.62 ms (max 1.81 ms), P5 re-run; test_nfr01_get_task_p95_under_30ms passes |
| List tasks (NFR-01, budget p95 < 80 ms) | benchmark mean 2.61 ms (max 3.45 ms), P5 re-run; test_nfr01_list_p95_under_80ms passes |
| Memory | Not measured |
| Error Rate | 0% across 224 test cases in P4; 0 failures in P5 re-run (224 passed) |

## 5. Known Issues
| Severity | Count | Description |
|----------|-------|-------------|
| HIGH | 0 | None open per Gate 3 manifest |
| MEDIUM | 0 | None. Previous NFR-09 traceability test failure resolved by a904f15 (re-run: 224 passed). |
| LOW | 2 | bandit low-severity findings in 03-development/src |

> HIGH severity count must be 0 before establishing baseline: met.

## 6. Change Log

| Date | Change | Commit / Ref |
|------|--------|--------------|
| 2026-10-05 | NFR-09 VERIFIED check accepts rendered matrix | a904f15 |
| 2026-10-05 | FR-10 Gate1 PASS, score 100.0 | 0984e0f |
| 2026-10-05 | FR-09 Gate1 PASS, score 100.0 | 760f065 |
| 2026-10-05 | FR-08 Gate1 PASS, score 99.7 | 381515a |
| 2026-10-05 | FR-07 Gate1 PASS, score 97.1 | 875a88e |
| 2026-10-05 | FR-06 Gate1 PASS, score 100.0 | 0318d14 |
| 2026-10-05 | FR-05 Gate1 PASS, score 99.5 | 23076aa |
| 2026-10-05 | FR-04 Gate1 PASS, score 100.0 | 23a7a5a |
| 2026-10-05 | FR-03 Gate1 PASS, score 99.0 | 70af709 |
| 2026-10-05 | FR-02 Gate1 PASS, score 100.0 | 966d24c |

## 7. Acceptance Sign-off
- Agent A: Claude (P5-verification-2026-10-05) - 2026-10-05
- Approver: Johnny (pending) - not signed

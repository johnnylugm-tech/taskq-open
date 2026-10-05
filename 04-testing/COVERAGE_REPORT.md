# COVERAGE_REPORT (Phase 4)

Command: `.venv/bin/python -m pytest 03-development/tests --cov=03-development/src --cov-report=term-missing -q`
Run result: `224 passed, 1 warning in 15.46s` (see TEST_RESULTS.md). Raw output: `04-testing/coverage_raw.txt`.

## Overall

`python -m coverage report --format=total` = **100%** (1052 statements, 0 missed). Gate 3 threshold >= 80%: met.

## Per-module breakdown

| Module | Stmts | Miss | Cover |
|--------|-------|------|-------|
| migrations/__init__.py | 0 | 0 | 100% |
| migrations/env.py | 28 | 0 | 100% |
| migrations/versions/__init__.py | 0 | 0 | 100% |
| migrations/versions/v1_initial.py | 16 | 0 | 100% |
| migrations/versions/v2_tags.py | 14 | 0 | 100% |
| migrations/versions/v3_split_results.py | 20 | 0 | 100% |
| taskq_api/__init__.py | 0 | 0 | 100% |
| taskq_api/__main__.py | 4 | 0 | 100% |
| taskq_api/api/__init__.py | 0 | 0 | 100% |
| taskq_api/api/deps.py | 31 | 0 | 100% |
| taskq_api/api/error_handlers.py | 21 | 0 | 100% |
| taskq_api/api/middleware.py | 34 | 0 | 100% |
| taskq_api/api/routes_health.py | 14 | 0 | 100% |
| taskq_api/api/routes_metrics.py | 10 | 0 | 100% |
| taskq_api/api/routes_runs.py | 23 | 0 | 100% |
| taskq_api/api/routes_tasks.py | 30 | 0 | 100% |
| taskq_api/api/schemas.py | 31 | 0 | 100% |
| taskq_api/app.py | 54 | 0 | 100% |
| taskq_api/cli.py | 31 | 0 | 100% |
| taskq_api/config.py | 19 | 0 | 100% |
| taskq_api/errors.py | 52 | 0 | 100% |
| taskq_api/models/__init__.py | 1 | 0 | 100% |
| taskq_api/models/api_key.py | 12 | 0 | 100% |
| taskq_api/models/base.py | 13 | 0 | 100% |
| taskq_api/models/rate_bucket.py | 10 | 0 | 100% |
| taskq_api/models/result.py | 14 | 0 | 100% |
| taskq_api/models/tag.py | 9 | 0 | 100% |
| taskq_api/models/task.py | 15 | 0 | 100% |
| taskq_api/repository/__init__.py | 0 | 0 | 100% |
| taskq_api/repository/api_keys.py | 13 | 0 | 100% |
| taskq_api/repository/migration_state.py | 53 | 0 | 100% |
| taskq_api/repository/rate_buckets.py | 17 | 0 | 100% |
| taskq_api/repository/results.py | 16 | 0 | 100% |
| taskq_api/repository/session.py | 56 | 0 | 100% |
| taskq_api/repository/stats.py | 19 | 0 | 100% |
| taskq_api/repository/tags.py | 9 | 0 | 100% |
| taskq_api/repository/tasks.py | 49 | 0 | 100% |
| taskq_api/service/__init__.py | 0 | 0 | 100% |
| taskq_api/service/auth.py | 32 | 0 | 100% |
| taskq_api/service/executor.py | 58 | 0 | 100% |
| taskq_api/service/health.py | 40 | 0 | 100% |
| taskq_api/service/ratelimit.py | 35 | 0 | 100% |
| taskq_api/service/redact.py | 6 | 0 | 100% |
| taskq_api/service/runner.py | 63 | 0 | 100% |
| taskq_api/service/runs.py | 40 | 0 | 100% |
| taskq_api/service/tasks.py | 38 | 0 | 100% |
| taskq_api/service/uow.py | 2 | 0 | 100% |
| **TOTAL** | **1052** | **0** | **100%** |

(All paths relative to `03-development/src/`.)

## Uncovered lines

None. The Missing column is empty for every module.

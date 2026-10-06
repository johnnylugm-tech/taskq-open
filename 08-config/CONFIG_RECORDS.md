# CONFIG_RECORDS.md - taskq-open

> On-demand Lazy Load template.

## 1. Version Information
- Version: vharness-v4-20261005-scoreXX-18-gac9ed15
- Git Commit: ac9ed15
- Release Date: 2026-10-06

## 2. Runtime Configuration
| Environment | Config |
|-------------|--------|
| Development | SQLite file `sqlite:///./taskq.db`; host 127.0.0.1:8000; log level INFO, json format; pool 5; CORS allow-list empty (deny all); all TASKQ_* defaults from `taskq_api.config.load_settings` |
| Production | Not provisioned in this repository (no deploy manifests present). Same TASKQ_* variables apply; `TASKQ_DB_URL` and `TASKQ_CORS_ORIGINS` must be set explicitly by the operator; values are not recorded here. |

## 3. Dependency List
```
# Generated from the installed environment; every direct and transitive runtime dependency pinned with ==.
alembic==1.20.0
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
click==8.5.0
fastapi==0.142.2
h11==0.16.0
idna==3.20
mako==1.4.3
markupsafe==3.0.4
opentelemetry-api==1.45.0
pydantic==2.13.5
pydantic-core==2.46.5
sqlalchemy==2.1.3
starlette==1.7.0
typing-extensions==4.16.0
typing-inspection==0.4.4
uvicorn==0.54.0
```

## 4. Environment Variables
| Variable | Type | Description |
|----------|------|-------------|
| TASKQ_DB_URL | secret | SQLAlchemy database URL (default `sqlite:///./taskq.db`); excluded from Settings repr (NFR-04) |
| TASKQ_DB_POOL_SIZE | config | DB connection pool size (default 5) |
| TASKQ_TASK_TIMEOUT | config | Per-task subprocess timeout in seconds (default 10.0) |
| TASKQ_RATE_BURST | config | Token-bucket burst size (default 20) |
| TASKQ_RATE_PER_SEC | config | Token-bucket refill rate per second (default 5.0) |
| TASKQ_MAX_CONCURRENT | config | Executor concurrency cap (default 8) |
| TASKQ_DRAIN_TIMEOUT | config | Graceful drain timeout in seconds (default 30.0) |
| TASKQ_CORS_ORIGINS | config | Comma-separated CORS allow-list (default empty, deny all) |
| TASKQ_LOG_LEVEL | config | Log level (default INFO) |
| TASKQ_LOG_FORMAT | config | Log format (default json) |
| TASKQ_HOST | config | Listen host (default 127.0.0.1) |
| TASKQ_PORT | config | Listen port (default 8000) |

## 5. Deployment Log
| Date | Version | Method | Executor |
|------|---------|--------|----------|
| 2026-10-06 | harness-v4-20261005-scoreXX-18-gac9ed15 | Not deployed: release record only (repository tagged; ASGI service started with `uvicorn taskq_api.app:app`, schema via `alembic upgrade head`) | N/A (no production deployment executed) |

## 6. Configuration Change Log
| Phase | Change | Rationale |
|-------|--------|----------|
| Phase 8 | No runtime configuration change; config baseline and records finalized for release | Release documentation only; defaults in `taskq_api.config` unchanged |

## 7. Rollback SOP
**Trigger Condition**: Post-release failure of `/healthz` or `/readyz`, or a failed migration (e.g. v3 `task_results` data migration) after `alembic upgrade head`.
**Commands**:
```bash
# 1. Stop the uvicorn process serving taskq_api.app:app
# 2. Revert schema one step (v3 downgrade moves task_results back into tasks.result_json)
alembic -c alembic.ini downgrade -1      # or `downgrade base` to revert all revisions
# 3. Redeploy the previous release tag (git tags present: gate4-20261005-score98)
git checkout <previous-tag>
# 4. Restart: uvicorn taskq_api.app:app, then verify /healthz and /readyz
```

## 8. Configuration Compliance
- [ ] Phase 7 risk mitigations implemented
- [ ] Monitoring thresholds configured
- [ ] Circuit breaker enabled

## Human Context (P8 append)
- Ownership per config item: all items (TASKQ_* variables, database URL, CORS allow-list, rate-limit and executor settings, alembic migrations) are owned by Johnny, the sole project owner on record (07-risk/RISK_REGISTER.md); reassign if a team exists.
- Secret rotation cadence: no cadence defined in the repository. Requires Verification: owner must set one. API keys are stored as SHA-256 hashes and plaintext is printed only once by `python -m taskq_api key create`; rotation = create a new key and set `revoked_at` on the old one. `TASKQ_DB_URL` rotation is manual.
- Access audit log reference: none exists in the repository. Unknown: the production access-audit location must be supplied by the operator. Config and release history is traceable via git history and 09-maintenance/MAINTENANCE_LOG.md.

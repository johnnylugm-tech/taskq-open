# RELEASE_CHECKLIST

## Pre-Release Checks
- [ ] All P1-P7 phases completed and artifacts generated.
- [ ] CI pipeline fully passed.
- [ ] Final Sign Off approved.
- [ ] Production environment provisioned.
- [ ] Rollback plan documented.

## Human Context (P8 append)
- Deployment runbook URL: none published. Unknown. Interim runbook is Rollback SOP in 08-config/CONFIG_RECORDS.md plus `make verify-system` in the repository Makefile.
- Rollback owner + on-call: Johnny (sole project owner on record). No on-call rotation or contact channel defined. Requires Verification.
- Post-release monitoring dashboard: none provisioned. Available signals are the `/healthz` and `/readyz` endpoints and structured json logs (TASKQ_LOG_FORMAT=json).
- Customer comms template: none exists in the repository. Unknown. Release content is in RELEASE_NOTES.md.

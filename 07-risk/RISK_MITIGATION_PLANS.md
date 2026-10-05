# Risk Mitigation Plans (HIGH, L x I >= 9)

- Date: 2026-10-06 | Owner for all items: Johnny (sole project owner on record; reassign if a team exists)
- Deadlines are proposed, relative to 2026-10-06, and require owner confirmation.
- Priority order: score descending, then open-gap items first.

## Open-gap plans (control incomplete)

### R14 Spec-declared tests undelivered (score 9) - Owner: Johnny - Deadline: 2026-10-13
- Action: for each of test_nfr10_integration_line_coverage_80, test_nfr12_verify_system_prints_pass, test_nfr03_request_txn_commit_rollback, test_nfr03_cancelled_error_reraised, write the test or record a waiver in the decision log with reason.
- Done when: gate4 spec_undelivered is empty or every entry has a waiver; gate re-run passes.
- Trigger/contingency: if tests cannot be written, waiver needs sign-off before release.

### R7 CancelledError swallowed (score 9) - Owner: Johnny - Deadline: 2026-10-13
- Action: add test_nfr03_cancelled_error_reraised (shared with R14); grep service/ and api/ for bare except / except BaseException that does not re-raise; lift error_handling dimension (85.7, lowest in Gate 4).
- Done when: test passes, grep clean, error_handling score improved.
- Contingency: shutdown hang detected in staging, then force-cancel with timeout in lifespan.

### R13 Surviving mutants (score 9) - Owner: Johnny - Deadline: 2026-10-20
- Action: triage 10 survivors from .methodology/mutation_survivors.json; priority runner.py (2) and auth.py (1) as high-risk modules, then executor.py (3). Add assertions to kill, or document as equivalent mutants.
- Done when: score >= 96.6 with survivors in high-risk modules at 0 or documented.
- Note: survivor line numbers are null in the artifact; re-run mutmut results to locate them.

## Controlled risks (control in place; plan is verification and monitoring)

| ID | Risk | Score | Verification action | Owner | Deadline |
|----|------|-------|---------------------|-------|----------|
| R5 | N+1 queries | 16 | Keep SQL-count assertions in CI; re-run on any repository change | Johnny | 2026-10-20 |
| R1 | v3 migration data loss | 15 | Run round-trip test on a production-sized snapshot before first deploy; keep backup-before-migrate step | Johnny | 2026-10-20 |
| R3 | API key leakage | 12 | Re-run secrets scan and log-redaction check on release candidate; review auth.py changes only with mutation re-run | Johnny | release candidate |
| R6 | Error body leaks internals | 12 | Fuzz error handlers; confirm detail whitelist; close low-severity redact#tq-gap | Johnny | 2026-10-20 |
| R9 | Migration forgotten | 12 | Deploy checklist includes /readyz check; verify fail-closed with stale schema | Johnny | release candidate |
| R4 | 403 existence leak | 9 | Keep test that 403/404 are indistinguishable for foreign resources | Johnny | 2026-10-27 |
| R8 | Orphan process on timeout | 9 | Soak test with hanging subprocess; confirm no leftover PID | Johnny | 2026-10-27 |
| R10 | Pool exhaustion | 9 | Load test at concurrency cap; confirm pool_pre_ping and recovery | Johnny | 2026-10-27 |
| R11 | Licence incompatibility | 9 | Re-scan lock file on every dependency change | Johnny | ongoing |

## Escalation
Any HIGH risk whose done-criterion is missed by its deadline is re-rated and reported at the next gate; do not advance past Gate 4 sign-off with R14/R7 unresolved and unwaived.

# Risk Register - taskq-open

- Date: 2026-10-06 | Phase: 7 | Owner: Johnny
- Sources: SPEC.md section 9 (R1-R12), .methodology/gate3_result.json, gate4_result.json (PASS, composite 98.02), mutation_score.json (96.6), bug_hunt_report.json (15 raw, 0 confirmed, 14 refuted), CLAUDE.md High-Risk Modules.
- Note: the task prompt seeded R1-R4 as concurrent write / subprocess hang / breaker deadlock / stale cache. SPEC.md section 9 defines R1-R4 differently (v3 migration data loss / SQL injection / API key leak / 403 existence leak). SPEC.md is authoritative and is used here. The prompt's themes map to R8 (subprocess hang), R12 (concurrent bucket race); breaker deadlock and stale cache have no SPEC risk and are not registered.
- Missing sources: .methodology/deferred_fixes.md and .sessi-work/issue_registry.json do not exist; nothing was read from them.
- Scale: likelihood and impact 1-5. SPEC low/medium/high mapped to 2/3/4 (high impact on R1 = 5 because of irreversible data loss; high likelihood on R5/R6 = 4). Score = L x I. HIGH >= 9.

## Register

| ID | Risk | L | I | Score | Level | Category | Mitigation approach | Evidence of control |
|----|------|---|---|-------|-------|----------|---------------------|---------------------|
| R1 | v3 migration loses data | 3 | 5 | 15 | HIGH | Data integrity | Round-trip reversibility test, real-DB column-by-column compare (FR-07, SPEC s8 #12) | FR-07 Gate1 97.1; module migrations.versions.v3_split_results is high-risk |
| R2 | SQL injection | 2 | 4 | 8 | MEDIUM | Security | No string concatenation, ORM/parameterised queries, grep gate (NFR-02); sqlalchemy confined to repository by import-linter | Gate4 security 98.0 |
| R3 | API key leakage | 3 | 4 | 12 | HIGH | Security | Hashed storage, constant-time compare, plaintext shown once (FR-03) | Gate4 secrets_scanning 100; auth is high-risk module |
| R4 | 403 leaks resource existence | 3 | 3 | 9 | HIGH | Security | Authorisation decided before resource lookup (FR-04, SPEC s8 #6) | FR-04 100.0 |
| R5 | N+1 queries collapse on large tables | 4 | 4 | 16 | HIGH | Performance | Explicit eager load, SQL-count assertions (NFR-01, s8 #14) | Gate4 performance 100 |
| R6 | Error body leaks internals | 4 | 3 | 12 | HIGH | Security | RFC 7807 fixed fields, detail whitelist (FR-10) | FR-10 100.0; redact module |
| R7 | CancelledError swallowed, hang on shutdown | 3 | 3 | 9 | HIGH | Reliability | Explicit prohibition plus test assertion (NFR-03) | Gate4 spec_undelivered lists test_nfr03_cancelled_error_reraised (absent); error_handling 85.7 |
| R8 | Task timeout leaves orphan process | 3 | 3 | 9 | HIGH | Reliability | kill() then await wait() (FR-08, s8 #25) | FR-08 99.7; runner/executor high-risk |
| R9 | Migration not run after deploy | 3 | 4 | 12 | HIGH | Operations | /readyz fails closed (FR-09, s8 #11) | FR-09 100.0 |
| R10 | Connection pool exhaustion | 3 | 3 | 9 | HIGH | Reliability | pool_pre_ping, concurrency cap (FR-06/08) | repository.session high-risk |
| R11 | Transitive dependency with incompatible licence | 3 | 3 | 9 | HIGH | Compliance | Lock file plus full-tree scan (NFR-07) | Gate4 license_compliance 100 |
| R12 | Rate bucket race over-admits | 2 | 3 | 6 | MEDIUM | Concurrency | Single transaction plus row-level lock (FR-05) | FR-05 99.5 |
| R13 | Surviving mutants hide weak assertions | 3 | 3 | 9 | HIGH | Test quality | Triage 10 survivors (executor 3, runner 2, tasks, auth, health, redact, runs 1 each); kill or document each as equivalent | mutation 96.6 (285 killed / 10 survived); 2 survivors in high-risk runner, 1 in auth |
| R14 | Spec-declared tests undelivered | 3 | 3 | 9 | HIGH | Traceability | Deliver or formally waive: nfr10 integration coverage 80, nfr12 verify-system pass, nfr03 txn commit/rollback, nfr03 CancelledError re-raise | Gate4 spec_undelivered (4 items, why=absent) of 143 declared |
| R15 | Residual threat-model gaps | 2 | 4 | 8 | MEDIUM | Security | 13 STRIDE targets (T-01..T-13) all refuted by hunt; keep as regression hunts. Open: low-severity redact#tq-gap | bug_hunt_report: confirmed_count 0 |

Notes:
- Scores are inherent (pre-mitigation) from SPEC ratings; controls above are in place and Gate 3 (97.9) and Gate 4 (98.0) pass. Residual re-rating was not independently verified in this task.
- R7 and R14 overlap: the missing CancelledError test is the concrete open item behind R7.
- R13/R14/R15 are new, derived from gate artifacts; they are not in SPEC.md.

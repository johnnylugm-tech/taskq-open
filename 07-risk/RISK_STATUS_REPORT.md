# Risk Status Report

- Date: 2026-10-06 | Phase 7 | Gate status: Gate 1 pass, Gate 2 98.9, Gate 3 97.9, Gate 4 pass (composite 98.02)
- Totals: 15 risks. HIGH 12 (R1, R3-R11, R13, R14), MEDIUM 3 (R2, R12, R15), LOW 0.
- Status values: Mitigated = control implemented and gate-verified; Open gap = control or evidence incomplete; Monitor = watch only.

| ID | Risk | Score | Level | Status | Owner | Target date | Note |
|----|------|-------|-------|--------|-------|-------------|------|
| R1 | v3 migration data loss | 15 | HIGH | Mitigated, verify on prod-size data | Johnny | 2026-10-20 | FR-07 97.1 |
| R2 | SQL injection | 8 | MEDIUM | Mitigated | Johnny | - | NFR-02, import-linter |
| R3 | API key leakage | 12 | HIGH | Mitigated | Johnny | release candidate | secrets 100 |
| R4 | 403 existence leak | 9 | HIGH | Mitigated | Johnny | 2026-10-27 | FR-04 |
| R5 | N+1 queries | 16 | HIGH | Mitigated | Johnny | 2026-10-20 | performance 100 |
| R6 | Error body leak | 12 | HIGH | Mitigated, one low gap | Johnny | 2026-10-20 | redact#tq-gap |
| R7 | CancelledError swallowed | 9 | HIGH | Open gap | Johnny | 2026-10-13 | test absent; error_handling 85.7 |
| R8 | Orphan subprocess | 9 | HIGH | Mitigated | Johnny | 2026-10-27 | FR-08 99.7 |
| R9 | Migration not run | 12 | HIGH | Mitigated | Johnny | release candidate | FR-09 |
| R10 | Pool exhaustion | 9 | HIGH | Mitigated, load test pending | Johnny | 2026-10-27 | |
| R11 | Licence incompatibility | 9 | HIGH | Mitigated | Johnny | ongoing | licence 100 |
| R12 | Rate bucket race | 6 | MEDIUM | Mitigated | Johnny | - | FR-05 99.5 |
| R13 | Surviving mutants | 9 | HIGH | Open gap | Johnny | 2026-10-20 | 10 survivors, score 96.6 |
| R14 | Undelivered spec tests | 9 | HIGH | Open gap | Johnny | 2026-10-13 | 4 of 143 absent |
| R15 | Threat-model gaps | 8 | MEDIUM | Monitor | Johnny | - | 0 confirmed findings |

## Summary
- No risk is currently known to be materialised. Bug hunt: 15 raw, 0 confirmed, 14 refuted.
- Three open gaps (R7, R13, R14), all test-evidence gaps rather than known defects.
- Unverified: residual scores after mitigation were not re-measured; owners and dates are proposals; deferred_fixes.md and issue_registry.json were absent.
- Detail: RISK_REGISTER.md, RISK_MITIGATION_PLANS.md.

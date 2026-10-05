# Traceability Matrix — `taskq-api`

> Requirements Traceability Matrix | Framework: harness-methodology | Version: v1.0 (P1, ROUND 1) | Created: 2026-10-04
> Sources: `SPEC.md` (v1.0.0) -> `01-requirements/SRS.md` (APPROVED) -> `01-requirements/SPEC_TRACKING.md` (APPROVED). Citations `SPEC L<n>` refer to `SPEC.md` line numbers.

## Overview

Bidirectional traceability **FR/NFR <-> SRS acceptance criterion <-> design element <-> test case**, supporting ASPICE SWE.3/SYS.4.
This is the P1 baseline. Design elements are the `implementation_functions` declared in the SRS FR Block; they are PLANNED until P2 (`02-architecture/SAD.md`) fixes the module design. Test cases are PLANNED IDs with proposed names; `02-architecture/TEST_SPEC.md` is the authoritative test catalog and names take precedence on conflict. `03-development/src/` and `03-development/tests/` are empty at P1, so no code or test exists yet.

**Status vocabulary**: `PLANNED` (requirement approved, test case named, nothing executed), `IN_PROGRESS` (code exists), `VERIFIED` (test actually executed and passed). Per AC-N9.6, `VERIFIED` is never assigned in this document by hand; it is assigned only from real test results in a downstream phase (`04-testing/TEST_RESULTS.md`, `05-verification/VERIFICATION_REPORT.md`). All rows are `PLANNED`.

**Layer vocabulary**: `unit`, `static` (scan/lint/config check), `integration` (real DB, httpx ASGITransport), `e2e` (`make verify-system`).

---

## 1. Requirement <-> SRS Mapping (Forward)

| Req ID | Requirement | SRS Section | Priority | ACs | Test Cases | Status |
|---|---|---|---|---|---|---|
| FR-01 | Task resource CRUD API | SRS §3 FR-01 | HIGH | AC-1.1..AC-1.8 (8) | TC-FR01-01..TC-FR01-08 | PLANNED |
| FR-02 | Task execution endpoint | SRS §3 FR-02 | HIGH | AC-2.1..AC-2.5 (5) | TC-FR02-01..TC-FR02-05 | PLANNED |
| FR-03 | API key authentication | SRS §3 FR-03 | HIGH | AC-3.1..AC-3.5 (5) | TC-FR03-01..TC-FR03-05 | PLANNED |
| FR-04 | Scope authorization | SRS §3 FR-04 | HIGH | AC-4.1..AC-4.4 (4) | TC-FR04-01..TC-FR04-04 | PLANNED |
| FR-05 | Rate limiting | SRS §3 FR-05 | HIGH | AC-5.1..AC-5.4 (4) | TC-FR05-01..TC-FR05-04 | PLANNED |
| FR-06 | Persistence layer and transaction boundary | SRS §3 FR-06 | HIGH | AC-6.1..AC-6.5 (5) | TC-FR06-01..TC-FR06-05 | PLANNED |
| FR-07 | Schema migration (Alembic v1/v2/v3) | SRS §3 FR-07 | HIGH | AC-7.1..AC-7.5 (5) | TC-FR07-01..TC-FR07-05 | PLANNED |
| FR-08 | Async executor | SRS §3 FR-08 | HIGH | AC-8.1..AC-8.4 (4) | TC-FR08-01..TC-FR08-04 | PLANNED |
| FR-09 | Health checks and observability | SRS §3 FR-09 | MEDIUM | AC-9.1..AC-9.5 (5) | TC-FR09-01..TC-FR09-05 | PLANNED |
| FR-10 | Error contract (RFC 7807) | SRS §3 FR-10 | HIGH | AC-10.1..AC-10.6 (6) | TC-FR10-01..TC-FR10-06 | PLANNED |
| NFR-01 | Performance and query efficiency | SRS §4 NFR-01 | HIGH | AC-N1.1..AC-N1.3 (3) | TC-N01-01..TC-N01-03 | PLANNED |
| NFR-02 | HTTP and data-layer security | SRS §4 NFR-02 | HIGH | AC-N2.1..AC-N2.7 (7) | TC-N02-01..TC-N02-07 | PLANNED |
| NFR-03 | Error handling, transactions, async correctness | SRS §4 NFR-03 | HIGH | AC-N3.1..AC-N3.6 (6) | TC-N03-01..TC-N03-06 | PLANNED |
| NFR-04 | Sensitive data redaction | SRS §4 NFR-04 | HIGH | AC-N4.1..AC-N4.3 (3) | TC-N04-01..TC-N04-03 | PLANNED |
| NFR-05 | Documentation coverage | SRS §4 NFR-05 | LOW | AC-N5.1..AC-N5.2 (2) | TC-N05-01..TC-N05-02 | PLANNED |
| NFR-06 | Architecture layering contract | SRS §4 NFR-06 | HIGH | AC-N6.1..AC-N6.4 (4) | TC-N06-01..TC-N06-04 | PLANNED |
| NFR-07 | Dependency and license compliance | SRS §4 NFR-07 | MEDIUM | AC-N7.1..AC-N7.4 (4) | TC-N07-01..TC-N07-04 | PLANNED |
| NFR-08 | Mutation testing | SRS §4 NFR-08 | MEDIUM | AC-N8.1..AC-N8.3 (3) | TC-N08-01..TC-N08-03 | PLANNED |
| NFR-09 | Verification authenticity (zero skip) | SRS §4 NFR-09 | HIGH | AC-N9.1..AC-N9.6 (6) | TC-N09-01..TC-N09-06 | PLANNED |
| NFR-10 | Integration coverage | SRS §4 NFR-10 | HIGH | AC-N10.1..AC-N10.3 (3) | TC-N10-01..TC-N10-03 | PLANNED |
| NFR-11 | Readability | SRS §4 NFR-11 | LOW | AC-N11.1..AC-N11.4 (4) | TC-N11-01..TC-N11-04 | PLANNED |
| NFR-12 | System verification target | SRS §4 NFR-12 | HIGH | AC-N12.1..AC-N12.3 (3) | TC-N12-01..TC-N12-03 | PLANNED |

SPEC_TRACKING.md Decision Framework per FR is consistent with the verification methods in section 3.

## 2. Requirement <-> Design Element Mapping

| Req ID | Design Element (SRS FR Block `implementation_functions` / project-side artifact) | Design Doc | Status |
|---|---|---|---|
| FR-01 | taskq_api.api.tasks; taskq_api.service.tasks; taskq_api.repository.tasks | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-02 | taskq_api.service.runner; taskq_api.api.runs; taskq_api.repository.results | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-03 | taskq_api.service.auth; taskq_api.repository.api_keys; taskq_api.__main__ | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-04 | taskq_api.service.auth.require_scope | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-05 | taskq_api.service.rate_limit; taskq_api.repository.rate_buckets | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-06 | taskq_api.repository.session; taskq_api.repository | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-07 | migrations/versions/v1; migrations/versions/v2; migrations/versions/v3_split_results | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-08 | taskq_api.service.runner; taskq_api.app.lifespan | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-09 | taskq_api.api.health; taskq_api.api.metrics; taskq_api.service.metrics | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| FR-10 | taskq_api.errors; taskq_api.api.error_handlers | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-01 | taskq_api.repository.tasks (eager loading); benchmark harness | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-02 | all of taskq_api (grep gates); taskq_api.app (CORS) | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-03 | taskq_api.repository.session; taskq_api.service.runner; migrations/versions | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-04 | taskq_api.service.redaction (planned); taskq_api.config | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-05 | all public symbols; FastAPI OpenAPI metadata | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-06 | .importlinter | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-07 | requirements.txt; requirements.lock; 08-config/SBOM.json | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-08 | .methodology/harness_config.json | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-09 | 03-development/tests (all); pytest configuration | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-10 | 03-development/tests/integration | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-11 | all of taskq_api (api handlers, file layout) | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |
| NFR-12 | Makefile (verify-system); .env.example | `02-architecture/SAD.md` (module design, pending P2) | PLANNED |

The design-element names are the SRS FR Block names; P2 may rename them, in which case this section is updated and the change is recorded in section 7.

## 3. Acceptance Criterion <-> Test Case Mapping

One test case per acceptance criterion (1:1). Test function names carry the `test_frNN` / `test_nfrNN` prefix so a test is attributable to its requirement by name.

### FR-01: Task resource CRUD API

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-1.1 | SPEC L83,L361 | TC-FR01-01 | integration | `test_fr01_create_task_returns_201` | pytest integration | PLANNED |
| AC-1.2 | SPEC L84 | TC-FR01-02 | integration | `test_fr01_get_task_returns_all_fields` | pytest integration | PLANNED |
| AC-1.3 | SPEC L85 | TC-FR01-03 | integration | `test_fr01_list_tasks_filters_and_cursor` | pytest integration | PLANNED |
| AC-1.4 | SPEC L86 | TC-FR01-04 | integration | `test_fr01_delete_task_removes_results_same_txn` | pytest integration | PLANNED |
| AC-1.5 | SPEC L88 | TC-FR01-05 | integration | `test_fr01_invalid_body_returns_422` | pytest integration (see NFR-99.2/99.3) | PLANNED |
| AC-1.6 | SPEC L89 | TC-FR01-06 | integration | `test_fr01_unknown_id_returns_404` | pytest integration | PLANNED |
| AC-1.7 | SPEC L90 | TC-FR01-07 | integration | `test_fr01_pagination_is_cursor_based` | pytest integration | PLANNED |
| AC-1.8 | SPEC L91 | TC-FR01-08 | integration | `test_fr01_list_limit_default_50_max_200` | pytest integration | PLANNED |

### FR-02: Task execution endpoint

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-2.1 | SPEC L95 | TC-FR02-01 | integration | `test_fr02_run_returns_202_with_run_id` | pytest integration | PLANNED |
| AC-2.2 | SPEC L96 | TC-FR02-02 | integration | `test_fr02_run_uses_exec_without_shell_and_times_out` | pytest integration + grep gate | PLANNED |
| AC-2.3 | SPEC L97 | TC-FR02-03 | integration | `test_fr02_run_lifecycle_state_machine` | pytest integration | PLANNED |
| AC-2.4 | SPEC L98 | TC-FR02-04 | integration | `test_fr02_results_persisted_in_task_results` | pytest integration | PLANNED |
| AC-2.5 | SPEC L99 | TC-FR02-05 | integration | `test_fr02_runs_history_newest_first` | pytest integration | PLANNED |

### FR-03: API key authentication

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-3.1 | SPEC L103 | TC-FR03-01 | integration | `test_fr03_missing_or_invalid_key_returns_401` | pytest integration | PLANNED |
| AC-3.2 | SPEC L104,L374 | TC-FR03-02 | integration | `test_fr03_key_stored_as_sha256_hash_only` | pytest DB inspection + grep hmac.compare_digest | PLANNED |
| AC-3.3 | SPEC L105 | TC-FR03-03 | integration | `test_fr03_key_create_cli_prints_plaintext_once` | pytest CLI | PLANNED |
| AC-3.4 | SPEC L106 | TC-FR03-04 | integration | `test_fr03_revoked_key_returns_401` | pytest integration | PLANNED |
| AC-3.5 | SPEC L107 | TC-FR03-05 | integration | `test_fr03_health_endpoints_need_no_key` | pytest integration | PLANNED |

### FR-04: Scope authorization

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-4.1 | SPEC L111 | TC-FR04-01 | integration | `test_fr04_scope_hierarchy_matrix` | pytest integration | PLANNED |
| AC-4.2 | SPEC L112 | TC-FR04-02 | integration | `test_fr04_insufficient_scope_returns_403` | pytest integration | PLANNED |
| AC-4.3 | SPEC L112,L362 | TC-FR04-03 | integration | `test_fr04_403_does_not_leak_existence` | pytest integration | PLANNED |
| AC-4.4 | SPEC L113 | TC-FR04-04 | unit | `test_fr04_every_v1_route_uses_scope_dependency` | pytest route introspection | PLANNED |

### FR-05: Rate limiting

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-5.1 | SPEC L117 | TC-FR05-01 | integration | `test_fr05_bucket_trigger_and_recovery` | pytest integration | PLANNED |
| AC-5.2 | SPEC L118,L365 | TC-FR05-02 | integration | `test_fr05_over_limit_returns_429_retry_after` | pytest integration | PLANNED |
| AC-5.3 | SPEC L119 | TC-FR05-03 | unit | `test_fr05_bucket_update_single_txn_row_lock` | pytest repository test + code review | PLANNED |
| AC-5.4 | SPEC L120 | TC-FR05-04 | integration | `test_fr05_health_endpoints_not_rate_limited` | pytest integration | PLANNED |

### FR-06: Persistence layer and transaction boundary

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-6.1 | SPEC L124 | TC-FR06-01 | static | `test_fr06_service_layer_holds_no_session` | lint-imports | PLANNED |
| AC-6.2 | SPEC L125 | TC-FR06-02 | unit | `test_fr06_session_commit_on_success_rollback_on_error` | pytest unit | PLANNED |
| AC-6.3 | SPEC L126,L373 | TC-FR06-03 | static | `test_fr06_no_string_built_sql` | SQL-concat scan | PLANNED |
| AC-6.4 | SPEC L127,L370 | TC-FR06-04 | integration | `test_fr06_list_query_count_constant` | pytest SQL count | PLANNED |
| AC-6.5 | SPEC L128 | TC-FR06-05 | unit | `test_fr06_engine_pool_size_and_pre_ping` | pytest unit | PLANNED |

### FR-07: Schema migration (Alembic v1/v2/v3)

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-7.1 | SPEC L132-138 | TC-FR07-01 | integration | `test_fr07_three_revisions_each_with_downgrade` | pytest real SQLite file | PLANNED |
| AC-7.2 | SPEC L140,L369 | TC-FR07-02 | integration | `test_fr07_upgrade_head_and_downgrade_base_clean` | pytest real SQLite file | PLANNED |
| AC-7.3 | SPEC L141,L368 | TC-FR07-03 | integration | `test_fr07_roundtrip_sample_data_identical_per_column` | pytest real SQLite file | PLANNED |
| AC-7.4 | SPEC L142 | TC-FR07-04 | integration | `test_fr07_downgrade_is_real_not_drop_shortcut` | pytest data comparison + code review | PLANNED |
| AC-7.5 | SPEC L143 | TC-FR07-05 | unit | `test_fr07_offline_sql_generation` | pytest alembic offline | PLANNED |

### FR-08: Async executor

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-8.1 | SPEC L147,L381 | TC-FR08-01 | integration | `test_fr08_graceful_drain_marks_interrupted` | pytest integration | PLANNED |
| AC-8.2 | SPEC L148 | TC-FR08-02 | unit | `test_fr08_concurrency_cap_queues_excess` | pytest unit | PLANNED |
| AC-8.3 | SPEC L149,L453 | TC-FR08-03 | integration | `test_fr08_timeout_kills_process_no_orphan` | pytest integration | PLANNED |
| AC-8.4 | SPEC L150 | TC-FR08-04 | unit | `test_fr08_cancelled_error_propagates` | pytest unit | PLANNED |

### FR-09: Health checks and observability

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-9.1 | SPEC L156 | TC-FR09-01 | integration | `test_fr09_healthz_returns_ok` | pytest integration | PLANNED |
| AC-9.2 | SPEC L157 | TC-FR09-02 | integration | `test_fr09_readyz_ok_when_db_up_and_at_head` | pytest integration | PLANNED |
| AC-9.3 | SPEC L157,L366 | TC-FR09-03 | integration | `test_fr09_readyz_503_when_db_down` | pytest integration | PLANNED |
| AC-9.4 | SPEC L160,L367 | TC-FR09-04 | integration | `test_fr09_readyz_503_when_migration_behind` | pytest integration | PLANNED |
| AC-9.5 | SPEC L158 | TC-FR09-05 | integration | `test_fr09_metrics_admin_payload` | pytest integration | PLANNED |

### FR-10: Error contract (RFC 7807)

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-10.1 | SPEC L164 | TC-FR10-01 | integration | `test_fr10_non_2xx_content_type_problem_json` | pytest integration | PLANNED |
| AC-10.2 | SPEC L165 | TC-FR10-02 | integration | `test_fr10_problem_body_required_fields` | pytest integration | PLANNED |
| AC-10.3 | SPEC L166,L375,L451 | TC-FR10-03 | integration | `test_fr10_500_body_leaks_no_internals` | pytest integration | PLANNED |
| AC-10.4 | SPEC L167 | TC-FR10-04 | integration | `test_fr10_correlation_id_header_matches_log` | pytest integration + log capture | PLANNED |
| AC-10.5 | SPEC L168,L335-345 | TC-FR10-05 | integration | `test_fr10_status_to_problem_type_mapping` | pytest integration | PLANNED |
| AC-10.6 | SPEC L344,L347 | TC-FR10-06 | integration | `test_fr10_timeout_is_200_and_cancel_not_500` | pytest integration | PLANNED |

### NFR-01: Performance and query efficiency

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N1.1 | SPEC L179,L371 | TC-N01-01 | integration | `test_nfr01_get_task_p95_under_30ms` | pytest-benchmark (see NFR-99.1) | PLANNED |
| AC-N1.2 | SPEC L180 | TC-N01-02 | integration | `test_nfr01_list_p95_under_80ms` | pytest-benchmark (see NFR-99.1) | PLANNED |
| AC-N1.3 | SPEC L182,L370 | TC-N01-03 | integration | `test_nfr01_sql_statement_count_constant` | pytest SQL count | PLANNED |

### NFR-02: HTTP and data-layer security

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N2.1 | SPEC L187-188,L372 | TC-N02-01 | static | `test_nfr02_no_shell_eval_exec` | grep gate | PLANNED |
| AC-N2.2 | SPEC L189,L373 | TC-N02-02 | static | `test_nfr02_no_sql_concatenation` | grep + code review | PLANNED |
| AC-N2.3 | SPEC L190 | TC-N02-03 | integration | `test_nfr02_api_key_hashed_compare_digest` | DB inspection | PLANNED |
| AC-N2.4 | SPEC L191 | TC-N02-04 | integration | `test_nfr02_403_no_existence_leak` | pytest integration | PLANNED |
| AC-N2.5 | SPEC L192 | TC-N02-05 | integration | `test_nfr02_error_body_no_internals` | pytest integration | PLANNED |
| AC-N2.6 | SPEC L193 | TC-N02-06 | integration | `test_nfr02_cors_default_deny` | pytest integration | PLANNED |
| AC-N2.7 | SPEC L194,L379 | TC-N02-07 | static | `test_nfr02_bandit_zero_high_medium` | bandit | PLANNED |

### NFR-03: Error handling, transactions, async correctness

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N3.1 | SPEC L199 | TC-N03-01 | unit | `test_nfr03_request_txn_commit_rollback` | pytest unit | PLANNED |
| AC-N3.2 | SPEC L200 | TC-N03-02 | static | `test_nfr03_no_bare_except_or_swallow` | ast-error-handling scan | PLANNED |
| AC-N3.3 | SPEC L201 | TC-N03-03 | unit | `test_nfr03_cancelled_error_reraised` | pytest unit | PLANNED |
| AC-N3.4 | SPEC L202 | TC-N03-04 | integration | `test_nfr03_db_failure_readyz_503_no_infinite_retry` | pytest integration | PLANNED |
| AC-N3.5 | SPEC L203 | TC-N03-05 | integration | `test_nfr03_timeout_leaves_no_orphan` | pytest integration | PLANNED |
| AC-N3.6 | SPEC L204 | TC-N03-06 | integration | `test_nfr03_failed_migration_rolls_back` | pytest real SQLite file | PLANNED |

### NFR-04: Sensitive data redaction

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N4.1 | SPEC L209-210 | TC-N04-01 | unit | `test_nfr04_secret_lines_redacted` | pytest unit | PLANNED |
| AC-N4.2 | SPEC L211,L376,L452 | TC-N04-02 | integration | `test_nfr04_db_url_absent_from_logs_errors_metrics` | pytest integration | PLANNED |
| AC-N4.3 | SPEC L212 | TC-N04-03 | integration | `test_nfr04_key_plaintext_never_persisted` | pytest DB inspection | PLANNED |

### NFR-05: Documentation coverage

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N5.1 | SPEC L217 | TC-N05-01 | static | `test_nfr05_public_symbols_docstring_with_fr_ref` | ast-docstrings scan | PLANNED |
| AC-N5.2 | SPEC L218 | TC-N05-02 | integration | `test_nfr05_openapi_summary_description_per_operation` | pytest /openapi.json | PLANNED |

### NFR-06: Architecture layering contract

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N6.1 | SPEC L223-229 | TC-N06-01 | static | `test_nfr06_layers_contract_declared` | lint-imports | PLANNED |
| AC-N6.2 | SPEC L230,L377 | TC-N06-02 | static | `test_nfr06_sqlalchemy_forbidden_outside_repository` | lint-imports + blocked-import test | PLANNED |
| AC-N6.3 | SPEC L231 | TC-N06-03 | static | `test_nfr06_lint_imports_exit_zero` | lint-imports exit code | PLANNED |
| AC-N6.4 | SPEC L232 | TC-N06-04 | static | `test_nfr06_contract_not_weakened` | code review of .importlinter | PLANNED |

### NFR-07: Dependency and license compliance

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N7.1 | SPEC L237 | TC-N07-01 | static | `test_nfr07_runtime_deps_pinned_and_locked` | pytest file parse | PLANNED |
| AC-N7.2 | SPEC L238,L378 | TC-N07-02 | static | `test_nfr07_licenses_within_allowlist` | pip-licenses | PLANNED |
| AC-N7.3 | SPEC L239 | TC-N07-03 | static | `test_nfr07_license_scan_covers_full_tree` | pip-licenses | PLANNED |
| AC-N7.4 | SPEC L240 | TC-N07-04 | static | `test_nfr07_sbom_content` | pytest SBOM parse | PLANNED |

### NFR-08: Mutation testing

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N8.1 | SPEC L245 | TC-N08-01 | static | `test_nfr08_mutation_feature_enabled` | pytest config parse | PLANNED |
| AC-N8.2 | SPEC L246,L380 | TC-N08-02 | static | `test_nfr08_mutation_score_at_least_70` | mutmut via mutation-test-score | PLANNED |
| AC-N8.3 | SPEC L247 | TC-N08-03 | static | `test_nfr08_scope_service_repository_with_rationale` | pytest config parse | PLANNED |

### NFR-09: Verification authenticity (zero skip)

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N9.1 | SPEC L252 | TC-N09-01 | static | `test_nfr09_no_skip_xfail_or_stub_tests` | pytest output + ast-assertions | PLANNED |
| AC-N9.2 | SPEC L253,L357 | TC-N09-02 | static | `test_nfr09_skipped_count_zero` | pytest -q | PLANNED |
| AC-N9.3 | SPEC L254 | TC-N09-03 | static | `test_nfr09_every_test_has_assert` | ast-assertions | PLANNED |
| AC-N9.4 | SPEC L255 | TC-N09-04 | static | `test_nfr09_no_test_exclusion_mechanisms` | pytest config review | PLANNED |
| AC-N9.5 | SPEC L256 | TC-N09-05 | integration | `test_nfr09_migration_tests_use_real_sqlite_file` | code review + AC-7.3 test | PLANNED |
| AC-N9.6 | SPEC L257 | TC-N09-06 | static | `test_nfr09_verified_only_when_tests_pass` | matrix vs pytest consistency (downstream) | PLANNED |

### NFR-10: Integration coverage

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N10.1 | SPEC L262,L359 | TC-N10-01 | integration | `test_nfr10_integration_line_coverage_80` | pytest --cov | PLANNED |
| AC-N10.2 | SPEC L263 | TC-N10-02 | static | `test_nfr10_integration_uses_asgi_transport` | code review | PLANNED |
| AC-N10.3 | SPEC L264 | TC-N10-03 | static | `test_nfr10_required_scenarios_enumerated` | TEST_SPEC coverage check | PLANNED |

### NFR-11: Readability

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N11.1 | SPEC L269 | TC-N11-01 | static | `test_nfr11_mi_at_least_80` | radon mi | PLANNED |
| AC-N11.2 | SPEC L269 | TC-N11-02 | static | `test_nfr11_function_cc_at_most_10` | radon cc | PLANNED |
| AC-N11.3 | SPEC L270 | TC-N11-03 | static | `test_nfr11_file_and_directory_size_limits` | pytest file scan | PLANNED |
| AC-N11.4 | SPEC L271 | TC-N11-04 | static | `test_nfr11_handler_length_at_most_40` | pytest AST | PLANNED |

### NFR-12: System verification target

| AC | SPEC cite | TC ID | Layer | Proposed Test Function | Verifier | Status |
|---|---|---|---|---|---|---|
| AC-N12.1 | SPEC L276-280 | TC-N12-01 | static | `test_nfr12_makefile_verify_system_steps` | pytest Makefile parse | PLANNED |
| AC-N12.2 | SPEC L281,L383 | TC-N12-02 | e2e | `test_nfr12_verify_system_prints_pass` | make verify-system | PLANNED |
| AC-N12.3 | SPEC L325,L382 | TC-N12-03 | static | `test_nfr12_env_example_declares_12_vars` | grep -c | PLANNED |

## 4. SPEC Section 8 Command <-> Acceptance Criterion

All 27 machine-decidable commands of SPEC §8 (L351-383) map to at least one AC and thus to a TC (SRS §5).

| SPEC §8 # | AC(s) | TC(s) |
|---|---|---|
| 1 | AC-N9.2 | TC-N09-02 |
| 2 | AC-N9.1 | TC-N09-01 |
| 3 | AC-N10.1 | TC-N10-01 |
| 4 | AC-1.1 | TC-FR01-01 |
| 5 | AC-3.1 | TC-FR03-01 |
| 6 | AC-4.2, AC-4.3 | TC-FR04-02, TC-FR04-03 |
| 7 | AC-1.6 | TC-FR01-06 |
| 8 | AC-10.5 | TC-FR10-05 |
| 9 | AC-5.2 | TC-FR05-02 |
| 10 | AC-9.3 | TC-FR09-03 |
| 11 | AC-9.4 | TC-FR09-04 |
| 12 | AC-7.3 | TC-FR07-03 |
| 13 | AC-7.2 | TC-FR07-02 |
| 14 | AC-N1.3 | TC-N01-03 |
| 15 | AC-N1.1 | TC-N01-01 |
| 16 | AC-N2.1 | TC-N02-01 |
| 17 | AC-N2.2 | TC-N02-02 |
| 18 | AC-3.2, AC-N2.3 | TC-FR03-02, TC-N02-03 |
| 19 | AC-10.3, AC-N2.5 | TC-FR10-03, TC-N02-05 |
| 20 | AC-N4.2 | TC-N04-02 |
| 21 | AC-N6.1, AC-N6.2, AC-N6.3 | TC-N06-01, TC-N06-02, TC-N06-03 |
| 22 | AC-N7.2, AC-N7.3 | TC-N07-02, TC-N07-03 |
| 23 | AC-N2.7 | TC-N02-07 |
| 24 | AC-N8.2 | TC-N08-02 |
| 25 | AC-8.1, AC-8.3 | TC-FR08-01, TC-FR08-03 |
| 26 | AC-N12.3 | TC-N12-03 |
| 27 | AC-N12.2 | TC-N12-02 |

## 5. Design Element <-> Code <-> Test (Reverse)

Code locations were fixed in P3 and are listed below. Each row cites one executed test function as evidence; coverage and pass counts come from `04-testing/TEST_RESULTS.md` and `04-testing/COVERAGE_REPORT.md` (224 passed, 100% line coverage of `03-development/src`).

| Design Element | Code File | Test Cases (by Req) | Coverage | Status |
|---|---|---|---|---|
| taskq_api.api.tasks; taskq_api.service.tasks; taskq_api.repository.tasks | `03-development/src/taskq_api/api/routes_tasks.py`, `03-development/src/taskq_api/service/tasks.py`, `03-development/src/taskq_api/repository/tasks.py` | TC-FR01-01..TC-FR01-08 (FR-01); `test_fr01_create_task_returns_201` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.service.runner; taskq_api.api.runs; taskq_api.repository.results | `03-development/src/taskq_api/service/runner.py`, `03-development/src/taskq_api/api/routes_runs.py`, `03-development/src/taskq_api/repository/results.py` | TC-FR02-01..TC-FR02-05 (FR-02); `test_fr02_run_returns_202_with_run_id` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.service.auth; taskq_api.repository.api_keys; taskq_api.__main__ | `03-development/src/taskq_api/service/auth.py`, `03-development/src/taskq_api/repository/api_keys.py`, `03-development/src/taskq_api/__main__.py` | TC-FR03-01..TC-FR03-05 (FR-03); `test_fr03_invalid_key_returns_401` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.service.auth.require_scope | `03-development/src/taskq_api/service/auth.py` | TC-FR04-01..TC-FR04-04 (FR-04); `test_fr04_scope_hierarchy_matrix` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.service.rate_limit; taskq_api.repository.rate_buckets | `03-development/src/taskq_api/service/ratelimit.py`, `03-development/src/taskq_api/repository/rate_buckets.py` | TC-FR05-01..TC-FR05-04 (FR-05); `test_fr05_bucket_trigger_and_recovery` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.repository.session; taskq_api.repository | `03-development/src/taskq_api/repository/session.py` | TC-FR06-01..TC-FR06-05 (FR-06); `test_fr06_session_commit_on_success_rollback_on_error` | 100% line coverage, 224 passed | VERIFIED |
| migrations/versions/v1; migrations/versions/v2; migrations/versions/v3_split_results | `03-development/src/migrations/versions/v1_initial.py`, `03-development/src/migrations/versions/v2_tags.py`, `03-development/src/migrations/versions/v3_split_results.py` | TC-FR07-01..TC-FR07-05 (FR-07); `test_fr07_upgrade_head_and_downgrade_base_clean` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.service.runner; taskq_api.app.lifespan | `03-development/src/taskq_api/service/runner.py`, `03-development/src/taskq_api/app.py` | TC-FR08-01..TC-FR08-04 (FR-08); `test_fr08_graceful_drain_marks_interrupted` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.api.health; taskq_api.api.metrics; taskq_api.service.metrics | `03-development/src/taskq_api/api/routes_health.py`, `03-development/src/taskq_api/api/routes_metrics.py`, `03-development/src/taskq_api/repository/stats.py` | TC-FR09-01..TC-FR09-05 (FR-09); `test_fr09_healthz_returns_ok` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.errors; taskq_api.api.error_handlers | `03-development/src/taskq_api/errors.py`, `03-development/src/taskq_api/api/error_handlers.py` | TC-FR10-01..TC-FR10-06 (FR-10); `test_fr10_problem_body_required_fields` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.repository.tasks (eager loading); benchmark harness | `03-development/src/taskq_api/repository/tasks.py` | TC-N01-01..TC-N01-03 (NFR-01); `test_nfr01_get_task_p95_under_30ms` | 100% line coverage, 224 passed | VERIFIED |
| all of taskq_api (grep gates); taskq_api.app (CORS) | `03-development/src/taskq_api/app.py` and every module under `03-development/src/taskq_api/` | TC-N02-01..TC-N02-07 (NFR-02); `test_nfr02_no_shell_eval_exec` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.repository.session; taskq_api.service.runner; migrations/versions | `03-development/src/taskq_api/repository/session.py`, `03-development/src/taskq_api/service/runner.py` | TC-N03-01..TC-N03-06 (NFR-03); `test_nfr03_no_bare_except_or_swallow` | 100% line coverage, 224 passed | VERIFIED |
| taskq_api.service.redaction (planned); taskq_api.config | `03-development/src/taskq_api/service/redact.py`, `03-development/src/taskq_api/config.py` | TC-N04-01..TC-N04-03 (NFR-04); `test_nfr04_secret_lines_redacted` | 100% line coverage, 224 passed | VERIFIED |
| all public symbols; FastAPI OpenAPI metadata | `03-development/src/taskq_api/api/routes_tasks.py` and every public symbol under `03-development/src/taskq_api/` | TC-N05-01..TC-N05-02 (NFR-05); `test_nfr05_public_symbols_docstring_with_fr_ref` | 100% line coverage, 224 passed | VERIFIED |
| .importlinter | `.importlinter` | TC-N06-01..TC-N06-04 (NFR-06); `test_nfr06_layers_contract_declared` | 100% line coverage, 224 passed | VERIFIED |
| requirements.txt; requirements.lock; 08-config/SBOM.json | `requirements.txt`, `requirements.lock`, `08-config/SBOM.json` | TC-N07-01..TC-N07-04 (NFR-07); `test_nfr07_runtime_deps_pinned_and_locked` | 100% line coverage, 224 passed | VERIFIED |
| .methodology/harness_config.json | `.methodology/harness_config.json` | TC-N08-01..TC-N08-03 (NFR-08); `test_nfr08_mutation_score_at_least_70` | 100% line coverage, 224 passed | VERIFIED |
| 03-development/tests (all); pytest configuration | `03-development/tests/`, `setup.cfg` | TC-N09-01..TC-N09-06 (NFR-09); `test_nfr09_skipped_count_zero` | 100% line coverage, 224 passed | VERIFIED |
| 03-development/tests/integration | `03-development/tests/integration/test_nfr10_integration.py` | TC-N10-01..TC-N10-03 (NFR-10); `test_nfr10_integration_uses_asgi_transport` | 100% line coverage, 224 passed | VERIFIED |
| all of taskq_api (api handlers, file layout) | every module under `03-development/src/taskq_api/` | TC-N11-01..TC-N11-04 (NFR-11); `test_nfr11_function_cc_at_most_10` | 100% line coverage, 224 passed | VERIFIED |
| Makefile (verify-system); .env.example | `Makefile`, `.env.example` | TC-N12-01..TC-N12-03 (NFR-12); `test_nfr12_makefile_verify_system_steps` | 100% line coverage, 224 passed | VERIFIED |

High-risk modules requiring per-module TDD coverage (SRS C-5, SPEC L427): `taskq_api.service.runner` (FR-02, FR-08, NFR-03), `taskq_api.service.auth` (FR-03, FR-04), `taskq_api.repository.session` (FR-06, NFR-03), `migrations/versions/v3_split_results.py` (FR-07).

## 6. Reverse Check: Test Case -> Requirement

Every TC in section 3 names exactly one parent requirement and one AC, so no orphan test case exists in the baseline. Cross-reference notes where one test case also evidences another requirement:

| TC | Primary Req | Also evidences |
|---|---|---|
| TC-N02-03 | NFR-02 | AC-3.2 (FR-03) |
| TC-N02-04 | NFR-02 | AC-4.3 (FR-04) |
| TC-N02-05 | NFR-02 | AC-10.3 (FR-10) |
| TC-N03-01 | NFR-03 | AC-6.2 (FR-06) |
| TC-N03-03 | NFR-03 | AC-8.4 (FR-08), AC-10.6 (FR-10) |
| TC-N03-05 | NFR-03 | AC-8.3 (FR-08) |
| TC-N09-05 | NFR-09 | AC-7.3 (FR-07) |
| TC-N06-02 | NFR-06 | AC-6.1 (FR-06) |
| TC-N02-02 | NFR-02 | AC-6.3 (FR-06) |
| TC-N01-03 | NFR-01 | AC-6.4 (FR-06) |

## 7. Completeness Verification

| Check | Target | Actual | Status |
|---|---|---|---|
| Requirement -> SRS section (10 FR + 12 NFR) | 100% | 22/22 = 100% | PASS |
| Requirement -> at least one AC | 100% | 22/22 = 100% | PASS |
| AC -> TC (1:1) | 100% | 99/99 = 100% | PASS |
| SPEC §8 commands -> AC | 27/27 | 27/27 | PASS |
| Requirement -> design element | 100% | 22/22 = 100% (names PLANNED) | PASS (provisional) |
| Design element -> code | 100% | 0% (no code at P1) | PENDING P3 |
| TC -> executed and passed | 100% | 0% (no tests at P1) | PENDING P3/P4 |
| Line coverage | 100% total, >=80% integration (SPEC §8 #2, #3) | not measured | PENDING |

## 8. Known Gaps and Dependencies

- **Open Issues carried from SRS §7**: NFR-99.1 (p95 measurement, AC-N1.1/N1.2), NFR-99.2 and NFR-99.3 (FR-01 validation rules and 422 vs 409 for duplicate name, AC-1.5 / AC-10.5 / SPEC §8 #8), NFR-99.4 (`interrupted` status, AC-8.1), NFR-99.5 (docstring scope for migrations, AC-N5.1), NFR-99.6 (100% coverage scope). Affected TCs may change expected values once resolved.
- **Framework dimension coverage**: per SRS coverage notes, the framework scoring dimensions verify only part of NFR-01..NFR-12; the dedicated tests listed in section 3 are required and must not be replaced by the dimension scores.
- **Derived mapping**: AC-N12.3 (SPEC §8 #26) is attached to NFR-12 because SPEC assigns it no owning NFR (SRS DERIVED note).
- **Framework-default gates without FR/NFR** (SRS §5): `linting`, `type_safety`, `test_coverage`, `architecture`, `secrets_scanning`; no TC rows in this matrix.
- **Stub downstream docs**: `TEST_INVENTORY.yaml` (project root) and `02-architecture/TEST_SPEC.md` are unfilled templates at this point; the proposed names above must be copied into TEST_INVENTORY.yaml (naming authority) and reconciled at P2.

## 9. Maintenance and Downstream Links

| Phase | Document | Matrix Section Updated |
|---|---|---|
| P2 | `02-architecture/SAD.md`, `02-architecture/ADR.md` | Section 2, section 5 (design elements) |
| P2 | `02-architecture/TEST_SPEC.md` | Section 3 (final test names) |
| P3 | `03-development/src/`, `03-development/tests/` | Section 5 (Code column); status VERIFIED in P4 |
| P4 | `04-testing/TEST_PLAN.md`, `04-testing/TEST_RESULTS.md` | Section 3 status (VERIFIED only from executed results) |
| P5 | `05-verification/VERIFICATION_REPORT.md` | Section 7 final audit |

## 10. ASPICE Compliance

| ASPICE Capability | Status | Evidence |
|---|---|---|
| SWE.3.B.SP1 Task-to-work-product traceability | PARTIAL | Req -> SRS -> design element -> TC links (sections 1-3); code links pending P3 |
| SWE.3.B.SP2 Bidirectional traceability | PARTIAL | Forward (sections 1-4) and reverse (sections 5-6) present; code and result links pending |
| SWE.3.B.SP3 Traceability consistency | PASS (P1 scope) | Counts in section 7 computed from sections 1-4; IDs match SRS ACs and SPEC_TRACKING FR list |

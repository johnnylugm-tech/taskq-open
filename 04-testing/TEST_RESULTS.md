# TEST_RESULTS (Phase 4)

Scope: `03-development/tests` (test_target from `.sessi-work/phase4_ctx.json`), run with the project venv (Python 3.11.15). Raw output: `04-testing/coverage_raw.txt`.

## Pytest summary line (verbatim)

```
224 passed, 1 warning in 15.46s
```

## Totals

| Metric | Count |
|--------|-------|
| Cases run | 224 |
| Passed | 224 |
| Failed | 0 |
| Skipped | 0 |

## Failures / deferred issues

- None. `test_nfr09_verified_only_when_tests_pass` now passes after the `01-requirements/TRACEABILITY_MATRIX.md` VERIFIED rows were changed to cite backticked `test_*` function names.

## Warnings

- StarletteDeprecationWarning: `httpx` with `starlette.testclient` is deprecated (third-party).

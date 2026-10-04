# TEST_RESULTS

Scope: `03-development/tests` (test_target from `.sessi-work/phase4_ctx.json`), run with the project venv (Python 3.11.15). Raw output: `04-testing/coverage_raw.txt`.

## Pytest summary line (verbatim)

```
1 failed, 221 passed, 1 warning in 15.41s
```

## Totals

| Metric | Count |
|--------|-------|
| Cases run | 222 |
| Passed | 221 |
| Failed | 1 |
| Skipped | 0 |

## Failures / deferred issues

- `03-development/tests/test_nfr_static.py::test_nfr09_verified_only_when_tests_pass` FAILED (NFR-09 AC-N9.6).
  `01-requirements/TRACEABILITY_MATRIX.md` has 13 rows marked VERIFIED whose cell lists test file names (for example `| NFR-01 | test_nfr_runtime.py | VERIFIED |`) instead of backticked `test_*` function names. The test therefore treats them as unresolved. Cause is the matrix format, not product code. Not fixed here (out of scope). Deferred.

## Warnings

- StarletteDeprecationWarning: `httpx` with `starlette.testclient` is deprecated (third-party).

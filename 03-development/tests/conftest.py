"""Run-wide pytest guard rails for the whole suite (NFR-08 mutation testing).

Mutation testing treats pytest exit code 1 as the only "mutant detected"
signal, and bounds each run by wall-clock time. Two guard rails keep a broken
build from being mistaken for a passing one or from hanging the run:

* a collection error (for example a module that no longer imports) fails the
  run with exit code 1 instead of pytest's "interrupted" code 2;
* a test that blocks longer than ``PER_TEST_TIMEOUT_S`` fails instead of
  hanging the process, and under the mutation sandbox the first failure
  stops the run.
"""

from __future__ import annotations

import os
import signal

import pytest

PER_TEST_TIMEOUT_S = 10.0
_MUTATION_BASELINE_ENV = "HARNESS_MUTATION_BASELINE"


def pytest_configure(config: pytest.Config) -> None:
    config.option.continue_on_collection_errors = True
    if os.environ.get(_MUTATION_BASELINE_ENV) == "1":
        config.option.maxfail = 1


def _on_timeout(signum, frame) -> None:
    raise TimeoutError(f"test exceeded {PER_TEST_TIMEOUT_S}s")


@pytest.fixture(autouse=True)
def _per_test_timeout():
    previous = signal.signal(signal.SIGALRM, _on_timeout)
    signal.setitimer(signal.ITIMER_REAL, PER_TEST_TIMEOUT_S, PER_TEST_TIMEOUT_S)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

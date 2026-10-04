"""Readiness decision and metrics aggregation.

[FR-09] ``/readyz`` is ready only when the DB is reachable **and** its
migration revision is head (fail closed); ``/v1/metrics`` reports task counts,
run latency percentiles and rate-limit rejections, never the DB URL (NFR-04).

Citations: SPEC.md L152-160 (FR-09); SPEC.md L343 (503 not-ready);
02-architecture/SAD.md L70, L105, L206, L244.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

from taskq_api.repository import migration_state
from taskq_api.service.uow import UnitOfWork

_PERCENTILES = (50, 95, 99)


@dataclass(frozen=True)
class Readiness:
    """[FR-09] Readiness verdict; ``detail`` names the failing check.

    Citations: SPEC.md L157.
    """

    ready: bool
    detail: str


def readiness(db_url: str) -> Readiness:
    """[FR-09] Ready when the DB answers and ``alembic current`` == head.

    Citations: SPEC.md L157, L160.
    """
    state = migration_state.probe(db_url)
    if not state.reachable:
        return Readiness(False, "database unavailable")
    if state.current != state.head:
        return Readiness(False, "migration not at head")
    return Readiness(True, "ready")


class RejectionCounter:
    """[FR-09] Thread-safe count of 429 responses served by this process.

    Citations: SPEC.md L158.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0

    def increment(self) -> None:
        """[FR-09] Record one rate-limit rejection. Citations: SPEC.md L158."""
        with self._lock:
            self._count += 1

    @property
    def value(self) -> int:
        """[FR-09] Rejections so far. Citations: SPEC.md L158."""
        return self._count


def metrics(uow: UnitOfWork, rejections: RejectionCounter) -> dict[str, Any]:
    """[FR-09] Task counts by status, latency percentiles (ms) and 429 count.

    Citations: SPEC.md L158; 02-architecture/SAD.md L244 (no DB URL in metrics).
    """
    durations = uow.stats.run_durations_ms()
    return {
        "tasks_by_status": uow.stats.task_counts_by_status(),
        "latency_percentiles": {f"p{p}": _percentile(durations, p) for p in _PERCENTILES},
        "rate_limit_rejections": rejections.value,
    }


def _percentile(sorted_values: list[int], pct: int) -> int | None:
    """[FR-09] Nearest-rank percentile of ascending values; None when empty.

    Citations: SPEC.md L158.
    """
    if not sorted_values:
        return None
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[rank - 1]

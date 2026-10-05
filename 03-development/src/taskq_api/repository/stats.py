"""Aggregate queries backing ``/v1/metrics``.

[FR-09] Task counts by status and the finished-run durations from which
latency percentiles are computed.

Citations: SPEC.md L152-158 (FR-09); SPEC.md L126 (no string-built SQL);
02-architecture/SAD.md L79, L105.
"""
# pragma: no error-handling — thin statements on the caller's Session; failures roll back in UnitOfWork.__exit__

from __future__ import annotations

from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from taskq_api.models.result import TaskResult
from taskq_api.models.task import Task


def task_counts_by_status(session: Session) -> dict[str, int]:
    """[FR-09] ``{status: count}`` over every task. Citations: SPEC.md L158."""
    stmt = select(Task.status, func.count()).group_by(Task.status)
    return {status: count for status, count in session.execute(stmt)}


def run_durations_ms(session: Session) -> list[int]:
    """[FR-09] Durations of finished runs, ascending. Citations: SPEC.md L158."""
    stmt = (
        select(TaskResult.duration_ms)
        .where(TaskResult.duration_ms.is_not(None))
        .order_by(TaskResult.duration_ms)
    )
    return cast(list[int], list(session.scalars(stmt)))


class StatsRepository:
    """[FR-09] Metrics queries bound to one session.

    Citations: SPEC.md L158; 02-architecture/SAD.md L134.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def task_counts_by_status(self) -> dict[str, int]:
        """[FR-09] See :func:`task_counts_by_status`. Citations: SPEC.md L158."""
        return task_counts_by_status(self._session)

    def run_durations_ms(self) -> list[int]:
        """[FR-09] See :func:`run_durations_ms`. Citations: SPEC.md L158."""
        return run_durations_ms(self._session)

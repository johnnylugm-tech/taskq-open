"""``task_results`` queries.

[FR-02] Creates a run row on submit, fills in its outcome when the run
finishes, and lists a task's runs newest first.

Citations: SPEC.md L93-99 (FR-02); SPEC.md L312 (task_results columns);
SPEC.md L126 (no string-built SQL).
"""
# pragma: no error-handling — thin statements on the caller's Session; failures roll back in UnitOfWork.__exit__

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskq_api.models.result import TaskResult


class ResultRepository:
    """[FR-02] Task result access bound to one session.

    Citations: SPEC.md L98-99.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, result: TaskResult) -> TaskResult:
        """[FR-02] Insert a run row.

        Citations: SPEC.md L95, L98.
        """
        self._session.add(result)
        self._session.flush()
        return result

    def get(self, run_id: str) -> TaskResult | None:
        """[FR-02] Fetch one run row by id.

        Citations: SPEC.md L98.
        """
        return self._session.get(TaskResult, run_id)

    def list_for_task(self, task_id: str) -> list[TaskResult]:
        """[FR-02] All runs of ``task_id``, newest first; unfinished runs lead.

        Citations: SPEC.md L99.
        """
        stmt = (
            select(TaskResult)
            .where(TaskResult.task_id == task_id)
            .order_by(TaskResult.finished_at.desc().nulls_first(), TaskResult.id)
        )
        return list(self._session.scalars(stmt))

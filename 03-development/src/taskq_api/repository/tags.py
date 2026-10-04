"""``task_tags`` queries.

[FR-01] Detaches a task's tags inside the delete transaction.

Citations: SPEC.md L86 (delete in one transaction); SPEC.md L311-312.
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from taskq_api.models.tag import task_tags


class TagRepository:
    """[FR-01] Tag association access bound to one session.

    Citations: SPEC.md L312.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def detach_task(self, task_id: str) -> None:
        """[FR-01] Remove every ``task_tags`` row of ``task_id``.

        Citations: SPEC.md L86, L312.
        """
        self._session.execute(delete(task_tags).where(task_tags.c.task_id == task_id))

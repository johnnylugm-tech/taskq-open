"""Task queries with keyset (cursor) pagination.

[FR-01] Create / get / list / delete for the ``tasks`` table. Pagination is
keyset-based on ``(created_at, id)``; no OFFSET is ever emitted.

Citations: SPEC.md L79-91 (FR-01); SPEC.md L90 (cursor-based, no offset);
SPEC.md L126 (no string-built SQL); 02-architecture/SAD.md L97.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from sqlalchemy import ColumnElement, and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taskq_api.errors import Conflict, ValidationFailed
from taskq_api.models.result import TaskResult
from taskq_api.models.task import Task


def encode_cursor(task: Task) -> str:
    """[FR-01] Opaque cursor pointing just after ``task``.

    Citations: SPEC.md L85, L90.
    """
    raw = json.dumps({"c": task.created_at.isoformat(), "i": task.id})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """[FR-01] Decode a cursor; malformed input raises :class:`ValidationFailed`.

    Citations: SPEC.md L85, L88, L90.
    """
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(data["c"]), str(data["i"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise ValidationFailed("cursor is invalid") from exc


def after_cursor(cursor: str) -> ColumnElement[bool]:
    """[FR-01] Keyset predicate selecting rows strictly after ``cursor``.

    Citations: SPEC.md L90.
    """
    created_at, task_id = decode_cursor(cursor)
    return or_(
        Task.created_at > created_at,
        and_(Task.created_at == created_at, Task.id > task_id),
    )


class TaskRepository:
    """[FR-01] Task access bound to one session.

    Citations: SPEC.md L79-91.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: Task) -> Task:
        """[FR-01] Insert ``task``; a duplicate name raises :class:`Conflict`.

        Citations: SPEC.md L83, L88, L342.
        """
        self._session.add(task)
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise Conflict("task name already exists") from exc
        return task

    def get(self, task_id: str) -> Task | None:
        """[FR-01] Fetch one task by primary key.

        Citations: SPEC.md L84.
        """
        return self._session.get(Task, task_id)

    def list_page(
        self, status: str | None, limit: int, cursor: str | None
    ) -> tuple[list[Task], str | None]:
        """[FR-01] One keyset page ordered by ``(created_at, id)`` plus next cursor.

        Fetches ``limit + 1`` rows to learn whether another page exists, so the
        statement count is constant (NFR-01).

        Citations: SPEC.md L85, L90-91.
        """
        stmt = select(Task).order_by(Task.created_at, Task.id).limit(limit + 1)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if cursor is not None:
            stmt = stmt.where(after_cursor(cursor))
        rows = list(self._session.scalars(stmt))
        if len(rows) <= limit:
            return rows, None
        page = rows[:limit]
        return page, encode_cursor(page[-1])

    def delete(self, task: Task) -> None:
        """[FR-01] Delete ``task`` and its result rows in the current transaction.

        Citations: SPEC.md L86.
        """
        self._session.execute(delete(TaskResult).where(TaskResult.task_id == task.id))
        self._session.delete(task)

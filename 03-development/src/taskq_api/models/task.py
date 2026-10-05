"""``tasks`` table mapping.

[FR-01] The task resource exposed by ``/v1/tasks``.

[FR-06] ``Task.tags`` maps the ``task_tags`` association; list queries load it
explicitly so the page has no N+1.

Citations: SPEC.md L79-91 (FR-01); SPEC.md L309 (tasks columns); SPEC.md L137 (v2 unique name);
SPEC.md L127 (FR-06 eager loading); SPEC.md L311-312 (tags, task_tags).
"""
# pragma: no error-handling — declarative ORM mapping, no executable logic

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from taskq_api.models.base import Base, IsoDateTime

if TYPE_CHECKING:
    from taskq_api.models.tag import Tag


class Task(Base):
    """[FR-01] A queued shell task; ``name`` is unique.

    [FR-06] ``tags`` is lazy by default; callers needing it eager-load it.

    Citations: SPEC.md L88, L127, L309, L312.
    """

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_status_created_at", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(IsoDateTime, nullable=False)
    tags: Mapped[list[Tag]] = relationship(secondary="task_tags")

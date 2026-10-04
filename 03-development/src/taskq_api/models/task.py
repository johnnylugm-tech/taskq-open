"""``tasks`` table mapping.

[FR-01] The task resource exposed by ``/v1/tasks``.

Citations: SPEC.md L79-91 (FR-01); SPEC.md L309 (tasks columns); SPEC.md L137 (v2 unique name).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from taskq_api.models.base import Base, IsoDateTime


class Task(Base):
    """[FR-01] A queued shell task; ``name`` is unique.

    Citations: SPEC.md L88, L309.
    """

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_status_created_at", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(IsoDateTime, nullable=False)

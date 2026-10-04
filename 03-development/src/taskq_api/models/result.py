"""``task_results`` table mapping.

[FR-01] Result rows removed together with their task on delete.

Citations: SPEC.md L86 (delete with results); SPEC.md L313 (task_results columns).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from taskq_api.models.base import Base, IsoDateTime


class TaskResult(Base):
    """[FR-01] One execution result of a task.

    Citations: SPEC.md L313.
    """

    __tablename__ = "task_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout_tail: Mapped[str | None] = mapped_column(Text)
    stderr_tail: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    finished_at: Mapped[datetime | None] = mapped_column(IsoDateTime)

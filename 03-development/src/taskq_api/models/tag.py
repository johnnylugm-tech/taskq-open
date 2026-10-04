"""``tags`` and ``task_tags`` table mappings.

[FR-01] Tag associations removed together with their task on delete.

Citations: SPEC.md L86 (delete in one transaction); SPEC.md L311-312 (tags, task_tags).
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from taskq_api.models.base import Base

task_tags = Table(
    "task_tags",
    Base.metadata,
    Column("task_id", String(36), ForeignKey("tasks.id"), primary_key=True),
    Column("tag_id", String(36), ForeignKey("tags.id"), primary_key=True),
)


class Tag(Base):
    """[FR-01] A label attachable to tasks.

    Citations: SPEC.md L311.
    """

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

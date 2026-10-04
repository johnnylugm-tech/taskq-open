"""Pydantic v2 request/response models.

[FR-01] ``TaskCreate`` request body and task response shapes.

Citations: SPEC.md L83-85 (FR-01 endpoints); SPEC.md L309 (task fields).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

TaskStatus = Literal["pending", "running", "done", "failed", "timeout", "interrupted"]


class TaskCreate(BaseModel):
    """[FR-01] Body of ``POST /v1/tasks``.

    Citations: SPEC.md L83.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    command: str


class TaskOut(BaseModel):
    """[FR-01] Full task representation.

    Citations: SPEC.md L84, L309.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    command: str
    name: str
    status: str
    created_at: datetime


class TaskPage(BaseModel):
    """[FR-01] One page of the task list plus the opaque next cursor.

    Citations: SPEC.md L85, L90.
    """

    items: list[TaskOut]
    next_cursor: str | None

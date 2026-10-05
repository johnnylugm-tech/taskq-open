"""Pydantic v2 request/response models.

[FR-01] ``TaskCreate`` request body and task response shapes.
[FR-02] Run submission and run history shapes.

Citations: SPEC.md L83-85 (FR-01 endpoints); SPEC.md L95-99 (FR-02 endpoints); SPEC.md L309 (task fields).
"""
# pragma: no error-handling — pydantic request/response models; validation failures are rendered by api.error_handlers

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    status: TaskStatus
    created_at: datetime


class TaskPage(BaseModel):
    """[FR-01] One page of the task list plus the opaque next cursor.

    Citations: SPEC.md L85, L90.
    """

    items: list[TaskOut]
    next_cursor: str | None


class RunAccepted(BaseModel):
    """[FR-02] Body of the 202 returned by ``POST /v1/tasks/{id}/run``.

    Citations: SPEC.md L95.
    """

    run_id: str


class RunOut(BaseModel):
    """[FR-02] One ``task_results`` row; ``run_id`` is the row id.

    Citations: SPEC.md L98-99, L312.
    """

    model_config = ConfigDict(from_attributes=True)

    run_id: str = Field(validation_alias="id")
    exit_code: int | None
    stdout_tail: str | None
    stderr_tail: str | None
    duration_ms: int | None
    finished_at: datetime | None


class RunPage(BaseModel):
    """[FR-02] Run history of one task, newest first.

    Citations: SPEC.md L99.
    """

    items: list[RunOut]

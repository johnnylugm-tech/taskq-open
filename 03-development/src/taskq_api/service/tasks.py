"""Task use cases and validation rules.

[FR-01] Validates task input (non-empty name/command, length bounds, command
injection blacklist) and orchestrates create / get / list / delete; name
uniqueness is enforced by the repository on insert.

Citations: SPEC.md L79-91 (FR-01); SPEC.md L88 (validation rules);
02-architecture/SAD.md L97.
"""
# pragma: no error-handling — pure domain logic; raises TaskqError, rendered by api.error_handlers

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from taskq_api.errors import NotFound, ValidationFailed
from taskq_api.models.task import Task
from taskq_api.service.uow import UnitOfWork

INITIAL_STATUS = "pending"
MAX_COMMAND_LENGTH = 1000
# Matches the ``tasks.name`` column width so an over-long name is a 422, not a DB error.
MAX_NAME_LENGTH = 255
# `;` is mandated; the remaining members are pending open decision NFR-99.2.
INJECTION_CHARS = frozenset(";&|`$<>\n\r")


def validate_command(command: str) -> None:
    """[FR-01] Reject empty, over-long, or shell-metacharacter commands.

    Citations: SPEC.md L88.
    """
    if not command.strip():
        raise ValidationFailed("command must not be empty")
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValidationFailed(f"command must be at most {MAX_COMMAND_LENGTH} characters")
    if INJECTION_CHARS.intersection(command):
        raise ValidationFailed("command contains forbidden characters")


def validate_name(name: str) -> None:
    """[FR-01] Reject empty or over-long task names.

    Citations: SPEC.md L88, L309.
    """
    if not name.strip():
        raise ValidationFailed("name must not be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationFailed(f"name must be at most {MAX_NAME_LENGTH} characters")


def create_task(uow: UnitOfWork, name: str, command: str) -> Task:
    """[FR-01] Validate and persist a new ``pending`` task.

    Citations: SPEC.md L83, L88.
    """
    validate_name(name)
    validate_command(command)
    task = Task(
        id=str(uuid.uuid4()),
        name=name,
        command=command,
        status=INITIAL_STATUS,
        created_at=datetime.now(timezone.utc),
    )
    return uow.tasks.add(task)


def get_task(uow: UnitOfWork, task_id: str) -> Task:
    """[FR-01] Return one task or raise :class:`NotFound`.

    Citations: SPEC.md L84, L89.
    """
    task = uow.tasks.get(task_id)
    if task is None:
        raise NotFound("task not found")
    return task


def list_tasks(
    uow: UnitOfWork, status: str | None, limit: int, cursor: str | None
) -> tuple[list[Task], str | None]:
    """[FR-01] One cursor page of tasks, optionally filtered by status.

    Citations: SPEC.md L85, L90-91.
    """
    return uow.tasks.list_page(status, limit, cursor)


def delete_task(uow: UnitOfWork, task_id: str) -> None:
    """[FR-01] Delete a task with its results and tag links in one transaction.

    Citations: SPEC.md L86, L89.
    """
    task = get_task(uow, task_id)
    uow.tags.detach_task(task.id)
    uow.tasks.delete(task)

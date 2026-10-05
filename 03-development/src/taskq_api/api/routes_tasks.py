"""``/v1/tasks`` CRUD routes.

[FR-01] POST / GET one / GET list / DELETE; each request runs in one
:class:`UnitOfWork` transaction.
[FR-04] ``GET`` needs ``read`` and ``DELETE`` needs ``admin``.
[FR-10] ``POST`` requires the ``write`` scope (403 ``/errors/forbidden``).

Citations: SPEC.md L79-91 (FR-01); SPEC.md L168, L339 (FR-10 403); SPEC.md L125 (per-request transaction); SPEC.md L111-113 (FR-04).
"""
# pragma: no error-handling — thin routing; TaskqError is rendered by api.error_handlers, anything else by CorrelationMiddleware

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from taskq_api.api.deps import get_uow_factory, guard
from taskq_api.api.schemas import TaskCreate, TaskOut, TaskPage, TaskStatus
from taskq_api.service import tasks as task_service
from taskq_api.service.uow import UnitOfWork

router = APIRouter(
    prefix="/v1/tasks", tags=["tasks"]
)

UowFactory = Annotated[Callable[[], UnitOfWork], Depends(get_uow_factory)]


@router.post(
    "", status_code=201, response_model=TaskOut, dependencies=guard("write")
)
def create_task(body: TaskCreate, uow_factory: UowFactory) -> TaskOut:
    """[FR-01] Create a task -> 201 with the stored task.

    [FR-10] A key below ``write`` scope gets 403.

    Citations: SPEC.md L83, L88, L339.
    """
    with uow_factory() as uow:
        task = task_service.create_task(uow, body.name, body.command)
        return TaskOut.model_validate(task)


@router.get("/{task_id}", response_model=TaskOut, dependencies=guard("read"))
def get_task(task_id: str, uow_factory: UowFactory) -> TaskOut:
    """[FR-01] Return one task with all fields, or 404.

    Citations: SPEC.md L84, L89.
    """
    with uow_factory() as uow:
        return TaskOut.model_validate(task_service.get_task(uow, task_id))


@router.get("", response_model=TaskPage, dependencies=guard("read"))
def list_tasks(
    uow_factory: UowFactory,
    status: TaskStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> TaskPage:
    """[FR-01] Cursor-paginated task list (default 50, max 200).

    Citations: SPEC.md L85, L90-91.
    """
    with uow_factory() as uow:
        tasks, next_cursor = task_service.list_tasks(uow, status, limit, cursor)
        items = [TaskOut.model_validate(task) for task in tasks]
    return TaskPage(items=items, next_cursor=next_cursor)


@router.delete("/{task_id}", status_code=204, dependencies=guard("admin"))
def delete_task(task_id: str, uow_factory: UowFactory) -> Response:
    """[FR-01] Delete a task and its results in one transaction -> 204.

    Citations: SPEC.md L86, L89.
    """
    with uow_factory() as uow:
        task_service.delete_task(uow, task_id)
    return Response(status_code=204)

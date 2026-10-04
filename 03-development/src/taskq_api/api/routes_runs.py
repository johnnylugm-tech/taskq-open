"""``/v1/tasks/{id}/run`` and ``/v1/tasks/{id}/runs`` routes.

[FR-02] Submits a background run (202 + ``run_id``) and returns a task's run
history newest first.

[FR-04] ``run`` needs ``write``; ``runs`` needs ``read``.

Citations: SPEC.md L93-99 (FR-02); SPEC.md L111-113 (FR-04).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from taskq_api.api.deps import get_executor, get_uow_factory, guard
from taskq_api.api.schemas import RunAccepted, RunOut, RunPage
from taskq_api.service import runs as run_service
from taskq_api.service.executor import Executor
from taskq_api.service.uow import UnitOfWork

router = APIRouter(
    prefix="/v1/tasks", tags=["runs"]
)

UowFactory = Annotated[Callable[[], UnitOfWork], Depends(get_uow_factory)]
BackgroundExecutor = Annotated[Executor, Depends(get_executor)]


@router.post(
    "/{task_id}/run",
    status_code=202,
    response_model=RunAccepted,
    dependencies=guard("write"),
)
async def run_task(task_id: str, uow_factory: UowFactory, executor: BackgroundExecutor) -> RunAccepted:
    """[FR-02] Queue a run of the task on the app's event loop -> 202, or 404.

    Citations: SPEC.md L95.
    """
    with uow_factory() as uow:
        run_id, command = run_service.submit(uow, task_id)
    run_service.start(executor, uow_factory, task_id, run_id, command)
    return RunAccepted(run_id=run_id)


@router.get("/{task_id}/runs", response_model=RunPage, dependencies=guard("read"))
def list_runs(task_id: str, uow_factory: UowFactory) -> RunPage:
    """[FR-02] The task's run history, newest first, or 404.

    Citations: SPEC.md L99.
    """
    with uow_factory() as uow:
        items = [RunOut.model_validate(result) for result in run_service.list_runs(uow, task_id)]
    return RunPage(items=items)

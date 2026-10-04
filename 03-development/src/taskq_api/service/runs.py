"""Task run use cases.

[FR-02] Submits a run (task reset to ``pending`` plus an unfinished
``task_results`` row), executes it in the background and records the
outcome; lists a task's run history.

Citations: SPEC.md L93-99 (FR-02); 02-architecture/SAD.md L185-198 (run flow).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from taskq_api.models.result import TaskResult
from taskq_api.service import runner
from taskq_api.service.tasks import get_task
from taskq_api.service.uow import UnitOfWork

UowFactory = Callable[[], UnitOfWork]


def submit(uow: UnitOfWork, task_id: str) -> tuple[str, str]:
    """[FR-02] Queue a run of ``task_id``; return ``(run_id, command)`` or raise NotFound.

    Citations: SPEC.md L95, L97-98.
    """
    task = get_task(uow, task_id)
    task.status = runner.PENDING
    result = uow.results.add(TaskResult(id=str(uuid.uuid4()), task_id=task.id))
    return result.id, task.command


def set_status(uow_factory: UowFactory, task_id: str, status: str) -> None:
    """[FR-02] Persist ``status`` on the task in its own transaction.

    Citations: SPEC.md L97.
    """
    with uow_factory() as uow:
        get_task(uow, task_id).status = status


async def execute(uow_factory: UowFactory, task_id: str, run_id: str, command: str) -> None:
    """[FR-02] Run ``command`` and store the outcome and final task status together.

    Citations: SPEC.md L96-98.
    """
    set_status(uow_factory, task_id, runner.RUNNING)
    outcome = await runner.run_command(command, machine=runner.TaskStateMachine())
    with uow_factory() as uow:
        record_outcome(uow.results.get(run_id), outcome)
        get_task(uow, task_id).status = outcome.status


def record_outcome(result: TaskResult, outcome: runner.RunOutcome) -> None:
    """[FR-02] Copy the outcome's ``task_results`` column values onto ``result``.

    Citations: SPEC.md L98.
    """
    result.exit_code = outcome.exit_code
    result.stdout_tail = outcome.stdout_tail
    result.stderr_tail = outcome.stderr_tail
    result.duration_ms = outcome.duration_ms
    result.finished_at = outcome.finished_at


def start(background: set[asyncio.Task[None]], uow_factory: UowFactory, task_id: str, run_id: str, command: str) -> None:
    """[FR-02] Schedule :func:`execute` on the running loop, holding a reference until done.

    Citations: SPEC.md L95.
    """
    job = asyncio.create_task(execute(uow_factory, task_id, run_id, command))
    background.add(job)
    job.add_done_callback(background.discard)


def list_runs(uow: UnitOfWork, task_id: str) -> list[TaskResult]:
    """[FR-02] Run history of ``task_id``, newest first, or raise NotFound.

    Citations: SPEC.md L99.
    """
    return uow.results.list_for_task(get_task(uow, task_id).id)

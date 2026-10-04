"""Bounded background executor.

[FR-08] Owns an ``asyncio.TaskGroup``; at most ``TASKQ_MAX_CONCURRENT`` jobs
run at once and the rest wait in a queue as uncalled job factories, so no
coroutine is created for them. ``drain()`` waits up to ``TASKQ_DRAIN_TIMEOUT``
and cancels whatever is still unfinished. ``CancelledError`` is never swallowed.

Citations: SPEC.md L145-150 (FR-08); SPEC.md L381 (graceful drain);
02-architecture/SAD.md L66, L190-198.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from types import TracebackType

from taskq_api.config import load_settings

Job = Callable[[], Awaitable[object]]


class Executor:
    """[FR-08] Async context manager running queued jobs under a concurrency cap.

    Citations: SPEC.md L147-148, L150.
    """

    def __init__(self) -> None:
        settings = load_settings()
        self._max_concurrent = settings.max_concurrent
        self._drain_timeout = settings.drain_timeout
        self._group = asyncio.TaskGroup()
        self._queue: deque[Job] = deque()
        self._in_flight: set[asyncio.Task[None]] = set()
        self._idle = asyncio.Event()
        self._idle.set()

    async def __aenter__(self) -> Executor:
        await self._group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return await self._group.__aexit__(exc_type, exc, tb)

    def enqueue(self, job: Job) -> None:
        """[FR-08] Queue ``job``; it is called only once a concurrency slot is free.

        Citations: SPEC.md L148.
        """
        self._queue.append(job)
        self._idle.clear()
        self._dispatch()

    def _dispatch(self) -> None:
        while self._queue and len(self._in_flight) < self._max_concurrent:
            task = self._group.create_task(self._run(self._queue.popleft()))
            self._in_flight.add(task)

    async def _run(self, job: Job) -> None:
        try:
            await job()
        finally:
            self._in_flight.discard(asyncio.current_task())  # type: ignore[arg-type]
            self._dispatch()
            if not self._in_flight:
                self._idle.set()

    async def drain(self) -> None:
        """[FR-08] Wait up to ``TASKQ_DRAIN_TIMEOUT`` for all jobs, then cancel the rest.

        Queued jobs that never started are dropped; in-flight jobs are
        cancelled and awaited so their cleanup (kill + reap) completes.

        Citations: SPEC.md L147, L381.
        """
        try:
            async with asyncio.timeout(self._drain_timeout):
                await self._idle.wait()
        except TimeoutError:
            self._queue.clear()
            for task in self._in_flight:
                task.cancel()
            await self._idle.wait()

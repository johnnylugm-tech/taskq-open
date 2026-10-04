"""FastAPI application factory.

[FR-01] Wires settings, the database engine and the ``/v1/tasks`` routes.
[FR-02] Adds the run routes; in-flight runs finish before the engine closes.
[FR-03] Adds the unauthenticated health routes.
[FR-05] Holds the rate-limit settings and clock; health routes stay unlimited.
[FR-08] Runs go through the bounded executor, drained on shutdown.

Citations: SPEC.md L145-150 (FR-08); SPEC.md L79-91 (FR-01); SPEC.md L93-99 (FR-02); SPEC.md L107 (FR-03);
SPEC.md L115-120 (FR-05);
SPEC.md L287-302 (5.1 settings);
02-architecture/SAD.md L46.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from taskq_api.api import error_handlers, routes_health, routes_runs, routes_tasks
from taskq_api.config import load_settings
from taskq_api.repository.session import build_engine, uow_factory
from taskq_api.service.executor import Executor
from taskq_api.service.ratelimit import SystemClock


def create_app() -> FastAPI:
    """[FR-01] Build the app from ``TASKQ_*`` settings; the engine lives for the app's lifespan.

    [FR-02] Background runs are awaited on shutdown, before ``engine.dispose()``.
    [FR-05] ``app.state.clock`` drives bucket refill (replaceable in tests).
    [FR-08] ``app.state.executor`` runs jobs under ``TASKQ_MAX_CONCURRENT``; on
    shutdown it drains for ``TASKQ_DRAIN_TIMEOUT`` and cancelled runs end ``interrupted``.

    Citations: SPEC.md L79-91, L93-99, L117, L147-148, L287-302.
    """
    settings = load_settings()
    engine = build_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with Executor() as executor:
            app.state.executor = executor
            yield
            await executor.drain()
        engine.dispose()

    app = FastAPI(title="taskq-api", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = SystemClock()
    app.state.uow_factory = uow_factory(engine)
    error_handlers.register(app)
    app.include_router(routes_tasks.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_health.router)
    return app

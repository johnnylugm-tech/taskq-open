"""FastAPI application factory.

[FR-01] Wires settings, the database engine and the ``/v1/tasks`` routes.
[FR-02] Adds the run routes; in-flight runs finish before the engine closes.
[FR-03] Adds the unauthenticated health routes.

Citations: SPEC.md L79-91 (FR-01); SPEC.md L93-99 (FR-02); SPEC.md L107 (FR-03);
SPEC.md L287-302 (5.1 settings);
02-architecture/SAD.md L46.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from taskq_api.api import error_handlers, routes_health, routes_runs, routes_tasks
from taskq_api.config import load_settings
from taskq_api.repository.session import build_engine, uow_factory


def create_app() -> FastAPI:
    """[FR-01] Build the app from ``TASKQ_*`` settings; the engine lives for the app's lifespan.

    [FR-02] Background runs are awaited on shutdown, before ``engine.dispose()``.

    Citations: SPEC.md L79-91, L93-99, L287-302.
    """
    engine = build_engine(load_settings())
    background_runs: set[asyncio.Task[None]] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await asyncio.gather(*background_runs)
        engine.dispose()

    app = FastAPI(title="taskq-api", lifespan=lifespan)
    app.state.uow_factory = uow_factory(engine)
    app.state.background_runs = background_runs
    error_handlers.register(app)
    app.include_router(routes_tasks.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_health.router)
    return app

"""FastAPI application factory.

[FR-01] Wires settings, the database engine and the ``/v1/tasks`` routes.

Citations: SPEC.md L79-91 (FR-01); SPEC.md L287-302 (5.1 settings);
02-architecture/SAD.md L46.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from taskq_api.api import error_handlers, routes_tasks
from taskq_api.config import load_settings
from taskq_api.repository.session import build_engine, uow_factory


def create_app() -> FastAPI:
    """[FR-01] Build the app from ``TASKQ_*`` settings; the engine lives for the app's lifespan.

    Citations: SPEC.md L79-91, L287-302.
    """
    engine = build_engine(load_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="taskq-api", lifespan=lifespan)
    app.state.uow_factory = uow_factory(engine)
    error_handlers.register(app)
    app.include_router(routes_tasks.router)
    return app

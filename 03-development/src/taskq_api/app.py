"""FastAPI application factory.

[FR-01] Wires settings, the database engine and the ``/v1/tasks`` routes.
[FR-02] Adds the run routes; in-flight runs finish before the engine closes.
[FR-03] Adds the unauthenticated health routes.
[FR-05] Holds the rate-limit settings and clock; health routes stay unlimited.
[FR-08] Runs go through the bounded executor, drained on shutdown.
[FR-09] Adds ``/v1/metrics`` and the process-wide rate-limit rejection counter.
[FR-04] Attaches routes flat so each /v1 route exposes its scope dependency.
[FR-10] Adds the correlation-id / 500 middleware and the CORS allow-list.

Citations: SPEC.md L162-168 (FR-10); SPEC.md L193 (NFR-02 CORS); SPEC.md L145-150 (FR-08); SPEC.md L152-160 (FR-09); SPEC.md L111-113 (FR-04); SPEC.md L79-91 (FR-01); SPEC.md L93-99 (FR-02); SPEC.md L107 (FR-03);
SPEC.md L115-120 (FR-05);
SPEC.md L287-302 (5.1 settings);
02-architecture/SAD.md L46.
"""
# pragma: no error-handling — composition root; startup failures abort boot and lifespan orders shutdown

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from taskq_api.api import error_handlers, middleware, routes_health, routes_metrics, routes_runs, routes_tasks
from taskq_api.config import Settings, load_settings
from taskq_api.repository.session import build_engine, uow_factory
from taskq_api.service.executor import Executor
from taskq_api.service.health import RejectionCounter
from taskq_api.service.ratelimit import SystemClock


_LOG_HANDLER_NAME = "taskq_api"


class JsonFormatter(logging.Formatter):
    """[FR-10] One JSON object per record; carries ``correlation_id`` when present.

    Citations: SPEC.md L167, L300.
    """

    def format(self, record: logging.LogRecord) -> str:
        """[FR-10] Render ``record`` as a single JSON line.

        Citations: SPEC.md L167.
        """
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(settings: Settings) -> None:
    """[FR-10] Apply ``TASKQ_LOG_LEVEL`` / ``TASKQ_LOG_FORMAT`` to the root logger.

    Citations: SPEC.md L299-300.
    """
    handler = logging.StreamHandler()
    handler.set_name(_LOG_HANDLER_NAME)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if h.get_name() != _LOG_HANDLER_NAME] + [handler]
    root.setLevel(settings.log_level)


def create_app() -> FastAPI:
    """[FR-01] Build the app from ``TASKQ_*`` settings; the engine lives for the app's lifespan.

    [FR-02] Background runs are awaited on shutdown, before ``engine.dispose()``.
    [FR-05] ``app.state.clock`` drives bucket refill (replaceable in tests).
    [FR-08] ``app.state.executor`` runs jobs under ``TASKQ_MAX_CONCURRENT``; on
    shutdown it drains for ``TASKQ_DRAIN_TIMEOUT`` and cancelled runs end ``interrupted``.
    [FR-09] ``app.state.rate_limit_rejections`` counts 429s for ``/v1/metrics``.
    [FR-10] Correlation ids and the 500 fallback wrap every request; CORS allows
    only ``TASKQ_CORS_ORIGINS``.

    Citations: SPEC.md L79-91, L93-99, L117, L147-148, L158, L164-168, L193, L287-302.
    """
    settings = load_settings()
    configure_logging(settings)
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
    app.state.rate_limit_rejections = RejectionCounter()
    error_handlers.register(app)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins))
    app.add_middleware(middleware.CorrelationMiddleware)
    # [FR-04] Routes are attached flat so every /v1 APIRoute (and its dependency tree) is inspectable.
    for router in (routes_tasks.router, routes_runs.router, routes_health.router, routes_metrics.router):
        app.router.routes.extend(router.routes)
    return app

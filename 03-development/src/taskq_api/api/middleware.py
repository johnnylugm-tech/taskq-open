"""Correlation-id and last-resort error middleware (pure ASGI).

[FR-10] Every request gets a correlation id, stored on ``request.state`` and
echoed in the ``X-Correlation-Id`` response header; any unhandled
``Exception`` becomes a generic 500 ``/errors/internal`` problem, logged
server-side with that id. ``asyncio.CancelledError`` is a ``BaseException``
and propagates untouched.

Citations: SPEC.md L162-168 (FR-10); SPEC.md L344-347 (500 / CancelledError);
SPEC.md L201 (NFR-03 CancelledError).
"""

from __future__ import annotations

import logging
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from taskq_api.api import error_handlers
from taskq_api.errors import InternalError

CORRELATION_HEADER = "X-Correlation-Id"
INTERNAL_DETAIL = InternalError.GENERIC_DETAIL

logger = logging.getLogger(__name__)


class CorrelationMiddleware:
    """[FR-10] Assign a correlation id per request and render unhandled errors as 500.

    Citations: SPEC.md L166-168, L344, L347.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """[FR-10] ASGI entry point; non-HTTP scopes pass through unchanged.

        Citations: SPEC.md L167, L344, L347.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = str(uuid.uuid4())
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        started = False

        async def send_with_header(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        except Exception:
            logger.exception(
                "unhandled error", extra={"correlation_id": correlation_id}
            )
            if started:
                raise
            response = error_handlers.problem_response(Request(scope), InternalError())
            await response(scope, receive, send_with_header)

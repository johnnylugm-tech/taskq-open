"""RFC 7807 ``application/problem+json`` rendering.

[FR-01] Maps domain errors and request-validation errors to problem+json.
[FR-10] Adds ``correlation_id`` to every body and logs each problem with it.

Citations: SPEC.md L88-91 (FR-01 422/404); SPEC.md L162-169 (FR-10);
SPEC.md L331-346 (7 error table).
"""

from __future__ import annotations

import logging
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from taskq_api.errors import TaskqError, ValidationFailed

PROBLEM_JSON = "application/problem+json"

logger = logging.getLogger(__name__)


def problem_response(request: Request, error: TaskqError) -> JSONResponse:
    """[FR-01] Render ``error`` as an RFC 7807 body.

    [FR-05] Carries the error's headers (``Retry-After``).
    [FR-10] Includes the request's ``correlation_id`` (set by
    ``api.middleware``) and logs the problem tagged with it.

    [FR-04] A 403 omits ``instance`` so the body cannot reveal whether the
    requested resource exists.

    Citations: SPEC.md L112, L118, L165-167.
    """
    correlation_id = request.state.correlation_id
    logger.info(
        "problem %s %s", error.status, error.type_uri, extra={"correlation_id": correlation_id}
    )
    body = {
        "type": error.type_uri,
        "title": error.title,
        "status": error.status,
        "detail": error.detail,
        "instance": None if error.status == 403 else request.url.path,
        "correlation_id": correlation_id,
    }
    return JSONResponse(
        body, status_code=error.status, headers=error.headers, media_type=PROBLEM_JSON
    )


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    """[FR-01] Handler for :class:`TaskqError` subclasses.

    ``exc`` is typed ``Exception`` to match Starlette's ``ExceptionHandler``;
    it is only ever registered for :class:`TaskqError`.

    Citations: SPEC.md L331-346.
    """
    return problem_response(request, cast(TaskqError, exc))


async def handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    """[FR-01] Handler turning FastAPI validation failures into 422 problems.

    [FR-10] Pydantic's error list is deliberately not echoed: ``detail`` stays
    generic so model/field internals do not leak.

    Citations: SPEC.md L88, L91, L166, L338.
    """
    return problem_response(request, ValidationFailed("request is invalid"))


def register(app: FastAPI) -> None:
    """[FR-01] Install the problem+json handlers on ``app``.

    Citations: SPEC.md L164.
    """
    app.add_exception_handler(TaskqError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation)

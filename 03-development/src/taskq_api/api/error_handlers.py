"""RFC 7807 ``application/problem+json`` rendering.

[FR-01] Maps domain errors and request-validation errors to problem+json.

Citations: SPEC.md L88-91 (FR-01 422/404); SPEC.md L162-169 (FR-10);
SPEC.md L331-346 (7 error table).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from taskq_api.errors import TaskqError, ValidationFailed

PROBLEM_JSON = "application/problem+json"


def problem_response(request: Request, error: TaskqError) -> JSONResponse:
    """[FR-01] Render ``error`` as an RFC 7807 body.

    Citations: SPEC.md L165-166.
    """
    body = {
        "type": error.type_uri,
        "title": error.title,
        "status": error.status,
        "detail": error.detail,
        "instance": request.url.path,
    }
    return JSONResponse(body, status_code=error.status, media_type=PROBLEM_JSON)


async def handle_domain_error(request: Request, exc: TaskqError) -> JSONResponse:
    """[FR-01] Handler for :class:`TaskqError` subclasses.

    Citations: SPEC.md L331-346.
    """
    return problem_response(request, exc)


async def handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    """[FR-01] Handler turning FastAPI validation failures into 422 problems.

    Citations: SPEC.md L88, L91, L338.
    """
    return problem_response(request, ValidationFailed("request is invalid"))


def register(app: FastAPI) -> None:
    """[FR-01] Install the problem+json handlers on ``app``.

    Citations: SPEC.md L164.
    """
    app.add_exception_handler(TaskqError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation)

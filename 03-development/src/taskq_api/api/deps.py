"""FastAPI dependencies.

[FR-01] Provides the per-request :class:`UnitOfWork` factory.
[FR-02] Provides the app-wide set of background run jobs.
[FR-03] Authenticates ``/v1`` requests by their ``X-API-Key`` header.
[FR-05] Rate-limits authenticated ``/v1`` requests per key.

Citations: SPEC.md L125 (one Session per request); SPEC.md L103 (X-API-Key);
SPEC.md L115-120 (FR-05);
02-architecture/SAD.md L52, L176.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Request

from taskq_api.errors import RateLimited
from taskq_api.models.api_key import ApiKey
from taskq_api.service import auth, ratelimit
from taskq_api.service.uow import UnitOfWork


def get_uow_factory(request: Request) -> Callable[[], UnitOfWork]:
    """[FR-01] Return the app-wide factory of request-scoped units of work.

    Citations: SPEC.md L125.
    """
    return request.app.state.uow_factory


def get_background_runs(request: Request) -> set[asyncio.Task[None]]:
    """[FR-02] Return the app-wide set of in-flight background run jobs.

    Citations: SPEC.md L95.
    """
    return request.app.state.background_runs


def authenticate(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> ApiKey:
    """[FR-03] Reject the request with 401 unless ``X-API-Key`` is an active key.

    [FR-05] Returns the key so the rate limiter can find its bucket.

    Citations: SPEC.md L103-104, L106, L117.
    """
    with get_uow_factory(request)() as uow:
        return auth.verify(uow, x_api_key)


def rate_limit(request: Request, api_key: Annotated[ApiKey, Depends(authenticate)]) -> None:
    """[FR-05] Take one token from the caller's bucket, else raise 429.

    Citations: SPEC.md L117-119.
    """
    settings = request.app.state.settings
    with get_uow_factory(request)() as uow:
        decision = ratelimit.consume(
            uow,
            api_key.id,
            capacity=settings.rate_burst,
            rate_per_sec=settings.rate_per_sec,
            now=request.app.state.clock.now(),
        )
    if not decision.allowed:
        raise RateLimited("rate limit exceeded", decision.retry_after_s)

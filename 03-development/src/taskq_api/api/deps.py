"""FastAPI dependencies.

[FR-01] Provides the per-request :class:`UnitOfWork` factory.
[FR-02] Provides the app-wide background run executor.
[FR-03] Authenticates ``/v1`` requests by their ``X-API-Key`` header.
[FR-05] Rate-limits authenticated ``/v1`` requests per key.
[FR-09] Enforces a minimum key scope and counts rate-limit rejections.

Citations: SPEC.md L125 (one Session per request); SPEC.md L103 (X-API-Key);
SPEC.md L115-120 (FR-05); SPEC.md L111-113 (FR-04); SPEC.md L158 (FR-09);
02-architecture/SAD.md L52, L176.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Request

from taskq_api.errors import Forbidden, RateLimited
from taskq_api.models.api_key import ApiKey
from taskq_api.service import auth, ratelimit
from taskq_api.service.executor import Executor
from taskq_api.service.uow import UnitOfWork


def get_uow_factory(request: Request) -> Callable[[], UnitOfWork]:
    """[FR-01] Return the app-wide factory of request-scoped units of work.

    Citations: SPEC.md L125.
    """
    return request.app.state.uow_factory


def get_executor(request: Request) -> Executor:
    """[FR-02] Return the app-wide executor that runs background jobs.

    [FR-08] The executor lives for the app's lifespan.

    Citations: SPEC.md L95, L147.
    """
    return request.app.state.executor


def authenticate(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> ApiKey:
    """[FR-03] Reject the request with 401 unless ``X-API-Key`` is an active key.

    [FR-05] Returns the key so the rate limiter can find its bucket.

    Citations: SPEC.md L103-104, L106, L117.
    """
    with get_uow_factory(request)() as uow:
        return auth.verify(uow, x_api_key)


def rate_limit(request: Request, api_key: Annotated[ApiKey, Depends(authenticate)]) -> None:
    """[FR-05] Take one token from the caller's bucket, else raise 429.

    [FR-09] Each 429 is counted for ``/v1/metrics``.

    Citations: SPEC.md L117-119, L158.
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
        request.app.state.rate_limit_rejections.increment()
        raise RateLimited("rate limit exceeded", decision.retry_after_s)


def require_scope(minimum: str) -> Callable[[ApiKey], None]:
    """[FR-09] Dependency raising 403 unless the caller's scope includes ``minimum``.

    Scopes are hierarchical: ``read`` < ``write`` < ``admin``.

    Citations: SPEC.md L111-112, L158, L339.
    """
    required_rank = auth.SCOPES.index(minimum)

    def check(api_key: Annotated[ApiKey, Depends(authenticate)]) -> None:
        if auth.SCOPES.index(api_key.scope) < required_rank:
            raise Forbidden("insufficient scope")

    return check

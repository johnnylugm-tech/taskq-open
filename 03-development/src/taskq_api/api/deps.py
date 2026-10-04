"""FastAPI dependencies.

[FR-01] Provides the per-request :class:`UnitOfWork` factory.
[FR-02] Provides the app-wide set of background run jobs.
[FR-03] Authenticates ``/v1`` requests by their ``X-API-Key`` header.

Citations: SPEC.md L125 (one Session per request); SPEC.md L103 (X-API-Key);
02-architecture/SAD.md L52, L176.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import Header, Request

from taskq_api.service import auth
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


def authenticate(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> None:
    """[FR-03] Reject the request with 401 unless ``X-API-Key`` is an active key.

    Citations: SPEC.md L103-104, L106.
    """
    with get_uow_factory(request)() as uow:
        auth.verify(uow, x_api_key)

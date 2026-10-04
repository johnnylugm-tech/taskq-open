"""FastAPI dependencies.

[FR-01] Provides the per-request :class:`UnitOfWork` factory.

Citations: SPEC.md L125 (one Session per request); 02-architecture/SAD.md L52.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from taskq_api.service.uow import UnitOfWork


def get_uow_factory(request: Request) -> Callable[[], UnitOfWork]:
    """[FR-01] Return the app-wide factory of request-scoped units of work.

    Citations: SPEC.md L125.
    """
    return request.app.state.uow_factory

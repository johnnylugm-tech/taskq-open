"""Unauthenticated ``/healthz`` and ``/readyz`` routes.

[FR-03] Health endpoints sit outside ``/v1`` and require no API key.
[FR-09] ``/readyz`` answers 503 ``/errors/not-ready`` naming the failing check.

Citations: SPEC.md L107 (FR-03); SPEC.md L157-158 (FR-09 health table).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from taskq_api.errors import NotReady
from taskq_api.service import health

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """[FR-03] Liveness probe -> 200 ``{"status": "ok"}``, no key required.

    Citations: SPEC.md L107, L157.
    """
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request) -> dict[str, str]:
    """[FR-03] Readiness probe reachable without a key.

    [FR-09] 200 only when the DB is reachable and at migration head; else 503.

    Citations: SPEC.md L107, L157, L160, L343.
    """
    verdict = health.readiness(request.app.state.settings.db_url)
    if not verdict.ready:
        raise NotReady(verdict.detail)
    return {"status": "ready"}

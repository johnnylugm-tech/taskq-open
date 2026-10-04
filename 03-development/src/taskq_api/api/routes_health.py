"""Unauthenticated ``/healthz`` and ``/readyz`` routes.

[FR-03] Health endpoints sit outside ``/v1`` and require no API key.

Citations: SPEC.md L107 (FR-03); SPEC.md L157-158 (FR-09 health table).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """[FR-03] Liveness probe -> 200 ``{"status": "ok"}``, no key required.

    Citations: SPEC.md L107, L157.
    """
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict[str, str]:
    """[FR-03] Readiness probe reachable without a key.

    Citations: SPEC.md L107, L158.
    """
    return {"status": "ready"}

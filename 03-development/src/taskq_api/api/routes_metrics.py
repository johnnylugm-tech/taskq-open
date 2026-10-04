"""Admin-only ``/v1/metrics`` route.

[FR-09] Task counts by status, run latency percentiles and rate-limit
rejection count, for keys of scope ``admin``.

Citations: SPEC.md L158 (FR-09); SPEC.md L111-113 (FR-04); 02-architecture/SAD.md L57.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from taskq_api.api.deps import get_uow_factory, guard
from taskq_api.service import health

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


@router.get("", dependencies=guard("admin"))
def get_metrics(request: Request) -> dict[str, Any]:
    """[FR-09] Aggregated service metrics; never includes the DB URL.

    Citations: SPEC.md L158.
    """
    with get_uow_factory(request)() as uow:
        return health.metrics(uow, request.app.state.rate_limit_rejections)

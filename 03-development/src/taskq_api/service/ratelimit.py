"""Per-key token-bucket rate limiting.

[FR-05] Bucket capacity ``TASKQ_RATE_BURST``, refill ``TASKQ_RATE_PER_SEC``;
an empty bucket yields a denial with an integer ``Retry-After``.

Citations: SPEC.md L115-120 (FR-05); SPEC.md L296-297 (settings);
02-architecture/SAD.md L68, L178, L665 (clock Protocol).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from taskq_api.service.uow import UnitOfWork


class Clock(Protocol):
    """[FR-05] Time source for bucket refill; substitutable in tests.

    Citations: SPEC.md L117; 02-architecture/SAD.md L665.
    """

    def now(self) -> datetime:
        """[FR-05] Current timezone-aware time. Citations: SPEC.md L117."""
        ...


class SystemClock:
    """[FR-05] Wall-clock :class:`Clock` (UTC).

    Citations: SPEC.md L117.
    """

    def now(self) -> datetime:
        """[FR-05] Current UTC time. Citations: SPEC.md L117."""
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RateDecision:
    """[FR-05] Outcome of one consume: admitted, or wait ``retry_after_s`` seconds.

    Citations: SPEC.md L118.
    """

    allowed: bool
    retry_after_s: int


def consume(
    uow: UnitOfWork, key_id: str, *, capacity: int, rate_per_sec: float, now: datetime
) -> RateDecision:
    """[FR-05] Refill ``key_id``'s bucket up to ``now`` and take one token if available.

    The read and write go through ``uow.rate_buckets`` in the caller's single
    transaction, the read holding a row lock.

    Citations: SPEC.md L117-119.
    """
    bucket = uow.rate_buckets.get_for_update(key_id)
    if bucket is None:
        tokens = float(capacity)
    else:
        elapsed = max((now - bucket.updated_at).total_seconds(), 0.0)
        tokens = min(float(capacity), bucket.tokens + elapsed * rate_per_sec)
    allowed = tokens >= 1.0
    if allowed:
        tokens -= 1.0
    uow.rate_buckets.save(bucket, key_id, tokens, now)
    if allowed:
        return RateDecision(allowed=True, retry_after_s=0)
    return RateDecision(allowed=False, retry_after_s=max(1, math.ceil((1.0 - tokens) / rate_per_sec)))

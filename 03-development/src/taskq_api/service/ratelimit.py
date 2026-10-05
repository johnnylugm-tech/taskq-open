"""Per-key token-bucket rate limiting.

[FR-05] Bucket capacity ``TASKQ_RATE_BURST``, refill ``TASKQ_RATE_PER_SEC``;
an empty bucket yields a denial with an integer ``Retry-After``.

Citations: SPEC.md L115-120 (FR-05); SPEC.md L296-297 (settings);
02-architecture/SAD.md L68, L178, L665 (clock Protocol).
"""
# pragma: no error-handling — pure domain logic; raises TaskqError, rendered by api.error_handlers

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from taskq_api.models.rate_bucket import RateBucket
from taskq_api.service.uow import UnitOfWork

_TOKEN_COST = 1.0
"""[FR-05] Tokens one request consumes. Citations: SPEC.md L117."""


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
    tokens = _refilled_tokens(bucket, capacity=capacity, rate_per_sec=rate_per_sec, now=now)
    allowed = tokens >= _TOKEN_COST
    if allowed:
        tokens -= _TOKEN_COST
    uow.rate_buckets.save(bucket, key_id, tokens, now)
    if allowed:
        return RateDecision(allowed=True, retry_after_s=0)
    return RateDecision(allowed=False, retry_after_s=_seconds_until_token(tokens, rate_per_sec))


def _refilled_tokens(
    bucket: RateBucket | None, *, capacity: int, rate_per_sec: float, now: datetime
) -> float:
    """[FR-05] Tokens held at ``now``: a new bucket starts full; refill caps at capacity.

    Citations: SPEC.md L117.
    """
    if bucket is None:
        return float(capacity)
    elapsed_s = max((now - bucket.updated_at).total_seconds(), 0.0)
    return min(float(capacity), bucket.tokens + elapsed_s * rate_per_sec)


def _seconds_until_token(tokens: float, rate_per_sec: float) -> int:
    """[FR-05] Whole seconds (at least 1) until the bucket refills one token.

    Citations: SPEC.md L118.
    """
    return max(1, math.ceil((_TOKEN_COST - tokens) / rate_per_sec))

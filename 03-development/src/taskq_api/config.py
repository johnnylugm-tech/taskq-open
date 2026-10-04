"""Typed settings read from ``TASKQ_*`` environment variables.

[FR-01] Supplies the database location used by the task CRUD API.
[FR-02] Supplies ``TASKQ_TASK_TIMEOUT`` for task runs.
[FR-05] Supplies the token-bucket burst and refill rate.

Citations: SPEC.md L287-302 (5.1 environment variables); SPEC.md L122-128 (FR-06 pool).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """[FR-01] Runtime settings; the DB URL is excluded from ``repr`` (NFR-04).

    Citations: SPEC.md L291-292.
    """

    db_url: str = field(repr=False)
    db_pool_size: int
    task_timeout: float
    rate_burst: int
    rate_per_sec: float


def load_settings() -> Settings:
    """[FR-01] Build :class:`Settings` from the process environment.

    [FR-02] Adds the per-task subprocess timeout.
    [FR-05] Adds the rate-limit burst and refill rate.

    Citations: SPEC.md L291-293, L296-297.
    """
    return Settings(
        db_url=os.environ.get("TASKQ_DB_URL", "sqlite:///./taskq.db"),
        db_pool_size=int(os.environ.get("TASKQ_DB_POOL_SIZE", "5")),
        task_timeout=float(os.environ.get("TASKQ_TASK_TIMEOUT", "10.0")),
        rate_burst=int(os.environ.get("TASKQ_RATE_BURST", "20")),
        rate_per_sec=float(os.environ.get("TASKQ_RATE_PER_SEC", "5.0")),
    )

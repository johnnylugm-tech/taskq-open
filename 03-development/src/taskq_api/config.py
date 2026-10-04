"""Typed settings read from ``TASKQ_*`` environment variables.

[FR-01] Supplies the database location used by the task CRUD API.
[FR-02] Supplies ``TASKQ_TASK_TIMEOUT`` for task runs.
[FR-05] Supplies the token-bucket burst and refill rate.
[FR-08] Supplies the executor concurrency cap and drain timeout.
[FR-10] Supplies the CORS allow-list (empty by default -> deny all).
Supplies the log level/format and the listen host/port (SPEC.md 5.1).

Citations: SPEC.md L287-302 (5.1 environment variables); SPEC.md L122-128 (FR-06 pool);
SPEC.md L145-150 (FR-08); SPEC.md L193 (NFR-02 CORS).
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
    max_concurrent: int
    drain_timeout: float
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"
    log_format: str = "json"
    host: str = "127.0.0.1"
    port: int = 8000


def load_settings() -> Settings:
    """[FR-01] Build :class:`Settings` from the process environment.

    [FR-02] Adds the per-task subprocess timeout.
    [FR-05] Adds the rate-limit burst and refill rate.
    [FR-08] Adds the executor concurrency cap and graceful-drain timeout.
    [FR-10] Adds the comma-separated ``TASKQ_CORS_ORIGINS`` allow-list.

    Citations: SPEC.md L291-297, L147-148, L193.
    """
    return Settings(
        db_url=os.environ.get("TASKQ_DB_URL", "sqlite:///./taskq.db"),
        db_pool_size=int(os.environ.get("TASKQ_DB_POOL_SIZE", "5")),
        task_timeout=float(os.environ.get("TASKQ_TASK_TIMEOUT", "10.0")),
        rate_burst=int(os.environ.get("TASKQ_RATE_BURST", "20")),
        rate_per_sec=float(os.environ.get("TASKQ_RATE_PER_SEC", "5.0")),
        max_concurrent=int(os.environ.get("TASKQ_MAX_CONCURRENT", "8")),
        drain_timeout=float(os.environ.get("TASKQ_DRAIN_TIMEOUT", "30.0")),
        cors_origins=tuple(
            origin.strip()
            for origin in os.environ.get("TASKQ_CORS_ORIGINS", "").split(",")
            if origin.strip()
        ),
        log_level=os.environ.get("TASKQ_LOG_LEVEL", "INFO").upper(),
        log_format=os.environ.get("TASKQ_LOG_FORMAT", "json").lower(),
        host=os.environ.get("TASKQ_HOST", "127.0.0.1"),
        port=int(os.environ.get("TASKQ_PORT", "8000")),
    )

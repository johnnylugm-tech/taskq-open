"""``rate_buckets`` table mapping.

[FR-05] Per-key token bucket state kept in the database so every worker sees
the same bucket.

Citations: SPEC.md L115-120 (FR-05); SPEC.md L119 (state in DB);
02-architecture/SAD.md L84, L101.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from taskq_api.models.base import Base, IsoDateTime


class RateBucket(Base):
    """[FR-05] Remaining tokens of one API key as of ``updated_at``.

    Citations: SPEC.md L117, L119.
    """

    __tablename__ = "rate_buckets"

    key_id: Mapped[str] = mapped_column(String(36), ForeignKey("api_keys.id"), primary_key=True)
    tokens: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(IsoDateTime, nullable=False)

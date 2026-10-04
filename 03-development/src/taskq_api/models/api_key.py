"""``api_keys`` table mapping.

[FR-01] API keys gating the task endpoints (hash only, never plaintext).

Citations: SPEC.md L79-86 (scopes per endpoint); SPEC.md L310 (api_keys columns).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from taskq_api.models.base import Base, IsoDateTime


class ApiKey(Base):
    """[FR-01] A hashed API key with a single scope.

    Citations: SPEC.md L310.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(IsoDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(IsoDateTime)

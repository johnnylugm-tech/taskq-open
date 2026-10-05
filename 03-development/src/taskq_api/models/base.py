"""Declarative base and shared column types.

[FR-01] Base class for every ORM model.

Citations: SPEC.md L304-316 (5.2 database schema); SPEC.md L68 (SQLAlchemy 2.x).
"""
# pragma: no error-handling — declarative ORM mapping, no executable logic

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """[FR-01] Declarative base holding the head-schema metadata.

    Citations: SPEC.md L304-316.
    """


class IsoDateTime(TypeDecorator):
    """[FR-01] Timezone-aware datetime stored as ISO-8601 text.

    ISO text sorts chronologically, which the keyset cursor relies on.

    Citations: SPEC.md L90 (cursor pagination), L309 (``created_at``).
    """

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> str | None:
        """[FR-01] Serialize a datetime to ISO-8601. Citations: SPEC.md L309."""
        return None if value is None else value.isoformat()

    def process_result_value(self, value: str | None, dialect) -> datetime | None:
        """[FR-01] Parse ISO-8601 text back to a datetime. Citations: SPEC.md L309."""
        return None if value is None else datetime.fromisoformat(value)

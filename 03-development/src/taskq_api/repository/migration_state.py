"""Alembic upgrade / downgrade helpers and current-revision inspection.

[FR-07] Drives ``alembic.command`` in-process against the ``migrations``
script directory, and renders offline (``--sql``) migration SQL.

Citations: SPEC.md L130-143 (FR-07); SPEC.md L368-369 (§8 #12-13);
02-architecture/SAD.md L80, L103.
"""

from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool

_SCRIPT_LOCATION = Path(__file__).resolve().parents[2] / "migrations"


def alembic_config(db_url: str, output_buffer: io.StringIO | None = None) -> Config:
    """[FR-07] Alembic config bound to ``db_url``. Citations: SPEC.md L140."""
    config = Config(output_buffer=output_buffer)
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def upgrade(db_url: str, revision: str = "head") -> int:
    """[FR-07] Upgrade to ``revision``; 0 on success. Citations: SPEC.md L140."""
    command.upgrade(alembic_config(db_url), revision)
    return 0


def downgrade(db_url: str, revision: str) -> int:
    """[FR-07] Downgrade to ``revision``; 0 on success. Citations: SPEC.md L140-141."""
    command.downgrade(alembic_config(db_url), revision)
    return 0


def current_revision(db_url: str) -> str | None:
    """[FR-07] Revision stamped in ``alembic_version`` (None at base).

    Citations: SPEC.md L140; 02-architecture/SAD.md L80.
    """
    engine = create_engine(db_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def offline_sql(db_url: str, start: str = "base", end: str = "head") -> str:
    """[FR-07] Render ``start:end`` upgrade SQL without connecting. Citations: SPEC.md L143."""
    buffer = io.StringIO()
    command.upgrade(alembic_config(db_url, buffer), f"{start}:{end}", sql=True)
    return buffer.getvalue()

"""Alembic upgrade / downgrade helpers and current-revision inspection.

[FR-07] Drives ``alembic.command`` in-process against the ``migrations``
script directory, and renders offline (``--sql``) migration SQL.
[FR-09] Probes DB reachability and current-vs-head revision for ``/readyz``.

Citations: SPEC.md L130-143 (FR-07); SPEC.md L368-369 (§8 #12-13); SPEC.md L157, L160 (FR-09);
02-architecture/SAD.md L80, L103.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, pool
from sqlalchemy.exc import SQLAlchemyError

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


@dataclass(frozen=True)
class MigrationProbe:
    """[FR-09] DB reachability plus current and head revisions. Citations: SPEC.md L157."""

    reachable: bool
    current: str | None
    head: str | None
    has_schema: bool = False


def has_schema(db_url: str) -> bool:
    """[FR-05] True when the application tables exist (schema built without alembic).

    Citations: SPEC.md L157.
    """
    engine = create_engine(db_url, poolclass=pool.NullPool)
    try:
        return inspect(engine).has_table("api_keys")
    finally:
        engine.dispose()


def head_revision(db_url: str) -> str | None:
    """[FR-09] Head revision of the ``migrations`` script directory. Citations: SPEC.md L157."""
    return ScriptDirectory.from_config(alembic_config(db_url)).get_current_head()


def probe(db_url: str) -> MigrationProbe:
    """[FR-09] Read ``alembic current``; an unreachable DB yields ``reachable=False``.

    Citations: SPEC.md L157, L160.
    """
    head = head_revision(db_url)
    try:
        current = current_revision(db_url)
        schema = current is None and has_schema(db_url)
    except SQLAlchemyError:
        return MigrationProbe(reachable=False, current=None, head=head)
    return MigrationProbe(reachable=True, current=current, head=head, has_schema=schema)


def offline_sql(db_url: str, start: str = "base", end: str = "head") -> str:
    """[FR-07] Render ``start:end`` upgrade SQL without connecting. Citations: SPEC.md L143."""
    buffer = io.StringIO()
    command.upgrade(alembic_config(db_url, buffer), f"{start}:{end}", sql=True)
    return buffer.getvalue()

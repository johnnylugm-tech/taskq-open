"""Alembic environment: runs revisions online or renders them offline.

[FR-07] Offline (``--sql``) mode renders literal SQL without connecting;
online mode runs against ``sqlalchemy.url`` in one transaction.

Citations: SPEC.md L140 (upgrade head / downgrade base); SPEC.md L143
(offline SQL); 02-architecture/SAD.md L103.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config


def run_migrations_offline() -> None:
    """[FR-07] Emit migration SQL as text. Citations: SPEC.md L143."""
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """[FR-07] Apply migrations to the configured database. Citations: SPEC.md L140."""
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Alembic environment: runs revisions online or renders them offline.

[FR-07] Offline (``--sql``) mode renders literal SQL without connecting;
online mode runs against ``sqlalchemy.url`` in one transaction.

Citations: SPEC.md L140 (upgrade head / downgrade base); SPEC.md L143
(offline SQL); 02-architecture/SAD.md L103.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, event, pool
from sqlalchemy.engine import Engine

config = context.config


def run_migrations_offline() -> None:
    """[FR-07] Emit migration SQL as text. Citations: SPEC.md L143."""
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _make_sqlite_ddl_transactional(engine: Engine) -> None:
    """[FR-07] Open every SQLite migration with an explicit ``BEGIN``.

    The driver otherwise autocommits DDL, so a revision that fails after
    creating a table would leave that table behind (NFR-03).

    Citations: SPEC.md L140; NFR-03 AC-N3.6.
    """

    @event.listens_for(engine, "connect")
    def _disable_driver_begin(dbapi_connection, connection_record) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn) -> None:
        conn.exec_driver_sql("BEGIN")


def run_migrations_online() -> None:
    """[FR-07] Apply migrations to the configured database. Citations: SPEC.md L140."""
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    transactional_ddl = engine.dialect.name == "sqlite"
    if transactional_ddl:
        _make_sqlite_ddl_transactional(engine)
    with engine.connect() as connection:
        context.configure(connection=connection, transactional_ddl=transactional_ddl)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

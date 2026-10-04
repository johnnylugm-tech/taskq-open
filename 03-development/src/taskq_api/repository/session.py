"""Engine, pool and the request-scoped :class:`UnitOfWork`.

[FR-01] Gives each task CRUD request one transaction: commit on success,
rollback on any exception.

[FR-05] SQLite transactions take the write lock at BEGIN (bucket row lock).

Citations: SPEC.md L86 (delete in one transaction); SPEC.md L119 (FR-05 lock);
SPEC.md L122-128 (FR-06);
02-architecture/SAD.md L20, L166.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import create_engine, event, make_url
from sqlalchemy.dialects.sqlite.base import SQLiteCompiler
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import taskq_api.models  # noqa: F401  (registers every table on Base.metadata)
from taskq_api.config import Settings
from taskq_api.repository.api_keys import ApiKeyRepository
from taskq_api.repository.rate_buckets import RateBucketRepository
from taskq_api.repository.results import ResultRepository
from taskq_api.repository.stats import StatsRepository
from taskq_api.repository.tags import TagRepository
from taskq_api.repository.tasks import TaskRepository


class KeysetSQLiteCompiler(SQLiteCompiler):
    """[FR-01] SQLite compiler that omits the dialect's implicit ``OFFSET 0``.

    Stock SQLAlchemy renders ``LIMIT ? OFFSET ?`` for every limited SQLite
    query; keyset pagination must not emit OFFSET at all (NFR-01).

    Citations: SPEC.md L90 (cursor-based, no offset).
    """

    def limit_clause(self, select, **kw) -> str:
        """[FR-01] Render ``LIMIT`` alone unless an offset was really requested.

        [FR-06] The keyword and the bound-parameter placeholder are joined as
        compiler tokens; no value is ever interpolated into the SQL text.

        Citations: SPEC.md L90, L126.
        """
        if select._offset_clause is None:
            return " ".join(("\n LIMIT", self.process(select._limit_clause, **kw)))
        return super().limit_clause(select, **kw)


def build_engine(settings: Settings) -> Engine:
    """[FR-01] Create the pooled engine.

    [FR-06] ``pool_size`` comes from ``TASKQ_DB_POOL_SIZE`` and stale pooled
    connections are detected with ``pool_pre_ping=True``.

    Citations: SPEC.md L90, L128.
    """
    is_sqlite = make_url(settings.db_url).get_backend_name() == "sqlite"
    engine = create_engine(
        settings.db_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if is_sqlite else {},
    )
    if is_sqlite:
        engine.dialect.statement_compiler = KeysetSQLiteCompiler
        _serialize_sqlite_transactions(engine)
    return engine


def _serialize_sqlite_transactions(engine: Engine) -> None:
    """[FR-05] Open every SQLite transaction with ``BEGIN IMMEDIATE``.

    SQLite ignores ``FOR UPDATE``; taking the database write lock at BEGIN
    makes a bucket read-modify-write atomic across concurrent requests.

    Citations: SPEC.md L119; 02-architecture/SAD.md L165.
    """

    @event.listens_for(engine, "connect")
    def _disable_driver_begin(dbapi_connection, connection_record) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")


class UnitOfWork:
    """[FR-01] Transaction scope exposing repositories; never leaks a ``Session``.

    [FR-02] Also exposes the ``task_results`` repository.
    [FR-03] Also exposes the ``api_keys`` repository.
    [FR-05] Also exposes the ``rate_buckets`` repository.
    [FR-09] Also exposes the ``stats`` (metrics) repository.

    Citations: SPEC.md L98, L104, L119, L125, L158; 02-architecture/SAD.md L134, L166.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> UnitOfWork:
        self._session = self._session_factory()
        self._bind_repositories(self._session)
        return self

    def _bind_repositories(self, session: Session) -> None:
        """[FR-06] Attach every repository to this unit's single ``Session``.

        Citations: SPEC.md L124-125.
        """
        self.tasks = TaskRepository(session)
        self.tags = TagRepository(session)
        self.results = ResultRepository(session)
        self.api_keys = ApiKeyRepository(session)
        self.rate_buckets = RateBucketRepository(session)
        self.stats = StatsRepository(session)

    def __exit__(self, exc_type, exc, tb) -> None:
        """[FR-06] Commit on clean exit, otherwise roll back; always close.

        Any ``BaseException`` (including ``asyncio.CancelledError``) takes the
        rollback path, and returning ``None`` lets it propagate unchanged.

        Citations: SPEC.md L125.
        """
        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()


def uow_factory(engine: Engine) -> Callable[[], UnitOfWork]:
    """[FR-01] Return a zero-argument factory producing fresh units of work.

    Citations: SPEC.md L125.
    """
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return lambda: UnitOfWork(session_factory)

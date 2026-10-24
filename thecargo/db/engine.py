from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import wraps

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import HTTPConnection

DEFAULT_POOL_TIMEOUT = 5


def make_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = DEFAULT_POOL_TIMEOUT,
    pool_recycle: int = 300,
    prepared_statement_cache_size: int = 0,
    echo: bool = False,
) -> AsyncEngine:
    """A pgbouncer-safe engine that fails fast when the pool is drained.

    SQLAlchemy's default pool_timeout of 30s turns pool exhaustion into
    30-second stalls that surface as user-facing 500s; a short timeout makes
    the exhaustion visible immediately instead of queueing requests behind it.

    There is no pre-ping: under asyncpg it sends BEGIN, a ping and ROLLBACK on
    every checkout, three extra round trips per request. ``pool_recycle``
    keeps connections younger than any idle cutoff between here and pgbouncer,
    and a dropped connection invalidates the pool on its first error.

    ``prepared_statement_cache_size`` stays 0 unless the pgbouncer in front
    tracks protocol-level prepared statements (``max_prepared_statements``);
    with it, each statement is parsed and planned once per server connection
    instead of on every execution.
    """
    return create_async_engine(
        database_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": prepared_statement_cache_size,
        },
    )


_REQUEST_GUARDS = text(
    "SELECT set_config('statement_timeout', :statement, true),"
    " set_config('idle_in_transaction_session_timeout', :idle, true)"
)


async def apply_request_guards(session: AsyncSession, *, statement: str = "30s", idle: str = "15s") -> None:
    await session.execute(_REQUEST_GUARDS, {"statement": statement, "idle": idle})


def guard_transactions(session: AsyncSession, *, statement: str = "30s", idle: str = "15s") -> None:
    """Bound every transaction the session opens, starting from its first statement.

    Applying the guards up front opens the transaction before the request needs the
    database, and under pgbouncer transaction pooling that pins a server connection
    through every await in between: token checks, Redis cache reads, calls to other
    services. A request answered from cache would hold one without running a query.
    ``after_begin`` sets the timeouts on the transaction's own connection the moment it
    starts, and again on every transaction that follows a commit.
    """
    params = {"statement": statement, "idle": idle}

    def bound(_session, _transaction, connection) -> None:
        connection.execute(_REQUEST_GUARDS, params)

    event.listen(session.sync_session, "after_begin", bound)


def read_only(endpoint):
    """Mark a route that only reads, so its request session runs without a transaction.

    A request session commits when the response has been sent, and under pgbouncer
    transaction pooling its server connection stays pinned from the first query until
    then: through every await between queries, the ORM loading, the serialization and
    the send. Measured on the GCP stack, a pinned connection spent about 70% of that
    time idle in transaction even at normal load, and once the App node ran out of CPU
    the pool drained into query waits and pool timeouts. An autocommit session hands the
    server connection back after every statement. Each statement already reads its own
    snapshot under READ COMMITTED, so a read loses nothing by it. The request guards'
    statement_timeout needs a transaction and does not apply here; pgbouncer's
    query_timeout still bounds every statement.
    """
    endpoint.__read_only__ = True
    return endpoint


def is_read_only(conn: HTTPConnection | None) -> bool:
    route = conn.scope.get("route") if conn is not None else None
    return getattr(getattr(route, "endpoint", None), "__read_only__", False)


def forbid_writes(session: AsyncSession) -> None:
    """Fail a write on a read-only session: under autocommit it would land one statement at a time."""

    def flush(sync_session, _flush_context, _instances) -> None:
        if sync_session.new or sync_session.deleted or any(sync_session.is_modified(o) for o in sync_session.dirty):
            raise RuntimeError("read-only request tried to write")

    def execute(state) -> None:
        if state.is_insert or state.is_update or state.is_delete:
            raise RuntimeError("read-only request tried to write")

    event.listen(session.sync_session, "before_flush", flush)
    event.listen(session.sync_session, "do_orm_execute", execute)


@asynccontextmanager
async def read_only_session(maker: async_sessionmaker) -> AsyncIterator[AsyncSession]:
    async with maker() as session:
        await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
        forbid_writes(session)
        yield session


@asynccontextmanager
async def task_session(database_url: str, **engine_kwargs) -> AsyncIterator[AsyncSession]:
    """One session on a task-owned engine, disposed before the loop closes.

    ``asyncio.run`` closes its loop on exit, so a Celery task that checks out
    from a module-level engine leaves connections bound to a dead loop and the
    next run dies with "Event loop is closed". Owning the engine per run keeps
    every connection's lifetime inside the loop that created it.
    """
    engine = make_engine(database_url, **engine_kwargs)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


def async_task(database_url_getter: Callable[[], str]):
    """Wrap a coroutine taking ``db`` as its first argument into a sync Celery body."""

    def decorate(fn: Callable[..., Awaitable]):
        @wraps(fn)
        def runner(*args, **kwargs):
            import asyncio

            async def _run():
                async with task_session(database_url_getter()) as db:
                    return await fn(db, *args, **kwargs)

            return asyncio.run(_run())

        return runner

    return decorate

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import wraps

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_POOL_TIMEOUT = 5


def make_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = DEFAULT_POOL_TIMEOUT,
    pool_recycle: int = 300,
    echo: bool = False,
) -> AsyncEngine:
    """A pgbouncer-safe engine that fails fast when the pool is drained.

    SQLAlchemy's default pool_timeout of 30s turns pool exhaustion into
    30-second stalls that surface as user-facing 500s; a short timeout makes
    the exhaustion visible immediately instead of queueing requests behind it.
    """
    return create_async_engine(
        database_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        pool_recycle=pool_recycle,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )


_REQUEST_GUARDS = text(
    "SELECT set_config('statement_timeout', :statement, true),"
    " set_config('idle_in_transaction_session_timeout', :idle, true)"
)


async def apply_request_guards(session: AsyncSession, *, statement: str = "30s", idle: str = "15s") -> None:
    await session.execute(_REQUEST_GUARDS, {"statement": statement, "idle": idle})


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

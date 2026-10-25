"""Request sessions that hold a transaction only from the first write to the commit.

Under pgbouncer transaction pooling a server connection belongs to a transaction for as long as it stays open. A
request session that begins at its first query keeps one pinned through every await after it: the ORM loading, calls
to other services, the serialization and, while the dependency waits for the send, the response itself. Sampled every
0.25 s through the GCP breakpoint test, 93% of the busy server connections of the shipment pool sat idle in
transaction waiting on the App, and the pool drained into 503s at about 400 rps with the database at 59% CPU.

A routing session reads through an autocommit engine, so a read hands its server connection back as soon as it ends,
and opens the transaction on the write engine with the first statement that needs one: a flush, DML, a locking read, a
savepoint, an explicit connection or a function with transaction-scoped effects. From there to the commit every
statement runs in that transaction, so the request reads its own writes. Under READ COMMITTED each statement takes its
own snapshot whether a transaction is open or not, so a read before the first write sees the same rows outside of it;
only locks and transaction-scoped settings need the transaction, and those statements open it.
"""

import re
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.sql.elements import Label, TextClause
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.sql.selectable import GenerativeSelect

from thecargo.db.engine import make_engine

AUTOCOMMIT = "AUTOCOMMIT"

TRANSACTIONAL_FUNCTIONS = frozenset(
    {
        "pg_advisory_lock",
        "pg_advisory_lock_shared",
        "pg_advisory_unlock",
        "pg_advisory_unlock_all",
        "pg_advisory_xact_lock",
        "pg_advisory_xact_lock_shared",
        "pg_current_xact_id",
        "pg_notify",
        "pg_try_advisory_lock",
        "pg_try_advisory_lock_shared",
        "pg_try_advisory_xact_lock",
        "pg_try_advisory_xact_lock_shared",
        "set_config",
        "txid_current",
    }
)

_READ_STATEMENT = re.compile(r"\s*(?:select|with|values|show|explain)\b", re.IGNORECASE)
_TRANSACTIONAL_SQL = re.compile(
    r"\bfor\s+(?:no\s+key\s+update|update|key\s+share|share)\b"
    r"|\binsert\s+into\b|\bupdate\s+\S+\s+set\b|\bdelete\s+from\b|\bmerge\s+into\b"
    r"|\bcreate\s+(?:(?:temp|temporary|unlogged)\s+)?table\b|\bsavepoint\b|\block\s+table\b",
    re.IGNORECASE,
)


class MisroutedStatementError(RuntimeError):
    """A statement that needs a transaction reached the autocommit read engine."""


class StatementRouter:
    """Tells the statements that need the write transaction from the ones a read engine may run."""

    def __init__(self, functions: Iterable[str] = ()):
        self.functions = TRANSACTIONAL_FUNCTIONS | {name.lower() for name in functions}
        self._calls = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, self.functions))) + r")\s*\(", re.IGNORECASE)
        self.sql_needs_transaction = lru_cache(maxsize=4096)(self._sql_needs_transaction)

    def _sql_needs_transaction(self, sql: str) -> bool:
        if not _READ_STATEMENT.match(sql):
            return True
        return bool(_TRANSACTIONAL_SQL.search(sql) or self._calls.search(sql))

    def _column_needs_transaction(self, column: Any) -> bool:
        if isinstance(column, Label):
            column = column.element
        if isinstance(column, FunctionElement):
            return column.name.lower() in self.functions
        if isinstance(column, TextClause):
            return self.sql_needs_transaction(column.text)
        return False

    def needs_transaction(self, clause: Any) -> bool:
        """Decide from the statement object, before it is compiled.

        DML, ``FOR UPDATE``/``FOR SHARE`` and a transactional function in the select list are caught here. A
        transactional construct nested deeper, such as DML inside a CTE, still reaches the read engine's guard, which
        refuses it loudly instead of running it outside a transaction.
        """
        if clause is None:
            return False
        if getattr(clause, "is_dml", False):
            return True
        if isinstance(clause, TextClause):
            return self.sql_needs_transaction(clause.text)
        if isinstance(clause, GenerativeSelect):
            if clause._for_update_arg is not None:
                return True
            return any(self._column_needs_transaction(column) for column in getattr(clause, "_raw_columns", ()))
        return False


class RoutingSession(Session):
    """A Session that reads through ``read_bind`` until a statement needs the write transaction.

    The switch is sticky: once the session writes, every statement runs in the write transaction until it commits or
    rolls back, and the next statement after that starts on the read engine again.
    """

    def __init__(self, *args: Any, read_bind: Engine | None = None, router: StatementRouter | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._read_bind = read_bind
        self._router = router or StatementRouter()
        self._writing = False

    @property
    def writing(self) -> bool:
        return self._writing

    def get_bind(self, mapper=None, *, clause=None, bind=None, **kwargs):
        if bind is None and self._read_bind is not None and not self._writing:
            if not self._flushing and not self._router.needs_transaction(clause):
                return self._read_bind
            self._writing = True
        return super().get_bind(mapper, clause=clause, bind=bind, **kwargs)

    def connection(self, bind_arguments=None, execution_options=None) -> Connection:
        if not execution_options or execution_options.get("isolation_level") != AUTOCOMMIT:
            self._writing = True
        return super().connection(bind_arguments=bind_arguments, execution_options=execution_options)

    def begin_nested(self) -> SessionTransaction:
        self._writing = True
        return super().begin_nested()


@event.listens_for(RoutingSession, "after_transaction_end")
def _back_to_reads(session: Session, transaction: SessionTransaction) -> None:
    """Hand reads back to the read engine once the outermost transaction ends, however it ended."""
    if transaction.parent is None and isinstance(session, RoutingSession):
        session._writing = False


def make_read_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """An engine with its own pool whose connections run every statement in autocommit."""
    return make_engine(database_url, **kwargs).execution_options(isolation_level=AUTOCOMMIT)


def guard_read_engine(engine: AsyncEngine, router: StatementRouter) -> None:
    """Refuse, on the read engine, any statement that needs a transaction instead of running it outside one."""

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def refuse(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if router.sql_needs_transaction(statement):
            raise MisroutedStatementError(
                f"statement needs a transaction but reached the read engine: {statement[:200]}"
            )


def routing_sessionmaker(
    write_engine: AsyncEngine,
    read_engine: AsyncEngine,
    *,
    transactional_functions: Iterable[str] = (),
    **kwargs: Any,
) -> async_sessionmaker:
    """Sessions that read through ``read_engine`` and write through ``write_engine``.

    ``transactional_functions`` names the service's own database functions that write or lock, so a ``SELECT`` that
    calls one opens the write transaction.
    """
    router = StatementRouter(transactional_functions)
    guard_read_engine(read_engine, router)
    return async_sessionmaker(
        write_engine,
        sync_session_class=RoutingSession,
        read_bind=read_engine.sync_engine,
        router=router,
        **kwargs,
    )

"""A request session reads in autocommit and holds a transaction only from its first write to the commit.

Under pgbouncer transaction pooling a transaction pins a server connection until it ends. Sampled through the GCP
breakpoint test, 93% of the shipment pool's busy server connections were idle in transaction, waiting on the App. These
tests pin the routing that hands a read's connection back right after the statement: reads go to the autocommit engine,
the first statement that needs a transaction opens it on the write engine and every statement after it stays there
until the commit, so the request still reads its own writes.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import String, create_engine, delete, event, func, insert, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from thecargo.db.engine import guard_transactions
from thecargo.db.routing import AUTOCOMMIT, MisroutedStatementError, RoutingSession, StatementRouter, guard_read_engine


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(String(50))


ROUTER = StatementRouter(["shipment_totals_fold"])


@pytest.fixture
def engines(tmp_path):
    url = f"sqlite:///{tmp_path / 'routing.db'}"
    write = create_engine(url)
    read = create_engine(url).execution_options(isolation_level=AUTOCOMMIT)
    Base.metadata.create_all(write)
    with write.begin() as conn:
        conn.execute(insert(Note).values(id=1, body="kept"))
    seen: list[tuple[str, str]] = []

    def watch(name):
        def record(_conn, _cursor, statement, _parameters, _context, _executemany):
            seen.append((name, statement.split()[0].upper()))

        return record

    event.listen(write, "before_cursor_execute", watch("write"))
    event.listen(read, "before_cursor_execute", watch("read"))
    yield write, read, seen
    write.dispose()
    read.dispose()


@pytest.fixture
def session(engines):
    write, read, _seen = engines
    with RoutingSession(bind=write, read_bind=read, router=ROUTER, expire_on_commit=False) as s:
        yield s


def _engines_used(seen) -> set[str]:
    return {name for name, _ in seen}


def test_reads_run_on_the_read_engine_and_open_no_write_transaction(session, engines):
    seen = engines[2]

    assert session.scalars(select(Note.body)).all() == ["kept"]
    assert session.get(Note, 1).body == "kept"

    assert _engines_used(seen) == {"read"}
    assert session.writing is False


def test_the_first_flush_opens_the_write_transaction_and_later_reads_see_the_write(session, engines):
    seen = engines[2]
    session.scalars(select(Note.id)).all()
    seen.clear()

    session.add(Note(id=2, body="new"))
    session.flush()
    ids = session.scalars(select(Note.id).order_by(Note.id)).all()

    assert ids == [1, 2]
    assert _engines_used(seen) == {"write"}
    assert session.writing is True


def test_a_commit_hands_the_next_reads_back_to_the_read_engine(session, engines):
    seen = engines[2]
    session.add(Note(id=2, body="new"))
    session.commit()
    seen.clear()

    ids = session.scalars(select(Note.id).order_by(Note.id)).all()

    assert ids == [1, 2]
    assert _engines_used(seen) == {"read"}
    assert session.writing is False


def test_leaving_a_begin_block_hands_the_next_reads_back_to_the_read_engine(session, engines):
    seen = engines[2]
    with session.begin():
        session.add(Note(id=2, body="in a block"))
    seen.clear()

    assert session.scalars(select(Note.id).order_by(Note.id)).all() == [1, 2]
    assert _engines_used(seen) == {"read"}
    assert session.writing is False


def test_a_rollback_drops_the_write_and_reads_from_the_read_engine_again(session, engines):
    seen = engines[2]
    session.add(Note(id=2, body="lost"))
    session.flush()
    session.rollback()
    seen.clear()

    assert session.scalars(select(Note.id)).all() == [1]
    assert _engines_used(seen) == {"read"}


@pytest.mark.parametrize(
    "statement",
    [
        update(Note).where(Note.id == 1).values(body="changed"),
        delete(Note).where(Note.id == 99),
        insert(Note).values(id=3, body="bulk"),
        text("UPDATE notes SET body = 'raw' WHERE id = 1"),
        select(Note).with_for_update(),
    ],
)
def test_dml_and_locking_reads_run_in_the_write_transaction(session, engines, statement):
    seen = engines[2]

    session.execute(statement)

    assert _engines_used(seen) == {"write"}
    assert session.writing is True


def test_a_savepoint_opens_the_write_transaction(session, engines):
    seen = engines[2]

    with session.begin_nested():
        session.scalars(select(Note.id)).all()

    assert _engines_used(seen) == {"write"}


def test_an_explicit_connection_writes_unless_it_asks_for_autocommit(session):
    session.connection(execution_options={"isolation_level": AUTOCOMMIT})
    assert session.writing is False

    session.connection()
    assert session.writing is True


@pytest.mark.parametrize(
    ("statement", "needs"),
    [
        (None, False),
        (select(Note), False),
        (select(func.count()).select_from(Note), False),
        (text("SELECT updated_at, deleted_at FROM notes WHERE body = 'update this'"), False),
        (select(Note).with_for_update(), True),
        (select(func.pg_try_advisory_xact_lock(7)), True),
        (select(func.set_config("statement_timeout", "5s", True).label("guard")), True),
        (select(func.shipment_totals_fold(100)), True),
        (insert(Note), True),
        (text("SELECT id FROM notes FOR NO KEY UPDATE"), True),
        (text("WITH moved AS (UPDATE notes SET body = 'x' RETURNING id) SELECT id FROM moved"), True),
        (text("DELETE FROM notes"), True),
        (text("CREATE TEMP TABLE scratch (id int)"), True),
        (text("SELECT pg_advisory_xact_lock(1)"), True),
    ],
)
def test_the_router_tells_statements_that_need_a_transaction(statement, needs):
    assert ROUTER.needs_transaction(statement) is needs


def test_the_read_engine_refuses_a_statement_that_needs_a_transaction_instead_of_running_it(engines):
    write, read, _seen = engines
    guard_read_engine(SimpleNamespace(sync_engine=read), ROUTER)

    with read.connect() as conn:
        with pytest.raises(MisroutedStatementError, match="needs a transaction"):
            conn.execute(text("UPDATE notes SET body = 'outside' WHERE id = 1"))

    with write.connect() as conn:
        assert conn.execute(select(Note.body)).scalar_one() == "kept"


def test_request_guards_bound_the_write_transaction_and_skip_autocommit_reads(session):
    guard_transactions(SimpleNamespace(sync_session=session))

    assert session.scalars(select(Note.body)).all() == ["kept"]

    session.add(Note(id=2, body="guarded"))
    with pytest.raises(OperationalError, match="set_config"):
        session.flush()

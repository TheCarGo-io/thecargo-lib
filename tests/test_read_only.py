from types import SimpleNamespace

import pytest
from sqlalchemy import String, create_engine, delete, insert, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from starlette.requests import HTTPConnection

from thecargo.db.engine import forbid_writes, is_read_only, read_only


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(String(50))


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Note(id=1, body="kept"))
        session.commit()
        forbid_writes(SimpleNamespace(sync_session=session))
        yield session


def _conn(scope_extra: dict) -> HTTPConnection:
    return HTTPConnection({"type": "http", **scope_extra})


def test_only_a_marked_route_reads_without_a_transaction():
    @read_only
    async def listing():
        return None

    async def editing():
        return None

    assert is_read_only(_conn({"route": SimpleNamespace(endpoint=listing)})) is True
    assert is_read_only(_conn({"route": SimpleNamespace(endpoint=editing)})) is False
    assert is_read_only(_conn({})) is False
    assert is_read_only(None) is False


def test_reads_go_through(db):
    assert db.scalars(select(Note.body)).all() == ["kept"]
    assert db.get(Note, 1).body == "kept"


def test_a_new_row_is_refused(db):
    db.add(Note(id=2, body="new"))
    with pytest.raises(RuntimeError, match="read-only request tried to write"):
        db.flush()


def test_a_changed_row_is_refused(db):
    db.get(Note, 1).body = "changed"
    with pytest.raises(RuntimeError, match="read-only request tried to write"):
        db.flush()


def test_a_deleted_row_is_refused(db):
    db.delete(db.get(Note, 1))
    with pytest.raises(RuntimeError, match="read-only request tried to write"):
        db.flush()


@pytest.mark.parametrize(
    "statement",
    [
        insert(Note).values(id=3, body="bulk"),
        update(Note).where(Note.id == 1).values(body="bulk"),
        delete(Note).where(Note.id == 1),
    ],
)
def test_write_statements_are_refused(db, statement):
    with pytest.raises(RuntimeError, match="read-only request tried to write"):
        db.execute(statement)

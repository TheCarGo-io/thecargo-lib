from datetime import datetime, timezone

import pytest
from sqlalchemy import String, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from thecargo.models.base import BaseModel, FieldTooLongError, NaiveDatetimeError


class GuardedRow(BaseModel):
    __tablename__ = "guarded_rows"

    name: Mapped[str | None] = mapped_column(String(5), default=None)
    seen_at: Mapped[datetime | None] = mapped_column(default=None)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    BaseModel.metadata.create_all(engine, tables=[GuardedRow.__table__])
    with Session(engine) as s:
        yield s


def test_aware_datetime_is_accepted(session):
    session.add(GuardedRow(seen_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)))
    session.flush()


def test_naive_datetime_is_rejected_on_insert(session):
    session.add(GuardedRow(seen_at=datetime(2026, 8, 5, 12, 0)))
    with pytest.raises(NaiveDatetimeError) as exc:
        session.flush()
    assert exc.value.table == "guarded_rows"
    assert exc.value.column == "seen_at"


def test_naive_datetime_is_rejected_on_update(session):
    row = GuardedRow(seen_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc))
    session.add(row)
    session.flush()
    row.seen_at = datetime(2026, 8, 6, 12, 0)
    with pytest.raises(NaiveDatetimeError):
        session.flush()


def test_string_length_guard_still_enforced(session):
    session.add(GuardedRow(name="toolong"))
    with pytest.raises(FieldTooLongError):
        session.flush()

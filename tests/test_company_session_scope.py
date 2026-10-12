from uuid import UUID, uuid4

import pytest
from sqlalchemy import ForeignKey, create_engine, delete, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, aliased, mapped_column, relationship

from thecargo.context import ANY_COMPANY, active_company, as_company, set_active_company
from thecargo.db.company_scope import install_company_scope, uninstall_company_scope
from thecargo.models.base import CompanyScoped


class Base(DeclarativeBase):
    pass


class Customer(Base, CompanyScoped):
    __tablename__ = "scope_customers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column()
    name: Mapped[str] = mapped_column()
    loads: Mapped[list["Load"]] = relationship(back_populates="customer")


class Load(Base, CompanyScoped):
    __tablename__ = "scope_loads"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column()
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("scope_customers.id"), default=None)
    status: Mapped[str] = mapped_column(default="new")
    customer: Mapped[Customer | None] = relationship(back_populates="loads")


class Note(Base):
    __tablename__ = "scope_notes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    load_id: Mapped[UUID] = mapped_column(ForeignKey("scope_loads.id"))
    body: Mapped[str] = mapped_column()


ORG, BLUE, OCEAN = uuid4(), uuid4(), uuid4()


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    install_company_scope()
    set_active_company(ANY_COMPANY)
    with Session(engine) as session:
        for company, name in ((None, "Org"), (BLUE, "Blue"), (OCEAN, "Ocean")):
            customer = Customer(organization_id=ORG, company_id=company, name=name)
            load = Load(organization_id=ORG, company_id=company, customer=customer)
            session.add_all([customer, load])
            session.flush()
            session.add(Note(load_id=load.id, body=name))
        session.commit()
        yield session
    set_active_company(ANY_COMPANY)
    uninstall_company_scope()


def _names(db) -> list[str]:
    return sorted(db.scalars(select(Customer.name).where(Customer.organization_id == ORG)))


def test_with_nobody_signed_in_a_query_sees_every_company(db):
    assert _names(db) == ["Blue", "Ocean", "Org"]


def test_a_plain_query_is_kept_inside_the_active_company(db):
    with as_company(BLUE):
        in_blue = _names(db)
    with as_company(None):
        in_org = _names(db)

    assert in_blue == ["Blue"]
    assert in_org == ["Org"]
    assert active_company() is ANY_COMPANY


def test_joins_aliases_subqueries_and_counts_follow_the_active_company(db):
    other = aliased(Customer)
    with as_company(BLUE):
        joined = db.scalars(select(Note.body).join(Load, Load.id == Note.load_id)).all()
        through_alias = db.scalars(select(other.name).where(other.organization_id == ORG)).all()
        by_subquery = db.scalars(
            select(Note.body).where(Note.load_id.in_(select(Load.id).where(Load.organization_id == ORG)))
        ).all()
        by_exists = db.scalars(
            select(Note.body).where(select(1).select_from(Load).where(Load.id == Note.load_id).exists())
        ).all()
        counted = db.scalar(select(func.count()).select_from(Load).where(Load.organization_id == ORG))
        by_key = [db.get(Customer, row.id) for row in db.scalars(select(Customer)).all()]

    assert joined == ["Blue"]
    assert through_alias == ["Blue"]
    assert by_subquery == ["Blue"]
    assert by_exists == ["Blue"]
    assert counted == 1
    assert [c.name for c in by_key] == ["Blue"]


def test_a_subquery_must_name_the_model_in_its_from_to_be_reached(db):
    named_only_in_where = select(Note.body).where(select(1).where(Load.id == Note.load_id).exists())
    named_in_from = select(Note.body).where(select(1).select_from(Load).where(Load.id == Note.load_id).exists())

    with as_company(BLUE):
        assert sorted(db.scalars(named_only_in_where)) == ["Blue", "Ocean", "Org"]
        assert db.scalars(named_in_from).all() == ["Blue"]


def test_a_row_of_another_company_cannot_be_fetched_by_its_id(db):
    ocean = db.scalar(select(Customer.id).where(Customer.name == "Ocean"))
    db.expunge_all()

    with as_company(BLUE):
        assert db.get(Customer, ocean) is None
        assert db.scalar(select(Customer).where(Customer.id == ocean)) is None
    assert db.get(Customer, ocean).name == "Ocean"


def test_update_and_delete_touch_only_the_active_company(db):
    with as_company(BLUE):
        db.execute(update(Load).where(Load.organization_id == ORG).values(status="done"))
        db.execute(delete(Customer).where(Customer.organization_id == ORG, Customer.name != "Blue"))
    db.expire_all()

    assert sorted(db.execute(select(Customer.name, Load.status).join(Load.customer)).all()) == [
        ("Blue", "done"),
        ("Ocean", "new"),
        ("Org", "new"),
    ]


def test_a_new_row_is_filed_under_the_active_company(db):
    with as_company(OCEAN):
        db.add(Customer(organization_id=ORG, name="Ocean two"))
        db.flush()
    with as_company(None):
        db.add(Customer(organization_id=ORG, name="Org two"))
        db.flush()
    db.add(Customer(organization_id=ORG, name="Nobody"))
    db.add(Customer(organization_id=ORG, company_id=BLUE, name="Blue two"))
    db.flush()

    filed = dict(db.execute(select(Customer.name, Customer.company_id)).all())
    assert filed["Ocean two"] == OCEAN
    assert filed["Org two"] is None
    assert filed["Nobody"] is None
    assert filed["Blue two"] == BLUE


def test_a_relationship_of_a_row_in_reach_still_loads(db):
    with as_company(BLUE):
        customer = db.scalar(select(Customer).where(Customer.organization_id == ORG))
        loads = customer.loads

    assert [load.customer.name for load in loads] == ["Blue"]

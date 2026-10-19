import asyncio
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from thecargo.context import active_company, set_active_company
from thecargo.dependencies import auth as auth_dep
from thecargo.dependencies.service_auth import COMPANY_HEADER, company_from_header, company_header
from thecargo.models.base import BaseModel, CompanyScoped
from thecargo.repositories.base import (
    ANY_COMPANY,
    TenantRepository,
    company_clause,
    company_for_new_row,
    concrete_company,
    in_company,
)

SECRET = "test-secret-at-least-thirty-two-bytes"


class Scoped(BaseModel, CompanyScoped):
    __tablename__ = "company_scope_test_scoped"

    organization_id: Mapped[UUID] = mapped_column()


class Lookalike(BaseModel):
    __tablename__ = "company_scope_test_lookalike"

    organization_id: Mapped[UUID] = mapped_column()
    company_id: Mapped[UUID | None] = mapped_column(default=None)


class ScopedRepository(TenantRepository):
    model = Scoped


class LookalikeRepository(TenantRepository):
    model = Lookalike


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


def _sql(query) -> str:
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _token(**extra) -> HTTPAuthorizationCredentials:
    payload = {
        "user_id": str(uuid4()),
        "org_id": str(uuid4()),
        "type": "access",
        "p": {},
        **extra,
    }
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(payload, SECRET, algorithm="HS256"))


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.delenv("ALLOWED_ORG_TYPES", raising=False)

    async def _state(user, check_role):
        return [None, 0, None, None, None]

    monkeypatch.setattr(auth_dep, "_token_state", _state)
    set_active_company(ANY_COMPANY)
    yield
    set_active_company(ANY_COMPANY)


def test_token_without_cid_is_the_organization_itself():
    user = asyncio.run(auth_dep.get_current_user(_token()))

    assert user.company_id is None
    assert asyncio.run(auth_dep.get_company_id(user)) is None


def test_token_carries_the_active_company():
    company = uuid4()
    user = asyncio.run(auth_dep.get_current_user(_token(cid=str(company))))

    assert user.company_id == company
    assert asyncio.run(auth_dep.get_company_id(user)) == company


def test_in_the_organization_itself_only_its_own_rows_match():
    org = uuid4()
    sql = _sql(ScopedRepository(FakeSession(), org, None)._base_query())

    assert "company_scope_test_scoped.company_id IS NULL" in sql


def test_a_signed_in_request_scopes_every_repository_without_being_told():
    org, company = uuid4(), uuid4()

    async def request(**claims):
        await auth_dep.get_current_user(_token(**claims))
        repo = ScopedRepository(FakeSession(), org)
        return _sql(repo._base_query()), await repo.create()

    inside, row = asyncio.run(request(cid=str(company)))
    in_org, own = asyncio.run(request())

    assert f"company_scope_test_scoped.company_id = '{company}'" in inside
    assert row.company_id == company
    assert "company_scope_test_scoped.company_id IS NULL" in in_org
    assert own.company_id is None
    assert active_company() is ANY_COMPANY


def test_with_nobody_signed_in_a_repository_spans_every_company():
    org = uuid4()

    assert active_company() is ANY_COMPANY
    assert "company_id" not in _sql(ScopedRepository(FakeSession(), org)._base_query()).split("WHERE")[1]


def test_inside_a_company_only_its_rows_match():
    org, company = uuid4(), uuid4()
    sql = _sql(ScopedRepository(FakeSession(), org, company)._base_query())

    assert f"company_scope_test_scoped.company_id = '{company}'" in sql
    assert "IS NULL" not in sql


def test_a_model_with_its_own_company_column_is_left_alone():
    org, company = uuid4(), uuid4()
    repo = LookalikeRepository(FakeSession(), org, company)

    assert not repo.company_scoped
    assert "company_id =" not in _sql(repo._base_query()).split("WHERE")[1]
    assert "IS NULL" not in _sql(repo._base_query())


def test_create_files_the_row_under_the_active_company():
    org, company, other = uuid4(), uuid4(), uuid4()
    session = FakeSession()

    row = asyncio.run(ScopedRepository(session, org, company).create(company_id=other))

    assert row.company_id == company
    assert row.organization_id == org
    assert session.added == [row]


def test_create_without_a_company_leaves_the_row_with_the_organization():
    row = asyncio.run(ScopedRepository(FakeSession(), uuid4(), None).create())

    assert row.company_id is None


def test_create_on_a_lookalike_keeps_what_the_caller_passed():
    theirs = uuid4()
    row = asyncio.run(LookalikeRepository(FakeSession(), uuid4(), uuid4()).create(company_id=theirs))

    assert row.company_id == theirs


def test_company_clause_matches_null_to_null():
    company = uuid4()

    assert "IS NULL" in _sql(company_clause(Scoped, None))
    assert f"= '{company}'" in _sql(company_clause(Scoped, company))


def test_a_caller_with_no_person_behind_it_can_ask_for_every_company():
    org, company = uuid4(), uuid4()
    repo = ScopedRepository(FakeSession(), org, ANY_COMPANY)

    row = asyncio.run(repo.create(company_id=company))

    assert "company_id" not in _sql(repo._base_query()).split("WHERE")[1]
    assert _sql(company_clause(Scoped, ANY_COMPANY)) == "true"
    assert row.company_id == company


def test_a_row_written_on_behalf_of_every_company_lands_in_the_organization():
    company = uuid4()

    assert concrete_company(ANY_COMPANY) is None
    assert concrete_company(None) is None
    assert concrete_company(company) == company


def test_a_row_is_in_reach_only_from_its_own_space():
    company, other = uuid4(), uuid4()

    assert in_company(company, company)
    assert in_company(None, None)
    assert in_company(ANY_COMPANY, company)
    assert not in_company(company, other)
    assert not in_company(company, None)
    assert not in_company(None, company)


def test_a_row_built_by_hand_can_ask_which_company_it_belongs_in():
    company = uuid4()

    async def request(**claims):
        await auth_dep.get_current_user(_token(**claims))
        return company_for_new_row()

    assert asyncio.run(request(cid=str(company))) == company
    assert asyncio.run(request()) is None
    assert company_for_new_row() is None


def test_a_service_tells_the_next_one_which_company_it_is_acting_for():
    company = uuid4()

    async def received(sent: dict[str, str]):
        set_active_company(ANY_COMPANY)
        await company_from_header(sent.get(COMPANY_HEADER))
        return active_company()

    set_active_company(company)
    for_a_company = company_header()
    set_active_company(None)
    for_the_organization = company_header()
    set_active_company(ANY_COMPANY)
    for_nobody = company_header()

    assert asyncio.run(received(for_a_company)) == company
    assert asyncio.run(received(for_the_organization)) is None
    assert for_nobody == {}
    assert asyncio.run(received(for_nobody)) is ANY_COMPANY
    with pytest.raises(Exception, match="Invalid company"):
        asyncio.run(company_from_header("not-a-company"))


def test_what_the_whole_organization_shares_is_changed_only_from_the_organization():
    in_the_organization = asyncio.run(auth_dep.get_current_user(_token()))
    in_a_company = asyncio.run(auth_dep.get_current_user(_token(cid=str(uuid4()))))

    assert asyncio.run(auth_dep.organization_only(in_the_organization)) is None
    with pytest.raises(Exception) as refused:
        asyncio.run(auth_dep.organization_only(in_a_company))
    assert (refused.value.status_code, refused.value.code) == (403, "ORGANIZATION_ONLY")


def test_the_organization_profile_is_asked_for_the_company_someone_is_in(monkeypatch):
    from thecargo.clients.auth import AuthServiceClient

    asked: list[dict | None] = []

    async def _get(self, path, params=None):
        asked.append(params)
        return {}

    monkeypatch.setattr(AuthServiceClient, "get", _get)
    company = uuid4()

    async def ask(space) -> None:
        set_active_company(space)
        await AuthServiceClient().organization(uuid4())

    for space in (company, None, ANY_COMPANY):
        asyncio.run(ask(space))

    assert asked == [{"company_id": str(company)}, None, None]


def test_an_audit_event_names_the_company_of_the_row_it_is_about():
    from thecargo.audit import _resolve_company_id

    company, elsewhere = uuid4(), uuid4()
    set_active_company(elsewhere)
    of_a_scoped_row = _resolve_company_id(Scoped(organization_id=uuid4(), company_id=company))
    of_a_row_with_its_own_column = _resolve_company_id(Lookalike(organization_id=uuid4(), company_id=company))
    of_a_row_without_one = _resolve_company_id(Lookalike(organization_id=uuid4()))
    set_active_company(ANY_COMPANY)
    with_nobody_signed_in = _resolve_company_id(Lookalike(organization_id=uuid4()))

    assert (of_a_scoped_row, of_a_row_with_its_own_column) == (str(company), str(company))
    assert of_a_row_without_one == str(elsewhere)
    assert with_nobody_signed_in is None


def test_an_email_asked_of_communication_carries_the_company_it_is_sent_for(monkeypatch):
    from thecargo.clients import communication
    from thecargo.clients.communication import CommunicationClient

    published: list[dict] = []

    async def _publish(topic, payload):
        published.append(payload)

    monkeypatch.setattr(communication.publisher, "publish", _publish)
    company = uuid4()
    headers = []

    async def ask(space) -> None:
        set_active_company(space)
        headers.append(CommunicationClient("http://communication", service_secret="s")._headers().get(COMPANY_HEADER))
        await CommunicationClient.send_email_by_template_async(category="invoice", to="a@example.com")

    for space in (company, None, ANY_COMPANY):
        asyncio.run(ask(space))
    set_active_company(ANY_COMPANY)

    assert headers == [str(company), "organization", None]
    assert [sent.get("company_id", "absent") for sent in published] == [str(company), None, "absent"]

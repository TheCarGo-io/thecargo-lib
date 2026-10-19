from uuid import uuid4

import pytest

from thecargo.events import consumer as consumer_module
from thecargo.events import user_sync
from thecargo.models.user_replica import UserReplica


class FakeResult:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.added = []
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.row)

    def add(self, row):
        self.added.append(row)


def _replica(organization_id):
    return UserReplica(id=uuid4(), organization_id=organization_id, email="dana@example.com", is_active=True)


def _moves(session):
    return [
        (statement.compile().params, str(statement.compile()))
        for statement in session.statements
        if statement.is_update
    ]


@pytest.mark.asyncio
async def test_a_user_who_moved_is_followed_only_from_the_organization_they_left():
    user_id, trial, own = uuid4(), uuid4(), uuid4()
    session = FakeSession()

    await user_sync._handle_user_organization_changed(
        session, {"id": str(user_id), "from_organization_id": str(trial), "to_organization_id": str(own)}
    )

    [(params, sql)] = _moves(session)
    assert sorted(params.values(), key=str) == sorted([user_id, trial, own], key=str)
    assert "SET organization_id" in sql
    assert "user_replicas.id = " in sql and "user_replicas.organization_id = " in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "moved",
    [
        {"from_organization_id": None, "to_organization_id": str(uuid4())},
        {"from_organization_id": str(uuid4()), "to_organization_id": "None"},
        {"from_organization_id": str(uuid4())},
        {"from_organization_id": "not-a-uuid", "to_organization_id": str(uuid4())},
    ],
)
async def test_a_move_that_does_not_name_both_organizations_moves_nobody(moved):
    session = FakeSession()

    await user_sync._handle_user_organization_changed(session, {"id": str(uuid4()), **moved})

    assert session.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize("organization_id", [str(uuid4()), None, "", "None", "not-a-uuid"])
async def test_an_update_never_moves_a_user_so_a_late_one_cannot_move_them_back(organization_id):
    home = uuid4()
    replica = _replica(home)
    data = {"id": str(replica.id), "organization_id": organization_id, "last_name": "Diaz"}

    await user_sync._handle_user_updated(FakeSession(replica), data)
    await user_sync._handle_user_updated(FakeSession(replica), {"id": str(replica.id), "ext": "12"})

    assert (replica.organization_id, replica.last_name, replica.ext) == (home, "Diaz", "12")


@pytest.mark.asyncio
async def test_an_update_for_a_user_not_seen_before_adds_them():
    user_id, organization_id = uuid4(), uuid4()
    session = FakeSession()

    await user_sync._handle_user_updated(
        session, {"id": str(user_id), "organization_id": str(organization_id), "email": "new@example.com"}
    )

    assert [(row.id, row.organization_id, row.email) for row in session.added] == [
        (user_id, organization_id, "new@example.com")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("organization_id", [None, "", "None", "not-a-uuid"])
async def test_a_user_not_seen_before_who_has_no_organization_is_not_added(organization_id):
    session = FakeSession()
    data = {"id": str(uuid4()), "organization_id": organization_id, "email": "nowhere@example.com"}

    await user_sync._handle_user_created(session, data)
    await user_sync._handle_user_updated(session, data)

    assert session.added == []


@pytest.mark.asyncio
async def test_the_consumer_takes_the_move_and_gets_a_failed_event_back_after_a_pause(monkeypatch):
    started = {}

    async def _start_consumer(**kwargs):
        started.update(kwargs)

    monkeypatch.setattr(user_sync, "start_consumer", _start_consumer)

    await user_sync.start_user_sync_consumer("amqp://localhost", None, "billing")

    assert started["queue_name"] == "billing-user-sync"
    assert "user.organization_changed" in started["routing_keys"]
    assert (started["requeue_failed"], started["requeue_delay"]) == (True, user_sync.REQUEUE_DELAY_SECONDS)
    assert "requeue_delay" in consumer_module.start_consumer.__code__.co_varnames

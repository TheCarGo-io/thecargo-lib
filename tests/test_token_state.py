from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from thecargo.dependencies import _settings as lib_settings
from thecargo.dependencies.auth import TokenPayload, _enforce_token_state, active_sessions_key, user_stale_key

pytestmark = pytest.mark.asyncio


def _payload(user_id, session_id=None):
    return TokenPayload(
        user_id=user_id,
        org_id=uuid4(),
        role_id=None,
        is_superuser=False,
        team_id=None,
        permissions={},
        session_id=session_id,
    )


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops: list[tuple] = []

    def get(self, key):
        self.ops.append(("get", key))

    def zcard(self, key):
        self.ops.append(("zcard", key))

    def zscore(self, key, member):
        self.ops.append(("zscore", key, member))

    async def execute(self):
        out = []
        for op in self.ops:
            if op[0] == "get":
                out.append(self.redis.store.get(op[1]))
            elif op[0] == "zcard":
                out.append(len(self.redis.zsets.get(op[1], {})))
            elif op[0] == "zscore":
                out.append(self.redis.zsets.get(op[1], {}).get(op[2]))
        return out


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction=True):
        return FakePipeline(self)


@pytest.fixture
def cache(monkeypatch):
    fake = FakeRedis()

    async def get_redis():
        return fake

    monkeypatch.setattr(lib_settings, "get_redis", get_redis)
    return fake


async def test_a_token_without_a_session_passes_when_no_slot_is_held(cache):
    await _enforce_token_state(_payload(uuid4()), 1000)


async def test_a_held_session_passes(cache):
    uid = uuid4()
    sid = str(uuid4())
    cache.zsets[active_sessions_key(uid)] = {sid: 1.0}
    await _enforce_token_state(_payload(uid, session_id=sid), 1000)


async def test_an_unknown_session_is_refused_even_when_no_slot_is_held(cache):
    uid = uuid4()
    with pytest.raises(HTTPException) as exc:
        await _enforce_token_state(_payload(uid, session_id=str(uuid4())), 1000)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "session_superseded"


async def test_a_token_issued_before_the_stale_mark_asks_for_a_refresh(cache):
    uid = uuid4()
    cache.store[user_stale_key(uid)] = "2000"
    with pytest.raises(HTTPException) as exc:
        await _enforce_token_state(_payload(uid), 1999)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "token_stale"


async def test_a_token_issued_after_the_stale_mark_passes(cache):
    uid = uuid4()
    cache.store[user_stale_key(uid)] = "2000"
    await _enforce_token_state(_payload(uid), 2000)


async def test_a_redis_outage_lets_the_token_through(monkeypatch):
    async def get_redis():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(lib_settings, "get_redis", get_redis)
    await _enforce_token_state(_payload(uuid4(), session_id=str(uuid4())), 1000)


async def test_an_unknown_session_is_refused_when_other_slots_are_held(cache):
    uid = uuid4()
    cache.zsets[active_sessions_key(uid)] = {str(uuid4()): 1.0}
    with pytest.raises(HTTPException) as exc:
        await _enforce_token_state(_payload(uid, session_id=str(uuid4())), 1000)
    assert exc.value.detail["code"] == "session_superseded"

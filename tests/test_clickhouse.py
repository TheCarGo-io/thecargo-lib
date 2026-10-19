import asyncio
import gc

import pytest

from thecargo import clickhouse


class _FakeClient:
    def __init__(self):
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture
def created(monkeypatch) -> list[_FakeClient]:
    clients: list[_FakeClient] = []

    async def get_async_client(**kwargs) -> _FakeClient:
        client = _FakeClient()
        clients.append(client)
        return client

    monkeypatch.setattr(clickhouse.clickhouse_connect, "get_async_client", get_async_client)
    monkeypatch.setattr(clickhouse, "_clients", {})
    monkeypatch.setattr(clickhouse, "_closers", {})
    clickhouse.configure_clickhouse(dsn="clickhouse://localhost")
    return clients


def test_each_event_loop_closes_its_client_when_it_ends(created):
    for _ in range(3):
        asyncio.run(clickhouse.get_client())

    assert len(created) == 3
    assert [client.closed for client in created] == [1, 1, 1]


def test_client_is_shared_and_open_while_its_loop_runs(created):
    async def main() -> None:
        first = await clickhouse.get_client()
        gc.collect()
        await asyncio.sleep(0)
        assert await clickhouse.get_client() is first
        assert first.closed == 0

    asyncio.run(main())

    assert len(created) == 1
    assert created[0].closed == 1


def test_explicit_close_is_not_repeated_when_the_loop_ends(created):
    async def main() -> None:
        await clickhouse.get_client()
        await clickhouse.close_clickhouse()

    asyncio.run(main())

    assert created[0].closed == 1


def test_client_reopened_after_close_is_closed_when_the_loop_ends(created):
    async def main() -> None:
        await clickhouse.get_client()
        await clickhouse.close_clickhouse()
        await clickhouse.get_client()

    asyncio.run(main())

    assert [client.closed for client in created] == [1, 1]

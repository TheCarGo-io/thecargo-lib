import asyncio
import json

from thecargo.middleware.load_shed import LoadShedMiddleware


def _scope(path: str = "/api/v1/things") -> dict:
    return {"type": "http", "method": "GET", "path": path, "headers": []}


async def _receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


class _Sent:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.messages if m["type"] == "http.response.start")

    @property
    def headers(self) -> dict:
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        return {k.decode(): v.decode() for k, v in start["headers"]}

    @property
    def body(self) -> dict:
        return json.loads(b"".join(m.get("body", b"") for m in self.messages if m["type"] == "http.response.body"))


def _blocking_app(release: asyncio.Event):
    async def app(scope, receive, send) -> None:
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    return app


def test_a_request_past_the_limit_is_turned_away_and_the_slot_frees_up():
    async def scenario():
        release = asyncio.Event()
        shed = LoadShedMiddleware(_blocking_app(release), limit=1)
        first = _Sent()
        running = asyncio.create_task(shed(_scope(), _receive, first))
        await asyncio.sleep(0)

        turned_away = _Sent()
        await shed(_scope(), _receive, turned_away)

        release.set()
        await running
        after = _Sent()
        await shed(_scope(), _receive, after)
        return first, turned_away, after, shed.in_flight

    first, turned_away, after, in_flight = asyncio.run(scenario())

    assert turned_away.status == 503
    assert turned_away.headers["retry-after"] == "1"
    assert turned_away.body["code"] == "SERVER_BUSY"
    assert first.status == 200
    assert after.status == 200
    assert in_flight == 0


def test_probes_and_internal_calls_are_never_turned_away():
    async def scenario():
        release = asyncio.Event()
        shed = LoadShedMiddleware(_blocking_app(release), limit=1)
        running = asyncio.create_task(shed(_scope(), _receive, _Sent()))
        await asyncio.sleep(0)

        passed = []
        for path in ("/health/live", "/metrics", "/api/internal/counts"):
            sent = _Sent()
            task = asyncio.create_task(shed(_scope(path), _receive, sent))
            await asyncio.sleep(0)
            passed.append((task, sent))
        release.set()
        await running
        for task, _ in passed:
            await task
        return [sent.status for _, sent in passed]

    assert asyncio.run(scenario()) == [200, 200, 200]


def test_a_failing_request_gives_its_slot_back():
    async def boom(scope, receive, send) -> None:
        raise ValueError("boom")

    async def scenario():
        shed = LoadShedMiddleware(boom, limit=1)
        for _ in range(3):
            try:
                await shed(_scope(), _receive, _Sent())
            except ValueError:
                pass
        return shed.in_flight

    assert asyncio.run(scenario()) == 0

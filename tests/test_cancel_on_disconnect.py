import asyncio

from thecargo.middleware.cancel_on_disconnect import CancelOnDisconnectMiddleware


def _scope(method: str = "GET", path: str = "/things") -> dict:
    return {"type": "http", "method": method, "path": path, "headers": []}


class _Client:
    def __init__(self) -> None:
        self.inbound: asyncio.Queue[dict] = asyncio.Queue()
        self.sent: list[dict] = []

    async def receive(self) -> dict:
        return await self.inbound.get()

    async def send(self, message: dict) -> None:
        self.sent.append(message)

    def disconnect(self) -> None:
        self.inbound.put_nowait({"type": "http.disconnect"})


def _run(coro_factory) -> None:
    asyncio.run(coro_factory())


def test_teardown_is_not_cancelled_after_full_response():
    state = {"cancelled": False, "finished": False}

    async def scenario() -> None:
        client = _Client()

        async def app(scope, receive, send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
            client.disconnect()
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
            state["finished"] = True

        await CancelOnDisconnectMiddleware(app)(_scope(), client.receive, client.send)

    _run(scenario)

    assert state["cancelled"] is False
    assert state["finished"] is True


def test_disconnect_before_response_cancels_and_sends_499():
    state = {"cancelled": False, "sent": []}

    async def scenario() -> None:
        client = _Client()

        async def app(scope, receive, send) -> None:
            client.disconnect()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

        await CancelOnDisconnectMiddleware(app)(_scope(), client.receive, client.send)
        state["sent"] = client.sent

    _run(scenario)

    assert state["cancelled"] is True
    assert [m["type"] for m in state["sent"]] == ["http.response.start", "http.response.body"]
    assert state["sent"][0]["status"] == 499


def test_streaming_response_is_cancelled_mid_stream_without_499():
    state = {"cancelled": False, "sent": []}

    async def scenario() -> None:
        client = _Client()

        async def app(scope, receive, send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"chunk", "more_body": True})
            client.disconnect()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

        await CancelOnDisconnectMiddleware(app)(_scope(), client.receive, client.send)
        state["sent"] = client.sent

    _run(scenario)

    assert state["cancelled"] is True
    assert [m["status"] for m in state["sent"] if m["type"] == "http.response.start"] == [200]


def test_mutating_method_bypasses_cancellation():
    state = {"finished": False}

    async def scenario() -> None:
        client = _Client()

        async def app(scope, receive, send) -> None:
            client.disconnect()
            await asyncio.sleep(0.05)
            state["finished"] = True

        await CancelOnDisconnectMiddleware(app)(_scope(method="POST"), client.receive, client.send)

    _run(scenario)

    assert state["finished"] is True

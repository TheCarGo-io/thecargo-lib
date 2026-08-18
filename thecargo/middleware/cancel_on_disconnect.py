import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)

Message = dict
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

DEFAULT_METHODS = frozenset({"GET", "HEAD"})


def _header(scope: Message, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value.decode("latin-1")
    return None


class CancelOnDisconnectMiddleware:
    def __init__(self, app, methods: Iterable[str] = DEFAULT_METHODS):
        self.app = app
        self.methods = frozenset(m.upper() for m in methods)

    async def __call__(self, scope: Message, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "").upper() not in self.methods:
            await self.app(scope, receive, send)
            return

        queue: asyncio.Queue[Message] = asyncio.Queue()
        disconnected = asyncio.Event()
        started = False
        completed = False

        async def pump() -> None:
            while True:
                message = await receive()
                await queue.put(message)
                if message["type"] == "http.disconnect":
                    disconnected.set()
                    return

        async def buffered_receive() -> Message:
            return await queue.get()

        async def tracking_send(message: Message) -> None:
            nonlocal started, completed
            message_type = message["type"]
            if message_type == "http.response.start":
                started = True
            elif message_type == "http.response.body" and not message.get("more_body", False):
                completed = True
            await send(message)

        pump_task = asyncio.create_task(pump())
        app_task = asyncio.create_task(self.app(scope, buffered_receive, tracking_send))
        watch_task = asyncio.create_task(disconnected.wait())

        try:
            done, _ = await asyncio.wait({app_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
            if app_task in done:
                app_task.result()
                return

            if completed:
                await app_task
                return

            app_task.cancel()
            try:
                await app_task
            except asyncio.CancelledError:
                pass

            logger.info(
                "request cancelled on client disconnect method=%s path=%s request_id=%s",
                scope.get("method"),
                scope.get("path"),
                _header(scope, b"x-request-id"),
            )

            if not started:
                try:
                    await send({"type": "http.response.start", "status": 499, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                except Exception:
                    pass
        finally:
            for task in (pump_task, watch_task):
                if not task.done():
                    task.cancel()

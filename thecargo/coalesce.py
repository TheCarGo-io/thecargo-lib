import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any


class Coalescer:
    """Hand everything queued within `delay` seconds to one `flush` call.

    After-commit bookkeeping opened a session and a transaction per commit: marking an outbox row published cost
    0.7 ms of CPU on a 3.4 ms customer create, and resolving audit labels 0.6 ms on an 8.8 ms shipment create. A busy
    process commits many times a second, so one transaction can carry all of them. `flush` handles its own errors.
    A drain cancelled while it waits, as at shutdown, flushes what it holds before it stops.
    """

    def __init__(self, flush: Callable[[list[Any]], Awaitable[None]], delay: float):
        self._flush = flush
        self._delay = delay
        self._items: list[Any] = []
        self._task: asyncio.Task | None = None

    def add(self, items: Iterable[Any]) -> None:
        loop = asyncio.get_running_loop()
        if self._task is not None and self._task.get_loop() is not loop:
            self._items, self._task = [], None
        self._items.extend(items)
        if self._task is None:
            self._task = loop.create_task(self._drain())

    async def _drain(self) -> None:
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            await asyncio.shield(self._flush(self._take()))
            raise
        await self._flush(self._take())

    def _take(self) -> list[Any]:
        items, self._items, self._task = self._items, [], None
        return items

import json

import pytest
from thecargo.events import consumer as consumer_module


class FakeMessage:
    def __init__(self, routing_key="call.ended", body=None, redelivered=False):
        self.routing_key = routing_key
        self.body = json.dumps(body if body is not None else {"ok": True}).encode()
        self.redelivered = redelivered
        self.acked = False
        self.requeued = False
        self.dropped = False

    async def ack(self):
        self.acked = True

    async def reject(self, requeue=False):
        if requeue:
            self.requeued = True
        else:
            self.dropped = True


class FakeQueue:
    def __init__(self):
        self.callback = None

    async def bind(self, exchange, routing_key):
        return None

    async def consume(self, callback):
        self.callback = callback


class FakeChannel:
    def __init__(self, queue):
        self.queue = queue

    async def set_qos(self, prefetch_count):
        return None

    async def declare_exchange(self, name, kind, durable):
        return object()

    async def declare_queue(self, name, durable):
        return self.queue


class FakeConnection:
    def __init__(self, queue):
        self.queue = queue

    async def channel(self):
        return FakeChannel(self.queue)


async def _start(monkeypatch, handler, **kwargs):
    queue = FakeQueue()

    async def _connect(url):
        return FakeConnection(queue)

    monkeypatch.setattr(consumer_module.aio_pika, "connect_robust", _connect)
    await consumer_module.start_consumer(
        rabbitmq_url="amqp://localhost",
        queue_name="test-queue",
        routing_keys=["call.ended"],
        handler=handler,
        **kwargs,
    )
    return queue


async def _explode(routing_key, body):
    raise RuntimeError("handler is broken")


async def _succeed(routing_key, body):
    return None


@pytest.mark.asyncio
async def test_a_failed_event_is_acknowledged_by_default(monkeypatch):
    queue = await _start(monkeypatch, _explode)
    message = FakeMessage()

    await queue.callback(message)

    assert message.acked is True
    assert message.requeued is False


@pytest.mark.asyncio
async def test_a_queue_that_asked_for_it_gets_the_failed_event_back(monkeypatch):
    queue = await _start(monkeypatch, _explode, requeue_failed=True)
    message = FakeMessage()

    await queue.callback(message)

    assert message.requeued is True
    assert message.acked is False


@pytest.mark.asyncio
async def test_an_event_that_fails_twice_is_dropped_rather_than_spun_on(monkeypatch):
    queue = await _start(monkeypatch, _explode, requeue_failed=True)
    message = FakeMessage(redelivered=True)

    await queue.callback(message)

    assert message.acked is True
    assert message.requeued is False


@pytest.mark.asyncio
async def test_an_event_the_handler_survives_is_acknowledged_either_way(monkeypatch):
    for requeue_failed in (False, True):
        queue = await _start(monkeypatch, _succeed, requeue_failed=requeue_failed)
        message = FakeMessage()

        await queue.callback(message)

        assert message.acked is True


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_does_not_take_the_consumer_down(monkeypatch):
    queue = await _start(monkeypatch, _succeed)
    message = FakeMessage()
    message.body = b"not json"

    await queue.callback(message)

    assert message.acked is True

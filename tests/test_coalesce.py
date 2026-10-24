import asyncio

from thecargo import audit
from thecargo.coalesce import Coalescer
from thecargo.events import outbox


def _recorder() -> tuple[list[list], Coalescer]:
    calls: list[list] = []

    async def flush(items):
        calls.append(items)

    return calls, Coalescer(flush, 0.01)


def test_items_queued_within_the_window_reach_one_flush():
    calls, coalescer = _recorder()

    async def scenario():
        coalescer.add([1])
        coalescer.add([2, 3])
        await asyncio.sleep(0.05)
        coalescer.add([4])
        await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert calls == [[1, 2, 3], [4]]


def test_a_drain_cancelled_while_it_waits_flushes_what_it_holds():
    calls: list[list] = []

    async def flush(items):
        calls.append(items)

    coalescer = Coalescer(flush, 60)

    async def scenario():
        coalescer.add(["a", "b"])
        drain = coalescer._task
        await asyncio.sleep(0)
        drain.cancel()
        await asyncio.gather(drain, return_exceptions=True)

    asyncio.run(scenario())

    assert calls == [["a", "b"]]


def test_a_new_event_loop_gets_its_own_drain():
    calls, coalescer = _recorder()

    async def queue_only():
        coalescer.add(["stale"])

    async def queue_and_wait():
        coalescer.add(["fresh"])
        await asyncio.sleep(0.05)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(queue_only())
    loop.close()
    asyncio.run(queue_and_wait())

    assert calls == [["fresh"]]


def test_outbox_rows_published_together_are_marked_in_one_write(monkeypatch):
    marked: list[list] = []

    async def deliver(routing_key, payload, event_id):
        return None

    async def mark(session_factory, event_ids):
        marked.append(event_ids)

    monkeypatch.setattr(outbox, "_deliver", deliver)
    monkeypatch.setattr(outbox, "_mark_published", mark)
    monkeypatch.setattr(outbox, "MARK_DELAY_SECONDS", 0.01)
    factory = object()

    async def scenario():
        await outbox._publish_one(factory, "e1", "shipment.updated", {})
        await outbox._publish_one(factory, "e2", "customer.created", {})
        await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert marked == [["e1", "e2"]]


def test_a_failed_delivery_queues_no_mark(monkeypatch):
    marked: list[list] = []

    async def deliver(routing_key, payload, event_id):
        raise RuntimeError("RabbitMQ not connected")

    async def mark(session_factory, event_ids):
        marked.append(event_ids)

    monkeypatch.setattr(outbox, "_deliver", deliver)
    monkeypatch.setattr(outbox, "_mark_published", mark)
    monkeypatch.setattr(outbox, "MARK_DELAY_SECONDS", 0.01)

    async def scenario():
        await outbox._publish_one(object(), "e1", "shipment.updated", {})
        await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert marked == []


def test_audit_labels_of_several_commits_resolve_in_one_pass(monkeypatch):
    passes: list[list] = []

    async def resolve_and_publish(session_maker, staged):
        passes.append(staged)

    monkeypatch.setattr(audit, "_resolve_and_publish", resolve_and_publish)
    monkeypatch.setattr(audit, "RESOLVE_DELAY_SECONDS", 0.01)
    maker = object()

    async def scenario():
        audit._resolver(maker).add([{"audit_id": "a"}])
        audit._resolver(maker).add([{"audit_id": "b"}, {"audit_id": "c"}])
        await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert passes == [[{"audit_id": "a"}, {"audit_id": "b"}, {"audit_id": "c"}]]

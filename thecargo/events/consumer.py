import json
import logging
from collections.abc import Callable
from typing import Any

import aio_pika

logger = logging.getLogger(__name__)


async def start_consumer(
    rabbitmq_url: str,
    queue_name: str,
    routing_keys: list[str],
    handler: Callable[[str, dict[str, Any]], Any],
    exchange: str = "thecargo.events",
    requeue_failed: bool = False,
):
    """Consume an exchange's events, acknowledging each one the handler survives.

    `requeue_failed` turns the default at-most-once delivery into at-least-once
    for queues that would rather see an event twice than lose it: a handler that
    raises sends the message back once, and a second failure drops it, so a
    message the handler can never process cannot spin forever. Leave it off for
    handlers whose work is not safe to repeat.
    """
    connection = await aio_pika.connect_robust(rabbitmq_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)

    ex = await channel.declare_exchange(exchange, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await channel.declare_queue(queue_name, durable=True)

    for key in routing_keys:
        await queue.bind(ex, routing_key=key)

    async def _process(message: aio_pika.abc.AbstractIncomingMessage):
        try:
            body = json.loads(message.body.decode())
            await handler(message.routing_key, body)
        except Exception:
            logger.exception("Failed to process message: %s", message.routing_key)
            if requeue_failed and not message.redelivered:
                await message.reject(requeue=True)
                return
            await message.ack()
            return
        await message.ack()

    await queue.consume(_process)
    logger.info("Consumer started: queue=%s, keys=%s", queue_name, routing_keys)
    return connection

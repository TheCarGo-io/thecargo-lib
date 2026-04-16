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
):
    connection = await aio_pika.connect_robust(rabbitmq_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)

    ex = await channel.declare_exchange(exchange, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await channel.declare_queue(queue_name, durable=True)

    for key in routing_keys:
        await queue.bind(ex, routing_key=key)

    async def _process(message: aio_pika.abc.AbstractIncomingMessage):
        async with message.process():
            try:
                body = json.loads(message.body.decode())
                await handler(message.routing_key, body)
            except Exception:
                logger.exception("Failed to process message: %s", message.routing_key)

    await queue.consume(_process)
    logger.info("Consumer started: queue=%s, keys=%s", queue_name, routing_keys)
    return connection

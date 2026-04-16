import json
import logging

import aio_pika

logger = logging.getLogger(__name__)

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_channel: aio_pika.abc.AbstractChannel | None = None


async def connect(rabbitmq_url: str):
    global _connection, _channel
    try:
        _connection = await aio_pika.connect_robust(rabbitmq_url)
        _channel = await _connection.channel()
        await _channel.declare_exchange("thecargo.events", aio_pika.ExchangeType.TOPIC, durable=True)
        await _channel.declare_exchange("thecargo.rpc", aio_pika.ExchangeType.DIRECT, durable=True)
        logger.info("RabbitMQ connected")
    except Exception as e:
        logger.warning("RabbitMQ not available: %s. Events disabled.", e)
        _connection = None
        _channel = None


async def disconnect():
    global _connection, _channel
    if _connection:
        await _connection.close()
    _connection = None
    _channel = None
    logger.info("RabbitMQ disconnected")


async def publish(routing_key: str, body: dict, exchange: str = "thecargo.events"):
    if not _channel:
        logger.warning("RabbitMQ not connected, skipping publish: %s", routing_key)
        return

    ex = await _channel.get_exchange(exchange)
    await ex.publish(
        aio_pika.Message(
            body=json.dumps(body, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=routing_key,
    )

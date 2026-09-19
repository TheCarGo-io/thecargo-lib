from __future__ import annotations

import asyncio
import logging
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.asyncclient import AsyncClient

from thecargo.utils.url import redact_credentials

logger = logging.getLogger(__name__)

_config: dict[str, Any] | None = None
_clients: dict[asyncio.AbstractEventLoop, AsyncClient] = {}


def configure_clickhouse(
    *,
    dsn: str,
    pool_size: int = 8,
    connect_timeout: int = 5,
    send_receive_timeout: int = 60,
    settings: dict[str, Any] | None = None,
) -> None:
    global _config
    _config = dict(
        dsn=dsn,
        settings=settings,
        connector_limit=pool_size,
        connector_limit_per_host=pool_size,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )


async def init_clickhouse(**kwargs: Any) -> None:
    configure_clickhouse(**kwargs)
    client = await get_client()
    try:
        await client.command("SELECT 1")
    except Exception:
        await close_clickhouse()
        logger.exception("ClickHouse init failed (dsn=%s)", redact_credentials(kwargs["dsn"]))
        raise
    logger.info("ClickHouse connected: %s", redact_credentials(kwargs["dsn"]))


async def get_client() -> AsyncClient:
    if _config is None:
        raise RuntimeError("ClickHouse not configured — call init_clickhouse() in lifespan")
    for stale in [loop for loop in _clients if loop.is_closed()]:
        _clients.pop(stale, None)
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None:
        client = await clickhouse_connect.get_async_client(**_config)
        _clients[loop] = client
    return client


async def close_clickhouse() -> None:
    client = _clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.close()
        logger.info("ClickHouse connection closed")

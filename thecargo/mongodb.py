from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from beanie import Document, init_beanie
from bson.codec_options import TypeEncoder, TypeRegistry
from bson.decimal128 import Decimal128
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db_name: str = ""


class _DecimalEncoder(TypeEncoder):
    python_type = Decimal

    def transform_python(self, value: Decimal) -> Decimal128:
        return Decimal128(value)


_TYPE_REGISTRY = TypeRegistry([_DecimalEncoder()])


def _client_kwargs(extra: dict[str, Any]) -> dict[str, Any]:
    return {"type_registry": _TYPE_REGISTRY, **extra}


async def init_mongo(
    *,
    uri: str,
    document_models: Sequence[type[Document]],
    db_name: str | None = None,
    max_pool_size: int = 50,
    min_pool_size: int = 5,
    server_selection_timeout_ms: int = 5_000,
    connect_timeout_ms: int = 10_000,
    max_idle_time_ms: int = 45_000,
) -> None:
    global _client, _db_name

    if _client is not None:
        logger.debug("MongoDB already initialised — skipping re-init")
        return

    client = AsyncIOMotorClient(
        uri,
        **_client_kwargs(
            dict(
                maxPoolSize=max_pool_size,
                minPoolSize=min_pool_size,
                serverSelectionTimeoutMS=server_selection_timeout_ms,
                connectTimeoutMS=connect_timeout_ms,
                maxIdleTimeMS=max_idle_time_ms,
            )
        ),
    )
    default_db = client.get_default_database()
    resolved_db_name = db_name or (default_db.name if default_db is not None else None)
    if not resolved_db_name:
        client.close()
        raise RuntimeError("MongoDB database name not specified — embed it in MONGODB_URI or pass db_name")

    try:
        await client.admin.command("ping")
        await init_beanie(database=client[resolved_db_name], document_models=list(document_models))
    except Exception:
        client.close()
        logger.exception("MongoDB init failed (uri=%s db=%s)", _redact(uri), resolved_db_name)
        raise

    _client = client
    _db_name = resolved_db_name
    logger.info(
        "MongoDB connected: %s/%s (%d documents)",
        _redact(uri),
        resolved_db_name,
        len(document_models),
    )


async def close_mongo() -> None:
    global _client
    if _client is None:
        return
    _client.close()
    _client = None
    logger.info("MongoDB connection closed")


def get_client() -> AsyncIOMotorClient:
    if _client is None:
        raise RuntimeError("MongoDB not initialised — call init_mongo() in lifespan")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[_db_name]


def _redact(uri: str) -> str:
    if "@" not in uri:
        return uri
    scheme, _, rest = uri.partition("://")
    _, _, host_part = rest.partition("@")
    return f"{scheme}://***@{host_part}"

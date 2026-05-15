"""Async MongoDB initialisation for FastAPI services.

Mirrors the contract of :mod:`thecargo.storage`: each service calls
:func:`init_mongo` from inside its lifespan with its own URI, database
name, and Beanie document classes. The shared library owns the client
singleton and pool tuning so individual services don't reinvent
connection lifecycle code.

Why fail-fast on init failure (unlike ``init_storage`` which warns and
disables): MongoDB-backed flows here are critical-path durable archives
for inbound webhooks. A service that came up with a broken Mongo
connection would silently lose payloads — better to refuse to start
and let the orchestrator retry.

Runtime errors raised by individual queries are *not* fatal; callers
decide whether to surface them to the HTTP layer (e.g. webhook
receiver returns 5xx so the upstream provider retries) or fall back
to a degraded path.
"""

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
    """Driver-level codec that maps Python ``Decimal`` onto BSON ``Decimal128``.

    Third-party SDKs (Stripe is the worst offender, but Authorize.net and
    Central Dispatch hand back ``Decimal`` too) leak ``Decimal`` instances
    deep inside webhook payloads we archive verbatim. Native BSON has no
    encoder for ``Decimal``, so without this codec every archive write
    that contains one fails with ``InvalidDocument`` and the upstream
    delivery is lost. Registering at the client level fixes the issue
    once for every collection (Beanie + raw motor) instead of asking
    every webhook receiver to remember to walk-and-convert before
    writing.
    """

    python_type = Decimal

    def transform_python(self, value: Decimal) -> Decimal128:
        return Decimal128(value)


_TYPE_REGISTRY = TypeRegistry([_DecimalEncoder()])


def _client_kwargs(extra: dict[str, Any]) -> dict[str, Any]:
    """Merge the shared codec into per-call client tuning so every connection picks it up."""
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
    """Open the pool, register Beanie documents, verify the server is reachable.

    The database is taken from ``db_name`` when supplied, otherwise
    from the URI path (``mongodb://host/<db>``) — matching the convention
    of putting DB selection in the URI itself. Either form must yield
    a non-empty name; otherwise we refuse to start.

    Idempotent on repeat calls with the same configuration so that a
    misordered import or a duplicated lifespan entry doesn't double-
    open a pool. The ``ping`` round-trip is what makes init fail fast:
    motor lazily resolves the topology, so without an explicit probe a
    bad URI would only surface on the first query.
    """
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
    """Drain the pool on shutdown.

    Safe to call when init was never run (e.g. a service that failed to
    boot for an unrelated reason) — the lifespan finalizer can call us
    unconditionally without guarding.
    """
    global _client
    if _client is None:
        return
    _client.close()
    _client = None
    logger.info("MongoDB connection closed")


def get_client() -> AsyncIOMotorClient:
    """Return the singleton client or raise if init was never run.

    Preferred over reaching for the module-level ``_client`` directly —
    keeps the "must call init_mongo first" contract in one place.
    """
    if _client is None:
        raise RuntimeError("MongoDB not initialised — call init_mongo() in lifespan")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """Return the bound database handle for collection-level access.

    Beanie handles the typed-document case; this helper exists for
    callers that need a raw collection (e.g. bulk operations, admin
    one-off queries) without going through a Document subclass.
    """
    return get_client()[_db_name]


def _redact(uri: str) -> str:
    """Strip credentials from a MongoDB URI before it lands in logs."""
    if "@" not in uri:
        return uri
    scheme, _, rest = uri.partition("://")
    _, _, host_part = rest.partition("@")
    return f"{scheme}://***@{host_part}"

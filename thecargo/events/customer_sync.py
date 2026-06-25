import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from thecargo.events.consumer import start_consumer
from thecargo.models.customer_replica import CustomerReplica
from thecargo.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

CUSTOMER_FIELDS = (
    "first_name",
    "last_name",
    "company",
    "company_type",
    "email",
    "phone",
    "secondary_phone",
    "company_phone",
)
_PHONE_FIELDS = ("phone", "secondary_phone", "company_phone")


def _values(data: dict) -> dict:
    out = {k: data.get(k) for k in CUSTOMER_FIELDS}
    for k in _PHONE_FIELDS:
        if out.get(k):
            out[k] = normalize_phone(out[k]) or out[k]
    return out


async def _handle_customer_created(session: AsyncSession, data: dict):
    if not data.get("organization_id"):
        return
    existing = await session.execute(select(CustomerReplica).where(CustomerReplica.id == UUID(data["id"])))
    if existing.scalar_one_or_none():
        return
    session.add(
        CustomerReplica(
            id=UUID(data["id"]),
            organization_id=UUID(data["organization_id"]),
            **_values(data),
        )
    )


async def _handle_customer_updated(session: AsyncSession, data: dict):
    result = await session.execute(select(CustomerReplica).where(CustomerReplica.id == UUID(data["id"])))
    replica = result.scalar_one_or_none()
    if not replica:
        return await _handle_customer_created(session, data)
    values = _values(data)
    for field in CUSTOMER_FIELDS:
        if field in data:
            setattr(replica, field, values[field])


async def _handle_customer_deleted(session: AsyncSession, data: dict):
    result = await session.execute(select(CustomerReplica).where(CustomerReplica.id == UUID(data["id"])))
    replica = result.scalar_one_or_none()
    if replica:
        await session.delete(replica)


HANDLERS = {
    "customer.created": _handle_customer_created,
    "customer.updated": _handle_customer_updated,
    "customer.deleted": _handle_customer_deleted,
}


async def _dispatch(session_factory: async_sessionmaker, routing_key: str, data: dict):
    handler = HANDLERS.get(routing_key)
    if not handler:
        return
    async with session_factory() as session:
        await handler(session, data)
        await session.commit()


async def start_customer_sync_consumer(rabbitmq_url: str, session_factory: async_sessionmaker, service_name: str):
    async def dispatch(routing_key: str, data: dict):
        await _dispatch(session_factory, routing_key, data)

    return await start_consumer(
        rabbitmq_url=rabbitmq_url,
        queue_name=f"{service_name}-customer-sync",
        routing_keys=list(HANDLERS.keys()),
        handler=dispatch,
    )


async def bootstrap_customers(session_factory: async_sessionmaker, shipment_service_url: str, service_secret: str):
    import httpx
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    url = f"{shipment_service_url}/api/internal/customers"
    headers = {"X-Service-Secret": service_secret}
    page_size = 1000

    async def _store(rows: list[dict]) -> int:
        records = [
            {"id": UUID(c["id"]), "organization_id": UUID(c["organization_id"]), **_values(c)}
            for c in rows
            if c.get("organization_id")
        ]
        if not records:
            return 0
        async with session_factory() as session:
            stmt = pg_insert(CustomerReplica).values(records).on_conflict_do_nothing(index_elements=["id"])
            await session.execute(stmt)
            await session.commit()
        return len(records)

    async with session_factory() as session:
        seeded = (await session.execute(select(CustomerReplica.id).limit(1))).first() is not None

    total = 0
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if seeded:
                resp = await client.get(url, params={"limit": 5000, "with_count": "false"}, headers=headers)
                resp.raise_for_status()
                total += await _store(resp.json().get("results") or [])
            else:
                after_id = "00000000-0000-0000-0000-000000000000"
                while True:
                    params: dict = {"limit": page_size, "with_count": "false", "after_id": after_id}
                    resp = await client.get(url, params=params, headers=headers)
                    resp.raise_for_status()
                    page = resp.json().get("results") or []
                    if not page:
                        break
                    total += await _store(page)
                    last_id = page[-1]["id"]
                    if last_id == after_id or len(page) < page_size:
                        break
                    after_id = last_id
    except Exception:
        logger.warning("Failed to sync customers from shipment service", exc_info=True)
        return

    if total:
        logger.info("Synced %d customers from shipment service", total)

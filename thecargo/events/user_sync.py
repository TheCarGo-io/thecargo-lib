import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from thecargo.events.consumer import start_consumer
from thecargo.models.user_replica import UserReplica

logger = logging.getLogger(__name__)

USER_FIELDS = ("email", "first_name", "last_name", "phone", "ext", "picture", "is_active")
REQUEUE_DELAY_SECONDS = 5


def _organization_id(value) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def _handle_user_created(session: AsyncSession, data: dict):
    organization_id = _organization_id(data.get("organization_id"))
    if organization_id is None:
        return
    existing = await session.execute(select(UserReplica).where(UserReplica.id == UUID(data["id"])))
    if existing.scalar_one_or_none():
        return
    replica = UserReplica(
        id=UUID(data["id"]),
        organization_id=organization_id,
        **{k: data.get(k) for k in USER_FIELDS},
    )
    session.add(replica)


async def _handle_user_updated(session: AsyncSession, data: dict):
    result = await session.execute(select(UserReplica).where(UserReplica.id == UUID(data["id"])))
    replica = result.scalar_one_or_none()
    if not replica:
        return await _handle_user_created(session, data)
    for field in USER_FIELDS:
        if field in data:
            setattr(replica, field, data[field])


async def _handle_user_organization_changed(session: AsyncSession, data: dict):
    left = _organization_id(data.get("from_organization_id"))
    joined = _organization_id(data.get("to_organization_id"))
    if left is None or joined is None:
        return
    await session.execute(
        update(UserReplica)
        .where(UserReplica.id == UUID(data["id"]), UserReplica.organization_id == left)
        .values(organization_id=joined)
    )


async def _handle_user_deleted(session: AsyncSession, data: dict):
    result = await session.execute(select(UserReplica).where(UserReplica.id == UUID(data["id"])))
    replica = result.scalar_one_or_none()
    if replica:
        await session.delete(replica)


HANDLERS = {
    "user.created": _handle_user_created,
    "user.updated": _handle_user_updated,
    "user.organization_changed": _handle_user_organization_changed,
    "user.deleted": _handle_user_deleted,
}


async def _dispatch(session_factory: async_sessionmaker, routing_key: str, data: dict):
    handler = HANDLERS.get(routing_key)
    if not handler:
        return
    async with session_factory() as session:
        await handler(session, data)
        await session.commit()


async def start_user_sync_consumer(rabbitmq_url: str, session_factory: async_sessionmaker, service_name: str):
    async def dispatch(routing_key: str, data: dict):
        await _dispatch(session_factory, routing_key, data)

    return await start_consumer(
        rabbitmq_url=rabbitmq_url,
        queue_name=f"{service_name}-user-sync",
        routing_keys=list(HANDLERS.keys()),
        handler=dispatch,
        requeue_failed=True,
        requeue_delay=REQUEUE_DELAY_SECONDS,
    )


async def bootstrap_users(session_factory: async_sessionmaker, auth_service_url: str, service_secret: str):
    import httpx
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async with session_factory() as session:
        seeded = (await session.execute(select(UserReplica.id).limit(1))).first() is not None
    if seeded:
        return

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{auth_service_url}/api/internal/users",
                headers={"X-Service-Secret": service_secret},
            )
            resp.raise_for_status()
            users = resp.json()
    except Exception:
        logger.warning("Failed to bootstrap users from auth service", exc_info=True)
        return

    records = [
        {
            "id": UUID(u["id"]),
            "organization_id": UUID(u["organization_id"]),
            **{k: u.get(k) for k in USER_FIELDS},
        }
        for u in users
        if u.get("organization_id")
    ]
    if not records:
        return
    async with session_factory() as session:
        await session.execute(pg_insert(UserReplica).values(records).on_conflict_do_nothing(index_elements=["id"]))
        await session.commit()
    logger.info("Bootstrapped %d users from auth service", len(records))

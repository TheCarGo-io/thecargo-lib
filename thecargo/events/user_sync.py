import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from thecargo.events.consumer import start_consumer
from thecargo.models.user_replica import UserReplica

logger = logging.getLogger(__name__)

USER_FIELDS = ("email", "first_name", "last_name", "phone", "ext", "picture", "is_active")


async def _handle_user_created(session: AsyncSession, data: dict):
    existing = await session.execute(select(UserReplica).where(UserReplica.id == UUID(data["id"])))
    if existing.scalar_one_or_none():
        return
    replica = UserReplica(
        id=UUID(data["id"]),
        organization_id=UUID(data["organization_id"]),
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


async def _handle_user_deleted(session: AsyncSession, data: dict):
    result = await session.execute(select(UserReplica).where(UserReplica.id == UUID(data["id"])))
    replica = result.scalar_one_or_none()
    if replica:
        await session.delete(replica)


HANDLERS = {
    "user.created": _handle_user_created,
    "user.updated": _handle_user_updated,
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
    )


async def bootstrap_users(session_factory: async_sessionmaker, auth_service_url: str, service_secret: str):
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{auth_service_url}/api/internal/users",
                headers={"X-Service-Secret": service_secret},
            )
            resp.raise_for_status()
            users = resp.json()
    except Exception:
        logger.warning("Failed to bootstrap users from auth service")
        return

    async with session_factory() as session:
        existing = await session.execute(select(UserReplica.id))
        existing_ids = {row for row in existing.scalars().all()}

        count = 0
        for u in users:
            uid = UUID(u["id"])
            if uid in existing_ids:
                continue
            session.add(
                UserReplica(
                    id=uid,
                    organization_id=UUID(u["organization_id"]),
                    **{k: u.get(k) for k in USER_FIELDS},
                )
            )
            count += 1

        await session.commit()
        if count:
            logger.info("Bootstrapped %d users from auth service", count)

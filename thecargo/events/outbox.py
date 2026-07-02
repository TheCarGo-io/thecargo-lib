from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import JSON, Integer, String, Text, delete, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from thecargo.events import publisher
from thecargo.models.base import BaseModel
from thecargo.utils.timezone import now_ny

logger = logging.getLogger(__name__)

_OUTBOX_KEY = "_outbox_pending"

RELAY_GRACE_SECONDS = 30
RELAY_BATCH = 200
RELAY_MAX_ATTEMPTS = 10
RELAY_INTERVAL_SECONDS = 5.0
CLEANUP_RETENTION_DAYS = 7
CLEANUP_EVERY_TICKS = 720


def _publisher_ready() -> bool:
    channel = publisher._channel
    return channel is not None and not channel.is_closed


async def _deliver(routing_key: str, payload: dict) -> None:
    if not _publisher_ready():
        raise RuntimeError("RabbitMQ not connected")
    await publisher.publish(routing_key, payload)


class OutboxEvent(BaseModel):
    __tablename__ = "outbox_events"

    routing_key: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)


def publish_event(db: AsyncSession, routing_key: str, payload: dict) -> None:
    row = OutboxEvent(routing_key=routing_key, payload=payload, status="pending")
    db.add(row)
    db.sync_session.info.setdefault(_OUTBOX_KEY, []).append(row)


async def _publish_one(session_factory, event_id, routing_key: str, payload: dict) -> None:
    try:
        await _deliver(routing_key, payload)
    except Exception as exc:
        logger.warning("outbox immediate publish failed (relay will retry): %s %s", routing_key, exc)
        return
    try:
        async with session_factory() as session:
            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id == event_id)
                .values(status="published", published_at=now_ny(), attempts=OutboxEvent.attempts + 1)
            )
            await session.commit()
    except Exception:
        logger.exception("outbox mark-published failed for %s (relay will reconcile)", event_id)


def register_outbox_listeners(session_class, session_factory) -> None:

    @event.listens_for(session_class, "after_commit")
    def _publish(session):
        staged = session.info.pop(_OUTBOX_KEY, [])
        if not staged:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("outbox publish deferred to relay: no running loop (count=%d)", len(staged))
            return
        for row in staged:
            loop.create_task(_publish_one(session_factory, row.id, row.routing_key, row.payload))

    @event.listens_for(session_class, "after_rollback")
    def _drop(session):
        session.info.pop(_OUTBOX_KEY, None)


async def relay_once(session_factory) -> int:
    if not _publisher_ready():
        return 0
    cutoff = now_ny() - timedelta(seconds=RELAY_GRACE_SECONDS)
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.status == "pending",
                        OutboxEvent.created_at < cutoff,
                        OutboxEvent.attempts < RELAY_MAX_ATTEMPTS,
                    )
                    .order_by(OutboxEvent.created_at)
                    .limit(RELAY_BATCH)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0
        published = 0
        for row in rows:
            try:
                await _deliver(row.routing_key, row.payload)
            except Exception as exc:
                row.attempts += 1
                row.last_error = str(exc)[:500]
                continue
            row.status = "published"
            row.published_at = now_ny()
            row.attempts += 1
            published += 1
        await session.commit()
        return published


async def cleanup_published(session_factory, older_than_days: int = CLEANUP_RETENTION_DAYS) -> int:
    cutoff = now_ny() - timedelta(days=older_than_days)
    async with session_factory() as session:
        result = await session.execute(
            delete(OutboxEvent).where(OutboxEvent.status == "published", OutboxEvent.published_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0


async def run_outbox_relay(
    session_factory,
    *,
    interval: float = RELAY_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    logger.info("outbox relay loop started (interval=%.1fs)", interval)
    tick = 0
    while stop_event is None or not stop_event.is_set():
        try:
            await relay_once(session_factory)
            if tick % CLEANUP_EVERY_TICKS == 0:
                deleted = await cleanup_published(session_factory)
                if deleted:
                    logger.info("outbox cleanup deleted %d published rows", deleted)
        except Exception:
            logger.exception("outbox relay tick failed")
        tick += 1
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            else:
                await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            pass
    logger.info("outbox relay loop stopped")

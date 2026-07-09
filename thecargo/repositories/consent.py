from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.events.outbox import publish_event
from thecargo.models.consent_record import (
    ConsentChannel,
    ConsentRecord,
    ConsentScope,
    ConsentSource,
    ConsentStatus,
)
from thecargo.utils.phone import normalize_phone

CONSENT_EVENT_ROUTING_KEY = "consent.recorded"


class ConsentRepository:
    def __init__(self, db: AsyncSession, organization_id: UUID):
        self.db = db
        self.org_id = organization_id

    async def history(self, customer_number: str, limit: int = 200) -> list[ConsentRecord]:
        normalized = normalize_phone(customer_number) or customer_number
        stmt = (
            select(ConsentRecord)
            .where(
                ConsentRecord.organization_id == self.org_id,
                ConsentRecord.customer_number == normalized,
            )
            .order_by(ConsentRecord.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def latest_states(
        self,
        customer_number: str,
    ) -> dict[tuple[str, str, str | None], ConsentRecord]:
        normalized = normalize_phone(customer_number) or customer_number
        stmt = (
            select(ConsentRecord)
            .distinct(ConsentRecord.channel, ConsentRecord.scope, ConsentRecord.line_number)
            .where(
                ConsentRecord.organization_id == self.org_id,
                ConsentRecord.customer_number == normalized,
            )
            .order_by(
                ConsentRecord.channel,
                ConsentRecord.scope,
                ConsentRecord.line_number,
                ConsentRecord.created_at.desc(),
            )
        )
        result = await self.db.execute(stmt)
        latest: dict[tuple[str, str, str | None], ConsentRecord] = {}
        for row in result.scalars().all():
            latest[(row.channel, row.scope, row.line_number)] = row
        return latest

    async def record(
        self,
        *,
        customer_number: str,
        channel: ConsentChannel,
        status: ConsentStatus,
        source: ConsentSource,
        scope: ConsentScope = ConsentScope.GLOBAL,
        line_number: str | None = None,
        source_detail: str | None = None,
        created_by_user_id: UUID | None = None,
        reason: str | None = None,
    ) -> ConsentRecord:
        row = ConsentRecord(
            organization_id=self.org_id,
            customer_number=customer_number,
            channel=channel.value,
            scope=scope.value,
            line_number=line_number,
            status=status.value,
            source=source.value,
            source_detail=source_detail,
            created_by_user_id=created_by_user_id,
            reason=reason,
        )
        self.db.add(row)
        await self.db.flush()

        publish_event(
            self.db,
            CONSENT_EVENT_ROUTING_KEY,
            {
                "consent_id": str(row.id),
                "organization_id": str(row.organization_id),
                "customer_number": row.customer_number,
                "channel": row.channel,
                "scope": row.scope,
                "line_number": row.line_number,
                "status": row.status,
                "source": row.source,
                "source_detail": row.source_detail,
                "created_by_user_id": str(row.created_by_user_id) if row.created_by_user_id else None,
                "reason": row.reason,
                "created_at": row.created_at.isoformat() if row.created_at is not None else None,
            },
        )
        return row

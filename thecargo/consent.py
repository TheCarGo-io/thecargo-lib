from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from thecargo.models.consent_record import (
    ConsentChannel,
    ConsentRecord,
    ConsentScope,
    ConsentSource,
    ConsentStatus,
    SendType,
)
from thecargo.utils.phone import normalize_phone

__all__ = [
    "Decision",
    "ContactabilityResult",
    "check_contactability",
    "check_contactability_sync",
    "load_consent_state",
    "load_consent_state_sync",
    "evaluate",
    "ConsentChannel",
    "ConsentScope",
    "ConsentStatus",
    "ConsentSource",
    "SendType",
]


class Decision(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True)
class ContactabilityResult:
    decision: Decision
    reason: str | None = None
    status: str | None = None
    source: str | None = None
    source_detail: str | None = None
    line_number: str | None = None
    recorded_at: datetime | None = None
    reason_record_id: UUID | None = None

    @property
    def is_allow(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def is_warn(self) -> bool:
        return self.decision is Decision.WARN

    @property
    def is_block(self) -> bool:
        return self.decision is Decision.BLOCK


_ALLOW = ContactabilityResult(decision=Decision.ALLOW)


async def load_consent_state(
    db: AsyncSession,
    organization_id: UUID,
    customer_number: str,
) -> list[ConsentRecord]:
    normalized = normalize_phone(customer_number) or customer_number
    stmt = (
        select(ConsentRecord)
        .where(
            ConsentRecord.organization_id == organization_id,
            ConsentRecord.customer_number == normalized,
        )
        .order_by(ConsentRecord.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _latest_by_bucket(records: Iterable[ConsentRecord]) -> dict[tuple[str, str, str | None], ConsentRecord]:
    out: dict[tuple[str, str, str | None], ConsentRecord] = {}
    for row in records:
        key = (row.channel, row.scope, row.line_number)
        prev = out.get(key)
        if prev is None or row.created_at >= prev.created_at:
            out[key] = row
    return out


def _pick_effective(
    records: Iterable[ConsentRecord],
    channel: ConsentChannel,
    our_line: str | None,
) -> ConsentRecord | None:
    latest = _latest_by_bucket(records)
    candidates: list[ConsentRecord] = []
    global_row = latest.get((channel.value, ConsentScope.GLOBAL.value, None))
    if global_row is not None and global_row.status != ConsentStatus.ALLOWED.value:
        candidates.append(global_row)
    if our_line is not None:
        exact = latest.get((channel.value, ConsentScope.LINE.value, our_line))
        if exact is not None and exact.status != ConsentStatus.ALLOWED.value:
            candidates.append(exact)
        for (ch, scope, ln), row in latest.items():
            if ch != channel.value or scope != ConsentScope.LINE.value:
                continue
            if ln is None and row.status != ConsentStatus.ALLOWED.value:
                candidates.append(row)
    other_line_blocks = [
        row
        for (ch, scope, ln), row in latest.items()
        if ch == channel.value
        and scope == ConsentScope.LINE.value
        and ln is not None
        and ln != our_line
        and row.status != ConsentStatus.ALLOWED.value
    ]
    if not candidates and not other_line_blocks:
        return None
    if candidates:
        return max(candidates, key=lambda r: r.created_at)
    return max(other_line_blocks, key=lambda r: r.created_at)


def _wrong_number_row(records: Iterable[ConsentRecord]) -> ConsentRecord | None:
    latest = _latest_by_bucket(records)
    row = latest.get((ConsentChannel.CALL.value, ConsentScope.GLOBAL.value, None))
    text_row = latest.get((ConsentChannel.TEXT.value, ConsentScope.GLOBAL.value, None))
    candidates = [r for r in (row, text_row) if r is not None and r.status == ConsentStatus.WRONG_NUMBER.value]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.created_at)


def evaluate(
    records: Iterable[ConsentRecord],
    channel: ConsentChannel,
    our_line: str | None,
    send_type: SendType,
) -> ContactabilityResult:
    records = list(records)
    if not records:
        return _ALLOW

    wrong = _wrong_number_row(records)
    if wrong is not None:
        return ContactabilityResult(
            decision=Decision.BLOCK,
            reason="wrong_number",
            status=wrong.status,
            source=wrong.source,
            source_detail=wrong.source_detail,
            line_number=wrong.line_number,
            recorded_at=wrong.created_at,
            reason_record_id=wrong.id,
        )

    effective = _pick_effective(records, channel, our_line)
    if effective is None:
        return _ALLOW

    status = effective.status
    scope = effective.scope
    row_line = effective.line_number

    if channel is ConsentChannel.CALL and status == ConsentStatus.DO_NOT_CALL.value:
        return _block(effective, reason="do_not_call")

    if channel is ConsentChannel.TEXT and status == ConsentStatus.DO_NOT_TEXT.value:
        if scope == ConsentScope.GLOBAL.value:
            return _block(effective, reason="do_not_text_global")
        if row_line is None:
            return _block(effective, reason="do_not_text_legacy_any_line")
        if our_line is not None and row_line == our_line:
            return _block(effective, reason="do_not_text_same_line")
        if send_type in (SendType.MASS, SendType.AUTOMATED):
            return _block(effective, reason="do_not_text_other_line_bulk")
        return _warn(effective, reason="do_not_text_other_line_manual")

    return _ALLOW


def _block(row: ConsentRecord, reason: str) -> ContactabilityResult:
    return ContactabilityResult(
        decision=Decision.BLOCK,
        reason=reason,
        status=row.status,
        source=row.source,
        source_detail=row.source_detail,
        line_number=row.line_number,
        recorded_at=row.created_at,
        reason_record_id=row.id,
    )


def _warn(row: ConsentRecord, reason: str) -> ContactabilityResult:
    return ContactabilityResult(
        decision=Decision.WARN,
        reason=reason,
        status=row.status,
        source=row.source,
        source_detail=row.source_detail,
        line_number=row.line_number,
        recorded_at=row.created_at,
        reason_record_id=row.id,
    )


async def check_contactability(
    db: AsyncSession,
    *,
    organization_id: UUID,
    customer_number: str,
    our_line: str | None,
    channel: ConsentChannel,
    send_type: SendType,
    cache: dict | None = None,
) -> ContactabilityResult:
    normalized_customer = normalize_phone(customer_number) or customer_number
    normalized_line = normalize_phone(our_line) if our_line else None

    if cache is not None:
        cache_key = ("consent_state", str(organization_id), normalized_customer)
        records = cache.get(cache_key)
        if records is None:
            records = await load_consent_state(db, organization_id, normalized_customer)
            cache[cache_key] = records
    else:
        records = await load_consent_state(db, organization_id, normalized_customer)

    return evaluate(records, channel=channel, our_line=normalized_line, send_type=send_type)


def load_consent_state_sync(
    db: Session,
    organization_id: UUID,
    customer_number: str,
) -> list[ConsentRecord]:
    normalized = normalize_phone(customer_number) or customer_number
    stmt = (
        select(ConsentRecord)
        .where(
            ConsentRecord.organization_id == organization_id,
            ConsentRecord.customer_number == normalized,
        )
        .order_by(ConsentRecord.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())


def check_contactability_sync(
    db: Session,
    *,
    organization_id: UUID,
    customer_number: str,
    our_line: str | None,
    channel: ConsentChannel,
    send_type: SendType,
) -> ContactabilityResult:
    normalized_customer = normalize_phone(customer_number) or customer_number
    normalized_line = normalize_phone(our_line) if our_line else None
    records = load_consent_state_sync(db, organization_id, normalized_customer)
    return evaluate(records, channel=channel, our_line=normalized_line, send_type=send_type)

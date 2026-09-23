from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from thecargo.clickhouse import get_client
from thecargo.dependencies._settings import get_redis
from thecargo.utils.timezone import utc_now

logger = logging.getLogger(__name__)

TABLE = "webhook_events"
DEDUP_TTL_SECONDS = 7 * 24 * 3600

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    source          LowCardinality(String),
    event_id        String,
    event_type      LowCardinality(String),
    status          LowCardinality(String),
    organization_id Nullable(UUID),
    received_at     DateTime64(3, 'UTC'),
    event_time      Nullable(DateTime64(3, 'UTC')),
    processed_at    Nullable(DateTime64(3, 'UTC')),
    headers         String CODEC(ZSTD(3)),
    body            String CODEC(ZSTD(3)),
    body_size_bytes UInt32,
    last_error      String,
    subscription_id String,
    extra           String CODEC(ZSTD(3)),
    version         UInt32,
    sg_message_id   String MATERIALIZED if(source = 'sendgrid', JSONExtractString(body, 'sg_message_id'), ''),
    INDEX idx_org organization_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_event_id event_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_sg sg_message_id TYPE ngrambf_v1(4, 8192, 3, 0) GRANULARITY 4
) ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(received_at)
ORDER BY (source, received_at, event_id)
"""

COLUMNS = (
    "source",
    "event_id",
    "event_type",
    "status",
    "organization_id",
    "received_at",
    "event_time",
    "processed_at",
    "headers",
    "body",
    "body_size_bytes",
    "last_error",
    "subscription_id",
    "extra",
    "version",
)
SELECT_COLUMNS = ", ".join(COLUMNS)
EXTRA_KEYS = ("merchant_id", "api_version", "livemode", "loadboard_id", "action", "metadata", "user_id", "rc_call_id")
_COLUMN_OF = {"error": "last_error"}


def _uuid_or_none(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _loads(raw: str) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


@dataclass(slots=True)
class WebhookRow:
    source: str
    event_id: str
    event_type: str = ""
    status: str = "received"
    organization_id: UUID | None = None
    received_at: datetime = field(default_factory=utc_now)
    event_time: datetime | None = None
    processed_at: datetime | None = None
    headers: dict[str, Any] = field(default_factory=dict)
    body: Any = field(default_factory=dict)
    body_size_bytes: int = 0
    last_error: str | None = None
    subscription_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        self.organization_id = _uuid_or_none(self.organization_id)

    def values(self) -> list[Any]:
        return [
            self.source,
            self.event_id,
            self.event_type or "",
            self.status or "received",
            self.organization_id,
            self.received_at,
            self.event_time,
            self.processed_at,
            _dumps(self.headers or {}),
            _dumps(self.body if self.body is not None else {}),
            int(self.body_size_bytes or 0),
            self.last_error or "",
            self.subscription_id or "",
            _dumps(self.extra or {}),
            int(self.version),
        ]

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> WebhookRow:
        extra = {key: doc[key] for key in EXTRA_KEYS if doc.get(key) not in (None, "", {}, False)}
        return cls(
            source=doc.get("source") or "",
            event_id=str(doc.get("event_id") or doc.get("_id") or ""),
            event_type=str(doc.get("event_type") or doc.get("action") or ""),
            status=doc.get("status") or "received",
            organization_id=doc.get("organization_id"),
            received_at=_aware(doc.get("received_at")) or utc_now(),
            event_time=_aware(doc.get("event_time")),
            processed_at=_aware(doc.get("processed_at")),
            headers=doc.get("headers") or {},
            body=doc.get("body") if doc.get("body") is not None else {},
            body_size_bytes=doc.get("body_size_bytes") or 0,
            last_error=doc.get("last_error") or doc.get("error"),
            subscription_id=doc.get("subscription_id"),
            extra=extra,
        )

    @classmethod
    def from_values(cls, values: tuple[Any, ...]) -> WebhookRow:
        data = dict(zip(COLUMNS, values, strict=True))
        for name in ("received_at", "event_time", "processed_at"):
            data[name] = _aware(data[name])
        data["headers"] = _loads(data["headers"])
        data["body"] = _loads(data["body"])
        data["extra"] = _loads(data["extra"])
        data["last_error"] = data["last_error"] or None
        data["subscription_id"] = data["subscription_id"] or None
        return cls(**data)

    def changed(self, **changes: Any) -> WebhookRow:
        extra = {**self.extra, **changes.pop("extra", {})}
        return replace(self, extra=extra, version=self.version + 1, **changes)


async def ensure_table() -> None:
    client = await get_client()
    await client.command(DDL)


async def is_new(source: str, event_id: str) -> bool:
    try:
        redis = await get_redis()
        return bool(await redis.set(f"webhook:seen:{source}:{event_id}", "1", nx=True, ex=DEDUP_TTL_SECONDS))
    except Exception:
        logger.warning("webhook dedup unavailable; treating %s/%s as new", source, event_id, exc_info=True)
        return True


async def insert(row: WebhookRow, **settings: Any) -> bool:
    try:
        client = await get_client()
        await client.insert(TABLE, [row.values()], column_names=COLUMNS, settings=settings or None)
        return True
    except Exception:
        logger.exception("webhook archive insert failed: %s/%s", row.source, row.event_id)
        return False


async def insert_many(rows: list[WebhookRow], **settings: Any) -> None:
    if not rows:
        return
    client = await get_client()
    await client.insert(TABLE, [row.values() for row in rows], column_names=COLUMNS, settings=settings or None)


async def fetch(source: str | None, event_id: str, organization_id: UUID | str | None = None) -> WebhookRow | None:
    params: dict[str, Any] = {"event_id": event_id}
    where = "event_id = {event_id:String}"
    if source is not None:
        where += " AND source = {source:String}"
        params["source"] = source
    if organization_id is not None:
        where += " AND organization_id = {org:UUID}"
        params["org"] = _uuid_or_none(organization_id)
    rows = await query(f"WHERE {where} ORDER BY version DESC LIMIT 1", params)
    return rows[0] if rows else None


async def query(clause: str, params: dict[str, Any] | None = None) -> list[WebhookRow]:
    client = await get_client()
    result = await client.query(f"SELECT {SELECT_COLUMNS} FROM {TABLE} FINAL {clause}", parameters=params)
    return [WebhookRow.from_values(values) for values in result.result_rows]


async def count(clause: str, params: dict[str, Any] | None = None) -> int:
    client = await get_client()
    result = await client.query(f"SELECT count() FROM {TABLE} FINAL {clause}", parameters=params)
    return int(result.result_rows[0][0]) if result.result_rows else 0


async def restamp(
    source: str | None,
    event_id: str,
    organization_id: UUID | str | None = None,
    *,
    row: WebhookRow | None = None,
    **changes: Any,
) -> WebhookRow | None:
    """Write the row again with the changes on it; ``row`` skips the read when the caller still holds it.

    A row written moments ago is still in the async-insert buffer and cannot be read back yet.
    """
    row = row or await fetch(source, event_id, organization_id)
    if row is None:
        logger.warning("webhook archive restamp skipped, row not visible yet: %s/%s", source, event_id)
        return None
    updated = row.changed(**changes)
    await insert(updated)
    return updated


async def store(doc: dict[str, Any]) -> WebhookRow:
    row = WebhookRow.from_document(doc)
    await insert(row)
    return row


async def stamp(
    source: str | None,
    event_id: str,
    organization_id: UUID | str | None = None,
    *,
    row: WebhookRow | None = None,
    **changes: Any,
) -> WebhookRow | None:
    columns = {_COLUMN_OF.get(name, name): value for name, value in changes.items()}
    return await restamp(
        source, event_id, organization_id, row=row, **{k: v for k, v in columns.items() if k in COLUMNS or k == "extra"}
    )


async def purge(organization_id: UUID | str) -> int:
    params = {"org": _uuid_or_none(organization_id)}
    deleted = await count("WHERE organization_id = {org:UUID}", params)
    await purge_organization(organization_id)
    return deleted


async def purge_organization(organization_id: UUID | str) -> None:
    client = await get_client()
    await client.command(
        f"DELETE FROM {TABLE} WHERE organization_id = {{org:UUID}}",
        parameters={"org": _uuid_or_none(organization_id)},
    )

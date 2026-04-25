"""Service-internal audit-log router used by the admin dashboard.

Each service mounts this router with its own ``get_db`` so admin can
list/inspect audit rows from any service without a direct DB connection.
The router is service-auth gated, so only callers presenting the shared
``SERVICE_SECRET_KEY`` (admin) can hit it.
"""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.dependencies.service_auth import verify_service_auth
from thecargo.models.audit_log import AuditLog


class AuditLogItem(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    actor_id: UUID | None = None
    actor_email: str | None = None
    service: str | None = None
    resource: str
    resource_id: str
    resource_label: str | None = None
    action: str
    changed_fields: list[str] | None = None
    # Legacy rows (from pre-listener era) occasionally stored arrays here,
    # so accept either shape rather than 500 on read.
    old_data: dict | list | None = None
    new_data: dict | list | None = None
    request_id: UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


def make_audit_internal_router(get_db: Callable) -> APIRouter:
    """Router factory — bind to the caller service's session dependency."""

    router = APIRouter(
        prefix="/api/internal/audit-logs",
        tags=["internal-audit"],
        dependencies=[Depends(verify_service_auth)],
        include_in_schema=False,
    )

    @router.get("", response_model=Page[AuditLogItem])
    async def list_logs(
        organization_id: UUID | None = None,
        resource: str | None = None,
        resource_id: str | None = None,
        actor_id: UUID | None = None,
        action: str | None = None,
        request_id: UUID | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        db: AsyncSession = Depends(get_db),
    ):
        query = select(AuditLog)
        if organization_id is not None:
            query = query.where(AuditLog.organization_id == organization_id)
        if resource is not None:
            query = query.where(AuditLog.resource == resource)
        if resource_id is not None:
            query = query.where(AuditLog.resource_id == resource_id)
        if actor_id is not None:
            query = query.where(AuditLog.actor_id == actor_id)
        if action is not None:
            query = query.where(AuditLog.action == action)
        if request_id is not None:
            query = query.where(AuditLog.request_id == request_id)
        if from_time is not None:
            query = query.where(AuditLog.created_at >= from_time)
        if to_time is not None:
            query = query.where(AuditLog.created_at <= to_time)

        query = query.order_by(AuditLog.created_at.desc())
        return await paginate(db, query)

    @router.get("/{log_id}", response_model=AuditLogItem)
    async def get_log(log_id: UUID, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(AuditLog).where(AuditLog.id == log_id))).scalar_one_or_none()
        if not row:
            raise HTTPException(400, "Audit log not found")
        return row

    return router

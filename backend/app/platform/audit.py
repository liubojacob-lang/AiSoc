"""Audit trail service. Append-only: nothing in the codebase updates or
deletes audit_logs; even this module has no such path."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.db.base import DEFAULT_TENANT_ID
from app.models.ops import AuditLog


async def audit(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    actor_id: uuid.UUID | None = None,
    actor_type: str = "user",
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
    request: Request | None = None,
) -> None:
    ip = None
    ua = None
    if request is not None:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent", "")[:255]
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            detail=detail or {},
            ip=ip,
            user_agent=ua,
            request_id=request_id_var.get(),
        )
    )
    # caller commits within its business transaction so audit + state change
    # are atomic — exactly what we want for integrity.


__all__ = ["audit"]

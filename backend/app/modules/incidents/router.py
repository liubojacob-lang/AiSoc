"""Incidents HTTP routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require
from app.db.session import get_session
from app.models.enums import Permission
from app.modules.incidents import schemas, service
from app.platform.audit import audit

router = APIRouter()


@router.post("", response_model=schemas.IncidentOut, status_code=201)
async def create_incident(
    body: schemas.IncidentCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.INCIDENT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    incident = await service.create_incident(
        session, principal.tenant_id, data=body, opened_by=principal.user_id
    )
    await audit(
        session,
        action="incident.create",
        resource_type="incident",
        resource_id=incident.id,
        actor_id=principal.user_id,
        tenant_id=principal.tenant_id,
        request=request,
        detail={"title": incident.title, "severity": incident.severity},
    )
    await session.commit()
    return incident


@router.get("", response_model=list[schemas.IncidentOut])
async def list_incidents(
    status: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require(Permission.INCIDENT_READ)),
    session: AsyncSession = Depends(get_session),
):
    rows, _total = await service.list_incidents(
        session,
        principal.tenant_id,
        status=status,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return rows


@router.get("/{incident_id}", response_model=schemas.IncidentOut)
async def get_incident(
    incident_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.INCIDENT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.get_incident(session, principal.tenant_id, incident_id)


@router.post("/{incident_id}/transition", response_model=schemas.IncidentOut)
async def transition_incident(
    incident_id: uuid.UUID,
    body: schemas.IncidentTransition,
    request: Request,
    principal: Principal = Depends(require(Permission.INCIDENT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    incident = await service.transition(
        session,
        principal.tenant_id,
        incident_id,
        to=body.to_status,
        reason=body.reason,
        close_summary=body.close_summary,
        actor=principal.user_id,
    )
    await audit(
        session,
        action="incident.transition",
        resource_type="incident",
        resource_id=incident.id,
        actor_id=principal.user_id,
        tenant_id=principal.tenant_id,
        request=request,
        detail={"to": body.to_status, "reason": body.reason[:200]},
    )
    await session.commit()
    return incident


# ---------- tasks ----------


@router.post("/{incident_id}/tasks", response_model=schemas.TaskOut, status_code=201)
async def create_task(
    incident_id: uuid.UUID,
    body: schemas.TaskCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.INCIDENT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    task = await service.create_task(
        session, principal.tenant_id, incident_id, data=body, created_by=principal.user_id
    )
    await audit(
        session,
        action="task.create",
        resource_type="task",
        resource_id=task.id,
        actor_id=principal.user_id,
        tenant_id=principal.tenant_id,
        request=request,
    )
    await session.commit()
    return task


@router.get("/{incident_id}/tasks", response_model=list[schemas.TaskOut])
async def list_tasks(
    incident_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.INCIDENT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_tasks(session, principal.tenant_id, incident_id)


@router.post("/tasks/{task_id}/transition", response_model=schemas.TaskOut)
async def transition_task(
    task_id: uuid.UUID,
    body: schemas.TaskTransition,
    request: Request,
    principal: Principal = Depends(require(Permission.INCIDENT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    task = await service.transition_task(
        session, principal.tenant_id, task_id, to=body.to_status, reason=body.reason
    )
    await audit(
        session,
        action="task.transition",
        resource_type="task",
        resource_id=task.id,
        actor_id=principal.user_id,
        tenant_id=principal.tenant_id,
        request=request,
        detail={"to": body.to_status, "reason": body.reason},
    )
    await session.commit()
    return task


# ---------- comments ----------


@router.post("/{incident_id}/comments", response_model=schemas.CommentOut, status_code=201)
async def add_comment(
    incident_id: uuid.UUID,
    body: schemas.CommentCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.INCIDENT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    comment = await service.add_comment(
        session, principal.tenant_id, incident_id, body=body.body, author=principal.user_id
    )
    await audit(
        session,
        action="incident.comment",
        resource_type="incident",
        resource_id=incident_id,
        actor_id=principal.user_id,
        tenant_id=principal.tenant_id,
        request=request,
    )
    await session.commit()
    return comment


@router.get("/{incident_id}/comments", response_model=list[schemas.CommentOut])
async def list_comments(
    incident_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.INCIDENT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_comments(session, principal.tenant_id, incident_id)

"""Incidents service: PICERL state machine, tasks, comments."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.base import utcnow
from app.models.alerts import Alert
from app.models.enums import (
    INCIDENT_TRANSITIONS,
    TASK_TRANSITIONS,
    IncidentStatus,
    TaskStatus,
)
from app.models.incidents import Comment, Incident, IncidentAlert, Task


async def create_incident(
    session: AsyncSession, tenant_id: uuid.UUID, *, data, opened_by: uuid.UUID
) -> Incident:
    incident = Incident(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        severity=data.severity,
        status=IncidentStatus.NEW,
        source_alert_id=data.source_alert_id,
        opened_by=opened_by,
    )
    session.add(incident)
    await session.flush()
    if data.source_alert_id is not None:
        alert = await session.get(Alert, data.source_alert_id)
        if alert is not None and alert.tenant_id == tenant_id:
            session.add(
                IncidentAlert(incident_id=incident.id, alert_id=alert.id, linked_by=opened_by)
            )
    await session.flush()
    return incident


async def get_incident(
    session: AsyncSession, tenant_id: uuid.UUID, incident_id: uuid.UUID
) -> Incident:
    incident = await session.get(Incident, incident_id)
    if incident is None or incident.tenant_id != tenant_id:
        raise NotFound("incident", incident_id)
    return incident


async def list_incidents(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Incident], int]:
    limit = max(1, min(limit, 100))
    conds = [Incident.tenant_id == tenant_id]
    if status:
        conds.append(Incident.status == status)
    if severity:
        conds.append(Incident.severity == severity)
    total = (
        await session.execute(select(func.count()).select_from(Incident).where(*conds))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(Incident)
                .where(*conds)
                .order_by(Incident.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def transition(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    *,
    to: str,
    reason: str,
    close_summary: str | None,
    actor: uuid.UUID,
) -> Incident:
    incident = await get_incident(session, tenant_id, incident_id)
    current = IncidentStatus(incident.status)
    try:
        target = IncidentStatus(to)
    except ValueError as e:
        raise ValidationFailed(f"unknown incident status: {to}") from e
    if target not in INCIDENT_TRANSITIONS.get(current, set()):
        raise Conflict(
            "incident.illegal_transition",
            f"cannot move incident from {current} to {target}",
        )
    if target == IncidentStatus.CLOSED and not close_summary:
        raise ValidationFailed("close_summary is required when closing an incident")
    if target == IncidentStatus.REOPENED:
        incident.reopened_count += 1

    incident.status = target
    if target == IncidentStatus.CLOSED:
        incident.closed_at = utcnow()
        incident.close_summary = close_summary
    else:
        incident.closed_at = None
    await session.flush()
    return incident


# ---------- tasks ----------


async def create_task(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    *,
    data,
    created_by: uuid.UUID,
) -> Task:
    await get_incident(session, tenant_id, incident_id)  # existence check
    task = Task(
        tenant_id=tenant_id,
        incident_id=incident_id,
        title=data.title,
        description=data.description,
        assignee=data.assignee,
        due_at=data.due_at,
        created_by=created_by,
        status=TaskStatus.TODO,
    )
    session.add(task)
    await session.flush()
    return task


async def list_tasks(
    session: AsyncSession, tenant_id: uuid.UUID, incident_id: uuid.UUID
) -> list[Task]:
    await get_incident(session, tenant_id, incident_id)
    rows = (
        (
            await session.execute(
                select(Task).where(Task.incident_id == incident_id).order_by(Task.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def transition_task(
    session: AsyncSession, tenant_id: uuid.UUID, task_id: uuid.UUID, *, to: str, reason: str | None
) -> Task:
    task = await session.get(Task, task_id)
    if task is None or task.tenant_id != tenant_id:
        raise NotFound("task", task_id)
    target = TaskStatus(to)
    current = TaskStatus(task.status)
    if target not in TASK_TRANSITIONS.get(current, set()):
        raise Conflict("task.illegal_transition", f"cannot move task from {current} to {target}")
    if target in (TaskStatus.BLOCKED, TaskStatus.CANCELLED) and not reason:
        raise ValidationFailed(f"reason is required when moving a task to {target}")
    task.status = target
    task.blocked_reason = reason if target == TaskStatus.BLOCKED else None
    if target == TaskStatus.DONE:
        task.completed_at = utcnow()
    await session.flush()
    return task


# ---------- comments ----------


async def add_comment(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    *,
    body: str,
    author: uuid.UUID,
) -> Comment:
    await get_incident(session, tenant_id, incident_id)
    comment = Comment(tenant_id=tenant_id, incident_id=incident_id, body=body, author_id=author)
    session.add(comment)
    await session.flush()
    return comment


async def list_comments(
    session: AsyncSession, tenant_id: uuid.UUID, incident_id: uuid.UUID
) -> list[Comment]:
    await get_incident(session, tenant_id, incident_id)
    rows = (
        (
            await session.execute(
                select(Comment)
                .where(Comment.incident_id == incident_id)
                .order_by(Comment.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# ---------- metrics support ----------


async def mttr_hours(session: AsyncSession, tenant_id: uuid.UUID) -> float | None:
    """Median closed-incident duration in hours."""
    rows = (
        await session.execute(
            select(Incident.created_at, Incident.closed_at).where(
                Incident.tenant_id == tenant_id,
                Incident.closed_at.is_not(None),
            )
        )
    ).all()
    if not rows:
        return None
    durations = sorted((c - o).total_seconds() / 3600 for o, c in rows)
    n = len(durations)
    mid = n // 2
    med = durations[mid] if n % 2 else (durations[mid - 1] + durations[mid]) / 2
    return round(med, 2)

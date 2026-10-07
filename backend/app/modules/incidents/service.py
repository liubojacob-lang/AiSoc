"""Incidents service: PICERL state machine, tasks, comments."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.engine import CursorResult
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

    # 新事件通知（in-app + 可选 webhook），失败不影响创建
    try:
        from app.platform.notify import notify_incident_created

        await notify_incident_created(
            session, tenant_id, incident_id=incident.id,
            title=incident.title, severity=incident.severity, opened_by=opened_by,
        )
    except Exception as e:  # noqa: BLE001
        from app.core.logging import get_logger

        get_logger("incidents").warning("notify_failed", incident_id=str(incident.id), error=str(e))
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

    # CAS：仅当状态仍是读取值时才迁移，防并发双重流转
    from sqlalchemy import update

    res = await session.execute(
        update(Incident)
        .where(Incident.id == incident.id, Incident.status == current)
        .values(
            status=target,
            updated_at=utcnow(),
            closed_at=utcnow() if target == IncidentStatus.CLOSED else None,
            close_summary=close_summary if target == IncidentStatus.CLOSED else None,
            reopened_count=incident.reopened_count + (1 if target == IncidentStatus.REOPENED else 0),
        )
    )
    if cast(CursorResult[Any], res).rowcount == 0:
        raise Conflict(
            "incident.concurrent_modification",
            f"incident state changed concurrently (was {current})",
        )
    await session.refresh(incident)
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

    # CAS：防并发双重流转（与告警/事件一致）
    from sqlalchemy import update

    res = await session.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == current)
        .values(
            status=target,
            updated_at=utcnow(),
            blocked_reason=reason if target == TaskStatus.BLOCKED else None,
            completed_at=utcnow() if target == TaskStatus.DONE else None,
        )
    )
    if cast(CursorResult[Any], res).rowcount == 0:
        raise Conflict("task.concurrent_modification", f"task state changed concurrently (was {current})")
    await session.refresh(task)
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
    durations = sorted(
        (c - o).total_seconds() / 3600
        for o, c in rows
        if o is not None and c is not None
    )
    n = len(durations)
    mid = n // 2
    med = durations[mid] if n % 2 else (durations[mid - 1] + durations[mid]) / 2
    return round(med, 2)

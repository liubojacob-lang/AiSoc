"""Platform HTTP routes: notifications (in-app inbox)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require
from app.db.base import utcnow
from app.db.session import get_session
from app.models.enums import Permission
from app.models.ops import Notification

router = APIRouter()


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    body: str
    link_path: str | None
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


@router.get("", response_model=list[NotificationOut])
async def my_notifications(
    limit: int = 30,
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(Notification)
            .where(Notification.recipient_id == principal.user_id)
            .order_by(Notification.created_at.desc())
            .limit(min(limit, 100))
        )
    ).scalars().all()
    return [
        NotificationOut(
            id=n.id, type=n.type, title=n.title, body=n.body,
            link_path=n.link_path, read_at=n.read_at, created_at=n.created_at,
        )
        for n in rows
    ]


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    count = (
        await session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.recipient_id == principal.user_id,
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()
    return UnreadCount(unread=count)


@router.post("/read-all")
async def read_all(
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        update(Notification)
        .where(
            Notification.recipient_id == principal.user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    )
    await session.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(Notification, notification_id)
    if row is None or row.recipient_id != principal.user_id:
        from app.core.errors import NotFound

        raise NotFound("notification", notification_id)
    if row.read_at is None:
        row.read_at = utcnow()
        await session.commit()
    return {"ok": True}

"""Notification service: in-app notifications (+ optional webhook fan-out).

Webhook URL is read from ``system_configs['notification.webhook_url']`` when
present; delivery is fire-and-forget (5s timeout, errors logged, never raise)
so a broken receiver cannot affect the business path.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.ops import Notification, SystemConfig

log = get_logger("notify")


async def notify_roles(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    roles: list[str],
    type_: str,
    title: str,
    body: str = "",
    link_path: str | None = None,
    exclude_user: uuid.UUID | None = None,
    cap: int = 20,
) -> int:
    """Create in-app notifications for all active users holding any of roles."""
    from app.models.identity import Role, User, UserRole

    rows = (
        await session.execute(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                Role.code.in_(roles),
            )
            .limit(cap)
        )
    ).scalars().all()
    count = 0
    for uid in rows:
        if exclude_user is not None and uid == exclude_user:
            continue
        session.add(
            Notification(
                tenant_id=tenant_id, recipient_id=uid, type=type_,
                title=title, body=body, link_path=link_path,
            )
        )
        count += 1
    return count


async def _webhook_url(session: AsyncSession) -> str | None:
    row = await session.get(SystemConfig, "notification.webhook_url")
    if row is None:
        return None
    url = row.value.get("url") if isinstance(row.value, dict) else None
    return url or None


async def notify_webhook(session: AsyncSession, event: dict) -> None:
    """Fire-and-forget webhook fan-out. Never raises."""
    import httpx

    url = await _webhook_url(session)
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=event, headers={"X-AISOC-Event": str(event.get("type", ""))})
    except Exception as e:  # noqa: BLE001
        log.warning("webhook_delivery_failed", url=url, error=str(e))


async def notify_triage_result(
    session: AsyncSession, tenant_id: uuid.UUID, *, alert_id: uuid.UUID,
    alert_title: str, classification: str, severity: str, triggered_by: uuid.UUID | None,
) -> None:
    """Alert triaged: critical/true-positive wakes the analysts; the user who
    triggered a manual/retry triage always gets a completion notice."""
    needs_attention = classification in ("true_positive", "suspicious") and severity in ("high", "critical")
    if needs_attention:
        await notify_roles(
            session, tenant_id, roles=["analyst", "admin"],
            type_="alert.triaged",
            title=f"[{severity.upper()}] 告警研判：{alert_title[:80]}",
            body=f"AI 判定 {classification}（置信度见详情），请确认。",
            link_path=f"/alerts?focus={alert_id}",
            exclude_user=triggered_by,
        )
    if triggered_by is not None:
        session.add(
            Notification(
                tenant_id=tenant_id, recipient_id=triggered_by, type="alert.triage_done",
                title=f"研判完成：{alert_title[:80]}",
                body=f"AI 结论 {classification}，点击查看报告与证据链。",
                link_path=f"/alerts?focus={alert_id}",
            )
        )
    await notify_webhook(
        session,
        {"type": "alert.triaged", "alert_id": str(alert_id), "title": alert_title,
         "classification": classification, "severity": severity},
    )


async def notify_incident_created(
    session: AsyncSession, tenant_id: uuid.UUID, *, incident_id: uuid.UUID,
    title: str, severity: str, opened_by: uuid.UUID,
) -> None:
    await notify_roles(
        session, tenant_id, roles=["analyst", "admin"],
        type_="incident.created",
        title=f"新事件（{severity}）：{title[:80]}",
        body="事件已创建，请认领并跟进处置。",
        link_path=f"/incidents?focus={incident_id}",
        exclude_user=opened_by,
    )
    await notify_webhook(
        session,
        {"type": "incident.created", "incident_id": str(incident_id), "title": title, "severity": severity},
    )

"""Action approval HTTP routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require
from app.db.session import get_session
from app.models.enums import Permission
from app.modules.actions import schemas, service
from app.platform.audit import audit

router = APIRouter()


@router.post("", response_model=schemas.ActionOut, status_code=201)
async def propose_action(
    alert_id: uuid.UUID,
    body: schemas.ActionPropose,
    request: Request,
    principal: Principal = Depends(require(Permission.ALERT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    row = await service.propose(
        session, principal.tenant_id, alert_id,
        actor=principal.user_id, action=body.action, target=body.target,
        reason=body.reason, triage_result_id=body.triage_result_id,
    )
    await audit(
        session, action="action.propose", resource_type="action_approval",
        resource_id=row.id, actor_id=principal.user_id,
        tenant_id=principal.tenant_id, request=request,
        detail={"action": row.action, "target": row.target},
    )
    await session.commit()
    # 提交后通知管理员进行 L2（以及提交者自己的记录）
    from app.platform.notify import notify_roles

    try:
        await notify_roles(
            session, principal.tenant_id, roles=["admin"],
            type_="action.proposed",
            title=f"处置审批待 L2：{row.action} → {row.target or '-'}",
            body=body.reason[:200],
            link_path="/approvals",
            exclude_user=principal.user_id,
        )
        await session.commit()
    except Exception as e:  # noqa: BLE001 - 通知失败不影响审批流
        import structlog
        structlog.get_logger("actions").warning("notify_failed", error=str(e))
    return row


@router.get("", response_model=list[schemas.ActionOut])
async def list_actions(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_actions(session, principal.tenant_id, status=status, limit=limit)


@router.get("/{action_id}", response_model=schemas.ActionOut)
async def get_action(
    action_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.get(session, principal.tenant_id, action_id)


@router.post("/{action_id}/approve", response_model=schemas.ActionOut)
async def approve_action(
    action_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.ALERT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    is_admin = "admin" in principal.roles
    row = await service.approve(
        session, principal.tenant_id, action_id, actor=principal.user_id, is_admin=is_admin
    )
    await audit(
        session,
        action="action.approve_l1" if row.status == "approved_l1" else "action.approve_l2",
        resource_type="action_approval", resource_id=row.id,
        actor_id=principal.user_id, tenant_id=principal.tenant_id, request=request,
    )
    await session.commit()
    return row


@router.post("/{action_id}/reject", response_model=schemas.ActionOut)
async def reject_action(
    action_id: uuid.UUID,
    body: schemas.RejectBody,
    request: Request,
    principal: Principal = Depends(require(Permission.ALERT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    row = await service.reject(
        session, principal.tenant_id, action_id, actor=principal.user_id, reason=body.reason
    )
    await audit(
        session, action="action.reject", resource_type="action_approval", resource_id=row.id,
        actor_id=principal.user_id, tenant_id=principal.tenant_id, request=request,
        detail={"reason": body.reason[:200]},
    )
    await session.commit()
    return row


@router.post("/{action_id}/cancel", response_model=schemas.ActionOut)
async def cancel_action(
    action_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.ALERT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    row = await service.cancel(session, principal.tenant_id, action_id, actor=principal.user_id)
    await audit(
        session, action="action.cancel", resource_type="action_approval", resource_id=row.id,
        actor_id=principal.user_id, tenant_id=principal.tenant_id, request=request,
    )
    await session.commit()
    return row


@router.post("/{action_id}/execute", response_model=schemas.ActionOut)
async def execute_action_route(
    action_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.SYSTEM_MANAGE)),
    session: AsyncSession = Depends(get_session),
):
    row = await service.execute(
        session, principal.tenant_id, action_id, actor=principal.user_id
    )
    await audit(
        session, action="action.execute", resource_type="action_approval", resource_id=row.id,
        actor_id=principal.user_id, tenant_id=principal.tenant_id, request=request,
        detail={"status": row.status, "mode": row.execution_mode},
    )
    await session.commit()
    return row

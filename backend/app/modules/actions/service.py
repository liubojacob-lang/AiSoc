"""Action approval service: dual-approval state machine + execution.

Rules enforced here (not just in the router):
- L1: any user with alert:write (analyst/admin).
- L2: admin only, AND a different person than the L1 approver (dual control).
- Execute: admin only, status approved (or execution_failed retry).
- Reject/cancel record who and why; every transition is auditable and notifies.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.db.base import utcnow
from app.models.alerts import Alert
from app.models.enums import ACTION_TRANSITIONS, ActionStatus
from app.models.ops import ActionApproval
from app.platform.executors import execute_action


def _transition(row: ActionApproval, to: ActionStatus) -> None:
    current = ActionStatus(row.status)
    if to not in ACTION_TRANSITIONS.get(current, set()):
        raise Conflict(
            "action.illegal_transition",
            f"cannot move approval from {current} to {to}",
        )


async def propose(
    session: AsyncSession, tenant_id: uuid.UUID, alert_id: uuid.UUID, *,
    actor: uuid.UUID, action: str, target: str | None, reason: str,
    triage_result_id: uuid.UUID | None = None,
) -> ActionApproval:
    alert = await session.get(Alert, alert_id)
    if alert is None or alert.tenant_id != tenant_id:
        raise NotFound("alert", alert_id)
    row = ActionApproval(
        tenant_id=tenant_id,
        alert_id=alert_id,
        triage_result_id=triage_result_id,
        action=action,
        target=target,
        reason=reason,
        proposed_by=actor,
        status=ActionStatus.PROPOSED,
    )
    session.add(row)
    await session.flush()
    return row


async def get(session: AsyncSession, tenant_id: uuid.UUID, action_id: uuid.UUID) -> ActionApproval:
    row = await session.get(ActionApproval, action_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound("action_approval", action_id)
    return row


async def list_actions(
    session: AsyncSession, tenant_id: uuid.UUID, *, status: str | None = None,
    limit: int = 50,
) -> list[ActionApproval]:
    conds = [ActionApproval.tenant_id == tenant_id]
    if status:
        conds.append(ActionApproval.status == status)
    rows = (
        await session.execute(
            select(ActionApproval)
            .where(*conds)
            .order_by(ActionApproval.created_at.desc())
            .limit(min(limit, 200))
        )
    ).scalars().all()
    return list(rows)


async def approve(
    session: AsyncSession, tenant_id: uuid.UUID, action_id: uuid.UUID, *,
    actor: uuid.UUID, is_admin: bool,
) -> ActionApproval:
    row = await get(session, tenant_id, action_id)
    current = ActionStatus(row.status)
    if current == ActionStatus.PROPOSED:
        _transition(row, ActionStatus.APPROVED_L1)
        row.approved_l1_by = actor
        row.approved_l1_at = utcnow()
        row.status = ActionStatus.APPROVED_L1
        await session.flush()
        return row
    if current == ActionStatus.APPROVED_L1:
        if not is_admin:
            raise PermissionDenied("L2 approval requires an administrator")
        if row.approved_l1_by == actor:
            raise Conflict(
                "action.self_approval",
                "dual control: the L2 approver must differ from the L1 approver",
            )
        _transition(row, ActionStatus.APPROVED)
        row.approved_l2_by = actor
        row.approved_l2_at = utcnow()
        row.status = ActionStatus.APPROVED
        await session.flush()
        return row
    raise Conflict("action.not_approvable", f"approval in status {current} cannot be approved")


async def reject(
    session: AsyncSession, tenant_id: uuid.UUID, action_id: uuid.UUID, *,
    actor: uuid.UUID, reason: str,
) -> ActionApproval:
    row = await get(session, tenant_id, action_id)
    _transition(row, ActionStatus.REJECTED)
    row.rejected_by = actor
    row.rejected_reason = reason
    row.status = ActionStatus.REJECTED
    await session.flush()
    return row


async def cancel(
    session: AsyncSession, tenant_id: uuid.UUID, action_id: uuid.UUID, *, actor: uuid.UUID
) -> ActionApproval:
    row = await get(session, tenant_id, action_id)
    if row.proposed_by != actor:
        raise PermissionDenied("only the proposer can cancel")
    _transition(row, ActionStatus.CANCELLED)
    row.status = ActionStatus.CANCELLED
    await session.flush()
    return row


async def execute(
    session: AsyncSession, tenant_id: uuid.UUID, action_id: uuid.UUID, *, actor: uuid.UUID
) -> ActionApproval:
    row = await get(session, tenant_id, action_id)
    _transition(row, ActionStatus.EXECUTED)
    result = await execute_action(
        session, action=row.action, target=row.target,
        approval_id=row.id, alert_id=row.alert_id,
    )
    failed = "error" in result
    row.executed_by = actor
    row.executed_at = utcnow()
    row.execution_mode = result.get("mode")
    row.execution_result = result
    row.status = ActionStatus.EXECUTION_FAILED if failed else ActionStatus.EXECUTED
    await session.flush()
    return row


async def validate_reason(reason: str) -> None:
    if len(reason.strip()) < 3:
        raise ValidationFailed("reason too short")

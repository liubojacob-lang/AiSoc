"""Alerts service: ingestion (idempotent), queries, human confirmation,
status-machine enforcement, triage pipeline orchestration."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.models.ai import AIRun, AIStep, AIToolCall
from app.models.alerts import Alert, AlertFeedback, TriageResult
from app.models.enums import (
    ALERT_TRANSITIONS,
    AlertStatus,
    HumanVerdict,
)
from app.modules.ai.agent import AgentRunner
from app.modules.ai.prompts import PROMPT_VERSION
from app.modules.ai.schemas import TriagedVerdict
from app.modules.alerts.schemas import (
    AlertDetail,
    AlertIngest,
    AlertOut,
    AlertPage,
    TriageReportOut,
    TriageResultOut,
    TriageStepOut,
)

# ---------- ingestion ----------


async def ingest(
    session: AsyncSession, tenant_id: uuid.UUID, payload: AlertIngest
) -> tuple[Alert, bool]:
    """Returns (alert, created). Duplicate (source, external_id) → existing."""

    values = dict(
        tenant_id=tenant_id,
        source=payload.source,
        external_id=payload.external_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        alert_type=payload.alert_type,
        src_ip=payload.src_ip,
        dst_ip=payload.dst_ip,
        src_host=payload.src_host,
        user_account=payload.user_account,
        raw_payload=payload.raw,
        occurred_at=payload.occurred_at or utcnow(),
        status=AlertStatus.NEW,
    )
    existing = (
        await session.execute(
            select(Alert).where(
                Alert.source == payload.source, Alert.external_id == payload.external_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    alert = Alert(**values)
    session.add(alert)
    await session.flush()
    return alert, True


# ---------- queries ----------


def _to_out(alert: Alert) -> AlertOut:
    return AlertOut(
        id=alert.id,
        source=alert.source,
        external_id=alert.external_id,
        title=alert.title,
        description=alert.description,
        severity=alert.severity,
        status=alert.status,
        alert_type=alert.alert_type,
        src_ip=str(alert.src_ip) if alert.src_ip else None,
        dst_ip=str(alert.dst_ip) if alert.dst_ip else None,
        src_host=alert.src_host,
        user_account=alert.user_account,
        occurred_at=alert.occurred_at,
        confirmed_as=alert.confirmed_as,
        confirm_reason=alert.confirm_reason,
        degraded=alert.degraded,
        created_at=alert.created_at,
    )


async def list_alerts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
    severity: str | None = None,
    alert_type: str | None = None,
    src_ip: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> AlertPage:
    limit = max(1, min(limit, 100))
    conds: list[Any] = [Alert.tenant_id == tenant_id, Alert.deleted_at.is_(None)]
    if status:
        conds.append(Alert.status == status)
    if severity:
        conds.append(Alert.severity == severity)
    if alert_type:
        conds.append(Alert.alert_type == alert_type)
    if src_ip:
        conds.append(Alert.src_ip == src_ip)
    if q:
        conds.append(Alert.title.ilike(f"%{q}%"))
    total = (
        await session.execute(select(func.count()).select_from(Alert).where(*conds))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(Alert)
                .where(*conds)
                .order_by(Alert.occurred_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return AlertPage(items=[_to_out(a) for a in rows], total=total, offset=offset, limit=limit)


async def get_alert(session: AsyncSession, tenant_id: uuid.UUID, alert_id: uuid.UUID) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None or alert.tenant_id != tenant_id or alert.deleted_at is not None:
        raise NotFound("alert", alert_id)
    return alert


async def alert_detail(
    session: AsyncSession, tenant_id: uuid.UUID, alert_id: uuid.UUID
) -> AlertDetail:
    alert = await get_alert(session, tenant_id, alert_id)
    result = await latest_triage_result(session, alert_id)
    return AlertDetail(
        **_to_out(alert).model_dump(),
        raw_payload=alert.raw_payload,
        triage=result,
    )


# ---------- status machine ----------


async def transition(session: AsyncSession, alert: Alert, to: AlertStatus) -> None:
    """Optimistic-concurrency state transition; illegal moves are business errors."""
    current = AlertStatus(alert.status)
    if to not in ALERT_TRANSITIONS.get(current, set()):
        raise Conflict(
            "alert.illegal_transition",
            f"cannot move alert from {current} to {to}",
            details={"from": current, "to": to},
        )
    # compare-and-swap
    from sqlalchemy import update

    res = await session.execute(
        update(Alert)
        .where(Alert.id == alert.id, Alert.status == current)
        .values(status=to, updated_at=utcnow())
    )
    if cast(CursorResult[Any], res).rowcount == 0:
        raise Conflict("alert.concurrent_modification", "alert state changed concurrently")
    alert.status = to


# ---------- human confirmation ----------


async def confirm(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    alert_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    verdict: HumanVerdict,
    reason: str,
) -> Alert:
    alert = await get_alert(session, tenant_id, alert_id)
    if alert.status != AlertStatus.TRIAGED:
        raise Conflict(
            "alert.not_confirmable",
            f"only triaged alerts can be confirmed (current: {alert.status})",
        )
    alert.confirmed_as = verdict
    alert.confirm_reason = reason
    alert.confirmed_by = user_id
    alert.confirmed_at = utcnow()
    target = (
        AlertStatus.CONFIRMED_TRUE
        if verdict == HumanVerdict.TRUE_POSITIVE
        else AlertStatus.CONFIRMED_FALSE
    )
    await transition(session, alert, target)

    # feedback row ties human verdict to the AI result for adoption-rate stats
    result = (
        await session.execute(
            select(TriageResult)
            .where(TriageResult.alert_id == alert.id)
            .order_by(TriageResult.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if result is not None:
        agreed = (
            verdict == HumanVerdict.TRUE_POSITIVE and result.classification == "true_positive"
        ) or (verdict == HumanVerdict.FALSE_POSITIVE and result.classification == "false_positive")
        session.add(
            AlertFeedback(
                alert_id=alert.id,
                triage_result_id=result.id,
                user_id=user_id,
                agreed=agreed,
                human_verdict=verdict,
                comment=reason,
            )
        )
    await session.commit()
    return alert


async def escalate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    alert_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> Alert:
    alert = await get_alert(session, tenant_id, alert_id)
    if alert.status != AlertStatus.CONFIRMED_TRUE:
        raise Conflict(
            "alert.not_escalatable", "only confirmed_true alerts can be linked to an incident"
        )
    from app.models.incidents import Incident, IncidentAlert

    incident = await session.get(Incident, incident_id)
    if incident is None or incident.tenant_id != tenant_id:
        raise NotFound("incident", incident_id)
    exists = (
        await session.execute(
            select(IncidentAlert).where(
                IncidentAlert.incident_id == incident_id, IncidentAlert.alert_id == alert.id
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(IncidentAlert(incident_id=incident_id, alert_id=alert.id, linked_by=user_id))
    await transition(session, alert, AlertStatus.INCIDENT_CREATED)
    await session.commit()
    return alert


# ---------- triage pipeline ----------


async def latest_triage_result(
    session: AsyncSession, alert_id: uuid.UUID
) -> TriageResultOut | None:
    row = (
        await session.execute(
            select(TriageResult)
            .where(TriageResult.alert_id == alert_id)
            .order_by(TriageResult.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return TriageResultOut(
        id=row.id,
        run_id=row.run_id,
        classification=row.classification,
        severity=row.severity,
        confidence=row.confidence,
        reasoning=row.reasoning,
        evidence=row.evidence,
        recommended_actions=row.recommended_actions,
        degraded=row.degraded,
        model_key=row.model_key,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
    )


async def triage_report(
    session: AsyncSession, tenant_id: uuid.UUID, alert_id: uuid.UUID
) -> TriageReportOut:
    await get_alert(session, tenant_id, alert_id)
    result = await latest_triage_result(session, alert_id)
    if result is None:
        return TriageReportOut(result=None, run=None, steps=[])
    run = await session.get(AIRun, result.run_id)
    step_rows = (
        (
            await session.execute(
                select(AIStep).where(AIStep.run_id == result.run_id).order_by(AIStep.step_no)
            )
        )
        .scalars()
        .all()
    )
    tool_rows = (
        (
            await session.execute(
                select(AIToolCall)
                .where(AIToolCall.run_id == result.run_id)
                .order_by(AIToolCall.step_no)
            )
        )
        .scalars()
        .all()
    )
    tool_by_step: dict[int, AIToolCall] = {t.step_no: t for t in tool_rows}
    steps = []
    for s in step_rows:
        t = tool_by_step.get(s.step_no)
        thought = (s.parsed or {}).get("thought")
        steps.append(
            TriageStepOut(
                step_no=s.step_no,
                kind=s.kind,
                thought=thought,
                tool=(s.parsed or {}).get("tool") or (t.tool_name if t else None),
                tool_args=(t.args if t else None),
                tool_result=(t.result if t else None),
                tool_error=(t.error if t else None),
            )
        )
    run_dict = None
    if run is not None:
        run_dict = {
            "id": str(run.id),
            "status": run.status,
            "model_key": run.model_key,
            "prompt_version": run.prompt_version,
            "total_prompt_tokens": run.total_prompt_tokens,
            "total_completion_tokens": run.total_completion_tokens,
            "total_cost_usd": float(run.total_cost_usd),
            "step_count": run.step_count,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
    return TriageReportOut(result=result, run=run_dict, steps=steps)


async def run_triage(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    alert_id: uuid.UUID,
    triggered_by: uuid.UUID | None = None,
) -> Alert:
    """Synchronous in-process triage used by the Celery task and manual retry."""
    from app.core.metrics import TRIAGE_RUNS
    from app.modules.ai.gateway import GatewayError, get_gateway

    alert = await get_alert(session, tenant_id, alert_id)
    if alert.status not in (AlertStatus.NEW, AlertStatus.TRIAGE_FAILED):
        raise Conflict("alert.not_triageable", f"cannot triage alert in status {alert.status}")
    await transition(session, alert, AlertStatus.TRIAGING)
    await session.commit()

    gateway = get_gateway()
    runner = AgentRunner(
        gateway, session, tenant_id=tenant_id, alert=alert, triggered_by=triggered_by
    )
    from app.modules.ai.agent import AgentFailed

    try:
        verdict = await runner.run()
        degraded = False
        await session.commit()
        TRIAGE_RUNS.labels("succeeded").inc()
    except (GatewayError, AgentFailed) as e:
        await session.rollback()
        await session.refresh(alert)  # rollback expired loaded state
        # persist a failed run row: degraded verdicts must still be auditable
        session.add(
            AIRun(
                alert_id=alert.id,
                purpose="triage",
                status="failed",
                prompt_version=PROMPT_VERSION,
                model_key=gateway.routing.get("triage", ["-"])[0]
                if gateway.routing.get("triage")
                else "-",
                input_snapshot={"alert_external_id": alert.external_id, "source": alert.source},
                error=f"agent failed: {e.__class__.__name__}: {e}",
                started_at=utcnow(),
                finished_at=utcnow(),
                triggered_by=triggered_by,
            )
        )
        await session.flush()
        verdict = _degraded_verdict(alert)
        degraded = True
        TRIAGE_RUNS.labels("degraded").inc()
        from app.core.logging import get_logger

        get_logger("alerts").warning(
            "triage_degraded_to_rules", alert_id=str(alert_id), error=str(e)
        )
    await _persist_result(session, alert, verdict, degraded=degraded)
    await transition(session, alert, AlertStatus.TRIAGED)
    alert.degraded = degraded
    await session.commit()

    # 研判完成通知（in-app + 可选 webhook），失败不影响主流程
    try:
        from app.platform.notify import notify_triage_result

        await notify_triage_result(
            session, tenant_id, alert_id=alert.id, alert_title=alert.title,
            classification=verdict.classification, severity=verdict.severity,
            triggered_by=triggered_by,
        )
        await session.commit()
    except Exception as e:  # noqa: BLE001
        from app.core.logging import get_logger

        get_logger("alerts").warning("notify_failed", alert_id=str(alert_id), error=str(e))
    return alert


def _degraded_verdict(alert: Alert) -> TriagedVerdict:
    from app.modules.ai.agent import rule_based_verdict

    return rule_based_verdict(alert)


async def _persist_result(
    session: AsyncSession, alert: Alert, verdict: TriagedVerdict, *, degraded: bool
) -> None:
    # find the run this verdict belongs to: latest run for the alert
    run = (
        await session.execute(
            select(AIRun)
            .where(AIRun.alert_id == alert.id)
            .order_by(AIRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one()
    session.add(
        TriageResult(
            alert_id=alert.id,
            run_id=run.id,
            classification=verdict.classification,
            severity=verdict.severity,
            confidence=verdict.confidence,
            reasoning=verdict.reasoning,
            evidence=[e.model_dump() for e in verdict.evidence],
            recommended_actions=[a.model_dump() for a in verdict.recommended_actions],
            prompt_version=run.prompt_version,
            degraded=degraded or verdict.reasoning.startswith("Degraded"),
            model_key=run.model_key,
        )
    )
    await session.flush()

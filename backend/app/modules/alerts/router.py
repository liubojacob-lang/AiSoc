"""Alerts HTTP routes."""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require, require_scope
from app.db.base import utcnow
from app.db.session import get_session
from app.models.enums import AlertStatus, Permission
from app.modules.alerts import schemas, service
from app.platform.audit import audit

router = APIRouter()


@router.post("/ingest/alerts", status_code=201)
async def ingest_alerts(
    body: schemas.AlertIngest,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_scope("alerts:write")),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Query(default=None, alias="Idempotency-Key"),
):
    """Machine ingestion endpoint (API key, scope ``alerts:write``).

    Idempotent twice over: natural key (source, external_id) plus optional
    Idempotency-Key replay for full response replay within 24h."""
    if idempotency_key:
        from app.models.ops import IdempotencyKey

        endpoint = "POST /ingest/alerts"
        row = await session.get(IdempotencyKey, (idempotency_key, endpoint))
        if row is not None and row.expires_at > utcnow():
            return Response(
                content=json.dumps(row.response_snapshot),
                status_code=row.status_code,
                media_type="application/json",
                headers={"X-Idempotent-Replay": "true"},
            )

    alert, created = await service.ingest(session, principal.tenant_id, body)
    if created:
        await audit(
            session,
            action="alert.ingest",
            resource_type="alert",
            resource_id=alert.id,
            actor_id=principal.api_key_id,
            actor_type="api_key",
            tenant_id=principal.tenant_id,
            request=request,
            detail={"source": alert.source, "external_id": alert.external_id},
        )
    await session.commit()
    if created:
        # pipeline reads the alert from its own session: row must be committed
        from app.workers.dispatch import dispatch_triage

        await dispatch_triage(alert.id, principal.tenant_id)

    payload = schemas.AlertOut(
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
    ).model_dump(mode="json")
    if idempotency_key and created:
        from datetime import timedelta

        from app.models.ops import IdempotencyKey

        session.add(
            IdempotencyKey(
                key=idempotency_key,
                endpoint=endpoint,
                tenant_id=principal.tenant_id,
                request_hash=hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
                response_snapshot=payload,
                status_code=201,
                expires_at=utcnow() + timedelta(hours=24),
            )
        )
        await session.commit()
    if not created:
        # duplicate delivery: return the existing alert with 200, not 201
        return Response(
            content=json.dumps(payload),
            status_code=200,
            media_type="application/json",
            headers={"X-Alert-Duplicate": "true"},
        )
    return payload


@router.get("", response_model=schemas.AlertPage)
async def list_alerts(
    status: str | None = None,
    severity: str | None = None,
    alert_type: str | None = None,
    src_ip: str | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_alerts(
        session,
        principal.tenant_id,
        status=status,
        severity=severity,
        alert_type=alert_type,
        src_ip=src_ip,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/{alert_id}", response_model=schemas.AlertDetail)
async def get_alert(
    alert_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.alert_detail(session, principal.tenant_id, alert_id)


@router.get("/{alert_id}/triage", response_model=schemas.TriageReportOut)
async def triage_report(
    alert_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    return await service.triage_report(session, principal.tenant_id, alert_id)


@router.post("/{alert_id}/confirm", response_model=schemas.AlertOut)
async def confirm_alert(
    alert_id: uuid.UUID,
    body: schemas.ConfirmRequest,
    request: Request,
    principal: Principal = Depends(require(Permission.ALERT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    alert = await service.confirm(
        session,
        principal.tenant_id,
        alert_id,
        user_id=principal.user_uuid,
        verdict=body.verdict,
        reason=body.reason,
    )
    await audit(
        session,
        action="alert.confirm",
        resource_type="alert",
        resource_id=alert.id,
        actor_id=principal.user_uuid,
        tenant_id=principal.tenant_id,
        request=request,
        detail={"verdict": body.verdict, "reason": body.reason[:200]},
    )
    await session.commit()
    return await service.alert_detail(session, principal.tenant_id, alert_id)


@router.post("/{alert_id}/escalate", response_model=schemas.AlertOut)
async def escalate_alert(
    alert_id: uuid.UUID,
    body: dict,
    request: Request,
    principal: Principal = Depends(require(Permission.ALERT_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    incident_id = body.get("incident_id")
    if not incident_id:
        from app.core.errors import ValidationFailed

        raise ValidationFailed("incident_id is required")
    alert = await service.escalate(
        session,
        principal.tenant_id,
        alert_id,
        user_id=principal.user_uuid,
        incident_id=uuid.UUID(incident_id),
    )
    await audit(
        session,
        action="alert.escalate",
        resource_type="alert",
        resource_id=alert.id,
        actor_id=principal.user_uuid,
        tenant_id=principal.tenant_id,
        request=request,
        detail={"incident_id": incident_id},
    )
    await session.commit()
    return await service.alert_detail(session, principal.tenant_id, alert_id)


@router.post("/{alert_id}/retry-triage", response_model=schemas.AlertOut)
async def retry_triage(
    alert_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.ALERT_TRIAGE)),
    session: AsyncSession = Depends(get_session),
):
    alert = await service.get_alert(session, principal.tenant_id, alert_id)
    if alert.status != AlertStatus.TRIAGE_FAILED:
        from app.core.errors import Conflict

        raise Conflict(
            "alert.not_retryable",
            f"only triage_failed alerts can be retried (current: {alert.status})",
        )
    await session.commit()
    from app.workers.dispatch import dispatch_triage

    await dispatch_triage(alert.id, principal.tenant_id, triggered_by=principal.user_uuid)
    await audit(
        session,
        action="alert.retry_triage",
        resource_type="alert",
        resource_id=alert.id,
        actor_id=principal.user_uuid,
        tenant_id=principal.tenant_id,
        request=request,
    )
    await session.commit()
    return await service.alert_detail(session, principal.tenant_id, alert_id)

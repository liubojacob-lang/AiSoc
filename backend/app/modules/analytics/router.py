"""Analytics dashboard: real aggregates from real tables — the numbers that
prove (or disprove) the AI's business value. No sampling, no fake data."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require
from app.db.base import utcnow
from app.db.session import get_session
from app.models.ai import LLMCall
from app.models.alerts import Alert, AlertFeedback
from app.models.enums import Permission
from app.modules.incidents.service import mttr_hours

router = APIRouter()


class StatusCount(BaseModel):
    status: str
    count: int


class SeverityCount(BaseModel):
    severity: str
    count: int


class CostByDay(BaseModel):
    day: str
    cost_usd: float
    calls: int


class Dashboard(BaseModel):
    alerts_total: int
    alerts_by_status: list[StatusCount]
    alerts_by_severity: list[SeverityCount]
    noise_reduction_rate: float | None  # confirmed_false / confirmed total
    ai_adoption_rate: float | None  # human feedback agreeing with AI
    triaged_pending_confirmation: int
    mttr_hours: float | None
    llm_cost_usd_total: float
    llm_cost_by_day: list[CostByDay]
    llm_calls_total: int


@router.get("/dashboard", response_model=Dashboard)
async def dashboard(
    days: int = 30,
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    tenant = principal.tenant_id
    since = utcnow() - timedelta(days=min(max(days, 1), 365))

    status_rows = (
        await session.execute(
            select(Alert.status, func.count())
            .where(Alert.tenant_id == tenant, Alert.deleted_at.is_(None))
            .group_by(Alert.status)
        )
    ).all()
    severity_rows = (
        await session.execute(
            select(Alert.severity, func.count())
            .where(Alert.tenant_id == tenant, Alert.deleted_at.is_(None))
            .group_by(Alert.severity)
        )
    ).all()
    alerts_total = sum(c for _, c in status_rows)

    confirmed_true = sum(c for s, c in status_rows if s == "confirmed_true") + sum(
        c for s, c in status_rows if s == "incident_created"
    )
    confirmed_false = sum(c for s, c in status_rows if s == "confirmed_false")
    noise_rate = (
        round(confirmed_false / (confirmed_true + confirmed_false), 4)
        if (confirmed_true + confirmed_false) > 0
        else None
    )

    feedback_total = (
        await session.execute(
            select(func.count()).select_from(AlertFeedback).where(AlertFeedback.created_at >= since)
        )
    ).scalar_one()
    feedback_agreed = (
        await session.execute(
            select(func.count())
            .select_from(AlertFeedback)
            .where(AlertFeedback.created_at >= since, AlertFeedback.agreed.is_(True))
        )
    ).scalar_one()
    adoption = round(feedback_agreed / feedback_total, 4) if feedback_total else None

    cost_rows = (
        await session.execute(
            select(
                func.date(LLMCall.created_at),
                func.sum(LLMCall.cost_usd),
                func.count(),
            )
            .where(LLMCall.created_at >= since)
            .group_by(func.date(LLMCall.created_at))
            .order_by(func.date(LLMCall.created_at))
        )
    ).all()
    cost_total = (
        await session.execute(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(LLMCall.created_at >= since)
        )
    ).scalar_one()
    calls_total = (
        await session.execute(
            select(func.count()).select_from(LLMCall).where(LLMCall.created_at >= since)
        )
    ).scalar_one()

    return Dashboard(
        alerts_total=alerts_total,
        alerts_by_status=[StatusCount(status=s, count=c) for s, c in status_rows],
        alerts_by_severity=[SeverityCount(severity=s, count=c) for s, c in severity_rows],
        noise_reduction_rate=noise_rate,
        ai_adoption_rate=adoption,
        triaged_pending_confirmation=sum(c for s, c in status_rows if s == "triaged"),
        mttr_hours=await mttr_hours(session, tenant),
        llm_cost_usd_total=float(cost_total),
        llm_cost_by_day=[
            CostByDay(day=str(d), cost_usd=float(c or 0), calls=n) for d, c, n in cost_rows
        ],
        llm_calls_total=calls_total,
    )

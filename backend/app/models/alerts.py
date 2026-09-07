"""Alerts domain: alerts, enrichments, triage results, human feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from ipaddress import IPv4Address

from sqlalchemy import (
    BOOLEAN,
    JSON,
    BigInteger,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.base import Base, Timestamped, UTCDateTime, UUIDPk, utcnow

JSONType = JSONB().with_variant(JSON(), "sqlite")
# INET is PG-only; sqlite falls back to VARCHAR(45) (enough for IPv6)
InetType = INET().with_variant(String(45), "sqlite")


class IPColumn(TypeDecorator):
    """Store ipaddress objects portably (PG INET validates, sqlite stores text)."""

    impl = InetType
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        try:
            return IPv4Address(value)
        except ValueError:
            return value


class Alert(Base, UUIDPk, Timestamped):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("uq_alerts_source_external", "source", "external_id", unique=True),
        Index(
            "ix_alerts_tenant_status_created",
            "tenant_id",
            "status",
            text("created_at DESC"),
        ),
        Index("ix_alerts_severity", "severity"),
        Index("ix_alerts_src_ip", "src_ip"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="new")
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    src_ip: Mapped[str | None] = mapped_column(IPColumn, nullable=True)
    dst_ip: Mapped[str | None] = mapped_column(IPColumn, nullable=True)
    src_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_account: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    confirmed_as: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confirm_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    degraded: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AlertEnrichment(Base, UUIDPk):
    __tablename__ = "alert_enrichments"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class TriageResult(Base, UUIDPk):
    __tablename__ = "triage_results"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_runs.id", ondelete="RESTRICT"), nullable=False
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0-100
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    recommended_actions: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    degraded: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, default=False)
    model_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class AlertFeedback(Base, UUIDPk):
    __tablename__ = "alert_feedback"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triage_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("triage_results.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    agreed: Mapped[bool] = mapped_column(BOOLEAN, nullable=False)
    human_verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

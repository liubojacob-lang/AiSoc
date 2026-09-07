"""Ops domain: audit log (append-only), notifications, configs, idempotency,
and the intel/asset tables backing triage tools."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigId, Timestamped, UTCDateTime, UUIDPk, utcnow

JSONType = JSONB().with_variant(JSON(), "sqlite")
InetType = INET().with_variant(String(45), "sqlite")


class ThreatIntel(Base, UUIDPk, Timestamped):
    """Local IOC store queried by the triage agent (no external calls at runtime)."""

    __tablename__ = "threat_intel"
    __table_args__ = (Index("uq_intel_tenant_ioc", "tenant_id", "ioc", "ioc_type", unique=True),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ioc: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ioc_type: Mapped[str] = mapped_column(String(16), nullable=False)  # ip/domain/hash
    reputation: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0-100
    tags: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    first_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Asset(Base, UUIDPk, Timestamped):
    __tablename__ = "assets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # host/container/service
    identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    criticality: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    __table_args__ = (Index("uq_assets_tenant_identifier", "tenant_id", "identifier", unique=True),)


class AuditLog(BigId, Base):
    """Append-only audit trail. No update/delete code paths exist anywhere."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_created", text("created_at DESC")),
        Index("ix_audit_actor", "actor_id", "created_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_action_created", "action", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(InetType, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Notification(Base, UUIDPk):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notif_recipient", "recipient_id", "read_at", text("created_at DESC")),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class SystemConfig(Timestamped, Base):
    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONType, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_snapshot: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    status_code: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)


__all__ = [
    "ThreatIntel",
    "Asset",
    "AuditLog",
    "Notification",
    "SystemConfig",
    "IdempotencyKey",
]

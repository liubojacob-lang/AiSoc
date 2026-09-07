"""Incidents domain: incidents, linked alerts, tasks, comments."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UTCDateTime, UUIDPk, utcnow


class Incident(Base, UUIDPk, Timestamped):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_tenant_status", "tenant_id", "status"),
        Index("ix_incidents_assigned", "assigned_to"),
        Index("ix_incidents_created", text("created_at DESC")),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    source_alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    opened_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    close_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reopened_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class IncidentAlert(Base):
    __tablename__ = "incident_alerts"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="RESTRICT"), primary_key=True
    )
    linked_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Task(Base, UUIDPk, Timestamped):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_incident", "incident_id", "status"),
        Index("ix_tasks_assignee", "assignee", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="todo")
    assignee: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class Comment(Base, UUIDPk, Timestamped):
    __tablename__ = "comments"
    __table_args__ = (
        # exactly one of incident_id / task_id (portable boolean comparison)
        CheckConstraint(
            "(incident_id IS NOT NULL) != (task_id IS NOT NULL)",
            name="one_target",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

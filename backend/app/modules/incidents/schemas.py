"""Incidents module schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    severity: str = Field(pattern="^(low|medium|high|critical)$")
    source_alert_id: uuid.UUID | None = None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    severity: str
    status: str
    assigned_to: uuid.UUID | None
    source_alert_id: uuid.UUID | None
    opened_by: uuid.UUID
    closed_at: datetime | None
    close_summary: str | None
    reopened_count: int
    created_at: datetime
    updated_at: datetime


class IncidentTransition(BaseModel):
    to_status: str = Field(
        pattern="^(investigating|contained|eradicated|recovered|closed|reopened)$"
    )
    reason: str = Field(min_length=3, max_length=2000)
    close_summary: str | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    assignee: uuid.UUID | None = None
    due_at: datetime | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    title: str
    description: str | None
    status: str
    assignee: uuid.UUID | None
    due_at: datetime | None
    blocked_reason: str | None
    completed_at: datetime | None
    created_at: datetime


class TaskTransition(BaseModel):
    to_status: str = Field(pattern="^(todo|in_progress|blocked|done|cancelled)$")
    reason: str | None = Field(default=None, max_length=255)  # required for blocked/cancelled


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID | None
    task_id: uuid.UUID | None
    body: str
    author_id: uuid.UUID
    created_at: datetime

"""Action approval schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionPropose(BaseModel):
    action: str = Field(
        pattern="^(block_ip|block_domain|isolate_host|reset_password|disable_account|monitor)$"
    )
    target: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=3, max_length=2000)
    triage_result_id: uuid.UUID | None = None


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_id: uuid.UUID | None
    triage_result_id: uuid.UUID | None
    action: str
    target: str | None
    reason: str
    status: str
    proposed_by: uuid.UUID
    approved_l1_by: uuid.UUID | None
    approved_l2_by: uuid.UUID | None
    rejected_by: uuid.UUID | None
    rejected_reason: str | None
    executed_by: uuid.UUID | None
    executed_at: datetime | None
    execution_mode: str | None
    execution_result: dict[str, Any] | None
    created_at: datetime


class RejectBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

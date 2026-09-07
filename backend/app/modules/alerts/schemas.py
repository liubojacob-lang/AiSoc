"""Alerts module schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from ipaddress import IPv4Address
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    HumanVerdict,
    TriageClassification,
)


class AlertIngest(BaseModel):
    """External alert payload. Strictly validated; extra fields preserved in
    raw_payload but these fields are indexed/required."""

    source: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    severity: AlertSeverity = AlertSeverity.MEDIUM
    alert_type: str = Field(min_length=1, max_length=64)
    src_ip: str | None = None
    dst_ip: str | None = None
    src_host: str | None = Field(default=None, max_length=255)
    user_account: str | None = Field(default=None, max_length=128)
    occurred_at: datetime | None = None  # default: now
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("src_ip", "dst_ip")
    @classmethod
    def _valid_ip(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        IPv4Address(v)  # raises on invalid (v4/v6 both OK via IPvAnyAddress below)
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    external_id: str
    title: str
    description: str | None
    severity: str
    status: AlertStatus
    alert_type: str
    src_ip: str | None = None
    dst_ip: str | None = None
    src_host: str | None = None
    user_account: str | None = None
    occurred_at: datetime
    confirmed_as: str | None = None
    confirm_reason: str | None = None
    degraded: bool
    created_at: datetime


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int
    offset: int
    limit: int


class EvidenceOut(BaseModel):
    source: str
    detail: str


class RecommendedActionOut(BaseModel):
    action: str
    target: str | None = None
    reason: str


class TriageResultOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    classification: TriageClassification
    severity: str
    confidence: int
    reasoning: str
    evidence: list[EvidenceOut]
    recommended_actions: list[RecommendedActionOut]
    degraded: bool
    model_key: str
    prompt_version: str
    created_at: datetime


class TriageStepOut(BaseModel):
    step_no: int
    kind: str
    thought: str | None = None
    tool: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None
    tool_error: str | None = None


class TriageReportOut(BaseModel):
    """Full AI triage report incl. replayable steps."""

    result: TriageResultOut | None
    run: dict | None = None
    steps: list[TriageStepOut] = []


class AlertDetail(AlertOut):
    raw_payload: dict
    triage: TriageResultOut | None = None


class ConfirmRequest(BaseModel):
    verdict: HumanVerdict
    reason: str = Field(min_length=3, max_length=2000)

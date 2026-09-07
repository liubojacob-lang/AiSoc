"""AI domain: LLM call accounting, agent runs/steps/tool-calls, conversations."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.base import Base, Timestamped, UTCDateTime, UUIDPk, utcnow

JSONType = JSONB().with_variant(JSON(), "sqlite")


class Money(TypeDecorator):
    """NUMERIC(10,6) on PostgreSQL; float storage on sqlite (bindings there
    cannot handle Decimal). Always reads back as Decimal."""

    impl = Numeric(10, 6)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        if dialect.name == "sqlite":
            return float(value)
        return value

    def process_result_value(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        return Decimal(str(value))


class LLMCall(Base, UUIDPk):
    """One row per LLM/embed call. The cost-accounting fact table (append-only)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_created", text("created_at DESC")),
        Index("ix_llm_calls_provider_model", "provider", "model_key"),
        Index("ix_llm_calls_purpose_created", "purpose", "created_at"),
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # triage/embed/chat/eval
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_key: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok/timeout/error/rate_limited
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_meta: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class AIRun(Base, UUIDPk):
    """One agent execution (e.g. triage of one alert). Full replay anchor."""

    __tablename__ = "ai_runs"

    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_key: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    output: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_prompt_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    total_completion_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0)
    step_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AIStep(Base, UUIDPk):
    __tablename__ = "ai_steps"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # plan/tool/finalize
    llm_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class AIToolCall(Base, UUIDPk):
    __tablename__ = "ai_tool_calls"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    args: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok/error
    latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class AIConversation(Base, UUIDPk, Timestamped):
    __tablename__ = "ai_conversations"  # P1 SOC copilot; schema shipped ahead

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新会话")


class AIMessage(Base, UUIDPk):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user/assistant/system/tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    refs: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

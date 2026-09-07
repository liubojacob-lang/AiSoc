"""AI module schemas: chat protocol + structured triage verdict.

``TriagedVerdict`` is the single contract between the AI subsystem and the
rest of the product. It is *always* validated by Pydantic before persistence;
malformed LLM output never becomes a stored conclusion.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import AlertSeverity, TriageClassification


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    purpose: str = "chat"  # routing key: triage | embed | chat | eval
    model_key: str | None = None  # explicit override of routing
    temperature: float = 0.2
    max_tokens: int = 2000
    json_mode: bool = False  # instruct provider to emit a JSON object


class ChatResponse(BaseModel):
    content: str
    provider: str
    model_key: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class Evidence(BaseModel):
    source: str = Field(description="tool name or 'alert' — where this fact came from")
    detail: str = Field(description="the fact itself, quoted or tightly summarized")


class RecommendedAction(BaseModel):
    action: str = Field(description="e.g. block_ip, isolate_host, reset_password, monitor")
    target: str | None = None
    reason: str


class TriagedVerdict(BaseModel):
    """Validated conclusion of an alert triage run."""

    classification: TriageClassification
    severity: AlertSeverity
    confidence: int = Field(ge=0, le=100)
    reasoning: str = Field(min_length=10)
    evidence: list[Evidence] = Field(min_length=1)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)


class AgentAction(BaseModel):
    """One step of the agent loop: either call a tool, or finalize."""

    thought: str
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    final: TriagedVerdict | None = None

    @model_validator(mode="after")
    def _exactly_one_branch(self) -> AgentAction:
        if (self.tool is None) == (self.final is None):
            raise ValueError("exactly one of 'tool' or 'final' must be present")
        if self.tool is not None and not self.tool:
            raise ValueError("tool must be a non-empty name")
        return self

    @field_validator("args")
    @classmethod
    def _args_is_object(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("args must be a JSON object")
        return v

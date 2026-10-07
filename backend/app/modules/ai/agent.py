"""AgentRunner: a self-implemented ReAct-style loop (ADR-4).

Why not LangChain: the loop is ≤8 bounded steps over a whitelisted internal
toolset, every step must be persisted for audit/replay, and outputs must pass
strict validation. Owning ~300 lines beats owning an abstraction we cannot
audit. (docs/ARCHITECTURE.md §6 / ADR-4)

Failure semantics:
- Gateway exhausts its chain   → AgentFailed → caller may fall back to rules
- Step / token budget exhausted → one forced finalize attempt, else AgentFailed
- Overall timeout              → enforced by the caller (worker) via wait_for
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.ai import AIRun, AIStep, AIToolCall
from app.models.alerts import Alert
from app.models.enums import AlertSeverity, RunStatus, TriageClassification
from app.modules.ai.gateway import GatewayError, LLMGateway
from app.modules.ai.prompts import PROMPT_VERSION, TRIAGE_SYSTEM, TRIAGE_USER_TEMPLATE
from app.modules.ai.schemas import AgentAction, ChatMessage, ChatRequest, Evidence, TriagedVerdict
from app.modules.ai.tools import (
    ToolContext,
    ToolResult,
    execute_tool,
    observations_to_text,
    tool_docs,
)

log = get_logger("ai.agent")


class AgentFailed(Exception):
    pass


def rule_based_verdict(alert: Alert) -> TriagedVerdict:
    """No-LLM fallback (ADR-10). Honest about being degraded: the caller marks
    ``degraded=True`` on the persisted result and the UI shows a banner."""
    danger_types = {"brute_force", "malware", "sql_injection", "web_attack", "lateral_movement"}
    critical_kw = ("domain admin", "dc", "backup", "payment")
    text = f"{alert.title} {alert.description or ''}".lower()

    if alert.alert_type in danger_types or any(k in text for k in critical_kw):
        sev = AlertSeverity.HIGH
        why = "dangerous alert type / critical keyword present"
    else:
        sev = AlertSeverity.MEDIUM
        why = "no decisive rule matched"
    return TriagedVerdict(
        classification=TriageClassification.NEEDS_INVESTIGATION,
        severity=sev,
        confidence=20,
        reasoning=(
            f"Degraded rule-based verdict (LLM unavailable): {why}. "
            "This is NOT a full AI analysis; manual review required."
        ),
        evidence=[
            Evidence(
                source="alert",
                detail=f"alert_type={alert.alert_type}; title={alert.title[:120]}",
            )
        ],
        recommended_actions=[],
    )


class AgentRunner:
    def __init__(
        self,
        gateway: LLMGateway,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        alert: Alert,
        run_id: uuid.UUID | None = None,
        triggered_by: uuid.UUID | None = None,
    ) -> None:
        self.gateway = gateway
        self.session = session
        self.tenant_id = tenant_id
        self.alert = alert
        self.run_id = run_id or uuid.uuid4()
        self.triggered_by = triggered_by
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.steps = 0

    # ---------- persistence ----------

    async def _ensure_run(self) -> AIRun:
        run = await self.session.get(AIRun, self.run_id)
        if run is None:
            run = AIRun(
                id=self.run_id,
                alert_id=self.alert.id,
                purpose="triage",
                status=RunStatus.RUNNING,
                prompt_version=PROMPT_VERSION,
                model_key=(self.gateway.routing.get("triage") or ["-"])[0],
                input_snapshot={
                    "alert_external_id": self.alert.external_id,
                    "source": self.alert.source,
                },
                started_at=datetime.now(UTC),
                triggered_by=self.triggered_by,
            )
            self.session.add(run)
            await self.session.flush()
        return run

    async def _persist_step(
        self, step_no: int, kind: str, raw: str | None, parsed: dict | None
    ) -> None:
        self.session.add(
            AIStep(run_id=self.run_id, step_no=step_no, kind=kind, llm_raw=raw, parsed=parsed)
        )

    async def _persist_tool_call(
        self, step_no: int, name: str, args: dict, result: ToolResult
    ) -> None:
        self.session.add(
            AIToolCall(
                run_id=self.run_id,
                step_no=step_no,
                tool_name=name,
                args=args,
                result=result.payload if result.ok else None,
                status="ok" if result.ok else "error",
                latency_ms=result.latency_ms,
                error=result.error,
            )
        )

    # ---------- prompt ----------

    def _alert_json(self) -> str:
        a = self.alert
        return json.dumps(
            {
                "external_id": a.external_id,
                "title": a.title,
                "description": a.description,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "src_ip": str(a.src_ip) if a.src_ip else None,
                "dst_ip": str(a.dst_ip) if a.dst_ip else None,
                "src_host": a.src_host,
                "user_account": a.user_account,
                "occurred_at": a.occurred_at.isoformat(),
            },
            ensure_ascii=False,
        )

    def _request(
        self, observations: list[tuple[str, ToolResult]], force_finalize: bool = False
    ) -> ChatRequest:
        system = TRIAGE_SYSTEM.replace("{tool_docs}", tool_docs())
        if force_finalize:
            system += (
                "\nSTEP BUDGET REACHED. You MUST finalize NOW using the evidence gathered so far."
            )
        user = TRIAGE_USER_TEMPLATE.replace("{alert_json}", self._alert_json()).replace(
            "{observations}", observations_to_text(observations)
        )
        return ChatRequest(
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ],
            purpose="triage",
            temperature=0.1,
            max_tokens=1500,
        )

    # ---------- loop ----------

    async def run(self) -> TriagedVerdict:
        run = await self._ensure_run()
        ctx = ToolContext(session=self.session, tenant_id=self.tenant_id, alert=self.alert)
        observations: list[tuple[str, ToolResult]] = []
        budget = settings.llm_budget_tokens_per_triage
        max_steps = settings.agent_max_steps

        try:
            for step_no in range(1, max_steps + 1):
                self.steps = step_no
                try:
                    action, resp = await self.gateway.chat_structured(
                        self._request(observations), AgentAction, run_id=self.run_id
                    )
                except GatewayError as e:
                    run.status = RunStatus.FAILED
                    run.error = f"gateway exhausted: {e.attempts}"
                    raise AgentFailed(run.error) from e

                self.prompt_tokens += resp.prompt_tokens
                self.completion_tokens += resp.completion_tokens
                await self._persist_step(
                    step_no,
                    "finalize" if action.final else "plan",
                    resp.content,
                    action.model_dump(),
                )

                if action.final is not None:
                    return await self._finalize(run, action.final)

                result = await execute_tool(ctx, action.tool or "", action.args)
                await self._persist_tool_call(step_no, action.tool or "", action.args, result)
                observations.append((action.tool or "unknown", result))

                if self.prompt_tokens + self.completion_tokens > budget:
                    observations.append(
                        (
                            "budget",
                            ToolResult(
                                ok=False,
                                error="TOKEN BUDGET EXHAUSTED — finalize with available evidence",
                            ),
                        )
                    )
                    break  # go to forced finalize

            return await self._force_finalize(run, observations)
        finally:
            run.total_prompt_tokens = self.prompt_tokens
            run.total_completion_tokens = self.completion_tokens
            run.step_count = self.steps
            if run.status == RunStatus.RUNNING:
                run.status = RunStatus.FAILED
                run.error = run.error or "agent loop ended without verdict"
            run.finished_at = datetime.now(UTC)

    async def _force_finalize(
        self, run: AIRun, observations: list[tuple[str, ToolResult]]
    ) -> TriagedVerdict:
        try:
            action, resp = await self.gateway.chat_structured(
                self._request(observations, force_finalize=True), AgentAction, run_id=self.run_id
            )
        except GatewayError as e:
            run.status = RunStatus.FAILED
            run.error = f"forced finalize gateway error: {e.attempts}"
            raise AgentFailed(run.error) from e
        self.prompt_tokens += resp.prompt_tokens
        self.completion_tokens += resp.completion_tokens
        self.steps += 1
        await self._persist_step(self.steps, "finalize", resp.content, action.model_dump())
        if action.final is not None:
            return await self._finalize(run, action.final)
        run.status = RunStatus.FAILED
        run.error = "forced finalize did not produce a verdict"
        raise AgentFailed(run.error)

    async def _finalize(self, run: AIRun, verdict: TriagedVerdict) -> TriagedVerdict:
        run.status = RunStatus.SUCCEEDED
        run.output = verdict.model_dump(mode="json")
        run.finished_at = datetime.now(UTC)
        return verdict

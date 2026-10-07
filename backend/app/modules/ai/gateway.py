"""LLM Gateway — the only door between business code and model vendors.

Responsibilities (docs/ARCHITECTURE.md §5.1): routing → timeout → retry with
backoff → provider failover chain → circuit breaker → structured-output
parsing with one repair round → per-call cost accounting (independent
transaction so accounting survives business rollbacks).

Business code sees: ``await gateway.chat(...)`` / ``chat_structured(...)`` /
``embed(...)``. Swapping vendors changes configuration, not code.
"""

from __future__ import annotations

import asyncio
import json
import random  # noqa: S311 - jitter/backoff only
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import AI_CALLS, AI_COST_USD, AI_LATENCY, AI_TOKENS
from app.core.security import decrypt_secret
from app.db.session import get_sessionmaker
from app.models.ai import LLMCall
from app.modules.ai import pricing
from app.modules.ai.providers.anthropic import AnthropicProvider
from app.modules.ai.providers.base import LLMProvider, ProviderError, ProviderFatalError
from app.modules.ai.providers.fake import FakeProvider
from app.modules.ai.providers.gemini import GeminiProvider
from app.modules.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.modules.ai.schemas import ChatMessage, ChatRequest, ChatResponse

log = get_logger("ai.gateway")

T = TypeVar("T", bound=BaseModel)


class GatewayError(Exception):
    """Every provider in the chain failed (after retries)."""

    def __init__(self, attempts: list[dict[str, str]]) -> None:
        self.attempts = attempts
        super().__init__(f"all providers failed: {attempts}")


# ---------------- circuit breaker ----------------


@dataclass
class _Window:
    events: deque = field(default_factory=deque)  # (monotonic_ts, ok)


class CircuitBreaker:
    """Per model_key sliding-window error-rate breaker (in-process).

    Good enough for the single-node deployment target; a distributed breaker
    (Redis) is a documented follow-up, not a correctness issue here.
    """

    def __init__(
        self, window_s: float = 120, min_calls: int = 5, rate: float = 0.5, cooldown_s: float = 60
    ) -> None:
        self.window_s = window_s
        self.min_calls = min_calls
        self.rate = rate
        self.cooldown_s = cooldown_s
        self._windows: dict[str, _Window] = {}
        self._open_until: dict[str, float] = {}

    def record(self, key: str, ok: bool) -> None:
        now = time.monotonic()
        w = self._windows.setdefault(key, _Window())
        w.events.append((now, ok))
        cutoff = now - self.window_s
        while w.events and w.events[0][0] < cutoff:
            w.events.popleft()
        recent = list(w.events)
        if len(recent) >= self.min_calls:
            err_rate = sum(1 for _, okk in recent if not okk) / len(recent)
            if err_rate > self.rate:
                self._open_until[key] = now + self.cooldown_s
                w.events.clear()

    def is_open(self, key: str) -> bool:
        until = self._open_until.get(key)
        if until is None:
            return False
        if time.monotonic() >= until:  # cooldown elapsed → half-open probe
            del self._open_until[key]
            return False
        return True


# ---------------- gateway ----------------


class LLMGateway:
    def __init__(
        self,
        registry: dict[str, LLMProvider],
        routing: dict[str, list[str]],
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._registry = registry
        self.routing = routing
        self.breaker = breaker or CircuitBreaker()
        self._prices = pricing.load_prices()

    # ---- construction ----

    @classmethod
    def from_settings(cls) -> LLMGateway:
        routing: dict[str, list[str]] = json.loads(settings.llm_routing)
        registry: dict[str, LLMProvider] = {"fake": FakeProvider()}
        for chain in routing.values():
            for model_key in chain:
                pname = model_key.partition(":")[0]
                if pname not in registry:
                    registry[pname] = cls._build_provider(pname)
        return cls(registry=registry, routing=routing)

    @staticmethod
    def _build_provider(name: str) -> LLMProvider:
        """Fail-fast: a routing entry referencing an unconfigured provider is a
        startup error, not a runtime surprise."""
        if name in ("openai", "deepseek", "qwen"):
            key = {
                "openai": settings.openai_api_key,
                "deepseek": settings.deepseek_api_key,
                "qwen": settings.dashscope_api_key,
            }[name]
            base = {"openai": settings.openai_base_url, "deepseek": None, "qwen": None}[name]
            return OpenAICompatibleProvider(name, key, base)
        if name == "ollama":
            return OpenAICompatibleProvider("ollama", None, settings.ollama_base_url)
        if name == "anthropic":
            return AnthropicProvider(settings.anthropic_api_key)
        if name == "gemini":
            return GeminiProvider(settings.gemini_api_key)
        raise ValueError(f"unknown LLM provider in routing: {name}")

    # ---- helpers ----

    def _timeout_for(self, purpose: str) -> float:
        return (
            settings.llm_triage_timeout_s if purpose == "triage" else settings.llm_request_timeout_s
        )

    async def _account(
        self,
        *,
        request: ChatRequest,
        model_key: str,
        run_id: Any | None,
        status: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        error_code: str | None,
    ) -> None:
        provider = model_key.partition(":")[0]
        cost = pricing.cost_usd(self._prices, model_key, prompt_tokens, completion_tokens)
        call = LLMCall(
            run_id=run_id,
            purpose=request.purpose,
            provider=provider,
            model_key=model_key,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
            request_meta={"temperature": request.temperature, "max_tokens": request.max_tokens},
        )
        AI_CALLS.labels(provider, model_key, request.purpose, status).inc()
        AI_TOKENS.labels(provider, model_key, "prompt").inc(prompt_tokens)
        AI_TOKENS.labels(provider, model_key, "completion").inc(completion_tokens)
        AI_COST_USD.labels(provider, model_key).inc(float(cost))
        try:
            # independent transaction: accounting survives business rollback
            # (PostgreSQL MVCC makes this safe; sqlite single-writer may not)
            maker = get_sessionmaker()
            async with maker() as session:
                session.add(call)
                await session.commit()
        except Exception:
            # fallback: piggyback on the caller's session so accounting is
            # never lost (commits with the business transaction there)
            from app.db.session import get_current_session

            current = get_current_session()
            if current is not None:
                current.add(call)
            else:
                log.error(
                    "llm_accounting_failed", model_key=model_key, error="no session available"
                )

    # ---- public API ----

    async def chat(self, request: ChatRequest, run_id: Any | None = None) -> ChatResponse:
        chain = [request.model_key] if request.model_key else self.routing.get(request.purpose, [])
        if not chain:
            raise GatewayError(
                [{"model": "-", "error": f"no routing for purpose={request.purpose}"}]
            )
        attempts_log: list[dict[str, str]] = []
        timeout_s = self._timeout_for(request.purpose)

        for model_key in chain:
            pname, _, model = model_key.partition(":")
            provider = self._registry.get(pname)
            if provider is None:
                attempts_log.append({"model": model_key, "error": "provider not registered"})
                continue
            if self.breaker.is_open(model_key):
                AI_CALLS.labels(pname, model_key, request.purpose, "breaker_open").inc()
                attempts_log.append({"model": model_key, "error": "circuit_open"})
                continue

            for attempt in range(settings.llm_max_retries):
                started = time.monotonic()
                try:
                    content, pt, ct = await provider.chat(
                        [m.model_dump() for m in request.messages],
                        model,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        timeout_s=timeout_s,
                        json_mode=request.json_mode,
                    )
                    latency_ms = int((time.monotonic() - started) * 1000)
                    self.breaker.record(model_key, True)
                    AI_LATENCY.labels(pname, model_key).observe(latency_ms / 1000)
                    await self._account(
                        request=request,
                        model_key=model_key,
                        run_id=run_id,
                        status="ok",
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        latency_ms=latency_ms,
                        error_code=None,
                    )
                    return ChatResponse(
                        content=content,
                        provider=pname,
                        model_key=model_key,
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        latency_ms=latency_ms,
                    )
                except ProviderFatalError as e:
                    self.breaker.record(model_key, False)
                    attempts_log.append({"model": model_key, "error": str(e)})
                    await self._account(
                        request=request,
                        model_key=model_key,
                        run_id=run_id,
                        status="error",
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error_code=e.code,
                    )
                    break  # fatal → next provider in chain
                except ProviderError as e:
                    self.breaker.record(model_key, False)
                    latency_ms = int((time.monotonic() - started) * 1000)
                    status = (
                        "timeout"
                        if e.code == "timeout"
                        else ("rate_limited" if e.code == "http.429" else "error")
                    )
                    await self._account(
                        request=request,
                        model_key=model_key,
                        run_id=run_id,
                        status=status,
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=latency_ms,
                        error_code=e.code,
                    )
                    if attempt == settings.llm_max_retries - 1:
                        break  # exhausted retries → next provider
                    backoff = 0.5 * (2**attempt) + random.uniform(0, 0.25)  # noqa: S311
                    await asyncio.sleep(backoff)

        raise GatewayError(attempts_log)

    async def chat_structured(
        self, request: ChatRequest, schema: type[T], run_id: Any | None = None
    ) -> tuple[T, ChatResponse]:
        """Structured output: schema-aware prompt + strict parse + one repair
        round. A malformed model answer NEVER becomes a stored conclusion."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = list(request.messages)
        messages.append(
            ChatMessage(
                role="system",
                content=(
                    "Respond with a single JSON object and nothing else "
                    "(no markdown fences, no commentary). It must satisfy this "
                    f"JSON schema:\n{schema_json}"
                ),
            )
        )
        req = request.model_copy(update={"messages": messages, "json_mode": True})

        last_resp: ChatResponse | None = None
        max_tokens = request.max_tokens
        for attempt in range(2):
            resp = await self.chat(req, run_id=run_id)
            last_resp = resp
            parsed = self._extract_json(resp.content)
            if parsed is not None:
                try:
                    return schema.model_validate(parsed), resp
                except ValidationError as e:
                    log.warning(
                        "structured_validation_failed", attempt=attempt, errors=e.errors()[:5]
                    )
                    messages.append(ChatMessage(role="assistant", content=resp.content))
                    messages.append(
                        ChatMessage(
                            role="user",
                            content=(
                                "Your JSON failed schema validation. Fix it and respond "
                                f"again with ONLY the corrected JSON. Validation errors: "
                                f"{e.errors()[:5]}"
                            ),
                        )
                    )
                    # 推理模型可能在思考上耗尽预算：修复轮放宽 token 上限
                    max_tokens = min(max_tokens * 2, 8000)
                    req = request.model_copy(
                        update={"messages": messages, "json_mode": True, "max_tokens": max_tokens}
                    )
                    continue
            else:
                empty_hint = (
                    "You produced no visible content (it was likely consumed by reasoning). "
                    if not resp.content.strip()
                    else ""
                )
                messages.append(ChatMessage(role="assistant", content=resp.content[:2000]))
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            empty_hint
                            + "That was not valid JSON per the schema. Respond again with ONLY valid JSON."
                        ),
                    )
                )
                max_tokens = min(max_tokens * 2, 8000)
                req = request.model_copy(
                    update={"messages": messages, "json_mode": True, "max_tokens": max_tokens}
                )
        assert last_resp is not None
        raise GatewayError(
            [{"model": last_resp.model_key, "error": "structured output failed validation"}]
        )

    async def embed(
        self, texts: list[str], purpose: str = "embed", run_id: Any | None = None
    ) -> list[list[float]]:
        if not texts:
            return []
        request = ChatRequest(messages=[ChatMessage(role="user", content="embed")], purpose=purpose)
        chain = self.routing.get(purpose, [])
        if not chain:
            raise GatewayError([{"model": "-", "error": f"no routing for purpose={purpose}"}])
        for model_key in chain:
            pname, _, model = model_key.partition(":")
            provider = self._registry.get(pname)
            if provider is None or self.breaker.is_open(model_key):
                continue
            for attempt in range(settings.llm_max_retries):
                started = time.monotonic()
                try:
                    vectors = await provider.embed(
                        texts, model, timeout_s=self._timeout_for(purpose)
                    )
                    self.breaker.record(model_key, True)
                    await self._account(
                        request=request,
                        model_key=model_key,
                        run_id=run_id,
                        status="ok",
                        prompt_tokens=sum(len(t) // 4 for t in texts),
                        completion_tokens=0,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error_code=None,
                    )
                    return vectors
                except ProviderFatalError as e:
                    self.breaker.record(model_key, False)
                    await self._account(
                        request=request,
                        model_key=model_key,
                        run_id=run_id,
                        status="error",
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error_code=e.code,
                    )
                    break
                except ProviderError:
                    self.breaker.record(model_key, False)
                    if attempt == settings.llm_max_retries - 1:
                        break
                    await asyncio.sleep(0.5 * (2**attempt) + random.uniform(0, 0.25))  # noqa: S311
        raise GatewayError([{"model": m, "error": "embed failed"} for m in chain])

    # ---- parsing ----

    @staticmethod
    def _extract_json(content: str) -> Any | None:
        """Best-effort JSON extraction: direct parse, then fenced, then first
        balanced object."""
        text = content.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None
        return None


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway.from_settings()
    return _gateway


def set_gateway(gw: LLMGateway | None) -> None:
    """Test hook."""
    global _gateway
    _gateway = gw


__all__ = [
    "LLMGateway",
    "GatewayError",
    "CircuitBreaker",
    "get_gateway",
    "set_gateway",
    "decrypt_secret",
]

"""Anthropic Messages API adapter."""

from __future__ import annotations

import httpx

from app.modules.ai.providers.base import LLMProvider, ProviderFatalError, ProviderTransientError

BASE_URL = "https://api.anthropic.com/v1"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, base_url: str | None = None) -> None:
        if api_key is None:
            raise ProviderFatalError(self.name, "API key not configured", "config.missing_key")
        self.api_key = api_key
        self.base_url = (base_url or BASE_URL).rstrip("/")

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
        json_mode: bool,
    ) -> tuple[str, int, int]:
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        rest = [m for m in messages if m["role"] != "system"]
        body = {
            "model": model,
            "system": "\n\n".join(system_parts) or None,
            "messages": [
                {
                    "role": "user" if m["role"] != "assistant" else "assistant",
                    "content": m["content"],
                }
                for m in rest
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body = {k: v for k, v in body.items() if v is not None}
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
                resp = await client.post(f"{self.base_url}/messages", json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise ProviderTransientError(self.name, f"timeout: {e}", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderTransientError(self.name, f"network: {e}", "network") from e

        if resp.status_code != 200:
            cls = (
                ProviderTransientError
                if (resp.status_code == 429 or resp.status_code >= 500)
                else ProviderFatalError
            )
            raise cls(
                self.name, f"HTTP {resp.status_code}: {resp.text[:200]}", f"http.{resp.status_code}"
            )
        data = resp.json()
        try:
            content = "".join(
                block.get("text", "") for block in data["content"] if block.get("type") == "text"
            )
            usage = data.get("usage", {})
            return (
                content,
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
            )
        except (KeyError, TypeError) as e:
            raise ProviderFatalError(self.name, f"malformed response: {e}", "bad_response") from e

    async def embed(self, texts: list[str], model: str, *, timeout_s: float) -> list[list[float]]:
        raise ProviderFatalError(
            self.name, "embeddings not supported; use an embedding provider", "unsupported"
        )

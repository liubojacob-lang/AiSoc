"""OpenAI-compatible chat/embeddings adapter.

One implementation covers OpenAI, DeepSeek, Qwen (DashScope compatible mode)
and Ollama — they all expose ``/chat/completions`` and ``/embeddings``.
"""

from __future__ import annotations

import httpx

from app.modules.ai.providers.base import LLMProvider, ProviderFatalError, ProviderTransientError

DEFAULT_BASE_URLS: dict[str, str | None] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "ollama": None,  # must come from settings.ollama_base_url
}


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self, provider_key: str, api_key: str | None, base_url: str | None) -> None:
        self.provider_key = provider_key
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URLS.get(provider_key) or "").rstrip("/")
        if not self.base_url:
            raise ProviderFatalError(
                provider_key, "no base_url configured (set it via settings)", "config.missing"
            )
        if self.api_key is None and provider_key != "ollama":
            raise ProviderFatalError(provider_key, "API key not configured", "config.missing_key")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _error(self, resp: httpx.Response) -> Exception:
        if resp.status_code in (408, 429) or resp.status_code >= 500:
            return ProviderTransientError(
                self.provider_key,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                f"http.{resp.status_code}",
            )
        return ProviderFatalError(
            self.provider_key,
            f"HTTP {resp.status_code}: {resp.text[:200]}",
            f"http.{resp.status_code}",
        )

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
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=body, headers=self._headers()
                )
        except httpx.TimeoutException as e:
            raise ProviderTransientError(self.provider_key, f"timeout: {e}", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderTransientError(self.provider_key, f"network: {e}", "network") from e

        if resp.status_code != 200:
            raise self._error(resp)
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            return (
                content,
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
            )
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderFatalError(
                self.provider_key, f"malformed response: {e}", "bad_response"
            ) from e

    async def embed(self, texts: list[str], model: str, *, timeout_s: float) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": model, "input": texts},
                    headers=self._headers(),
                )
        except httpx.TimeoutException as e:
            raise ProviderTransientError(self.provider_key, f"timeout: {e}", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderTransientError(self.provider_key, f"network: {e}", "network") from e

        if resp.status_code != 200:
            raise self._error(resp)
        data = resp.json()
        try:
            rows = sorted(data["data"], key=lambda d: d["index"])
            return [row["embedding"] for row in rows]
        except (KeyError, TypeError) as e:
            raise ProviderFatalError(
                self.provider_key, f"malformed response: {e}", "bad_response"
            ) from e

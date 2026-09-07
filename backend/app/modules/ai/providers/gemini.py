"""Google Gemini generateContent adapter."""

from __future__ import annotations

import httpx

from app.modules.ai.providers.base import LLMProvider, ProviderFatalError, ProviderTransientError

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    name = "gemini"

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
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            contents.append(
                {
                    "role": "model" if m["role"] == "assistant" else "user",
                    "parts": [{"text": m["content"]}],
                }
            )
        generation = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        body: dict = {"contents": contents, "generationConfig": generation}
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/models/{model}:generateContent?key={self.api_key}",
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
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
                part.get("text", "") for part in data["candidates"][0]["content"]["parts"]
            )
            usage = data.get("usageMetadata", {})
            return (
                content,
                int(usage.get("promptTokenCount", 0)),
                int(usage.get("candidatesTokenCount", 0)),
            )
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderFatalError(self.name, f"malformed response: {e}", "bad_response") from e

    async def embed(self, texts: list[str], model: str, *, timeout_s: float) -> list[list[float]]:
        out: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
                for text in texts:
                    resp = await client.post(
                        f"{self.base_url}/models/{model}:embedContent?key={self.api_key}",
                        json={"model": f"models/{model}", "content": {"parts": [{"text": text}]}},
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code != 200:
                        cls = (
                            ProviderTransientError
                            if (resp.status_code == 429 or resp.status_code >= 500)
                            else ProviderFatalError
                        )
                        raise cls(self.name, f"HTTP {resp.status_code}", f"http.{resp.status_code}")
                    out.append(resp.json()["embedding"]["values"])
        except httpx.TimeoutException as e:
            raise ProviderTransientError(self.name, f"timeout: {e}", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderTransientError(self.name, f"network: {e}", "network") from e
        return out

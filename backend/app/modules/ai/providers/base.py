"""Provider abstraction + error taxonomy.

Transport semantics every adapter must honor:
- ``ProviderTransientError``: worth retrying (429 / 5xx / network / timeout)
- ``ProviderFatalError``: never retry (bad request, bad key, unknown model)
Tokens are always (prompt_tokens, completion_tokens) ints when available.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Base. ``retryable`` tells the gateway whether backoff-retry applies."""

    retryable: bool = False

    def __init__(self, provider: str, message: str, code: str = "provider.error") -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.code = code


class ProviderTransientError(ProviderError):
    retryable = True


class ProviderFatalError(ProviderError):
    retryable = False


class LLMProvider(ABC):
    """Uniform interface every vendor adapter implements."""

    name: str = "abstract"

    @abstractmethod
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
        """Returns (content, prompt_tokens, completion_tokens)."""

    @abstractmethod
    async def embed(self, texts: list[str], model: str, *, timeout_s: float) -> list[list[float]]:
        """Returns one vector per input text."""

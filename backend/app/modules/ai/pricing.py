"""Token pricing. Approximate list prices (USD per 1k tokens); override via
settings.llm_price_table JSON (model_key -> {prompt, completion}).

Prices change constantly — this table drives *relative* cost dashboards and
budget breakers, not invoices. Update via config, not code.
"""

from __future__ import annotations

import json
from decimal import Decimal

from app.core.config import settings

DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gpt-4.1": {"prompt": 0.002, "completion": 0.008},
    "gpt-4.1-mini": {"prompt": 0.0004, "completion": 0.0016},
    "text-embedding-3-small": {"prompt": 0.00002, "completion": 0.0},
    "claude-sonnet-4": {"prompt": 0.003, "completion": 0.015},
    "gemini-2.5-pro": {"prompt": 0.00125, "completion": 0.01},
    "gemini-2.5-flash": {"prompt": 0.0003, "completion": 0.0025},
    "qwen-max": {"prompt": 0.0016, "completion": 0.0064},
    "qwen-plus": {"prompt": 0.0004, "completion": 0.0012},
    "deepseek-chat": {"prompt": 0.00027, "completion": 0.0011},
}


def load_prices() -> dict[str, dict[str, float]]:
    try:
        override = json.loads(settings.llm_price_table)
    except json.JSONDecodeError:
        override = {}
    return {**DEFAULT_PRICES, **override}


def cost_usd(
    prices: dict[str, dict[str, float]], model_key: str, prompt_tokens: int, completion_tokens: int
) -> Decimal:
    p = prices.get(model_key)
    if not p:
        return Decimal("0")
    cost = prompt_tokens / 1000 * p.get("prompt", 0) + completion_tokens / 1000 * p.get(
        "completion", 0
    )
    return Decimal(round(cost, 6))

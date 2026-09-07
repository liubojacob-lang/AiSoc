"""Prometheus metrics shared across API and workers."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_LATENCY = Histogram(
    "aisoc_http_request_seconds",
    "HTTP request latency",
    ["method", "route", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

AI_CALLS = Counter(
    "aisoc_ai_calls_total",
    "LLM provider calls",
    ["provider", "model", "purpose", "status"],  # ok|timeout|error|rate_limited| breaker_open
)

AI_TOKENS = Counter(
    "aisoc_ai_tokens_total",
    "LLM tokens consumed",
    ["provider", "model", "kind"],  # prompt|completion
)

AI_COST_USD = Counter(
    "aisoc_ai_cost_usd_total",
    "LLM cost in USD (price-table based)",
    ["provider", "model"],
)

AI_LATENCY = Histogram(
    "aisoc_ai_latency_seconds",
    "LLM call latency",
    ["provider", "model"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

TRIAGE_RUNS = Counter(
    "aisoc_triage_runs_total",
    "Alert triage runs",
    ["status"],  # succeeded|failed|timeout|degraded
)

CELERY_QUEUE_DEPTH = Gauge(
    "aisoc_celery_queue_depth",
    "Messages waiting in a Celery queue",
    ["queue"],
)

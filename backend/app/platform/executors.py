"""Pluggable action executors.

Configured via ``system_configs['action.executors']`` JSON:
    {"block_ip": {"type": "webhook", "url": "https://fw.internal/api/block"}, ...}

Two executor types:
- ``webhook``: POST the action payload to the configured URL. Non-2xx or
  transport error → execution failure (recorded, retryable).
- ``manual`` (default): no automated integration configured — the approval
  record becomes a signed handoff to the runbook owner. Honest by design:
  we never pretend a control was enforced when it wasn't.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.ops import SystemConfig

log = get_logger("executors")

KNOWN_ACTIONS = {
    "block_ip",
    "block_domain",
    "isolate_host",
    "reset_password",
    "disable_account",
    "monitor",
}


async def _executor_config(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(SystemConfig, "action.executors")
    if row is None or not isinstance(row.value, dict):
        return {}
    return row.value


async def execute_action(
    session: AsyncSession,
    *,
    action: str,
    target: str | None,
    approval_id: uuid.UUID,
    alert_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Run the configured executor. Returns the execution record (mode + outcome).
    Raises nothing: failures are returned as ``{"mode": ..., "error": ...}`` so
    the caller can persist an EXECUTION_FAILED state."""
    cfgs = await _executor_config(session)
    cfg = cfgs.get(action) or {"type": "manual"}
    payload = {
        "approval_id": str(approval_id),
        "alert_id": str(alert_id) if alert_id else None,
        "action": action,
        "target": target,
    }

    if cfg.get("type") == "webhook" and cfg.get("url"):
        url = str(cfg["url"])
        secret = cfg.get("secret")
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-AISOC-Secret"] = str(secret)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if 200 <= resp.status_code < 300:
                return {
                    "mode": "webhook",
                    "status_code": resp.status_code,
                    "detail": resp.text[:300],
                }
            return {
                "mode": "webhook",
                "error": f"executor returned HTTP {resp.status_code}",
                "detail": resp.text[:300],
            }
        except httpx.HTTPError as e:
            log.warning("action_webhook_failed", action=action, error=str(e))
            return {"mode": "webhook", "error": f"transport error: {e.__class__.__name__}"}

    # manual handoff (default)
    return {
        "mode": "manual",
        "note": (
            "no automated executor configured for this action; "
            "record this approval as an instruction to the runbook owner"
        ),
        "action": action,
        "target": target,
    }

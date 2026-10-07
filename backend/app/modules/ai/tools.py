"""Triage agent tool registry.

Hard rules (docs/ARCHITECTURE.md §6):
- Whitelist: only tools registered here are callable, and each has a strict
  Pydantic args model — the LLM cannot invent parameters or tools.
- Read-only: all query tools hit our own DB. The single no-side-effect tool
  (propose_action) only records a suggestion; enforcement requires a human.
- No free network access: the agent has no HTTP client at all.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.alerts import Alert
from app.models.ops import Asset, ThreatIntel
from app.modules.ai import rag


class ToolArgs(BaseModel):
    """Base for all tool arg models."""


class ThreatIntelArgs(ToolArgs):
    ioc: str = Field(description="IP, domain, or file hash to look up")


class AssetArgs(ToolArgs):
    identifier: str = Field(description="IP or hostname of the asset")


class SimilarAlertsArgs(ToolArgs):
    src_ip: str | None = Field(default=None, description="source IP to match")
    alert_type: str | None = Field(default=None, description="alert type to match")


class KnowledgeArgs(ToolArgs):
    query: str = Field(description="natural-language search over playbooks/knowledge")


class ProposeActionArgs(ToolArgs):
    action: str = Field(description="e.g. block_ip | isolate_host | reset_password | monitor")
    target: str | None = Field(default=None, description="what the action applies to")
    reason: str = Field(description="why this action is recommended")


@dataclass
class ToolContext:
    session: AsyncSession
    tenant_id: uuid.UUID
    alert: Alert


@dataclass
class ToolSpec[ArgsT: ToolArgs]:
    name: str
    description: str
    args_model: type[ArgsT]
    fn: Callable[[ToolContext, ArgsT], Awaitable[dict[str, Any]]]


# ---------- implementations (all read-only) ----------


async def _query_threat_intel(ctx: ToolContext, args: ThreatIntelArgs) -> dict:
    rows = (
        (
            await ctx.session.execute(
                select(ThreatIntel).where(
                    ThreatIntel.tenant_id == ctx.tenant_id,
                    func.lower(ThreatIntel.ioc) == args.ioc.lower(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"known": False, "ioc": args.ioc, "note": "no local intel record"}
    best = max(rows, key=lambda r: r.reputation)
    return {
        "known": True,
        "ioc": args.ioc,
        "reputation": best.reputation,  # 0-100, >=70 is considered malicious
        "tags": best.tags,
        "source": best.source,
        "first_seen_at": best.first_seen_at.isoformat() if best.first_seen_at else None,
        "last_seen_at": best.last_seen_at.isoformat() if best.last_seen_at else None,
    }


async def _query_asset(ctx: ToolContext, args: AssetArgs) -> dict:
    row = (
        await ctx.session.execute(
            select(Asset).where(
                Asset.tenant_id == ctx.tenant_id,
                func.lower(Asset.identifier) == args.identifier.lower(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"known": False, "identifier": args.identifier, "note": "asset not inventoried"}
    return {
        "known": True,
        "identifier": row.identifier,
        "kind": row.kind,
        "display_name": row.display_name,
        "criticality": row.criticality,  # low|medium|high
        "owner": row.owner,
        "tags": row.tags,
    }


async def _search_similar_alerts(ctx: ToolContext, args: SimilarAlertsArgs) -> dict:
    since = utcnow() - timedelta(days=90)
    conds = [Alert.tenant_id == ctx.tenant_id, Alert.occurred_at >= since]
    if args.src_ip:
        conds.append(Alert.src_ip == args.src_ip)
    if args.alert_type:
        conds.append(Alert.alert_type == args.alert_type)
    if not args.src_ip and not args.alert_type:
        return {"error": "provide src_ip and/or alert_type"}
    rows = (
        (
            await ctx.session.execute(
                select(Alert).where(*conds).order_by(Alert.occurred_at.desc()).limit(50)
            )
        )
        .scalars()
        .all()
    )
    others = [a for a in rows if a.id != ctx.alert.id]
    verdicts = [a.confirmed_as for a in others if a.confirmed_as]
    return {
        "matched": len(others),
        "confirmed_distribution": {
            "true_positive": verdicts.count("true_positive"),
            "false_positive": verdicts.count("false_positive"),
        },
        "samples": [
            {
                "title": a.title,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "status": a.status,
                "occurred_at": a.occurred_at.isoformat(),
            }
            for a in others[:5]
        ],
    }


async def _search_knowledge(ctx: ToolContext, args: KnowledgeArgs) -> dict:
    from app.modules.ai.gateway import get_gateway

    results = await rag.retrieve(
        ctx.session, get_gateway(), query=args.query, k=4, tenant_id=ctx.tenant_id
    )
    if not results:
        return {"matches": 0, "note": "no relevant knowledge base content"}
    return {
        "matches": len(results),
        "results": [
            {
                "content": r["content"][:1200],
                "score": r["score"],
                "document_id": r["document_id"],
                "heading": (r.get("meta") or {}).get("heading"),
            }
            for r in results
        ],
    }


async def _list_alert_context(ctx: ToolContext, _args: ToolArgs) -> dict:
    a = ctx.alert
    related = (
        (
            await ctx.session.execute(
                select(Alert)
                .where(
                    Alert.tenant_id == ctx.tenant_id,
                    Alert.src_ip == a.src_ip,
                    Alert.id != a.id,
                    Alert.occurred_at >= a.occurred_at - timedelta(hours=24),
                    Alert.occurred_at <= a.occurred_at + timedelta(hours=24),
                )
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return {
        "alert": {
            "title": a.title,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "src_ip": str(a.src_ip) if a.src_ip else None,
            "dst_ip": str(a.dst_ip) if a.dst_ip else None,
            "src_host": a.src_host,
            "user_account": a.user_account,
            "occurred_at": a.occurred_at.isoformat(),
            "description": (a.description or "")[:800],
        },
        "related_alerts_same_src_24h": [
            {"title": r.title, "alert_type": r.alert_type, "occurred_at": r.occurred_at.isoformat()}
            for r in related
        ],
    }


async def _propose_action(ctx: ToolContext, args: ProposeActionArgs) -> dict:
    # deliberately side-effect free: the suggestion is stored with the run and
    # surfaced in the UI; execution always requires human approval.
    return {
        "recorded": True,
        "requires_approval": True,
        "action": args.action,
        "target": args.target,
        "reason": args.reason,
    }


_SPECS: list[ToolSpec[Any]] = [

        ToolSpec(
            "query_threat_intel",
            "Look up an IP/domain/hash in the local threat-intel store (reputation 0-100, tags).",
            ThreatIntelArgs,
            _query_threat_intel,
        ),
        ToolSpec(
            "query_asset",
            "Look up an asset by IP/hostname: kind, criticality, owner, tags.",
            AssetArgs,
            _query_asset,
        ),
        ToolSpec(
            "search_similar_alerts",
            "Find similar alerts (last 90 days) by src_ip and/or alert_type, with human verdict distribution.",
            SimilarAlertsArgs,
            _search_similar_alerts,
        ),
        ToolSpec(
            "search_knowledge",
            "Semantic search over the knowledge base (playbooks, response plans). Returns cited chunks.",
            KnowledgeArgs,
            _search_knowledge,
        ),
        ToolSpec(
            "list_alert_context",
            "Show the full alert and related alerts from the same source within 24h.",
            ToolArgs,
            _list_alert_context,
        ),
        ToolSpec(
            "propose_action",
            "Record a RECOMMENDED response action (e.g. block_ip). Requires human approval; does not execute.",
            ProposeActionArgs,
            _propose_action,
        ),
]

REGISTRY: dict[str, ToolSpec[Any]] = {spec.name: spec for spec in _SPECS}


def tool_docs() -> str:
    return "\n".join(
        f"- {name}: {spec.description} args: {list(spec.args_model.model_fields)}"
        for name, spec in REGISTRY.items()
    )


@dataclass
class ToolResult:
    ok: bool
    payload: dict = field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0


async def execute_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
    """Whitelist + strict args validation + latency. Never raises."""
    started = time.monotonic()
    spec = REGISTRY.get(name)
    if spec is None:
        return ToolResult(ok=False, error=f"unknown tool: {name}")
    try:
        parsed = spec.args_model.model_validate(args)
    except Exception as e:  # pydantic ValidationError
        return ToolResult(
            ok=False,
            error=f"invalid args for {name}: {e}",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    try:
        payload = await spec.fn(ctx, parsed)
        return ToolResult(
            ok=True,
            payload=payload,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as e:  # noqa: BLE001 - tool failure is an observation, not a crash
        return ToolResult(
            ok=False,
            error=f"tool {name} failed: {e}",
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def observations_to_text(results: list[tuple[str, ToolResult]]) -> str:
    lines = []
    for name, res in results:
        if res.ok:
            lines.append(f"[{name}] {json.dumps(res.payload, ensure_ascii=False)[:1500]}")
        else:
            lines.append(f"[{name}] ERROR: {res.error}")
    return "\n".join(lines) or "(no tool calls yet)"

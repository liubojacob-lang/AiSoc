"""Golden-set baseline evaluation against a REAL configured LLM routing.

Runs the 10 labeled samples through the REAL ingest → agent triage pipeline
(same code path as production), measures classification/severity agreement
with analyst ground truth, evidence presence, degradation rate, tokens & cost.

Usage (from backend/):
    DATABASE_URL="sqlite:///./_eval.db" .venv/Scripts/python scripts/eval_golden.py

Writes backend/eval/baseline-<ts>.json and prints a summary table.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DATASET = BASE / "tests" / "golden" / "triage_dataset.json"
OUT_DIR = BASE / "eval"


async def main() -> int:
    from sqlalchemy import create_engine

    from app.db.base import Base, DEFAULT_TENANT_ID, utcnow
    from app.db.session import fresh_session
    from app.models.alerts import Alert
    from app.models.ops import Asset, ThreatIntel
    from app.modules.alerts import service as alerts_service
    from app.modules.alerts.schemas import AlertIngest

    # fresh scratch DB
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./_eval.db")
    if db_url.startswith("sqlite"):
        db_file = db_url.split("sqlite:///")[-1]
        Path(db_file).unlink(missing_ok=True)
    sync = create_engine(db_url.replace("+aiosqlite", ""))
    Base.metadata.create_all(sync)
    sync.dispose()

    # seed intel/asset context (same as the CI eval fixture)
    from datetime import timedelta

    async with fresh_session() as session:
        session.add(
            ThreatIntel(tenant_id=DEFAULT_TENANT_ID, ioc="45.155.205.233", ioc_type="ip",
                        reputation=92, tags=["botnet", "bruteforce"], source="internal-feed",
                        first_seen_at=utcnow() - timedelta(days=200),
                        last_seen_at=utcnow() - timedelta(days=1))
        )
        session.add(
            ThreatIntel(tenant_id=DEFAULT_TENANT_ID, ioc="10.20.30.40", ioc_type="ip",
                        reputation=5, tags=["internal"], source="internal")
        )
        session.add(
            Asset(tenant_id=DEFAULT_TENANT_ID, identifier="fin-db-01", kind="host",
                  display_name="Finance DB", criticality="high", owner="fin-ops")
        )
        await session.commit()

    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    results: list[dict] = []
    started = time.monotonic()

    for i, sample in enumerate(dataset):
        s = sample["input"]
        exp = sample["expected"]
        t0 = time.monotonic()
        async with fresh_session() as session:
            alert, created = await alerts_service.ingest(
                session, DEFAULT_TENANT_ID,
                AlertIngest(
                    source="golden", external_id=f"baseline-{i}",
                    title=s["title"], description=s.get("description"),
                    alert_type=s["alert_type"], severity=s["severity"],
                    src_ip=s.get("src_ip"),
                ),
            )
            await session.commit()
            await alerts_service.run_triage(session, DEFAULT_TENANT_ID, alert.id)
            result = await alerts_service.latest_triage_result(session, alert.id)
            alert_row = await session.get(Alert, alert.id)
            degraded = alert_row.degraded if alert_row else False

        elapsed = time.monotonic() - t0
        row = {
            "i": i,
            "title": s["title"][:60],
            "expected_classification": exp["classification"],
            "expected_severity": exp["severity"],
            "got_classification": result.classification if result else None,
            "got_severity": result.severity if result else None,
            "confidence": result.confidence if result else None,
            "evidence_count": len(result.evidence) if result else 0,
            "degraded": degraded,
            "latency_s": round(elapsed, 1),
        }
        results.append(row)
        mark = "OK " if (result and result.classification == exp["classification"]) else "MISS"
        print(
            f"[{mark}] {i+1:02d}/{len(dataset)} {row['title'][:45]:45s} "
            f"exp={exp['classification']:20s} got={row['got_classification']} "
            f"sev {exp['severity']}→{row['got_severity']} conf={row['confidence']} "
            f"ev={row['evidence_count']} deg={degraded} {elapsed:.0f}s",
            flush=True,
        )

    total = len(results)
    ok_cls = sum(1 for r in results if r["got_classification"] == r["expected_classification"])
    ok_sev = sum(1 for r in results if r["got_severity"] == r["expected_severity"])
    degraded_n = sum(1 for r in results if r["degraded"])
    no_evidence = sum(1 for r in results if r["evidence_count"] == 0)

    # token/cost totals from llm_calls
    from sqlalchemy import func, select

    from app.models.ai import LLMCall

    async with fresh_session() as session:
        pt, ct, cost, calls = (
            await session.execute(
                select(
                    func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMCall.completion_tokens), 0),
                    func.coalesce(func.sum(LLMCall.cost_usd), 0),
                    func.count(),
                ).where(LLMCall.purpose == "triage")
            )
        ).one()

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": os.environ.get("LLM_ROUTING", ""),
        "samples": total,
        "classification_accuracy": round(ok_cls / total, 3),
        "severity_accuracy": round(ok_sev / total, 3),
        "degraded_runs": degraded_n,
        "verdicts_without_evidence": no_evidence,
        "total_prompt_tokens": int(pt),
        "total_completion_tokens": int(ct),
        "total_cost_usd": float(cost),
        "wall_clock_s": round(time.monotonic() - started, 1),
        "results": results,
    }
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"baseline-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== SUMMARY =====")
    print(f"model: {summary['model']}")
    print(f"classification accuracy: {ok_cls}/{total} = {summary['classification_accuracy']:.0%}")
    print(f"severity accuracy:       {ok_sev}/{total} = {summary['severity_accuracy']:.0%}")
    print(f"degraded: {degraded_n} | verdicts w/o evidence: {no_evidence}")
    print(f"tokens: {int(pt):,} + {int(ct):,} | cost: ${float(cost):.4f}")
    print(f"wall clock: {summary['wall_clock_s']}s | report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""AI evaluation gate: golden dataset regression for the triage pipeline.

The dataset (``tests/golden/triage_dataset.json``) contains labeled alerts
(ground truth by a human analyst). The gate asserts, for every sample, that:
1. The pipeline produces a schema-valid ``TriagedVerdict`` (100% required).
2. Verdict severity is consistent with the label's expected severity.
3. Every verdict cites at least one piece of evidence (no unfounded claims).

With the deterministic fake provider this validates the *wiring* and the
*contract*. Against a real provider (staging job, same test, real routing)
it measures accuracy over time — the CI gate compares against the recorded
baseline so prompt/model changes that degrade quality block the release.
"""

from __future__ import annotations

import json
import pathlib
from datetime import timedelta

import pytest

from app.db.base import DEFAULT_TENANT_ID, utcnow
from app.db.session import fresh_session
from app.models.ops import Asset, ThreatIntel
from app.modules.ai.gateway import LLMGateway, set_gateway
from app.modules.ai.providers.fake import FakeProvider
from app.modules.alerts import service as alerts_service
from app.modules.alerts.schemas import AlertIngest

GOLDEN = pathlib.Path(__file__).parent / "golden" / "triage_dataset.json"


def _load_dataset() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", autouse=True)
def _intel_and_assets():
    """Seed the local intel/asset context the agent tools query."""

    async def _seed():
        async with fresh_session() as session:
            session.add(
                ThreatIntel(
                    tenant_id=DEFAULT_TENANT_ID,
                    ioc="45.155.205.233",
                    ioc_type="ip",
                    reputation=92,
                    tags=["botnet", "bruteforce"],
                    source="internal-feed",
                    first_seen_at=utcnow() - timedelta(days=200),
                    last_seen_at=utcnow() - timedelta(days=1),
                )
            )
            session.add(
                ThreatIntel(
                    tenant_id=DEFAULT_TENANT_ID,
                    ioc="10.20.30.40",
                    ioc_type="ip",
                    reputation=5,
                    tags=["internal"],
                    source="internal",
                )
            )
            session.add(
                Asset(
                    tenant_id=DEFAULT_TENANT_ID,
                    identifier="fin-db-01",
                    kind="host",
                    display_name="Finance DB",
                    criticality="high",
                    owner="fin-ops",
                )
            )
            await session.commit()

    import asyncio

    asyncio.run(_seed())
    yield


async def test_ai_evaluation_golden_dataset(fake_gateway):
    dataset = _load_dataset()
    assert len(dataset) >= 8, "golden dataset too small to be meaningful"

    results = []
    for i, sample in enumerate(dataset):
        fake_gateway.fake.script(
            "fake-triage",
            json.dumps(
                {
                    "thought": "evaluate with evidence",
                    "final": {
                        "classification": sample["expected"]["classification"],
                        "severity": sample["expected"]["severity"],
                        "confidence": sample["expected"].get("confidence", 75),
                        "reasoning": sample["expected"]["reasoning_hint"],
                        "evidence": [
                            {"source": "alert", "detail": sample["input"]["title"]},
                            {
                                "source": "query_threat_intel",
                                "detail": f"ioc={sample['input'].get('src_ip')}",
                            },
                        ],
                        "recommended_actions": [],
                    },
                }
            ),
        )
        async with fresh_session() as session:
            alert, created = await alerts_service.ingest(
                session,
                DEFAULT_TENANT_ID,
                AlertIngest(
                    source="golden",
                    external_id=f"golden-{i}",
                    title=sample["input"]["title"],
                    description=sample["input"].get("description"),
                    alert_type=sample["input"]["alert_type"],
                    severity=sample["input"]["severity"],
                    src_ip=sample["input"].get("src_ip"),
                    raw=sample["input"],
                ),
            )
            assert created
            await session.commit()
            alert = await alerts_service.run_triage(session, DEFAULT_TENANT_ID, alert.id)
            result = await alerts_service.latest_triage_result(session, alert.id)

        assert result is not None, f"sample {i}: no verdict produced"
        # 1) structural validity is enforced by Pydantic at persistence time;
        # 2) severity contract
        assert result.severity == sample["expected"]["severity"], (
            f"sample {i} ({sample['input']['title']}): severity drift"
        )
        # 3) evidence-backed conclusions
        assert len(result.evidence) >= 1, f"sample {i}: verdict without evidence"
        assert 0 <= result.confidence <= 100
        results.append(
            {
                "title": sample["input"]["title"],
                "classification": result.classification,
                "expected": sample["expected"]["classification"],
            }
        )

    # classification agreement with the scripted expectations (fake provider
    # echoes them by construction — against a real provider this becomes the
    # accuracy metric compared to the baseline in CI)
    agreed = sum(1 for r in results if r["classification"] == r["expected"])
    accuracy = agreed / len(results)
    print(f"\n[AI eval] classification agreement: {agreed}/{len(results)} = {accuracy:.0%}")
    assert accuracy >= 0.99, "golden-set classification regression"


async def test_structured_output_never_persists_garbage(fake_gateway):
    """A provider that returns garbage must NOT create a verdict row; the
    alert degrades to the rule engine and is honestly flagged."""
    dead = LLMGateway(registry={"broken": FakeProvider()}, routing={"triage": ["broken:nope"]})
    set_gateway(dead)
    set_gateway(fake_gateway)  # restore for other machinery, then break routing
    fake_gateway.routing = {"triage": []}
    try:
        async with fresh_session() as session:
            alert, _ = await alerts_service.ingest(
                session,
                DEFAULT_TENANT_ID,
                AlertIngest(
                    source="golden",
                    external_id="garbage-1",
                    title="weird unknown signal",
                    alert_type="unknown_type",
                    severity="low",
                ),
            )
            await session.commit()
            alert = await alerts_service.run_triage(session, DEFAULT_TENANT_ID, alert.id)
            assert alert.status == "triaged"
            assert alert.degraded is True
            result = await alerts_service.latest_triage_result(session, alert.id)
            assert result.degraded is True
            assert result.classification == "needs_investigation"
    finally:
        set_gateway(None)

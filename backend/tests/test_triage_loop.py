"""The core closed loop: ingest → AI triage → report → human confirm → stats.
Plus degraded fallback when the LLM chain is dead."""

from __future__ import annotations

import json

from app.modules.ai.gateway import LLMGateway, set_gateway
from app.modules.ai.providers.fake import FakeProvider


def _alert(n: int, alert_type: str = "brute_force", src: str = "198.51.100.23") -> dict:
    return {
        "source": "edr",
        "external_id": f"edr-{n}",
        "title": f"SSH brute force from {src}",
        "description": "multiple failed logins followed by success",
        "alert_type": alert_type,
        "severity": "high",
        "src_ip": src,
        "raw": {"agent": "host-01"},
    }


async def test_ingest_idempotent(client, api_key_headers, fake_gateway):
    r1 = await client.post("/api/v1/alerts/ingest/alerts", headers=api_key_headers, json=_alert(1))
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/alerts/ingest/alerts", headers=api_key_headers, json=_alert(1))
    assert r2.status_code == 200
    assert r2.headers.get("x-alert-duplicate") == "true"
    assert r2.json()["id"] == r1.json()["id"]


async def test_full_closed_loop(client, api_key_headers, analyst_headers, fake_gateway):
    """ingest → AI triage (scripted) → report with steps → confirm → feedback stats."""
    fake_gateway.fake.script(
        "fake-triage",
        json.dumps(
            {
                "thought": "check intel for the source IP",
                "tool": "query_threat_intel",
                "args": {"ioc": "198.51.100.23"},
            }
        ),
        json.dumps(
            {
                "thought": "enough evidence",
                "final": {
                    "classification": "true_positive",
                    "severity": "high",
                    "confidence": 82,
                    "reasoning": "Source IP is known-bad and pattern matches credential attack.",
                    "evidence": [
                        {"source": "alert", "detail": "brute_force pattern with success"},
                        {"source": "query_threat_intel", "detail": "reputation 95, tag botnet"},
                    ],
                    "recommended_actions": [
                        {
                            "action": "block_ip",
                            "target": "198.51.100.23",
                            "reason": "known malicious source",
                        }
                    ],
                },
            }
        ),
    )
    r = await client.post("/api/v1/alerts/ingest/alerts", headers=api_key_headers, json=_alert(2))
    assert r.status_code == 201
    alert_id = r.json()["id"]

    # inline pipeline already ran: alert must be triaged
    r = await client.get(f"/api/v1/alerts/{alert_id}", headers=analyst_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "triaged"
    assert body["triage"]["classification"] == "true_positive"
    assert body["triage"]["confidence"] == 82
    assert body["triage"]["degraded"] is False

    # replayable report
    r = await client.get(f"/api/v1/alerts/{alert_id}/triage", headers=analyst_headers)
    report = r.json()
    assert report["result"]["run_id"]
    assert len(report["steps"]) == 2
    assert report["steps"][0]["tool"] == "query_threat_intel"
    assert report["steps"][0]["tool_result"]["known"] is False  # empty intel store
    assert report["run"]["total_prompt_tokens"] > 0

    # human confirms true
    r = await client.post(
        f"/api/v1/alerts/{alert_id}/confirm",
        headers=analyst_headers,
        json={"verdict": "true_positive", "reason": "confirmed attacking host in firewall"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed_true"

    # feedback recorded → adoption stats
    r = await client.get("/api/v1/analytics/dashboard", headers=analyst_headers)
    dash = r.json()
    assert dash["ai_adoption_rate"] is not None
    assert dash["ai_adoption_rate"] >= 0.99  # our only feedback agreed
    assert dash["llm_calls_total"] >= 2  # triage steps accounted


async def test_degraded_fallback_when_llm_dead(client, api_key_headers, analyst_headers):
    """Gateway chain dead → rule-based verdict, alert still triaged, honestly
    flagged degraded."""
    dead = LLMGateway(registry={"fake": FakeProvider()}, routing={"triage": []})
    set_gateway(dead)
    try:
        r = await client.post(
            "/api/v1/alerts/ingest/alerts", headers=api_key_headers, json=_alert(3)
        )
        assert r.status_code == 201
        alert_id = r.json()["id"]
        r = await client.get(f"/api/v1/alerts/{alert_id}", headers=analyst_headers)
        body = r.json()
        assert body["status"] == "triaged"
        assert body["degraded"] is True
        assert body["triage"]["degraded"] is True
        assert body["triage"]["classification"] == "needs_investigation"
    finally:
        set_gateway(None)


async def test_confirm_requires_triaged_state(
    client, api_key_headers, analyst_headers, fake_gateway
):
    fake_gateway.fake.script(
        "fake-triage",
        json.dumps(
            {
                "thought": "benign",
                "final": {
                    "classification": "false_positive",
                    "severity": "low",
                    "confidence": 70,
                    "reasoning": "routine admin activity pattern, no intel match.",
                    "evidence": [{"source": "alert", "detail": "single event, off-hours admin"}],
                    "recommended_actions": [],
                },
            }
        ),
    )
    r = await client.post(
        "/api/v1/alerts/ingest/alerts", headers=api_key_headers, json=_alert(4, "policy_violation")
    )
    alert_id = r.json()["id"]
    # double confirm → second must fail (illegal transition)
    r1 = await client.post(
        f"/api/v1/alerts/{alert_id}/confirm",
        headers=analyst_headers,
        json={"verdict": "false_positive", "reason": "benign confirmed"},
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/alerts/{alert_id}/confirm",
        headers=analyst_headers,
        json={"verdict": "true_positive", "reason": "trying again"},
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "alert.not_confirmable"

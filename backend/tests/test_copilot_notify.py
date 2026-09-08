"""Copilot chat + notification tests."""

from __future__ import annotations

import json

# ---------- copilot ----------

async def test_copilot_tool_turn(client, api_key_headers, analyst_headers, fake_gateway):
    # 自造一条高危告警（本文件独立运行时库里可能没有数据）
    r = await client.post("/api/v1/alerts/ingest/alerts", headers=api_key_headers,
                          json={"source": "edr", "external_id": "copilot-seed-1",
                                "title": "Impossible travel login", "alert_type": "account_compromise",
                                "severity": "high", "src_ip": "198.51.100.7"})
    assert r.status_code == 201, r.text
    fake_gateway.fake.script(
        "fake-chat",
        json.dumps({"thought": "查最近高危告警", "tool": "search_alerts",
                    "args": {"severity": "high"}}),
        "最近的高危告警包括 SSH 暴力破解等，建议优先处理暴力破解类。",
    )
    r = await client.post("/api/v1/ai/chat", headers=analyst_headers,
                          json={"question": "现在有哪些高危告警？"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"].startswith("最近的高危告警")
    assert body["model_key"] == "fake:fake-chat"
    # search_alerts 的结果转化为 refs
    assert len(body["refs"]) >= 1
    assert body["refs"][0]["kind"] == "alert"

    conv_id = body["conversation_id"]
    r = await client.get(f"/api/v1/ai/conversations/{conv_id}/messages", headers=analyst_headers)
    roles = [m["role"] for m in r.json()]
    assert roles == ["user", "assistant"]  # tool message is internal
    r = await client.get("/api/v1/ai/conversations", headers=analyst_headers)
    assert any(c["id"] == conv_id for c in r.json())


async def test_copilot_direct_answer(client, analyst_headers, fake_gateway):
    fake_gateway.fake.script(
        "fake-chat",
        json.dumps({"thought": "打招呼无需数据", "tool": None, "args": {},
                    "direct_answer": "你好！我是 AISOC 助手，可以帮你查询告警、事件和知识库。"}),
    )
    r = await client.post("/api/v1/ai/chat", headers=analyst_headers,
                          json={"question": "你好"})
    assert r.status_code == 200
    assert "AISOC 助手" in r.json()["answer"]


async def test_copilot_requires_ai_run_permission(client, viewer_headers):
    r = await client.post("/api/v1/ai/chat", headers=viewer_headers,
                          json={"question": "test"})
    assert r.status_code == 403


# ---------- notifications ----------

async def test_triage_creates_notifications(client, api_key_headers, analyst_headers,
                                            admin_headers, fake_gateway):
    """高危告警 AI 判定为真实攻击 → 分析师收到站内通知。"""
    fake_gateway.fake.script(
        "fake-triage",
        json.dumps({"thought": "critical", "final": {
            "classification": "true_positive", "severity": "critical",
            "confidence": 90, "reasoning": "known bad source confirmed.",
            "evidence": [{"source": "alert", "detail": "brute force"}],
            "recommended_actions": [],
        }}),
    )
    r = await client.post("/api/v1/alerts/ingest/alerts", headers=api_key_headers,
                          json={"source": "edr", "external_id": "notify-001",
                                "title": "Critical brute force", "alert_type": "brute_force",
                                "severity": "critical", "src_ip": "45.155.205.233"})
    assert r.status_code == 201

    r = await client.get("/api/v1/notifications/unread-count", headers=analyst_headers)
    assert r.json()["unread"] >= 1

    r = await client.get("/api/v1/notifications", headers=analyst_headers)
    notes = r.json()
    assert any("brute force" in n["title"] for n in notes)

    # 标记全部已读 → 未归零
    r = await client.post("/api/v1/notifications/read-all", headers=analyst_headers)
    assert r.status_code == 200
    r = await client.get("/api/v1/notifications/unread-count", headers=analyst_headers)
    assert r.json()["unread"] == 0


async def test_incident_creation_notifies(client, analyst_headers, admin_headers):
    r = await client.post("/api/v1/incidents", headers=analyst_headers,
                          json={"title": "Notify test incident", "severity": "high"})
    assert r.status_code == 201
    # 创建者本人被排除（设计行为），其他分析角色（admin）应收到通知
    r = await client.get("/api/v1/notifications", headers=admin_headers)
    assert any("Notify test incident" in n["title"] for n in r.json())

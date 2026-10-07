"""处置审批双人流测试：propose → L1 → L2（禁自批）→ execute；驳回/取消/越权。"""

from __future__ import annotations


async def _mk_alert(client, api_key_headers, ext: str) -> str:
    fake = {"source": "edr", "external_id": ext, "title": "C2 beacon on critical host",
            "alert_type": "malware", "severity": "critical", "src_ip": "10.20.30.40"}
    r = await client.post("/api/v1/alerts/ingest/alerts", headers=api_key_headers, json=fake)
    assert r.status_code in (201, 200), r.text
    return r.json()["id"]


async def _propose(client, analyst_headers, alert_id: str, action: str = "block_ip") -> str:
    r = await client.post(
        f"/api/v1/actions?alert_id={alert_id}",
        headers=analyst_headers,
        json={"action": action, "target": "10.20.30.40",
              "reason": "known malicious source confirmed by intel"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_full_dual_approval_flow(client, api_key_headers, analyst_headers,
                                       admin_headers, fake_gateway):
    alert_id = await _mk_alert(client, api_key_headers, "act-001")
    aid = await _propose(client, analyst_headers, alert_id)

    # proposed 状态可查
    r = await client.get(f"/api/v1/actions/{aid}", headers=analyst_headers)
    assert r.json()["status"] == "proposed"

    # L1: analyst 批准
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=analyst_headers)
    assert r.status_code == 200 and r.json()["status"] == "approved_l1"

    # L2: 同一个人（analyst）自批必须被拒绝
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=analyst_headers)
    assert r.status_code == 403, "L2 requires admin"
    assert r.json()["error"]["code"] == "permission.denied"

    # L2: admin 批准（不同人）
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "approved"

    # 执行（默认 manual 执行器 → 诚实交接记录）
    r = await client.post(f"/api/v1/actions/{aid}/execute", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "executed"
    assert body["execution_mode"] == "manual"
    assert "runbook" in body["execution_result"]["note"]

    # 终态不可再流转
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=admin_headers)
    assert r.status_code == 409


async def test_admin_cannot_be_l1_then_l2_same_person(client, api_key_headers,
                                                      analyst_headers, admin_headers):
    alert_id = await _mk_alert(client, api_key_headers, "act-002")
    aid = await _propose(client, analyst_headers, alert_id)
    # admin 自己做 L1，再做 L2 → 自批拒绝
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=admin_headers)
    assert r.status_code == 200
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "action.self_approval"


async def test_reject_flow(client, api_key_headers, analyst_headers, admin_headers):
    alert_id = await _mk_alert(client, api_key_headers, "act-003")
    aid = await _propose(client, analyst_headers, alert_id)
    r = await client.post(f"/api/v1/actions/{aid}/reject", headers=admin_headers,
                          json={"reason": "target wrong, use perimeter firewall instead"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # rejected 终态：不可批准
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=admin_headers)
    assert r.status_code == 409


async def test_proposer_cancel(client, api_key_headers, analyst_headers):
    alert_id = await _mk_alert(client, api_key_headers, "act-004")
    aid = await _propose(client, analyst_headers, alert_id)
    r = await client.post(f"/api/v1/actions/{aid}/cancel", headers=analyst_headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


async def test_viewer_cannot_propose(client, viewer_headers, api_key_headers,
                                     analyst_headers, fake_gateway):
    alert_id = await _mk_alert(client, api_key_headers, "act-005")
    r = await client.post(
        f"/api/v1/actions?alert_id={alert_id}", headers=viewer_headers,
        json={"action": "monitor", "target": "x", "reason": "just watching"},
    )
    assert r.status_code == 403


async def test_propose_invalid_action_rejected(client, api_key_headers, analyst_headers, fake_gateway):
    alert_id = await _mk_alert(client, api_key_headers, "act-006")
    r = await client.post(
        f"/api/v1/actions?alert_id={alert_id}", headers=analyst_headers,
        json={"action": "nuke_datacenter", "target": "all", "reason": "trying something invalid"},
    )
    assert r.status_code == 422

"""Incident state machine + knowledge base RAG tests."""

from __future__ import annotations

# ---------- incidents ----------


async def _mk_incident(client, headers) -> str:
    r = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Ransomware outbreak finance", "severity": "critical"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_incident_illegal_transition(client, analyst_headers):
    inc = await _mk_incident(client, analyst_headers)
    r = await client.post(
        f"/api/v1/incidents/{inc}/transition",
        headers=analyst_headers,
        json={"to_status": "closed", "reason": "skipping everything"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "incident.illegal_transition"


async def test_incident_full_picerl_flow(client, analyst_headers):
    inc = await _mk_incident(client, analyst_headers)
    for status in ["investigating", "contained", "eradicated", "recovered"]:
        r = await client.post(
            f"/api/v1/incidents/{inc}/transition",
            headers=analyst_headers,
            json={"to_status": status, "reason": "step done"},
        )
        assert r.status_code == 200, (status, r.text)
    # close without summary refused
    r = await client.post(
        f"/api/v1/incidents/{inc}/transition",
        headers=analyst_headers,
        json={"to_status": "closed", "reason": "done"},
    )
    assert r.status_code == 422
    r = await client.post(
        f"/api/v1/incidents/{inc}/transition",
        headers=analyst_headers,
        json={
            "to_status": "closed",
            "reason": "done",
            "close_summary": "root cause fixed, hosts rebuilt",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "closed"


async def test_task_blocked_requires_reason(client, analyst_headers):
    inc = await _mk_incident(client, analyst_headers)
    r = await client.post(
        f"/api/v1/incidents/{inc}/tasks",
        headers=analyst_headers,
        json={"title": "Isolate host-07"},
    )
    task_id = r.json()["id"]
    # todo -> blocked is not an allowed transition (must go through in_progress)
    r = await client.post(
        f"/api/v1/incidents/tasks/{task_id}/transition",
        headers=analyst_headers,
        json={"to_status": "blocked", "reason": "trying to skip states"},
    )
    assert r.status_code == 409
    r = await client.post(
        f"/api/v1/incidents/tasks/{task_id}/transition",
        headers=analyst_headers,
        json={"to_status": "in_progress"},
    )
    assert r.status_code == 200
    # blocked without reason refused
    r = await client.post(
        f"/api/v1/incidents/tasks/{task_id}/transition",
        headers=analyst_headers,
        json={"to_status": "blocked"},
    )
    assert r.status_code == 422
    r = await client.post(
        f"/api/v1/incidents/tasks/{task_id}/transition",
        headers=analyst_headers,
        json={"to_status": "blocked", "reason": "waiting for change window"},
    )
    assert r.status_code == 200
    assert r.json()["blocked_reason"] == "waiting for change window"


async def test_incident_comments(client, analyst_headers):
    inc = await _mk_incident(client, analyst_headers)
    r = await client.post(
        f"/api/v1/incidents/{inc}/comments",
        headers=analyst_headers,
        json={"body": "EMSIFF started"},
    )
    assert r.status_code == 201
    r = await client.get(f"/api/v1/incidents/{inc}/comments", headers=analyst_headers)
    assert len(r.json()) == 1


async def test_viewer_cannot_create_incident(client, viewer_headers):
    r = await client.post(
        "/api/v1/incidents", headers=viewer_headers, json={"title": "x", "severity": "low"}
    )
    assert r.status_code == 403


# ---------- knowledge base ----------

PLAYBOOK = """# Brute Force Response Playbook

## Identification
Confirm source is not a corporate VPN exit. Check auth logs for account lockouts.

## Containment
Block source IP at the perimeter firewall. Force password reset for the targeted account.

## Eradication
Review for successful logins; if success observed, treat as compromise and rebuild host.
"""


async def test_kb_upload_ask_flow(client, analyst_headers, fake_gateway):
    files = {"file": ("playbook.md", PLAYBOOK.encode(), "text/markdown")}
    r = await client.post(
        "/api/v1/kb/documents?title=Brute%20Force%20Playbook",
        headers=analyst_headers,
        files=files,
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "indexed", doc  # inline indexing
    assert doc["chunk_count"] >= 1

    r = await client.get("/api/v1/kb/documents", headers=analyst_headers)
    assert any(d["id"] == doc["id"] for d in r.json())

    # grounded ask: scripted answer must reference the retrieval context
    fake_gateway.fake.script(
        "fake-chat",
        "依据 Playbook [1]：在防火墙封禁来源 IP，并重置目标账户密码（Containment 部分）。",
    )
    r = await client.post(
        "/api/v1/kb/ask",
        headers=analyst_headers,
        json={"question": "What are the containment steps in the brute force response playbook?"},
    )
    body = r.json()
    assert body["degraded"] is False
    assert "[1]" in body["answer"]
    assert len(body["citations"]) >= 1
    assert "Playbook" in body["citations"][0]["document_title"]

    # duplicate upload refused
    r = await client.post(
        "/api/v1/kb/documents?title=dup",
        headers=analyst_headers,
        files={"file": ("playbook2.md", PLAYBOOK.encode(), "text/markdown")},
    )
    assert r.status_code == 422


async def test_kb_ask_empty_state(client, analyst_headers, fake_gateway):
    r = await client.post(
        "/api/v1/kb/ask", headers=analyst_headers, json={"question": "什么是量子密钥分发?"}
    )
    body = r.json()
    assert body["citations"] == []
    assert "没有" in body["answer"]

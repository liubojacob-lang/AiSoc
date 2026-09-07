"""Auth flow + RBAC enforcement tests."""

from __future__ import annotations

ALERT = {
    "source": "waf",
    "external_id": "waf-001",
    "title": "SQL injection attempt",
    "alert_type": "sql_injection",
    "severity": "high",
    "src_ip": "203.0.113.66",
}


async def test_health(client):
    r = await client.get("/api/v1/healthz")
    assert r.status_code == 200


async def test_login_wrong_password(client):
    r = await client.post(
        "/api/v1/auth/login", json={"email": "admin@aisoc.dev", "password": "definitely-wrong-1"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.bad_credentials"


async def test_me_requires_auth(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_login_me_flow(client, admin_headers):
    r = await client.get("/api/v1/auth/me", headers=admin_headers)
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "admin@aisoc.dev"
    assert "admin" in me["roles"]


async def test_refresh_rotation(client):
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@aisoc.dev", "password": "test-admin-password-123"},
    )
    refresh_cookie = login.cookies.get("aisoc_refresh")
    assert refresh_cookie, "refresh cookie must be set"

    r1 = await client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    # reuse the OLD (rotated-out) token → reuse detection revokes the family
    client.cookies.set("aisoc_refresh", refresh_cookie)
    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "auth.refresh_reuse"


async def test_rbac_viewer_cannot_write(client, viewer_headers):
    r = await client.get("/api/v1/alerts", headers=viewer_headers)
    assert r.status_code == 200  # read ok
    r = await client.post(
        "/api/v1/alerts/00000000-0000-0000-0000-000000000000/confirm",
        headers=viewer_headers,
        json={"verdict": "false_positive", "reason": "test"},
    )
    assert r.status_code == 403


async def test_rbac_analyst_cannot_manage_users(client, analyst_headers):
    r = await client.get("/api/v1/auth/users", headers=analyst_headers)
    assert r.status_code == 403


async def test_rbac_analyst_can_read(client, analyst_headers):
    r = await client.get("/api/v1/alerts", headers=analyst_headers)
    assert r.status_code == 200


async def test_api_key_scoped(client, api_key_headers):
    # api key works on ingest…
    r = await client.post("/api/v1/alerts/ingest/alerts", headers=api_key_headers, json=ALERT)
    assert r.status_code == 201, r.text
    # …but not on user-facing routes (no bearer token)
    r = await client.get("/api/v1/alerts", headers=api_key_headers)
    assert r.status_code == 401


async def test_account_lockout_after_5_failures(client, admin_headers):
    # dedicated user so the lockout never poisons other tests in this session
    r = await client.post(
        "/api/v1/auth/users",
        headers=admin_headers,
        json={
            "email": "lockme@aisoc.dev",
            "password": "lockme-password-123",
            "display_name": "Lock Me",
            "roles": ["viewer"],
        },
    )
    assert r.status_code == 201, r.text
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/login", json={"email": "lockme@aisoc.dev", "password": "wrong-password-x"}
        )
        assert r.status_code in (401, 423)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "lockme@aisoc.dev", "password": "lockme-password-123"}
    )
    assert r.status_code == 423, "correct password must be refused while locked"

"""Test configuration.

Environment is pinned BEFORE any app import (settings are import-time).
DB: file-based sqlite (migrations verified separately); tasks run inline;
LLM: deterministic fake gateway injected per-test via ``set_gateway``.
"""

from __future__ import annotations

import os
import pathlib

# --- must be set before importing app modules ---
os.environ["ENV"] = "test"
os.environ["TASK_INLINE"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_test_aisoc.db"
os.environ["LLM_ROUTING"] = (
    '{"triage":["fake:fake-triage"],"embed":["fake:fake-embed"],"chat":["fake:fake-chat"]}'
)
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "test-admin-password-123"

import asyncio  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

DB_PATH = pathlib.Path("./_test_aisoc.db")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Fresh schema per test session."""
    from app.db import seed
    from app.db.base import Base

    DB_PATH.unlink(missing_ok=True)
    sync = create_engine("sqlite:///./_test_aisoc.db")
    Base.metadata.create_all(sync)
    sync.dispose()

    from app.db.session import get_sessionmaker

    async def _seed():
        maker = get_sessionmaker()
        async with maker() as session:
            await seed.seed(session)

    asyncio.run(_seed())
    yield
    DB_PATH.unlink(missing_ok=True)


@pytest.fixture()
async def client():
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture()
async def fake_gateway():
    """Deterministic gateway; tests script responses per model."""
    from app.modules.ai.gateway import LLMGateway, set_gateway
    from app.modules.ai.providers.fake import FakeProvider

    provider = FakeProvider()
    gw = LLMGateway(
        registry={"fake": provider},
        routing={
            "triage": ["fake:fake-triage"],
            "embed": ["fake:fake-embed"],
            "chat": ["fake:fake-chat"],
        },
    )
    set_gateway(gw)
    gw.fake = provider
    yield gw
    set_gateway(None)


# ---------- auth helpers ----------


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
async def admin_headers(client):
    token = (await _login(client, "admin@aisoc.dev", "test-admin-password-123"))["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def analyst_headers(client, admin_headers):
    r = await client.post(
        "/api/v1/auth/users",
        headers=admin_headers,
        json={
            "email": "analyst@aisoc.dev",
            "password": "analyst-password-123",
            "display_name": "Analyst",
            "roles": ["analyst"],
        },
    )
    if r.status_code == 409:  # already exists from a previous test in session
        token = (await _login(client, "analyst@aisoc.dev", "analyst-password-123"))["access_token"]
    else:
        assert r.status_code == 201, r.text
        token = (await _login(client, "analyst@aisoc.dev", "analyst-password-123"))["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def viewer_headers(client, admin_headers):
    r = await client.post(
        "/api/v1/auth/users",
        headers=admin_headers,
        json={
            "email": "viewer@aisoc.dev",
            "password": "viewer-password-123",
            "display_name": "Viewer",
            "roles": ["viewer"],
        },
    )
    if r.status_code == 409:
        token = (await _login(client, "viewer@aisoc.dev", "viewer-password-123"))["access_token"]
    else:
        assert r.status_code == 201, r.text
        token = (await _login(client, "viewer@aisoc.dev", "viewer-password-123"))["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def api_key_headers(client, admin_headers):
    r = await client.post(
        "/api/v1/auth/api-keys",
        headers=admin_headers,
        json={"name": "test-ingest", "scopes": ["alerts:write"]},
    )
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["plaintext_key"]}

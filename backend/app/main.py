"""AISOC API application assembly."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger, request_id_var
from app.core.metrics import HTTP_LATENCY
from app.db.session import get_sessionmaker
from app.modules.actions.router import router as actions_router
from app.modules.ai.router import router as ai_router
from app.modules.alerts.router import router as alerts_router
from app.modules.analytics.router import router as analytics_router
from app.modules.identity.router import router as identity_router
from app.modules.incidents.router import router as incidents_router
from app.modules.knowledge.router import router as knowledge_router
from app.platform.router import router as notifications_router

log = get_logger("main")

DESCRIPTION = """
AI-Powered Security Operations Center.

* Alert ingestion (API key) → AI triage (agent + tools) → human confirmation
* Incidents, tasks, knowledge base (RAG), dashboards, full audit trail
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level, pretty=not settings.is_prod)
    log.info(
        "starting",
        env=settings.env,
        db=settings.database_url.split("@")[-1],
        task_inline=settings.task_inline,
    )
    if settings.env in ("dev", "test"):
        from app.db import seed

        maker = get_sessionmaker()
        async with maker() as session:
            await seed.seed(session)
    yield
    from app.db.session import dispose_engine

    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request, call_next):
        import time
        import uuid as _uuid

        rid = request.headers.get("x-request-id") or _uuid.uuid4().hex
        request_id_var.set(rid)
        started = time.monotonic()
        response = await call_next(request)
        latency = time.monotonic() - started
        HTTP_LATENCY.labels(request.method, request.url.path, response.status_code).observe(latency)
        response.headers["X-Request-ID"] = rid
        return response

    try:
        from app.core.ratelimit import RateLimitMiddleware

        app.add_middleware(RateLimitMiddleware, redis_client=_make_redis())
    except Exception as e:  # noqa: BLE001 - dev without redis still runs
        log.warning("ratelimit_middleware_disabled", error=str(e))

    for router, prefix in [
        (identity_router, "/auth"),
        (alerts_router, "/alerts"),
        (incidents_router, "/incidents"),
        (knowledge_router, "/kb"),
        (analytics_router, "/analytics"),
        (actions_router, "/actions"),
        (ai_router, "/ai"),
        (notifications_router, "/notifications"),
    ]:
        app.include_router(
            router,
            prefix=f"{settings.api_prefix}{prefix}",
            tags=[
                {
                    "auth": "auth",
                    "alerts": "alerts",
                    "incidents": "incidents",
                    "kb": "knowledge",
                    "analytics": "analytics",
                    "actions": "actions",
                    "ai": "ai",
                    "notifications": "notifications",
                }[prefix.strip("/")],
            ],
        )

    @app.get(f"{settings.api_prefix}/healthz", tags=["ops"])
    async def healthz():
        return {"status": "ok"}

    @app.get(f"{settings.api_prefix}/readyz", tags=["ops"])
    async def readyz():
        checks: dict[str, str] = {}
        try:
            maker = get_sessionmaker()
            async with maker() as session:
                await session.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["db"] = f"error: {e.__class__.__name__}"
        try:
            redis = _make_redis()
            if redis is not None:
                await redis.ping()
            checks["redis"] = "ok" if redis is not None else "not_configured"
        except Exception as e:  # noqa: BLE001
            checks["redis"] = f"error: {e.__class__.__name__}"
        healthy = checks.get("db") == "ok"
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ready" if healthy else "not_ready", "checks": checks},
        )

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    @app.get("/metrics", tags=["ops"])
    async def metrics():
        from fastapi.responses import Response

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def _make_redis():
    """Redis client for rate limiting; None in inline/test mode."""
    if settings.task_inline or settings.env == "test":
        return None
    if settings.redis_url.startswith("redis"):
        import redis.asyncio as aioredis

        return aioredis.from_url(settings.redis_url, decode_responses=True)
    return None


app = create_app()

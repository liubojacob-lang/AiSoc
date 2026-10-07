"""Task bodies. Each body runs on its own fresh engine/session (one asyncio
loop per invocation) — safe under both Celery workers and the inline
dev/test dispatcher.

Retry policy: the gateway retries LLM calls internally; the Celery wrapper
retries transient infra errors x3 with backoff. Permanent failures land the
alert in ``triage_failed`` for manual/beat retry.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

from app.core.config import settings
from app.core.logging import configure_logging, get_logger, request_id_var

if settings.env != "dev":
    configure_logging(settings.log_level, pretty=False)

log = get_logger("workers.tasks")

TRIAGE_TIMEOUT_S = settings.llm_triage_timeout_s + 30  # headroom over LLM budget


async def triage_alert_body(
    alert_id: str, tenant_id: str, triggered_by: str | None, request_id: str
) -> dict:
    """Full triage pipeline for one alert."""
    request_id_var.set(request_id or "-")
    from app.db.base import utcnow
    from app.db.session import fresh_session
    from app.models.alerts import Alert
    from app.models.enums import AlertStatus
    from app.modules.ai.gateway import GatewayError
    from app.modules.alerts import service as alerts_service

    alert_uuid = uuid.UUID(alert_id)
    tenant_uuid = uuid.UUID(tenant_id)
    async with fresh_session() as session:
        alert = await session.get(Alert, alert_uuid)
        if alert is None or alert.tenant_id != tenant_uuid:
            log.warning("triage_task_alert_missing", alert_id=alert_id)
            return {"status": "missing"}
        if alert.status not in (AlertStatus.NEW, AlertStatus.TRIAGE_FAILED):
            # concurrent triage or human already acted: skip quietly
            return {"status": "skipped", "reason": f"status={alert.status}"}

        trigger_uuid = uuid.UUID(triggered_by) if triggered_by else None
        try:
            await asyncio.wait_for(
                alerts_service.run_triage(
                    session, tenant_uuid, alert_uuid, triggered_by=trigger_uuid
                ),
                timeout=TRIAGE_TIMEOUT_S,
            )
            return {"status": "done", "alert_status": alert.status}
        except TimeoutError:
            alert.status = AlertStatus.TRIAGE_FAILED
            alert.updated_at = utcnow()
            await session.commit()
            log.error("triage_timeout", alert_id=alert_id, timeout_s=TRIAGE_TIMEOUT_S)
            return {"status": "timeout"}
        except GatewayError as e:
            alert.status = AlertStatus.TRIAGE_FAILED
            alert.updated_at = utcnow()
            await session.commit()
            log.error("triage_gateway_error", alert_id=alert_id, attempts=e.attempts)
            return {"status": "gateway_error"}


async def index_document_body(document_id: str, tenant_id: str) -> dict:
    """(Re)index a knowledge document: chunk + embed + persist."""
    from pathlib import Path

    from sqlalchemy import select

    from app.core.config import BASE_DIR
    from app.db.session import fresh_session
    from app.models.enums import DocumentStatus
    from app.models.knowledge import KnowledgeDocument
    from app.modules.ai.gateway import get_gateway
    from app.modules.ai.rag import index_document

    doc_uuid = uuid.UUID(document_id)
    async with fresh_session() as session:
        doc = (
            await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id == doc_uuid,
                    KnowledgeDocument.tenant_id == uuid.UUID(tenant_id),
                )
            )
        ).scalar_one_or_none()
        if doc is None:
            return {"status": "missing"}
        path = Path(BASE_DIR) / "data" / "knowledge" / doc.source_path
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            doc.status = DocumentStatus.FAILED
            doc.error = f"file unreadable: {e}"[:500]
            await session.commit()
            return {"status": "failed", "error": doc.error}

        doc.status = DocumentStatus.PENDING
        await session.commit()
        try:
            count = await index_document(
                session,
                get_gateway(),
                document_id=doc.id,
                title=doc.title,
                content=raw,
            )
            doc.chunk_count = count
            doc.status = DocumentStatus.INDEXED
            doc.error = None
            await session.commit()
            return {"status": "indexed", "chunks": count}
        except Exception as e:  # noqa: BLE001 - indexing failure is a document state
            doc.status = DocumentStatus.FAILED
            doc.error = str(e)[:500]
            await session.commit()
            log.error("kb_index_failed", document_id=document_id, error=str(e))
            return {"status": "failed", "error": str(e)}


async def cleanup_expired_body() -> dict:
    """清理过期幂等键与已读通知（保留 30 天）。"""
    from datetime import timedelta

    from sqlalchemy import delete, select, text
    from sqlalchemy.engine import CursorResult

    from app.db.base import utcnow
    from app.db.session import fresh_session
    from app.models.ops import IdempotencyKey, Notification

    async with fresh_session() as session:
        r1 = await session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expires_at < utcnow())
        )
        cutoff = utcnow() - timedelta(days=30)
        ids = (
            await session.execute(
                select(Notification.id).where(
                    Notification.read_at.is_not(None), Notification.created_at < cutoff
                )
            )
        ).scalars().all()
        r2 = await session.execute(
            delete(Notification).where(Notification.id.in_(ids) if ids else text("false"))
        )
        await session.commit()
        return {
            "idempotency_deleted": cast(CursorResult[Any], r1).rowcount,
            "notifications_deleted": cast(CursorResult[Any], r2).rowcount,
        }


# ---------------- Celery task wrappers ----------------


def _register_celery_tasks() -> None:
    from app.workers.celery_app import celery_app

    global triage_alert_task, index_document_task

    @celery_app.task(
        name="app.workers.tasks.triage_alert_task",
        bind=True,
        max_retries=3,
        autoretry_for=(Exception,),
        retry_backoff=2,
        retry_jitter=True,
    )
    def triage_alert_task(
        self, alert_id: str, tenant_id: str, triggered_by: str | None, request_id: str
    ):  # noqa: F811
        return asyncio.run(triage_alert_body(alert_id, tenant_id, triggered_by, request_id))

    @celery_app.task(
        name="app.workers.tasks.index_document_task",
        bind=True,
        max_retries=3,
        autoretry_for=(Exception,),
        retry_backoff=2,
        retry_jitter=True,
    )
    def index_document_task(self, document_id: str, tenant_id: str):  # noqa: F811
        return asyncio.run(index_document_body(document_id, tenant_id))


triage_alert_task = None
index_document_task = None
try:
    _register_celery_tasks()
    log.info("celery_tasks_registered")
except Exception as e:  # pragma: no cover - dev without broker config
    log.warning("celery_tasks_not_registered", error=str(e))

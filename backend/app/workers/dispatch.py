"""Task dispatch layer: Celery in staging/prod; inline execution in dev/test
(``settings.task_inline=True``) so the full closed loop runs without a broker.

Inline mode awaits the very same task body on a fresh engine/session — the
production Celery task calls exactly the same function.
"""

from __future__ import annotations

import uuid

from app.core.config import settings
from app.core.logging import get_logger, request_id_var

log = get_logger("workers.dispatch")


async def dispatch_triage(
    alert_id: uuid.UUID, tenant_id: uuid.UUID, triggered_by: uuid.UUID | None = None
) -> None:
    """Must be called AFTER the alert row is committed."""
    from app.workers.tasks import triage_alert_body

    request_id = request_id_var.get()
    if settings.task_inline:
        await triage_alert_body(
            str(alert_id),
            str(tenant_id),
            str(triggered_by) if triggered_by else None,
            request_id,
        )
    else:
        # 任务对象定义在 tasks 模块（celery_app 仅提供 app 实例）
        from app.workers.tasks import triage_alert_task

        if triage_alert_task is None:  # pragma: no cover - celery 注册失败已在启动期告警
            raise RuntimeError("celery triage task not registered")
        triage_alert_task.delay(
            str(alert_id),
            str(tenant_id),
            str(triggered_by) if triggered_by else None,
            request_id,
        )


async def dispatch_index_document(document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    from app.workers.tasks import index_document_body

    if settings.task_inline:
        await index_document_body(str(document_id), str(tenant_id))
    else:
        from app.workers.tasks import index_document_task

        if index_document_task is None:  # pragma: no cover
            raise RuntimeError("celery index task not registered")
        index_document_task.delay(str(document_id), str(tenant_id))


def _celery_tasks_registered() -> bool:
    """回归守卫：Celery 模式下任务对象必须可解析（Docker 首跑曾因
    从错误模块导入而在 ingest 后 500）。"""
    from app.workers import tasks as t

    return t.triage_alert_task is not None and t.index_document_task is not None

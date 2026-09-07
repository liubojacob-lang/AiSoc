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
        from app.workers.celery_app import triage_alert_task

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
        from app.workers.celery_app import index_document_task

        index_document_task.delay(str(document_id), str(tenant_id))

"""Celery application (staging/prod). Task bodies live in ``tasks.py`` so the
inline dev/test dispatcher can call them without Celery."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings

celery_app = Celery(
    "aisoc",
    broker=settings.redis_url,
    backend=None,  # task state lives in the DB (ai_runs), not in celery results
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_default_queue="default",
    task_queues=(
        Queue("default"),
        Queue("triage"),
        Queue("kb"),
    ),
    task_routes={
        "app.workers.tasks.triage_alert_task": {"queue": "triage"},
        "app.workers.tasks.index_document_task": {"queue": "kb"},
    },
    task_acks_late=True,  # ack after completion: crash-safe re-delivery
    worker_prefetch_multiplier=1,  # fair dispatch for long AI tasks
    task_time_limit=300,
    task_soft_time_limit=240,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # 清理过期幂等键（24h 窗口）；每天 03:17 执行
        'cleanup-idempotency-keys': {
            'task': 'app.workers.tasks.cleanup_expired_task',
            'schedule': crontab(hour=3, minute=17),
        },
    },
)

from app.workers import tasks  # noqa: E402,F401 - register tasks

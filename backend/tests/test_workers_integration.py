"""跨模式集成守卫：真实 Celery 模式的任务分发必须可解析。

背景：Docker 首跑发现 dispatch 从错误模块导入 Celery 任务对象，
仅在非内联模式下暴露（内联路径直接调用任务体）。本文件锁死该类问题。
"""

from __future__ import annotations

from app.core.config import settings


def test_celery_tasks_registered():
    """任务对象存在于 tasks 模块且已注册到 celery app。"""
    from app.workers import tasks as t

    assert t.triage_alert_task is not None, "Celery 任务未注册（broker 配置失败？）"
    assert t.index_document_task is not None
    assert t.triage_alert_task.name == "app.workers.tasks.triage_alert_task"
    assert t.index_document_task.name == "app.workers.tasks.index_document_task"


def test_dispatch_imports_resolve_in_celery_mode():
    """模拟非内联分支的导入路径：dispatch 引用的任务名必须真实存在。"""
    # 直接复刻 dispatch.py 的 celery 分支导入
    from app.workers.tasks import index_document_task, triage_alert_task  # noqa: F401

    assert hasattr(triage_alert_task, "delay")
    assert hasattr(index_document_task, "delay")


def test_inline_mode_is_default_in_test_env():
    assert settings.task_inline is True  # 测试环境由 conftest 固定

"""Demo dataset: realistic alerts, intel, assets, a response playbook.

Goes through the REAL ingest + triage pipeline (so verdicts come from
whatever LLM routing is configured). Usage:

    python -m app.db.demo_data          # after `alembic upgrade head`

Idempotent by external_id: re-running only tops up missing samples.
"""

from __future__ import annotations

import asyncio
import random
from datetime import timedelta

from app.core.config import BASE_DIR
from app.db.base import DEFAULT_TENANT_ID, utcnow
from app.db.session import fresh_session
from app.modules.alerts import service as alerts_service
from app.modules.alerts.schemas import AlertIngest
from app.workers.tasks import index_document_body

random.seed(42)  # reproducible demo

PLAYBOOK = """# 告警处置通用 Playbook

## 一、暴力破解（brute_force）
1. 确认来源 IP 是否为已知扫描器/情报恶意 IP（query_threat_intel）。
2. 检查是否存在成功登录：若存在，按口令泄露处理——禁用账号、强制改密、隔离主机。
3. 处置：边界防火墙封禁来源；对目标账号开启 MFA。

## 二、Web 攻击（web_attack / sql_injection）
1. 确认 WAF 是否已拦截，后端是否出现 SQL 错误日志或异常查询。
2. 处置：IP 封禁 + 对受影响接口做参数化审计；保存请求证据。

## 三、恶意代码（malware）
1. 确认进程信誉、落盘哈希（query_threat_intel hash）。
2. 若主机为重要资产（query_asset criticality=high），立即建议隔离。
3. 处置：隔离主机、全盘扫描、排查横向移动痕迹。
"""

DEMO_ALERTS = [
    # (source, external_id, title, description, type, severity, src_ip, minutes_ago)
    ("edr", "demo-001", "SSH 暴力破解后成功登录",
     "45.155.205.233 对 root 账户 142 次失败尝试后成功登录，会话仍在线",
     "brute_force", "critical", "45.155.205.233", 12),
    ("waf", "demo-002", "SQL 注入攻击被 WAF 拦截",
     "UNION SELECT 注入尝试命中规则，/api/search 接口，已拦截",
     "web_attack", "medium", "198.51.100.66", 35),
    ("ids", "demo-003", "检测到对外 C2 心跳流量",
     "fin-db-01 每 60s 向可疑域名发起 TLS 连接，行为匹配 Beacon 模型",
     "malware", "critical", "10.20.30.40", 8),
    ("auth", "demo-004", "异地异地登录告警",
     "jsmith 账号 40 分钟内先后在两个国家登录，地理位置不可达",
     "account_compromise", "high", "203.0.113.99", 47),
    ("edr", "demo-005", "办公终端 EICAR 测试文件告警",
     "安全团队例行自检触发 AV 告警，EICAR 标准测试样本",
     "malware", "low", "10.20.30.40", 90),
    ("nids", "demo-006", "内网端口扫描",
     "192.0.2.50 对服务器网段进行 SYN 全端口扫描，未发现后续利用行为",
     "reconnaissance", "low", "192.0.2.50", 150),
    ("cloud", "demo-007", "堡垒机提权至 Domain Admin",
     "svc-backup 账户在变更窗口外被加入 DA 组，域控操作日志告警",
     "lateral_movement", "critical", "10.20.30.40", 5),
    ("waf", "demo-008", "爬虫高频抓取价格接口",
     "单 IP 每分钟 600+ 请求抓取 /price 接口，UA 为 python-requests",
     "reconnaissance", "low", "192.0.2.88", 200),
    ("dlp", "demo-009", "重要资产大流量外发",
     "fin-db-01 非工作时段向个人网盘持续上传 4GB 数据",
     "data_exfiltration", "critical", "10.20.30.40", 18),
    ("auth", "demo-010", "员工上报钓鱼邮件",
     "员工主动上报凭证钓鱼邮件，网关确认未点击链接",
     "phishing", "low", None, 300),
]

INTEL = [
    ("45.155.205.233", "ip", 92, ["botnet", "bruteforce"], "internal-feed", 200, 1),
    ("198.51.100.66", "ip", 55, ["scanner"], "osint", 90, 3),
    ("203.0.113.99", "ip", 70, ["proxy", "credential-abuse"], "osint", 60, 1),
    ("192.0.2.50", "ip", 15, ["research"], "osint", 30, 10),
]

ASSETS = [
    ("10.20.30.40", "host", "fin-db-01", "财务数据库", "high", "fin-ops"),
    ("10.20.30.55", "host", "dc-01", "域控制器", "high", "it-infra"),
    ("10.20.30.101", "container", "web-frontend", "对外 Web 前端", "medium", "app-team"),
]


async def run() -> dict:
    from app.db import seed as identity_seed

    stats = {"alerts": 0, "duplicates": 0, "intel": 0, "assets": 0, "kb_docs": 0}

    # knowledge base document
    kb_dir = BASE_DIR / "data" / "knowledge" / str(DEFAULT_TENANT_ID)
    kb_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    import uuid as _uuid

    digest = hashlib.sha256(PLAYBOOK.encode()).hexdigest()
    async with fresh_session() as session:
        from sqlalchemy import select

        from app.models.identity import User
        from app.models.knowledge import KnowledgeDocument
        from app.models.ops import Asset as AssetModel
        from app.models.ops import ThreatIntel as IntelModel

        admin = (
            await session.execute(select(User).where(User.email == identity_seed.ADMIN_EMAIL))
        ).scalar_one()

        for ioc, ioc_type, rep, tags, source, first_ago, last_ago in INTEL:
            exists = (
                await session.execute(
                    select(IntelModel).where(IntelModel.ioc == ioc, IntelModel.ioc_type == ioc_type)
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(
                    IntelModel(
                        tenant_id=DEFAULT_TENANT_ID, ioc=ioc, ioc_type=ioc_type,
                        reputation=rep, tags=tags, source=source,
                        first_seen_at=utcnow() - timedelta(days=first_ago),
                        last_seen_at=utcnow() - timedelta(days=last_ago),
                    )
                )
                stats["intel"] += 1
        await session.commit()

        for identifier, kind, _display, name, crit, owner in ASSETS:
            exists = (
                await session.execute(
                    select(AssetModel).where(AssetModel.identifier == identifier)
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(
                    AssetModel(
                        tenant_id=DEFAULT_TENANT_ID, identifier=identifier, kind=kind,
                        display_name=name, criticality=crit, owner=owner,
                    )
                )
                stats["assets"] += 1
        await session.commit()

        doc = (
            await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.sha256 == digest)
            )
        ).scalar_one_or_none()
        if doc is None:
            rel = f"{DEFAULT_TENANT_ID}/{_uuid.uuid4()}.md"
            (BASE_DIR / "data" / "knowledge" / rel).write_text(PLAYBOOK, encoding="utf-8")
            doc = KnowledgeDocument(
                tenant_id=DEFAULT_TENANT_ID,
                title="告警处置通用 Playbook",
                source_path=rel,
                mime_type="text/markdown",
                size_bytes=len(PLAYBOOK.encode()),
                sha256=digest,
                uploaded_by=admin.id,
            )
            session.add(doc)
            await session.commit()
            await index_document_body(str(doc.id), str(DEFAULT_TENANT_ID))
            stats["kb_docs"] += 1

    # alerts through the real pipeline
    for source, ext, title, desc, atype, sev, sip, minutes in DEMO_ALERTS:
        async with fresh_session() as session:
            alert, created = await alerts_service.ingest(
                session, DEFAULT_TENANT_ID,
                AlertIngest(
                    source=source, external_id=ext, title=title, description=desc,
                    alert_type=atype, severity=sev, src_ip=sip,
                    occurred_at=utcnow() - timedelta(minutes=minutes),
                    raw={"demo": True},
                ),
            )
            await session.commit()
            if not created:
                stats["duplicates"] += 1
                continue
            await alerts_service.run_triage(session, DEFAULT_TENANT_ID, alert.id)
            stats["alerts"] += 1

    print(f"[demo] done: {stats}")
    return stats


if __name__ == "__main__":
    asyncio.run(run())

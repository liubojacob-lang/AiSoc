<div align="center">

# AISOC · AI-Powered Security Operations Center

[![CI/CD](https://github.com/liubojacob-lang/AiSoc/actions/workflows/ci.yml/badge.svg)](https://github.com/liubojacob-lang/AiSoc/actions/workflows/ci.yml)

**开源、可私有化部署的 AI 安全运营平台**
告警自动富化研判（LLM Agent + 工具调用）→ 人机协同确认 → 事件处置闭环，全程可审计、可回放、成本可核算。

`FastAPI` · `PostgreSQL + pgvector` · `Celery + Redis` · `React 18 + TypeScript` · `LLM Gateway`（OpenAI / Anthropic / Gemini / Qwen / DeepSeek / Ollama）

</div>

---

## 这是什么

SOC 分析师每天面对海量告警，大部分时间消耗在重复的 Tier-1 分诊上。AISOC 把这件事交给 AI Agent：

```
告警源(EDR/SIEM/WAF/脚本)                       分析师
        │ POST /api/v1/alerts/ingest/alerts        │
        ▼ (API Key, 幂等)                          │
   ┌──────────────┐   Celery 异步          ┌──────────▼─────────┐
   │  FastAPI API  │ ────────────────────▶ │  AI 研判 Agent      │
   └──────────────┘                        │  ├ 威胁情报查询      │
                                           │  ├ 资产查询          │
                                           │  ├ 历史相似告警      │
                                           │  ├ 知识库检索(RAG)   │
                                           │  └ 结构化结论+证据链  │
                                           └──────────┬─────────┘
                                                      ▼
                              分析师确认（真实/误报）→ 升级事件 → 处置任务
                                            全程审计 + token 成本记账
```

**核心原则：AI 只建议，不处置。** 每一条 AI 结论都带证据链与置信度，必须由人确认；每一次 LLM 调用都落库可回放；LLM 全部故障时规则引擎兜底降级（明示 `degraded` 标记），系统不瘫。

---

## 60 秒本地启动

> 依赖：Python 3.12+、Node 20+。无 Docker/Redis/LLM Key 也能跑通全流程（SQLite + 内联任务 + 确定性内置模型）。

```bash
# 1) 后端
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # Linux/macOS: .venv/bin/pip
cp ../.env.example .env   # 按需修改
.venv/Scripts/alembic upgrade head
TASK_INLINE=true BOOTSTRAP_ADMIN_PASSWORD=admin12345 .venv/Scripts/python -m app.db.seed
TASK_INLINE=true .venv/Scripts/python -m app.db.demo_data            # 10 条演示告警走真实研判管线
TASK_INLINE=true .venv/Scripts/python -m uvicorn app.main:app --port 8000

# 2) 前端（新终端）
cd frontend
npm install && npm run dev          # http://localhost:5173  admin@aisoc.dev / admin12345
```

生产部署（单机 Docker Compose，含 TLS 前置、备份 sidecar、Celery worker/beat）见 **`docs/DEPLOYMENT.md`**。

---

## 功能总览（全部为可验证的真实实现）

| 模块 | 能力 |
|---|---|
| 告警接入 | REST + API Key（sha256 存储、scope 限权、限流配额）、`(source, external_id)` 幂等去重、Idempotency-Key 重放 |
| AI 告警研判 | 自研 ReAct Agent：威胁情报/资产/历史告警/知识库检索四类富化工具 + 处置建议；Pydantic 强制结构化结论（分类/定级/置信度/证据/建议）；每步落库可回放；token 预算与超时控制 |
| LLM Gateway | 多 Provider 统一抽象（OpenAI/Anthropic/Gemini/Qwen/DeepSeek/Ollama/内置确定性 Fake）；路由→预算→超时→重试→熔断→降级链；结构化输出失败自动修复重试；逐调用 token/成本记账（独立事务） |
| RAG 知识库 | Markdown 感知切片（800 tok/15% 重叠）、pgvector HNSW（SQLite 开发态自动降级为暴力余弦）、强制引用溯源、无证据不下结论 |
| 人工确认 | Human-in-the-loop 确认（真实/误报+理由）→ 反馈表 → AI 采纳率统计 |
| 事件中心 | PICERL 状态机（非法迁移拒绝）、任务、评论、MTTR 统计 |
| 平台 | RBAC（admin/analyst/viewer + 权限矩阵）、JWT 双令牌轮换+重用检测、argon2id、账号锁定、Redis 滑动窗口限流（Redis 服务端时钟）、append-only 审计日志、站内通知 + Webhook 事件推送、Prometheus 指标 + Grafana 看板 + 告警规则、request_id 全链路结构化日志、健康检查 |
| SOC 助手 | 自然语言查询告警/事件/统计/知识库：规划→工具→有据回答，带引用卡片与会话历史（`/assistant`） |
| 处置审批 | AI 建议一键发起审批：分析师 L1 → 管理员 L2 双人批准（禁止自批）→ 可插拔执行器（webhook / 人工交接），全程审计+通知 |
| 看板 | 告警量/降噪率/采纳率/MTTR/LLM 成本，全部真实表聚合 |

**交互式架构可视化：打开根目录 `architecture.html`**（自包含单文件，含系统模块/数据流/AI 调用链/状态机/部署拓扑/ADR）。

---

## 测试与质量

```bash
cd backend
ruff check app tests && ruff format --check app tests   # lint 全绿
pytest tests/ -q                                         # 23 个测试全通过
```

- **闭环测试**：接入→研判→报告回放→确认→采纳率统计，端到端断言（30 项后端测试）
- **E2E**：`tests_e2e/`（Playwright + 系统 Chrome，对运行中的 Docker 栈执行；`E2E_BASE_URL=http://localhost:8080 pytest tests_e2e/`）
- **AI 评估门禁**：`tests/golden/triage_dataset.json`（10 条带 ground truth 的标注告警），结构化合法率 100%、证据强制、定级一致性进 CI 门禁
- **安全测试**：RBAC 越权、账号锁定、Refresh 重用检测、API Key scope
- **迁移验证**：Alembic upgrade→downgrade→upgrade 往返
- **降级测试**：LLM 全故障 → 规则引擎兜底 + `degraded` 如实标记

---

## 接入你的第一台告警源

```bash
# 管理后台创建 API Key 后：
curl -X POST http://localhost:8000/api/v1/alerts/ingest/alerts \
  -H "X-API-Key: ais_xxxx..." -H "Content-Type: application/json" \
  -d '{
    "source": "waf", "external_id": "evt-20260907-001",
    "title": "SQL 注入尝试", "alert_type": "web_attack", "severity": "high",
    "src_ip": "203.0.113.66", "description": "UNION SELECT payload 已被 WAF 拦截"
  }'
# 202 → 异步 AI 研判（P95 ≤ 60s）→ 前端「告警中心」查看结论与回放
```

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) | 产品定位、竞品分析、MVP 范围、成功指标 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 12 个架构视图 + 10 条 ADR（含备选方案否决理由） |
| [`architecture.html`](architecture.html) | 交互式架构可视化（浏览器直接打开） |
| [`docs/DATABASE.md`](docs/DATABASE.md) | 29 表 Schema 权威定义（索引/约束/审计/并发） |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | 部署、迁移、备份、回滚、监控 |
| [`PROJECT_COMPLETION_REPORT.md`](PROJECT_COMPLETION_REPORT.md) | 生产就绪审计：完成度、技术债、诚实结论 |

---

## License

MIT（依赖与模型使用条款见各厂商）

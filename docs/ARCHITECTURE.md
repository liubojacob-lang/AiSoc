# AISOC 系统架构设计（ARCHITECTURE.md）

> 版本 v1.0 ｜ Phase 1 ｜ 配套可视化：`architecture.html`（根目录，浏览器直接打开）
>
> 每个决策均给出「选择 + 备选方案 + 理由」。ADR 汇总见文末。

---

## 1. Overall Architecture（总体架构）

**决策：模块化单体（Modular Monolith），不是微服务。**

理由：目标团队规模 1–5 人、目标用户运维能力有限（单机部署）；微服务的分布式事务/服务发现/链路传播成本远超收益。单体内部按**限界上下文**严格分包，模块间只允许通过 Service 接口调用、不允许跨模块直连对方表，未来可按模块平滑拆分。

```
┌─────────────────────────────────────────────────────────────────────┐
│  Client Layer                                                        │
│  React SPA (Desktop-first SaaS UI)  │  外部告警源 (EDR/SIEM/WAF/脚本)  │
└──────────────┬──────────────────────────────┬───────────────────────┘
               │ HTTPS (JWT)                  │ HTTPS (API Key)
┌──────────────▼──────────────────────────────▼───────────────────────┐
│  Edge: Nginx/Caddy (TLS、静态资源、安全头、限流第一层)                     │
├─────────────────────────────────────────────────────────────────────┤
│  Application Layer — FastAPI 单体（模块化）                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Identity │ │ Alerts   │ │ Incidents│ │ Knowledge│ │ Analytics │  │
│  │ 认证/RBAC │ │ 告警接入  │ │ 事件/任务 │ │ 知识库RAG │ │ 统计看板   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ AI Core (内部共享模块)      │  │ Platform (审计/通知/配置/健康检查)  │ │
│  │ Gateway·Agent·RAG·Cost    │  │                                   │ │
│  └──────────────────────────┘  └──────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│  Async Worker Layer — Celery workers（AI 研判流水线、通知、知识库索引）    │
├─────────────────────────────────────────────────────────────────────┤
│  Data Layer                                                          │
│  PostgreSQL 16 (+pgvector) │ Redis 7 (cache/lock/ratelimit/broker)   │
│  Object Storage: 本地卷/MinIO (知识库原始文档)                          │
├─────────────────────────────────────────────────────────────────────┤
│  External LLM Providers（可替换）: OpenAI / Anthropic / Gemini /       │
│  Qwen / DeepSeek / Ollama(本地模型) —— 经 AI Gateway 统一接入           │
└─────────────────────────────────────────────────────────────────────┘
```

**关键数据流（主闭环）**：外部告警 → Ingest API（API Key 鉴权、幂等去重）→ `alerts` 表 → Celery 任务 `triage_alert` → AI Agent（工具富化 + LLM 结构化研判）→ `triage_results` → 分析师确认 → 升级事件/关闭 → 统计与审计。

---

## 2. Backend Architecture

- **框架**：FastAPI（异步原生，适配 LLM 流式与高 IO；Pydantic v2 同时承担「API 校验」与「LLM 结构化输出」两个职责，一份模型两处使用）。
- **分层**：`api(路由/鉴权/限流) → service(业务逻辑/事务边界) → repository(数据访问) → model(SQLAlchemy)`。Service 层是唯一事务边界；API 层禁止直接操作 ORM。
- **目录结构（领域分包）**：

```
backend/app/
├── core/            # 配置、安全、依赖注入、异常、日志
├── modules/
│   ├── identity/    # 用户/角色/权限/API Key
│   ├── alerts/      # 告警接入、去重、查询、确认
│   ├── incidents/   # 事件、任务、评论
│   ├── knowledge/   # 文档、切片、向量检索
│   ├── analytics/   # 看板统计
│   └── ai/          # AI Gateway、Agent、工具注册表、Prompt、成本
├── platform/        # 审计、通知、系统配置、健康检查
├── workers/         # Celery 任务（triage_pipeline、kb_index、notify）
└── main.py
```

- **错误处理**：统一异常体系（业务异常 `AppError(code, message, http_status)` → 全局 handler 输出统一错误体 `{code, message, request_id, details}`）；未知异常打 error 日志并返回 500 通用信息（不泄漏堆栈）。
- **幂等**：写接口支持 `Idempotency-Key` 头（key 存 Redis + 落库 `idempotency_keys`，24h 窗口内重放返回首次结果）；告警接入按 `(source, external_id)` 唯一键天然去重。

---

## 3. Frontend Architecture

| 决策点 | 选择 | 理由 |
|---|---|---|
| 框架 | React 18 + TypeScript(strict) + Vite | 生态最大、类型体系成熟、Vite 开发体验好 |
| 服务端状态 | TanStack Query v5 | 缓存/重试/失效/乐观更新，替代手写请求状态机 |
| 客户端状态 | Zustand | 轻；只放 UI 状态（主题、侧栏、弹窗），**不放服务端数据** |
| 路由 | React Router v6（懒加载 + 路由级 code splitting） | 标准选择 |
| 样式 | TailwindCSS + CSS 变量主题 | Dark Mode = `class` 策略切换变量；不引重型组件库，保持观感现代 |
| 组件 | 自建 shadcn 风格基础件（Button/Dialog/Toast/Table/Tabs/Skeleton…） | 避免"传统后台管理系统"观感；完全可控 |
| API 客户端 | 手写类型化 client（axios + 拦截器） | 与后端 Pydantic schema 对齐；401 自动刷新 token |

**页面结构**：登录 → 工作台（Dashboard）/ 告警中心（列表+详情抽屉，AI 研判报告页）/ 事件中心（事件+任务）/ 知识库（文档+问答）/ AI 助手（P1）/ 管理（用户/角色/模型/审计日志）。

**UX 硬性要求**（Phase 7 验收标准）：所有列表有 loading skeleton 与空状态；所有写操作有二次确认；所有异步操作有 toast 反馈；表单内联校验；键盘可达（Tab 顺序、Esc 关闭弹窗、Enter 提交）；WCAG AA 对比度；≥1280px 桌面优先、≥375px 可用。

---

## 4. Database Architecture

- **PostgreSQL 16 单库**（关系 + JSONB 半结构化 + pgvector 向量，**三合一**）。
  - 理由：本项目向量规模（知识库 ≤ 10⁵ chunks）远未到独立向量库（Milvus 等）的运维必要性；单库事务保证「业务数据与审计/成本数据强一致」。备选 Qdrant 单独部署被否——多一个有状态服务，收益不成立。
- **主键**：业务表 UUID（应用层生成 UUIDv7，时间有序利于索引局部性，且不暴露计数）；审计/日志大表用 BIGIDENTITY + 时间分区预留。
- **通用约定**：所有表 `created_at/updated_at (timestamptz, UTC)`；软删除仅用于 `knowledge_documents`、`alerts`（`deleted_at`），审计日志**只增不改**（应用层无 UPDATE/DELETE 路径）。
- **领域划分**（详见 `docs/DATABASE.md`，Phase 2）：
  `identity`(users/roles/permissions/api_keys) · `alerts`(alerts/enrichments/triage_results/feedback) · `incidents`(incidents/incident_tasks/comments) · `knowledge`(documents/chunks+vector) · `ai`(llm_calls/ai_runs/ai_steps/ai_tool_calls/ai_conversations/ai_messages) · `ops`(audit_logs/notifications/system_configs/idempotency_keys)。
- **性能**：高频查询路径建索引（告警列表：`(status, created_at DESC)`、`(severity)`、GIN on JSONB）；向量列 HNSW (cosine)；列表接口强制分页（默认 20/最大 100，keyset 分页预留）。
- **迁移**：Alembic（版本化、可回滚），CI 中对空库跑全量迁移作为测试前置。
- **备份**：每日 `pg_dump` 全量 + WAL 归档（P1），保留 30 天；恢复演练脚本纳入文档。

---

## 5. AI Architecture（核心）

### 5.1 LLM Gateway（统一抽象层）

业务代码**只依赖** `ai.gateway.LLMGateway.chat()/stream()/embed()` 接口，不感知厂商。

```python
class LLMProvider(Protocol):
    async def chat(self, request: ChatRequest) -> ChatResponse: ...
    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Gateway 职责链（每个职责都可独立测试）：

1. **Model Routing**：按「任务类型 + 能力要求 + 成本权重 + 健康度」选择 Provider（配置化：研判→强模型，摘要/嵌入→廉价模型）。
2. **超时**：连接 5s / 总 60s（研判链路 120s），超时视为失败进入重试。
3. **重试**：指数退避 + 抖动（base 0.5s, factor 2, max 3 次），仅对 429/5xx/网络错误重试；**4xx 参数错误不重试**。
4. **Fallback 链**：主模型连续失败 → 备模型 → **规则引擎降级**（关键词+阈值打标，系统功能不中断，结果标记 `degraded=true` 前端明示）。
5. **熔断**：滑动窗口错误率 >50% 熔断 60s，直接走 fallback（防止雪崩与烧钱重试）。
6. **结构化输出**：Prompt 要求 JSON Schema + Pydantic 校验；校验失败自动携带错误信息重试一次；仍失败则报错（**不允许把畸形输出当结论入库**）。
7. **Token/成本核算**：每次调用记录 prompt/completion tokens、模型单价、折算成本（`llm_calls` 表），按用户/任务/模型可聚合。
8. **可观测**：每次调用产生 trace span + 结构化日志（模型、耗时、tokens、结果状态）。

### 5.2 RAG（知识库检索增强）

- 切片：800 token / 15% 重叠，保留标题层级路径入 metadata。
- 嵌入：通过 Gateway `embed()`（OpenAI text-embedding-3-small 或 Ollama bge-m3，配置切换）。
- 检索：pgvector HNSW cosine Top-K=6，相似度阈值 0.3 以下丢弃；引用强制——**答案中的每条结论必须携带 chunk 引用编号，前端可点击跳转原文高亮**。
- 注入防护：知识库内容与告警内容在 Prompt 中均标记为「不可信数据」，与系统指令结构隔离。

### 5.3 成本与预算控制

单次研判 token 预算（默认 30k）→ 超限中止并标记；按天/按任务成本仪表盘；模型单价配置表驱动，换模型不改代码。

---

## 6. Agent Architecture（告警研判 Agent）

**决策：自研轻量 Agent 循环（ReAct 变体），不用 LangChain/LangGraph。**

理由：本场景 Agent 步骤有限（≤8 步）、工具是内部受控集合、每步必须落库审计——自研循环约 300 行，完全可控可测；引入重型框架会增加不可控抽象与依赖风险，且面试价值反而低（"你用了 LangChain" vs "你实现了 Agent 运行时"）。

```
triage_alert(alert_id)
  └─ AgentRunner.run(context=告警+资产+策略)
       ├─ Step: LLM 生成计划 + 工具调用请求（function calling, 强制 JSON）
       ├─ ToolRegistry.execute(tool)      # 白名单 + 参数 Pydantic 校验 + 权限检查
       │    ├ query_threat_intel(ioc)     # 本地情报库（自维护 IOC 表）
       │    ├ query_asset(ip/hostname)    # 资产库
       │    ├ search_similar_alerts(...)  # 历史告警向量/结构检索
       │    ├ search_knowledge(query)     # RAG 检索 Playbook
       │    └ request_approval(action)    # 危险动作 → 生成"建议处置"待人工批准
       ├─ 每步持久化: ai_steps / ai_tool_calls（输入输出、耗时、token）
       ├─ 终止条件: 达成结论 | max_steps=8 | token 预算耗尽 | 超时 120s
       └─ 产出 TriagedVerdict(Pydantic): classification, severity,
            confidence, reasoning, evidence[], recommended_actions[]
```

**安全约束**：工具白名单硬编码注册；工具无网络自由访问（只有注入的内部服务客户端）；Agent 无写权限（只能产生建议，不能修改告警/事件状态）；每次运行有唯一 `run_id`，失败可从任一步骤重放。

---

## 7. Workflow Architecture

**决策：显式状态机（enum + 迁移表校验），不引入工作流引擎。**

理由：本期只有 3 条状态流，工作流引擎（Temporal/Camunda）的部署与学习成本不成立；状态机代码 100 行内可测试。可视化 Playbook 编排器属于 P2，届时评估 Temporal。

| 流 | 状态机 |
|---|---|
| 告警 | `new → triaging → triaged → (confirmed_true → incident_created) / (confirmed_false) / (escalated)`，取消/重开路径显式定义 |
| 事件 | `new → investigating → contained → eradicated → recovered → closed`，任意非关闭态可 `reopened` |
| 任务 | `todo → in_progress → blocked → done / cancelled` |

迁移规则集中定义（`ALLOWED_TRANSITIONS: dict[state, set[state]]`），非法迁移抛业务异常并审计记录。状态流转产生领域事件（进程内事件总线）驱动通知与统计。

---

## 8. Authentication Architecture

| 项 | 决策 | 理由 |
|---|---|---|
| 方案 | JWT（无状态访问令牌）+ Refresh Token（轮换） | 前后端分离 + 未来多实例水平扩展，避免 session 亲和 |
| Access Token | 15min，`sub/role/permissions_hash/jti`，内存存储（不落 localStorage，防 XSS 窃取） | 最小暴露面 |
| Refresh Token | 7d，**httpOnly + Secure + SameSite=Strict Cookie**，每次刷新轮换；旧 token 进 Redis 撤销名单（`jti`，TTL=剩余有效期）→ **重用检测**（旧 token 再用即判定泄漏，撤销整条链并审计告警） | OWASP 推荐模式 |
| 密码 | argon2id（内存硬化） | 当前公认最优 |
| 登录保护 | 同账号 5 次失败锁 15min；IP 维度限流 | 防爆破 |
| 机器认证 | API Key（`ais_` 前缀，仅创建时展示明文，库存 sha256），绑定 scope（`alerts:write`）与限流配额 | 告警源是机器不是人 |
| 登出 | 撤销 refresh 链 + access 剩余期 denylist | |

---

## 9. Authorization Architecture（RBAC）

- 模型：`users ─ user_roles ─ roles ─ role_permissions ─ permissions`，权限字符串 `resource:action`（如 `alert:read`、`alert:triage`、`incident:write`、`user:manage`、`kb:write`、`audit:read`、`ai:run`）。
- **角色预设**（MVP 固定三角色，角色表可扩展）：
  - `admin`：全部权限 + 用户/模型/系统配置管理
  - `analyst`：告警/事件/知识库读写、触发 AI 研判、确认结论（不可管理用户与系统配置）
  - `viewer`：只读（看板、告警、事件）
- **执行机制**：FastAPI 依赖 `require("alert:write")` 在路由层强制；对象级校验（如事件关闭需处理人本人或 admin）在 Service 层强制；前端仅做菜单/按钮显隐（**前端权限只是 UX，不是安全边界**——所有接口后端强制校验，Phase 6 有专项权限测试）。
- 预留：所有业务表含 `tenant_id`（MVP 恒为 default 租户，索引已预留，多租户化为 P2 过滤条件改造）。

---

## 10. Security Architecture（OWASP 对齐）

| 威胁 | 对策 |
|---|---|
| SQL 注入 | SQLAlchemy 参数化全覆盖，禁止字符串拼接 SQL（CI grep 检查） |
| XSS | React 转义 + 禁止 `dangerouslySetInnerHTML`（AI 输出 markdown 渲染经 sanitize）+ CSP 响应头 |
| CSRF | API 用 Authorization 头（非 Cookie 携带业务请求），refresh Cookie SameSite=Strict |
| 暴力破解 | 登录限流 + 账号锁定 |
| 越权 | 路由层 RBAC + Service 层对象级校验 + 权限专项测试 |
| 注入攻击 → LLM（Prompt Injection） | 告警/知识内容视为数据非指令（结构隔离 + 明确 system 边界）；Agent 工具白名单、无写权限、危险动作必须人工批准；输出必须通过 Pydantic 结构校验 |
| SSRF | 出网仅限 LLM Provider 域名白名单；用户不可提供任意 URL 给后端抓取 |
| 敏感泄露 | 统一错误体不含堆栈；日志脱敏（密码/token/API Key 字段强制 redact）；`.env` 不入库（gitignore + 提供 `.env.example`） |
| 密钥管理 | 环境变量注入；生产用 Docker secrets 或外部 KMS（文档化）；LLM API Key 加密落库（Fernet，主密钥来自环境） |
| 供应链 | CI 集成 `pip-audit` + `npm audit`（fail on high） |
| 传输 | 强制 HTTPS（生产 Nginx/Caddy TLS），HSTS |
| 审计 | 登录/鉴权失败/AI 研判/确认/事件操作/配置变更全量 `audit_logs`（actor, action, resource, before/after 摘要, ip, ua, request_id） |

**速率限制**（Redis 滑动窗口）：全局 100 req/min/user；登录 5/min/IP；AI 触发 10/h/user；告警接入按 API Key 配额（默认 600/min）。

---

## 11. Observability Architecture

三支柱全部落地（不只在文档里）：

1. **Logging**：structlog JSON 输出；每请求注入 `request_id`（中间件生成/继承 `X-Request-ID`），Celery 任务传播同一 id → **全链路一个 ID 串起来**；级别、模块、耗时字段标准化。
2. **Metrics**：Prometheus `/metrics`（进程指标 + 业务指标：HTTP 时延直方图按路由、告警接入速率、AI 调用耗时/token/成本按 provider、Celery 队列深度、研判成功率）。Grafana JSON dashboard 随仓库交付。
3. **Tracing**：OpenTelemetry SDK（OTLP 导出，可接 Jaeger）；span 覆盖 HTTP → Service → Celery → LLM Gateway → Provider，AI 研判每步一个 span。
4. **健康检查**：`/healthz`（进程活）与 `/readyz`（依赖检查：DB/Redis/LLM 可达性），供编排探针与发布门禁。
5. **错误追踪**：Sentry SDK 可选（DSN 为空则关闭），异常含 request_id 便于关联。

---

## 12. Deployment Architecture

**决策：单机 Docker Compose 为目标生产形态（中小企业可运维），K8s manifest 作为 P2 交付。**

```
CI/CD (GitHub Actions)
  lint(ruff/mypy) → unit+integration tests(Postgres service容器) →
  build images(多阶段, sha tag) → 扫描(trivy) → 推送 registry →
  deploy staging → smoke test → [手动审批] → deploy prod
  回滚 = 切回上一镜像 tag + alembic downgrade（脚本化, 文档化）
```

**生产拓扑（单机 Compose）**：`nginx`(TLS/静态/限流) + `api`(uvicorn×2 worker) + `worker`(celery) + `beat`(celery beat 定时) + `postgres` + `redis` + 可选 `ollama`(本地模型)。资源限制、`restart: unless-stopped`、健康检查、日志轮转齐备。

**环境矩阵**：`dev`（本机 SQLite 可选降级 + 真实/模拟 LLM）→ `test`（CI，Postgres service + FakeLLM 确定性测试）→ `staging`（生产同构，模拟告警源压测）→ `prod`。配置全部环境变量驱动（pydantic-settings 校验，缺失即启动失败——**fail fast，不允许默认密钥上线**）。

---

## 13. 架构决策记录（ADR 摘要）

| # | 决策 | 备选（被否） | 核心理由 |
|---|---|---|---|
| ADR-1 | 模块化单体 | 微服务 | 团队规模与运维成本；模块边界保住可拆分性 |
| ADR-2 | FastAPI + Pydantic v2 | Spring Boot / NestJS | AI 生态、异步、Pydantic 一份模型服务 API 校验与 LLM 结构化输出 |
| ADR-3 | PostgreSQL + pgvector 单库 | 独立向量库(Milvus/Qdrant) | 数据规模小；少一个有状态服务；事务一致性 |
| ADR-4 | 自研 Agent 循环 | LangChain/LangGraph | 步骤有限、审计要求每步可控可测、避免重抽象 |
| ADR-5 | Celery + Redis | ARQ / Dramatiq / RQ | 企业认知度最高、重试/定时/监控成熟、利于简历 |
| ADR-6 | JWT + Refresh 轮换 | 服务端 Session | 无状态水平扩展；OWASP 推荐的轮换+重用检测 |
| ADR-7 | 显式状态机 | 工作流引擎 | 本期仅 3 条简单流；引擎成本不成立（P2 再评估） |
| ADR-8 | React + Tailwind 自建组件 | AntD/ElementPlus | 避免"传统后台"观感；现代 SaaS 质感 |
| ADR-9 | 单机 Compose 生产 | K8s 优先 | 目标用户运维能力；K8s manifest 留作 P2 |
| ADR-10 | 无 LLM 时规则引擎降级 | 硬依赖 LLM | 安全运营系统不允许因外部 API 故障而整体不可用 |

---

Phase 1 产物：本文件 + `architecture.html`（交互式可视化）。进入 Phase 2 数据库设计。

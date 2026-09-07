# AISOC 数据库设计（DATABASE.md）

> 版本 v1.0 ｜ Phase 2 ｜ 引擎：PostgreSQL 16 + pgvector ｜ 迁移：Alembic
>
> 本文件是 schema 的**权威定义**，代码中的 SQLAlchemy 模型与迁移以此为准。实现落位：`backend/app/models/`（Phase 2 交付）。

---

## 1. 全局约定

| 约定 | 规则 | 理由 |
|---|---|---|
| 主键 | 业务表 `id UUID`（应用层生成 UUIDv7） | 时间有序利于 B-tree 局部性；不暴露业务计数；未来多库合并安全 |
| 审计列 | 所有表 `created_at`、`updated_at`（`timestamptz`，UTC，应用层填充） | 统一时区，杜绝本地时间歧义 |
| 软删除 | 仅 `alerts`、`knowledge_documents` 有 `deleted_at` | 审计类数据只增不删；其余硬删除（有审计兜底） |
| 外键 | 显式 `ON DELETE` 行为：业务关系 `RESTRICT`，归属关系 `CASCADE` | 防误删链式扩散 |
| 命名 | 表/列 snake_case 单数；索引 `ix_<table>_<cols>`；唯一 `uq_`；FK `fk_<table>_<ref>` | 可读、可 grep |
| 枚举 | Python Enum + `VARCHAR(32)` 存储（非 PG 原生 ENUM） | 原生 ENUM 迁移痛苦，应用层校验足够 |
| 审计表 | `audit_logs`/`llm_calls`/`ai_steps` 只增不删，无 UPDATE/DELETE 代码路径 | 不可篡改性 |
| 多租户 | 所有业务表含 `tenant_id UUID`，MVP 恒为 default 租户 | P2 多租户化无需改表 |
| 向量 | `embedding vector(1024)`（bge-m3 维度），HNSW cosine | 维度由默认嵌入模型定，更换模型需重建索引（文档化） |

### ER 总览（6 域 26 表）

```
identity ──┐                     alerts ── incidents
users ─ roles ─ permissions        alerts → alert_enrichments → triage_results → alert_feedback
api_keys                           alerts ─< incident_alerts >─ incidents ─< tasks / comments
                                   knowledge_documents ─< knowledge_chunks
ai ──────────────────────────────── llm_calls ─< ai_runs ─< ai_steps / ai_tool_calls
                                   ai_conversations ─< ai_messages
ops ─────────────────────────────── audit_logs · notifications · system_configs · idempotency_keys
                                   threat_intel · assets（研判工具的数据底座）
```

---

## 2. Identity 域（认证授权）

### users
| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| tenant_id | UUID | NOT NULL, default default-tenant | 多租户预留 |
| email | VARCHAR(255) | NOT NULL, **UQ**(tenant_id,email) | 登录标识 |
| password_hash | VARCHAR(255) | NOT NULL | argon2id |
| display_name | VARCHAR(64) | NOT NULL | |
| is_active | BOOLEAN | NOT NULL DEFAULT true | 停用而非删除 |
| failed_login_count | SMALLINT | NOT NULL DEFAULT 0 | 锁定计数 |
| locked_until | TIMESTAMPTZ | NULL | 锁定截止 |
| last_login_at | TIMESTAMPTZ | NULL | |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL | |

索引：`uq_users_tenant_email(tenant_id,email)`。

### roles / permissions / role_permissions / user_roles
经典 RBAC 五表（users 之上）。
- `roles(id, tenant_id, code VARCHAR(32) UQ, name, is_system BOOLEAN)`——`admin/analyst/viewer` 为系统预设不可删。
- `permissions(id, code VARCHAR(64) UQ, description)`——`resource:action` 格式，种子数据初始化。
- `role_permissions(role_id FK CASCADE, permission_id FK RESTRICT)`——PK(role_id,permission_id)。
- `user_roles(user_id FK CASCADE, role_id FK RESTRICT)`——PK(user_id,role_id)。

### api_keys（机器接入）
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(64) | 标识用途（如 "waf-ingest"） |
| key_prefix | VARCHAR(12) NOT NULL | 明文前缀（`ais_`+8位），用于展示辨识 |
| key_hash | CHAR(64) NOT NULL UQ | sha256(完整 key) |
| scopes | JSONB NOT NULL | `["alerts:write"]` |
| rate_limit_per_min | INT NOT NULL DEFAULT 600 | |
| is_active | BOOLEAN DEFAULT true | |
| last_used_at | TIMESTAMPTZ NULL | |
| expires_at | TIMESTAMPTZ NULL | 可选过期 |
| created_by | UUID FK→users RESTRICT | |

索引：`key_hash` 唯一即查询路径。

### refresh_tokens
`id UUID PK, user_id FK CASCADE, jti CHAR(36) UQ NOT NULL, family_id UUID NOT NULL`（轮换链，重用检测按 family 整链撤销）`, expires_at, revoked_at NULL, created_at`。索引：`ix(jti)`、`ix(family_id)`、`ix(user_id, expires_at)`。

---

## 3. Alerts 域（告警闭环）

### alerts
| 列 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| tenant_id | UUID | NOT NULL, ix(tenant_id,status,created_at) | |
| source | VARCHAR(64) | NOT NULL | 来源标识（edr/waf/custom） |
| external_id | VARCHAR(255) | NOT NULL, **UQ(source, external_id)** | 幂等去重键 |
| title | VARCHAR(255) | NOT NULL | |
| description | TEXT | NULL | |
| severity | VARCHAR(16) | NOT NULL, ix | 原始级别 low/medium/high/critical |
| status | VARCHAR(24) | NOT NULL DEFAULT 'new', ix(tenant,status,created_at) | 状态机 |
| alert_type | VARCHAR(64) | NOT NULL | 分类（brute_force/malware/…） |
| src_ip | INET | NULL, ix | 检索维度 |
| dst_ip | INET | NULL | |
| src_host | VARCHAR(255) | NULL | |
| user_account | VARCHAR(128) | NULL | 涉事账号 |
| raw_payload | JSONB | NOT NULL, GIN | 原始报文，完整保真 |
| occurred_at | TIMESTAMPTZ | NOT NULL, ix | 事件发生时间 |
| confirmed_by | UUID FK→users NULL | | |
| confirmed_as | VARCHAR(16) NULL | | true_positive/false_positive |
| confirm_reason | TEXT NULL | | |
| confirmed_at | TIMESTAMPTZ NULL | | |
| degraded | BOOLEAN NOT NULL DEFAULT false | | 规则降级研判标记 |
| deleted_at | TIMESTAMPTZ NULL | | 软删除 |

索引：`uq_alerts_source_external(source,external_id)`、`ix_alerts_tenant_status_created(tenant_id,status,created_at DESC)`、`ix_alerts_severity(severity)`、`ix_alerts_src_ip(src_ip)`、GIN `ix_alerts_raw_payload`。

### alert_enrichments（工具富化结果，一条告警多次）
`id, alert_id FK CASCADE, tool_name VARCHAR(64), payload JSONB, latency_ms INT, created_at`。索引：`ix(alert_id)`。供研判报告页"证据"展示与回放。

### triage_results（AI 研判结论，1:1~N 告警，最新有效）
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| alert_id | UUID FK→alerts CASCADE, ix | |
| run_id | UUID FK→ai_runs | 关联执行记录（可回放） |
| classification | VARCHAR(32) | true_positive/false_positive/benign_suspicious/needs_investigation |
| severity | VARCHAR(16) | AI 定级 |
| confidence | SMALLINT | 0–100 |
| reasoning | TEXT | 结论说明 |
| evidence | JSONB | `[{source, ref, quote}]` 强制引用 |
| recommended_actions | JSONB | `[{action, target, reason, requires_approval}]` |
| prompt_version | VARCHAR(32) | 评估可复现 |
| degraded | BOOLEAN | 降级标记 |
| model_key | VARCHAR(64) | 实际使用的模型 |
| created_at | | |

索引：`ix_triage_results_alert(alert_id, created_at DESC)`——取最新一条。

### alert_feedback（人工反馈，闭环评估数据源）
`id, alert_id FK CASCADE, triage_result_id FK RESTRICT, user_id FK RESTRICT, agreed BOOLEAN, human_verdict VARCHAR(32), comment TEXT NULL, created_at`。采纳率 = agreed 占比。

---

## 4. Incidents 域（事件处置）

### incidents
`id, tenant_id, title, description NULL, severity, status VARCHAR(16) DEFAULT 'new'（PICERL 状态机）, assigned_to FK→users NULL, source_alert_id FK→alerts SET NULL, sla_due_at NULL, opened_by FK→users, closed_at NULL, close_summary NULL, reopened_count SMALLINT DEFAULT 0, created_at/updated_at`。
索引：`ix_incidents_tenant_status(tenant_id,status)`、`ix_incidents_assigned(assigned_to)`、`ix_incidents_created(created_at DESC)`。

### incident_alerts（多对多）
`incident_id FK CASCADE, alert_id FK RESTRICT, linked_by FK→users, linked_at`，PK(incident_id, alert_id)。RESTRICT 防止删告警悬空事件证据链。

### tasks
`id, incident_id FK CASCADE, tenant_id, title, description NULL, status VARCHAR(16) DEFAULT 'todo', assignee FK→users NULL, due_at NULL, blocked_reason VARCHAR(255) NULL, completed_at NULL, created_by FK→users, created_at/updated_at`。索引：`ix_tasks_incident(incident_id,status)`、`ix_tasks_assignee(assignee,status)`。

### comments（事件/任务评论，polymorphic 受限实现）
`id, tenant_id, author_id FK→users RESTRICT, incident_id FK CASCADE NULL, task_id FK CASCADE NULL, body TEXT, created_at, updated_at`。CHECK `(incident_id IS NOT NULL) <> (task_id IS NOT NULL)`——恰好挂在一处。

---

## 5. Knowledge 域（RAG）

### knowledge_documents
`id, tenant_id, title, source_path VARCHAR(512)（存储相对路径）, mime_type, size_bytes BIGINT, sha256 CHAR(64)（去重+完整性）, status VARCHAR(16)（pending/indexed/failed）, chunk_count INT DEFAULT 0, error TEXT NULL, uploaded_by FK→users, deleted_at NULL（软删）, created_at/updated_at`。
索引：`ix_docs_tenant_status(tenant_id,status)`、UQ(sha256)。

### knowledge_chunks
`id, document_id FK CASCADE, chunk_index INT, content TEXT, token_count INT, embedding vector(1024) NULL, meta JSONB（标题路径/页码）, created_at`。
索引：`uq_chunks_doc_idx(document_id, chunk_index)`、**HNSW(embedding vector_cosine_ops)**。

> SQLite 降级（本地开发）：embedding 存 BLOB，检索用 numpy 暴力余弦（<10⁵ chunk 无感差异）；生产 PG 走 HNSW。检索接口抽象不变。

---

## 6. AI 域（治理与审计核心）

### llm_calls（每次 LLM 调用一条，成本核算事实表）
`id UUID, run_id UUID NULL FK→ai_runs SET NULL, purpose VARCHAR(32)（triage/embed/chat/eval）, provider VARCHAR(32), model_key VARCHAR(64), prompt_tokens INT, completion_tokens INT, cost_usd NUMERIC(10,6), latency_ms INT, status VARCHAR(16)（ok/timeout/error/rate_limited）, error_code VARCHAR(64) NULL, request_meta JSONB（不含敏感内容）, created_at`。
索引：`ix_llm_calls_created(created_at DESC)`、`ix_llm_calls_provider_model(provider,model_key)`、`ix_llm_calls_purpose_created(purpose,created_at)`。

### ai_runs（一次 Agent 执行）
`id, alert_id FK→alerts NULL, purpose VARCHAR(32), status VARCHAR(16)（running/succeeded/failed/cancelled/timeout）, prompt_version, model_key, input_snapshot JSONB, output JSONB NULL, error TEXT NULL, total_prompt_tokens INT, total_completion_tokens INT, total_cost_usd NUMERIC(10,6), step_count SMALLINT, started_at, finished_at NULL, triggered_by FK→users NULL`。

### ai_steps / ai_tool_calls（回放粒度）
- `ai_steps(id, run_id FK CASCADE, step_no SMALLINT, kind VARCHAR(16)（plan/tool/finalize）, llm_raw TEXT, parsed JSONB NULL, created_at)`，UQ(run_id, step_no)。
- `ai_tool_calls(id, run_id FK CASCADE, step_no SMALLINT, tool_name VARCHAR(64), args JSONB, result JSONB NULL, status VARCHAR(16), latency_ms INT, error TEXT NULL, created_at)`，索引 ix(run_id)。

### ai_conversations / ai_messages（P1 对话助手，表先行）
`ai_conversations(id, user_id FK CASCADE, title, created_at/updated_at)`；`ai_messages(id, conversation_id FK CASCADE, role VARCHAR(16)（user/assistant/system/tool）, content TEXT, refs JSONB NULL（引用的 chunk/告警）, llm_call_id FK→llm_calls NULL, created_at)`。

---

## 7. Ops 域（平台运营）

### threat_intel（研判工具数据底座，可由连接器扩充）
`id, tenant_id, ioc VARCHAR(255) NOT NULL, ioc_type VARCHAR(16)（ip/domain/hash）, reputation SMALLINT（0–100）, tags JSONB, source VARCHAR(64), first_seen_at, last_seen_at, created_at/updated_at`。UQ(tenant_id, ioc, ioc_type)。

### assets
`id, tenant_id, kind VARCHAR(16)（host/container/service）, identifier VARCHAR(255)（IP/hostname）, display_name, criticality VARCHAR(8)（low/medium/high）, owner VARCHAR(64) NULL, tags JSONB, created_at/updated_at`。UQ(tenant_id, identifier)。

### audit_logs（append-only）
`id BIGGENERATED IDENTITY PK, tenant_id, actor_id UUID NULL（系统动作为 NULL）, actor_type VARCHAR(16)（user/api_key/system）, action VARCHAR(64)（如 alert.confirm / ai.triage / user.login）, resource_type VARCHAR(32), resource_id VARCHAR(64) NULL, detail JSONB（before/after 摘要，脱敏）, ip INET NULL, user_agent VARCHAR(255) NULL, request_id VARCHAR(36), created_at`。
索引：`ix_audit_created(created_at DESC)`、`ix_audit_actor(actor_id,created_at)`、`ix_audit_resource(resource_type,resource_id)`、`ix_audit_action_created(action,created_at)`。
**无 updated_at；应用层无 UPDATE/DELETE 路径；大表按月分区预留。**

### notifications
`id, tenant_id, recipient_id FK→users CASCADE, type VARCHAR(32), title VARCHAR(255), body TEXT, link_path VARCHAR(255) NULL, read_at TIMESTAMPTZ NULL, created_at`。索引：`ix_notif_recipient(recipient_id, read_at, created_at DESC)`。

### system_configs
`key VARCHAR(64) PK, value JSONB NOT NULL, description VARCHAR(255), updated_by FK→users NULL, updated_at`。运行时可变配置（模型路由策略、限流参数）；启动级配置走环境变量（fail-fast），此处仅存运营期可调项。

### idempotency_keys
`key VARCHAR(128), tenant_id, endpoint VARCHAR(255), request_hash CHAR(64), response_snapshot JSONB, status_code SMALLINT, created_at, expires_at`。PK(key, endpoint)；索引 ix(expires_at) 供清理任务。

---

## 8. 并发 / 一致性 / 性能设计要点

1. **告警状态机并发**：状态迁移用乐观并发——`UPDATE alerts SET status=:to WHERE id=:id AND status=:from`，影响行数为 0 即抛 `ConcurrentModification`（幂等重试安全）。
2. **研判幂等**：`triage_alert` 任务以 `alert_id + 当前 updated_at 指纹` 作幂等哨兵；重复投递时若已有 `running` 的 ai_run 则跳过（`ix` + 行锁 `FOR UPDATE SKIP LOCKED` 于消费查询）。
3. **计数类统计**（降噪率/采纳率）：不做触发器维护计数器，直接对索引列聚合 + 5min 缓存；数据量（≤10⁶）下 <100ms。
4. **GIN 与 JSONB**：raw_payload 全量 GIN 支持条件检索；高频过滤字段已提为列（src_ip/severity/status），不依赖 JSONB 查询。
5. **归档策略**：`alerts`/`audit_logs`/`llm_calls` 按 `created_at` 超 180 天迁至归档表（beat 定时任务，Phase 8 交付脚本）；在线表保持小索引。
6. **迁移纪律**：Alembic 每个变更可 `downgrade()`；破坏性变更两段式（先加后删，跨版本）。

---

## 9. 与实现物的对应

| 本文件 | 代码 |
|---|---|
| §2–7 表定义 | `backend/app/models/*.py`（SQLAlchemy 2.0 Mapped 风格） |
| 枚举 | `backend/app/models/enums.py`（Python Enum，单一事实来源） |
| 初始 schema | `backend/alembic/versions/0001_initial.py` |
| 种子数据（角色/权限/管理员） | `backend/app/db/seed.py` |
| SQLite 降级策略 | `backend/app/db/compat.py`（向量 BLOB + 暴力检索） |

Phase 2 完成。进入 Phase 3（AI 系统实现）。

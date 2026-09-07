# AISOC — AI 驱动的安全运营中心（AI-Powered Security Operations Center）

> 版本：v1.0 ｜ 日期：2026-09-07 ｜ 阶段：Phase 0 项目调研
>
> 一句话定位：**面向中小企业与安全团队的开源、可私有化部署的 AI 安全运营平台——用 LLM Agent 自动完成安全告警的富化、研判与分诊，人机协同处置安全事件，全流程可审计。**

---

## 1. 项目背景与问题定义

### 1.1 行业现状

安全运营中心（SOC）的核心日常工作是**告警分诊（Alert Triage）**：安全设备（IDS/EDR/WAF/防火墙/云审计）每天产生成百上千条告警，分析师需要对每条告警判断"是真攻击还是误报、严重程度如何、下一步怎么办"。

这个环节存在公认的结构性问题：

| 痛点 | 说明 | 业界数据 |
|---|---|---|
| **告警疲劳（Alert Fatigue）** | 告警量远超人力处理能力，大量告警无人查看 | 业界普遍报告 30%+ 告警从未被查看，误报率常在 50% 以上 |
| **研判耗时** | 单条告警研判需要跨多个系统查询（情报、资产、历史事件） | 人工研判单条告警约 10–40 分钟；Dropzone AI 宣称可压缩至 3–11 分钟 |
| **7×24 人力成本高** | 一线值守需要 3 班倒 | Tier-1 分析师是 SOC 最大的人力开支项 |
| **经验难沉淀** | 研判知识在老分析师脑中，人员流动即流失 | 中小企业通常没有成体系的 Playbook |
| **大厂方案贵且绑定** | Microsoft Security Copilot 单 SCU 约 $2,920/月，且绑定 Sentinel/Defender 生态 | 中小企业/MSSP 无法负担，也无法私有化 |

### 1.2 目标用户

| 用户 | 场景 | 核心诉求 |
|---|---|---|
| **中小企业安全工程师（主要）** | 1–5 人安全团队，自建或半自建安全体系 | 用 AI 顶替大部分 Tier-1 分诊工作，告警降噪，不再漏报 |
| **安全服务厂商 / MSSP（扩展）** | 同时服务多个客户的安全监控 | 多租户、告警集中研判、按客户隔离 |
| **安全运营个人学习者（简历/面试场景）** | 需要一个有真实业务闭环的 AI 工程项目 | 完整展示 LLM Gateway、Agent、RAG、RBAC、审计等工程能力 |

### 1.3 核心用户故事（驱动需求）

1. **作为安全分析师**，我希望平台自动接入各来源告警，并对每条告警自动完成"情报富化 → 关联分析 → 风险定级 → 给出研判结论与证据"，这样我只看 AI 判定为"需要人工介入"的告警。
2. **作为安全分析师**，我希望看到 AI 的每一步操作（调了什么工具、查了什么数据、引用了什么知识），**且 AI 只给建议不自动处置**，最终由我确认"真实事件 / 误报 / 需处置"。
3. **作为安全分析师**，我希望把确认结果反哺给平台（AI 判断对不对），并能把确认的真实事件升级为事件（Incident）、创建处置任务。
4. **作为 SOC 负责人**，我要求每一次 AI 研判都有完整审计记录：谁触发的、用了哪个模型、花了多少 token、AI 给了什么结论、人是否采纳。
5. **作为平台管理员**，我通过 RBAC 管理用户与权限（管理员 / 分析师 / 只读观察者），配置告警接入源与 AI 模型路由。
6. **作为安全工程师**，我可以向知识库导入安全 Playbook / 内部预案文档，AI 研判与问答基于知识库（RAG）作答并**给出引用出处**，不允许无依据编造。

---

## 2. 产品核心价值与差异化

### 2.1 核心价值主张

> **把 Tier-1 分析师的重复研判工作交给 AI Agent，人负责确认与处置；全过程可审计、可回放、可评估。**

四条业务闭环（每条都是完整闭环，不是 Demo）：

1. **告警闭环**：接入 → 去重 → AI 富化研判 → 人工确认 → 升级事件 / 关闭误报 → 统计降噪率。
2. **事件闭环**：告警升级为事件 → 事件处置任务（Task）→ 状态流转 → 复盘关闭 → MTTR 统计。
3. **知识闭环**：导入 Playbook/情报文档 → 切片向量化 → RAG 检索增强研判与问答 → 引用溯源。
4. **AI 治理闭环**：LLM 统一网关 → 模型路由/降级 → Token 成本核算 → AI 决策采纳率评估 → 反哺 Prompt 优化。

### 2.2 竞品分析（2025–2026 市场格局）

市场分为三类玩家：

| 阵营 | 代表产品 | 优势 | 劣势（即我们的空间） |
|---|---|---|---|
| **平台型 Copilot** | Microsoft Security Copilot（约 $2,920/月/SCU）、CrowdStrike Charlotte AI（宣称 98% 分诊准确率）、SentinelOne Purple AI | 与自家检测引擎深度整合、开箱即用 | 价格昂贵；深度绑定厂商生态；无法私有化；对非该生态告警源支持弱 |
| **自主分诊型创业公司** | Dropzone AI（$37M B 轮）、Prophet Security、Radiant Security、Qevlar AI | 供应商无关、7×24 自主调查 | 商业闭源 SaaS，数据需出境/出域；价格不透明；无法二次开发 |
| **SOAR 转型厂商** | Torq、Tines、D3、Swimlane | Playbook 编排成熟 | 本质是规则编排，AI 能力是附加项；同样闭源昂贵 |
| **开源/研究项目** | Vigil（Apache 2.0，13 Agent）、zhadyz/AI_SOC、NVIDIA Morpheus | 免费、可学习 | 多为研究级或框架级：缺产品化的权限/审计/多用户/前端/可观测性，离"可上线"距离远 |

### 2.3 我们的差异化（Product Moat）

1. **开源自托管**：数据不出域——这是与所有商业 AI SOC 的本质区别，也是安全行业客户的硬需求。
2. **Human-in-the-loop 是产品设计原则而非开关**：AI 只产生"研判建议 + 证据 + 置信度"，处置动作（封禁、工单）必须人工批准，天然规避"AI 自主处置事故"的企业落地最大阻力。
3. **AI 治理产品化**：Token 成本核算、模型路由与降级、AI 决策采纳率统计、每次研判可回放——商业产品很少把这些做成一等公民。
4. **完整企业工程栈**：RBAC、审计日志、限流、幂等、结构化日志、链路追踪、CI/CD——区别于开源研究项目。
5. **供应商无关的告警接入**：Webhook/API 标准接入 + 内置常见格式（syslog/EDR 风格样例），不绑定任何厂商。

### 2.4 明确不做的事（Scope 边界，防止范围失控）

- ❌ 不做日志采集/解析引擎（不做 SIEM 的数据接入层，告警通过 API/Webhook 进入）
- ❌ 不做检测规则引擎 / Sigma 规则管理（不做检测能力，只做告警后处理）
- ❌ MVP 不做自动处置（不自动封 IP/隔离主机，只生成"建议处置"）
- ❌ MVP 不做 SOAR 可视化 Playbook 编排器（放入 P2 路线图）
- ❌ 不训练/微调模型（只做应用层：Prompt、RAG、Agent、评估）

---

## 3. MVP 范围与优先级

### P0 — MVP（本期必须交付，全部要求真实可用、可测试）

| # | 功能 | 闭环要求 |
|---|---|---|
| 1 | 用户认证 + RBAC（admin / analyst / viewer） | 登录、角色权限贯穿 API 与前端 |
| 2 | 告警接入 API（API Key + Webhook）+ 告警列表/详情 | 外部可真实推入告警，幂等去重 |
| 3 | **AI 告警研判（核心）**：Agent 编排富化工具（威胁情报库查询、资产库查询、历史告警关联、知识库检索）→ 结构化结论（定级/定性/置信度/证据/建议） | 每次研判落库、可回放、token 成本可查 |
| 4 | 研判结果人工确认（真实事件/误报/需处置）+ 反馈记录 | 采纳率可统计 |
| 5 | 事件管理：告警升级事件、任务、状态流转、评论 | MTTR 可统计 |
| 6 | 知识库：文档上传、切片、向量化、RAG 检索问答（带引用） | 引用可溯源到原文档 |
| 7 | 安全仪表盘：告警量/降噪率/AI 采纳率/MTTR/token 成本 | 数据来自真实表 |
| 8 | 审计日志：登录、AI 研判、确认、事件操作全量审计 | 不可篡改追加写入 |

### P1 — 上线后第一个迭代

- AI 会话助手（SOC Copilot Chat：自然语言查告警/事件/知识库）
- 邮件/Webhook 通知通道
- 告警批量操作、高级筛选与saved search
- 模型路由策略可配置化（按任务/成本/优先级）

### P2 — 扩展方向

- 可视化 Playbook 编排器（SOAR 化）
- 多租户（MSSP 场景，Schema 预留 tenant_id）
- 更多连接器（Email、Syslog、云厂商告警格式适配器）
- 自动处置闭环（经双重审批后执行封禁类动作）
- AI 评估平台化（黄金数据集回归评测、Prompt A/B）

---

## 4. 成功指标（如何证明业务价值）

| 指标 | 定义 | 目标 |
|---|---|---|
| 告警降噪率 | AI 判定误报且被人确认的比例 / 总告警 | ≥ 40%（模拟数据集下验证） |
| 研判时延 | P95 告警接入 → AI 结论产出 | ≤ 60s |
| AI 采纳率 | 人确认与 AI 结论一致的比例 | ≥ 75% |
| MTTR | 事件创建 → 关闭中位时长 | 相比纯人工基线可对比 |
| 成本可控 | 每次研判 token 成本落库、可按模型统计 | 100% 覆盖 |

> 说明：本项目在本阶段使用**构造的真实感安全告警数据集**（标注了真/误报的 ground truth）验证以上指标——这是 AI 评估（Evaluation）的标准做法，用带标签数据集度量系统，而非用假数据冒充功能。

---

## 5. 关键风险与对策（需求评审意见）

| 风险 | 对策 |
|---|---|
| LLM 幻觉导致误判 | 结构化输出（Pydantic 校验）+ 证据字段强制引用（工具返回的真实数据）+ 置信度 + 无证据不下"真实攻击"结论 |
| LLM 服务不可用 | 多 Provider 故障转移链（主→备→规则引擎降级：无 LLM 时基于规则打标，系统不瘫） |
| Token 成本失控 | 网关层预算控制：单次研判 token 上限、按租户/天预算熔断、成本落库 |
| AI 被提示注入（告警内容本身可能携带恶意指令） | 告警数据视为不可信输入：与系统指令隔离、工具白名单、输出结构化校验、危险工具需人工批准 |
| 数据安全 | 开源自托管；API Key 加密存储；数据库不存明文密钥 |
| 范围蔓延 | 严格执行上文 Scope 边界，P1/P2 需求一律进 Backlog 不进本期 |

---

## 6. 技术选型结论（理由详见 ARCHITECTURE.md）

| 层 | 选型 | 一句话理由 |
|---|---|---|
| 后端 | Python 3.12+ / FastAPI / Pydantic v2 | AI 生态最成熟；Pydantic 即结构化输出与校验层；异步适配 LLM 流式调用 |
| 数据库 | PostgreSQL 16 + pgvector | 关系数据与向量同库，运维成本最低；JSONB 承接告警半结构化数据 |
| 缓存/队列 | Redis 7 + Celery | 限流、分布式锁、异步任务（AI 研判后台化）的成熟组合 |
| 前端 | React 18 + TypeScript + Vite + TailwindCSS | 现代 SaaS 观感（非传统后台）；类型安全；生态最全 |
| AI 接入 | 自研 LLM Gateway（OpenAI/Anthropic/Gemini/Qwen/DeepSeek/Ollama 适配器） | 统一抽象：路由、重试、超时、降级、成本核算，业务代码不感知厂商 |
| 部署 | Docker Compose（单机生产）+ GitHub Actions | 目标用户（中小企业）运维能力有限，单机 Compose 是最务实的生产形态 |

---

## 7. 竞品调研来源

- [Microsoft Security Copilot 定价与 Agent（Microsoft Learn / 官方定价页）](https://www.microsoft.com/en-us/security/pricing/microsoft-security-copilot)
- [Security Alert Triage Agent（Microsoft Learn）](https://learn.microsoft.com/en-us/defender-xdr/security-alert-triage-agent)
- [CrowdStrike Charlotte AI Detection Triage（官方，宣称 98% 准确率、每周节省 40+ 小时）](https://www.crowdstrike.com/en-us/platform/charlotte-ai/)
- [Dropzone AI $37M B 轮（BusinessWire）](https://www.businesswire.com/news/home/20260115943406/en/)、[Dropzone 官网（100% 告警 7×24 调查、MTTC 30–40 分钟 → 3–11 分钟）](https://www.dropzone.ai/)
- [The 12 Best Agentic SOC Platforms（D3 Security）](https://d3security.com/blog/best-agentic-soc-platforms/)
- [AI Tools for Security Alert Triage（Panther，价格区间 $36K–$810K+）](https://panther.com/blog/ai-tools-security-alert-triage)
- [AI-Augmented SOC: A Survey of LLMs and Agents（MDPI 2025）](https://www.mdpi.com/2624-800X/5/4/95)
- [Vigil: The Open Source AI SOC（Apache 2.0）](https://vigilsoc.org/)、[zhadyz/AI_SOC（GitHub，研究级）](https://github.com/zhadyz/AI_SOC)

---

**Phase 0 结论**：需求成立，方向为"AI 告警研判 + 安全事件管理"，MVP 八项功能构成完整业务闭环，范围边界明确。进入 Phase 1 系统架构设计。

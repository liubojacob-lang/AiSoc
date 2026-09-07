# AISOC 部署运维手册（DEPLOYMENT.md）

> 目标形态：**单机 Docker Compose 生产**（中小企业可运维），K8s manifest 为 P2。
> 环境矩阵：dev → test → staging → prod（配置全部环境变量驱动，prod 缺密钥拒绝启动）。

---

## 1. 首次部署（单机）

```bash
git clone <repo> && cd AISOC
cp .env.example .env
# 生成密钥并填入 .env：
python3 -c "import secrets;print(secrets.token_hex(32))"          # JWT_SECRET
python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # FERNET_KEY
# 编辑 .env：POSTGRES_PASSWORD / BOOTSTRAP_ADMIN_PASSWORD / LLM_ROUTING / 各 Provider Key

docker compose up -d --build
docker compose ps                       # 全部 healthy
curl -fsS http://localhost:8080/api/v1/readyz
# 浏览器打开 http://localhost:8080 → 用 BOOTSTRAP_ADMIN_PASSWORD 登录
```

启动顺序自动完成：`alembic upgrade head` → 种子（权限/角色/管理员）→ uvicorn(×2) / celery worker / beat / nginx(SPA+反代) / 备份 sidecar。

## 2. TLS

- 单机直接对外：推荐 Caddy 替换 nginx 边缘（自动 Let's Encrypt），或在宿主机用 certbot + 443 转发 8080。
- 有 LB/网关：在 LB 终止 TLS，nginx 容器仅 80 内部（安全头已在 nginx.conf 配置，HSTS 建议在 LB 加）。

## 3. 发布流程（CI/CD）

`GitHub Actions (.github/workflows/ci.yml)`：

```
lint+mypy → 测试(PG/Redis service 容器, golden-set AI 评估门禁) →
前端 tsc+build → 镜像构建(sha tag) → [trivy 扫描, 注册表配置后启用] →
deploy staging → /readyz 冒烟 → [environment: production 人工审批] → deploy prod
```

上线即执行迁移（`alembic upgrade head` 在 api 容器 entrypoint）；**破坏性迁移两段式**（先加后删，跨版本）。

## 4. 回滚（≤5 分钟）

```bash
./scripts/rollback.sh <previous_git_sha>
# 脚本：用旧 sha 镜像重建 api/worker/beat/frontend；
# 如上个版本 schema 更低，需手动执行 alembic downgrade -1（见脚本内提示）。
```

回滚演练：每次发布后在 staging 实际执行一次 rollback 脚本并验证 /readyz。

## 5. 备份与恢复

- 自动备份：`backup` sidecar 每日 `pg_dump -F c` → `./backups/`，保留 30 天。
- 恢复演练（建议每季度）：

```bash
docker compose exec db pg_restore -U aisoc -d aisoc_clean --no-owner /backups/aisoc_YYYYMMDD_HHMMSS.dump
# 校验：行数抽样 + 应用层 /readyz + 看板数据一致性
```

- 知识库原始文档在 `data/knowledge/` 卷，与 DB 备份同期归档。

## 6. 监控与告警

- 指标：`GET /metrics`（Prometheus 格式）——HTTP 时延直方图、AI 调用/耗时/token/成本计数、研判结果计数。
- 建议 Prometheus 抓取 15s + 以下告警规则（Grafana 导入随交付）：
  - `rate(aisoc_http_request_seconds_count{status=~"5.."}[5m]) / rate(...)` > 2% 持续 10min
  - `increase(aisoc_triage_runs_total{status="degraded"}[30m]) > 总量 30%` → LLM 链路异常
  - `aisoc_celery_queue_depth{queue="triage"} > 100` 持续 15min → 扩容 worker
  - 日成本 `aisoc_ai_cost_usd_total` 突增 > 5×7 日均值 → 预算异常
- 健康探针：`/healthz`（进程）`/readyz`（DB/Redis 依赖）——编排器以 readyz 为流量门禁。

## 7. 安全运维清单（上线前逐项打勾）

- [ ] `.env` 权限 600，不入库；所有默认密码已更换
- [ ] HTTPS 强制 + HSTS；CSP 已由 nginx 下发
- [ ] Postgres/Redis 不暴露公网端口（仅 compose 内网）
- [ ] API Key 最小 scope、按 Key 限流配额复核
- [ ] 日志脱敏抽查（密码/token/API Key 字段 redact）
- [ ] 备份恢复演练通过；回滚脚本演练通过
- [ ] LLM Provider 密钥只走环境变量；轮换流程 documented

## 8. 故障排查（Troubleshooting）

| 现象 | 排查 |
|---|---|
| api 启动即退出 | `docker compose logs api`——prod 缺 JWT_SECRET/FERNET_KEY 会 fail-fast；LLM_ROUTING 引用未配置 Key 的 provider 亦会拒绝启动 |
| 告警停在 triaging | 看 worker 日志与 `ai_runs.error`；LLM 超时（默认 120s）或预算超限；超时后告警转 `triage_failed` 可重试 |
| 研判全部 degraded | fallback 链耗尽：检查 Provider Key/额度/网络；规则兜底已保证功能可用，前端有明示标记 |
| refresh 登录失效 | refresh cookie path 限定 `/api/v1/auth`；反向代理不得改写 Cookie；`SameSite=Strict` 需要前后端同站（或调整 CORS/域名规划） |
| 队列堆积 | `aisoc_celery_queue_depth` 指标；优先扩 worker 副本（无状态），其次降低 LLM_ROUTING 档位 |

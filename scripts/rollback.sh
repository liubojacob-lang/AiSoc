#!/usr/bin/env bash
# AISOC 回滚脚本：切回上一镜像 tag 并降级数据库（如需要）。
# 用法: ./scripts/rollback.sh <previous_git_sha>
set -euo pipefail

TAG="${1:?usage: rollback.sh <previous_git_sha>}"
echo ">> rolling back to image tag: $TAG"

export DOCKER_REGISTRY="${DOCKER_REGISTRY:-ghcr.io/your-org/aisoc}"
cat > .env.rollback <<EOF
API_IMAGE=${DOCKER_REGISTRY}/api:${TAG}
FRONTEND_IMAGE=${DOCKER_REGISTRY}/frontend:${TAG}
EOF

echo ">> scaling down"
docker compose --env-file .env.rollback down api worker beat frontend

echo ">> (可选) 数据库降级 — 仅当上一个版本要求更低 schema 时执行:"
echo "   docker compose run --rm api alembic downgrade -1"

echo ">> starting previous version"
docker compose --env-file .env.rollback up -d
echo ">> verify: curl -fsS http://localhost:8080/api/v1/readyz"

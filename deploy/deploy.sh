#!/usr/bin/env bash
# ============================================================
# Eventron — 手动部署脚本 (在服务器上执行)
# 用法: ssh root@47.103.77.98 'bash /opt/eventron/repo/deploy/deploy.sh'
# ============================================================
set -euo pipefail

DEPLOY_DIR=/opt/eventron
REPO_DIR="$DEPLOY_DIR/repo"
COMPOSE_FILE="docker-compose.prod.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date +'%H:%M:%S')] ⚠️${NC} $1"; }
err() { echo -e "${RED}[$(date +'%H:%M:%S')] ❌${NC} $1"; }

# ── Pre-flight checks ────────────────────────────────────────
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    err ".env 文件不存在: $DEPLOY_DIR/.env"
    echo "请先从 deploy/.env.prod.example 复制并填写:"
    echo "  cp $REPO_DIR/deploy/.env.prod.example $DEPLOY_DIR/.env"
    echo "  vim $DEPLOY_DIR/.env"
    exit 1
fi

cd "$REPO_DIR"

# ── Pull latest code ─────────────────────────────────────────
log "拉取最新代码..."
git pull origin main 2>/dev/null || warn "git pull 失败，使用当前代码"

# ── Sync .env ─────────────────────────────────────────────────
log "同步 .env 配置..."
cp "$DEPLOY_DIR/.env" .env

# ── Database migration ────────────────────────────────────────
log "运行数据库迁移..."
docker compose -f "$COMPOSE_FILE" run --rm app alembic upgrade head || warn "迁移可能失败，继续..."

# ── Build & deploy ────────────────────────────────────────────
log "构建镜像 (可能需要几分钟)..."
docker compose -f "$COMPOSE_FILE" build app

log "启动服务..."
docker compose -f "$COMPOSE_FILE" up -d

# ── Cleanup ───────────────────────────────────────────────────
log "清理旧镜像..."
docker image prune -f

# ── Health check ──────────────────────────────────────────────
log "等待服务启动..."
sleep 15

max_retries=6
for i in $(seq 1 $max_retries); do
    if curl -sf http://localhost/health > /dev/null 2>&1; then
        echo ""
        log "✅ 部署成功！"
        echo ""
        echo "  🌐 http://47.103.77.98"
        echo "  📋 API: http://47.103.77.98/api/events"
        echo "  📊 Health: http://47.103.77.98/health"
        echo ""
        docker compose -f "$COMPOSE_FILE" ps
        exit 0
    fi
    warn "健康检查 ($i/$max_retries) 等待中..."
    sleep 5
done

err "健康检查超时！查看日志:"
docker compose -f "$COMPOSE_FILE" logs --tail=50 app
exit 1

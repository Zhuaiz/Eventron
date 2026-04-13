#!/bin/bash
# ============================================================
# 证书自动拉取 — event.bheartmedia.com
# 证书写到宿主机 /opt/eventron/ssl/，nginx 容器只读挂载
# crontab: 0 3 * * * /opt/eventron/repo/deploy/cert-pull.sh
# ============================================================
set -euo pipefail

API_URL="http://certkeeper.sjtickettech.com/api/cert/pull"
TOKEN="L17zFsKRZejBUcN8EGlOyJzvlEiOqjtRCX_KzibZ_80"
DOMAIN="bheartmedia.com"
CERT_DIR="/opt/eventron/ssl"
LOG_FILE="/var/log/cert-pull.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

mkdir -p "$CERT_DIR"

# 下载证书
TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

HTTP_CODE=$(curl -sf -o "$TMP_DIR/bundle.tar" -w '%{http_code}' \
    --max-time 30 "$API_URL?token=$TOKEN&domain=$DOMAIN&format=tar")

if [ "$HTTP_CODE" != "200" ]; then
    log "ERROR: 拉取失败 HTTP $HTTP_CODE"
    exit 1
fi

tar xf "$TMP_DIR/bundle.tar" -C "$TMP_DIR" 2>/dev/null

if [ ! -f "$TMP_DIR/cert.pem" ] || [ ! -f "$TMP_DIR/key.pem" ]; then
    log "ERROR: tar 包内容不完整"
    exit 1
fi

# 指纹比对
FP_FILE="$CERT_DIR/.fingerprint"
NEW_FP=$(openssl x509 -in "$TMP_DIR/cert.pem" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2)
OLD_FP=""
[ -f "$FP_FILE" ] && OLD_FP=$(cat "$FP_FILE")

if [ "$NEW_FP" = "$OLD_FP" ] && [ -n "$OLD_FP" ]; then
    log "INFO: 证书未变化，跳过"
    exit 0
fi

# 验证证书有效性
if ! openssl x509 -in "$TMP_DIR/cert.pem" -noout 2>/dev/null; then
    log "ERROR: 证书文件无效"
    exit 1
fi

# 验证证书和私钥匹配
CERT_MOD=$(openssl x509 -noout -modulus -in "$TMP_DIR/cert.pem" 2>/dev/null | openssl md5)
KEY_MOD=$(openssl rsa -noout -modulus -in "$TMP_DIR/key.pem" 2>/dev/null | openssl md5)
if [ "$CERT_MOD" != "$KEY_MOD" ]; then
    log "ERROR: 证书与私钥不匹配"
    exit 1
fi

# 备份旧证书
if [ -f "$CERT_DIR/$DOMAIN.pem" ]; then
    cp "$CERT_DIR/$DOMAIN.pem" "$CERT_DIR/$DOMAIN.pem.bak"
    cp "$CERT_DIR/$DOMAIN.key" "$CERT_DIR/$DOMAIN.key.bak"
fi

# 部署新证书到宿主机
cp "$TMP_DIR/cert.pem" "$CERT_DIR/$DOMAIN.pem"
cp "$TMP_DIR/key.pem"  "$CERT_DIR/$DOMAIN.key"
chmod 644 "$CERT_DIR/$DOMAIN.pem"
chmod 600 "$CERT_DIR/$DOMAIN.key"

# nginx -t 验证，失败则回滚
if ! docker exec repo-nginx-1 nginx -t 2>/dev/null; then
    log "ERROR: nginx -t 失败，回滚"
    if [ -f "$CERT_DIR/$DOMAIN.pem.bak" ]; then
        mv "$CERT_DIR/$DOMAIN.pem.bak" "$CERT_DIR/$DOMAIN.pem"
        mv "$CERT_DIR/$DOMAIN.key.bak" "$CERT_DIR/$DOMAIN.key"
    fi
    exit 1
fi

# Reload nginx
docker exec repo-nginx-1 nginx -s reload
echo "$NEW_FP" > "$FP_FILE"
log "OK: 证书已更新 ($OLD_FP → $NEW_FP)"

#!/usr/bin/env bash
# ============================================================
# Eventron — 阿里云服务器初始化脚本
# 用法: ssh root@47.103.77.98 'bash -s' < deploy/server-init.sh
# ============================================================
set -euo pipefail

echo "========== [1/7] 配置国内镜像源 (apt) =========="
cp /etc/apt/sources.list /etc/apt/sources.list.bak 2>/dev/null || true
cat > /etc/apt/sources.list << 'EOF'
deb https://mirrors.aliyun.com/ubuntu/ jammy main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ jammy-updates main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ jammy-security main restricted universe multiverse
EOF
apt-get update -qq

echo "========== [2/7] 安装基础工具 =========="
apt-get install -y -qq curl git ca-certificates gnupg lsb-release ufw

echo "========== [3/7] 安装 Docker (阿里云镜像) =========="
if ! command -v docker &>/dev/null; then
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker && systemctl start docker
    echo "Docker 安装完成: $(docker --version)"
else
    echo "Docker 已安装: $(docker --version)"
fi

echo "========== [4/7] 配置 Docker 国内镜像加速 =========="
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
    "registry-mirrors": [
        "https://mirror.ccs.tencentyun.com",
        "https://docker.m.daocloud.io",
        "https://hub-mirror.c.163.com"
    ],
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "20m",
        "max-file": "3"
    },
    "storage-driver": "overlay2"
}
EOF
systemctl daemon-reload && systemctl restart docker
echo "Docker 镜像加速已配置"

echo "========== [5/7] 创建部署目录 =========="
mkdir -p /opt/eventron/data
mkdir -p /opt/eventron/uploads
mkdir -p /opt/eventron/nginx/ssl
chown -R root:root /opt/eventron

echo "========== [6/7] 配置防火墙 =========="
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw --force enable
echo "防火墙已配置 (22, 80, 443)"

echo "========== [7/7] 环境信息 =========="
echo "---"
echo "OS:       $(lsb_release -ds 2>/dev/null || cat /etc/os-release | head -1)"
echo "Docker:   $(docker --version)"
echo "Compose:  $(docker compose version)"
echo "Disk:     $(df -h / | tail -1)"
echo "Memory:   $(free -h | grep Mem | awk '{print $2}')"
echo "---"
echo "✅ 服务器初始化完成！接下来："
echo "   1. 将 .env 文件放到 /opt/eventron/.env"
echo "   2. push 代码到 GitHub，CI/CD 将自动部署"

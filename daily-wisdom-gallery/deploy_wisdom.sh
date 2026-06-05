#!/bin/bash
# 每日箴言部署脚本
# 1. 重新构建静态站到 ~/Desktop/wisdom_site/（避开 iCloud provenance 锁）
# 2. 在 /tmp 下跑 wrangler，绕开 ~/.wrangler/ 的 iCloud 锁
# 3. 部署到 Cloudflare Pages 项目 wisdom-1986318
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 0. 准备 /tmp 工作目录（iCloud 锁 ~/.wrangler，必须用 /tmp）
WORK_DIR="/tmp/wrangler-work"
HOME_DIR="/tmp/wrangler-home"
mkdir -p "$WORK_DIR" "$HOME_DIR/.wrangler/config"

# 1. 同步 wrangler config（含 OAuth token）
if [ -f "$HOME/.wrangler/config/default.toml" ]; then
  cp "$HOME/.wrangler/config/default.toml" "$HOME_DIR/.wrangler/config/" > /tmp/_cp_log 2>&1 || true
fi

# 2. 构建静态站
echo "[1/2] 构建静态站..."
python3 "$SCRIPT_DIR/build_wisdom_site.py"

# 3. 部署到 Cloudflare Pages
echo "[2/2] 部署到 Cloudflare Pages (project: wisdom-1986318)..."
cd "$WORK_DIR"
HOME="$HOME_DIR" wrangler pages deploy /tmp/wisdom_site --project-name wisdom-1986318 --commit-dirty=true

#!/bin/bash
# 每日箴言部署脚本
# 1. 重新构建静态站到 ~/Desktop/wisdom_site/（避开 iCloud provenance 锁）
# 2. 在 /tmp 下跑 wrangler，绕开 ~/.wrangler/ 的 iCloud 锁
# 3. 部署到 Cloudflare Pages 项目 wisdom-1986318
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 0. 准备环境变量（API Token 优先于 OAuth）
if [ -z "$CLOUDFLARE_API_TOKEN" ] && [ -f "$HOME/.zshrc" ]; then
  eval "$(grep 'CLOUDFLARE_API_TOKEN=' $HOME/.zshrc)"
fi
export CLOUDFLARE_API_TOKEN

# 1. 准备 /tmp 工作目录（iCloud 锁 ~/.wrangler，必须用 /tmp）
WORK_DIR="/tmp/wrangler-work"
mkdir -p "$WORK_DIR" "$WORK_DIR/.wrangler/config" "$WORK_DIR/.wrangler/tmp"
# 绕开 ~/.wrangler 的 iCloud provenance 锁
# wrangler 4.86 的 getPagesProjectRoot() 默认用 process.cwd()，
# 所以只要 cwd 在 /tmp，.wrangler 就会创建在 /tmp 下，完全绕开 iCloud 锁
WRANGLER_CMD="wrangler"

# 2. 构建静态站
echo "[1/2] 构建静态站..."
python3 "$SCRIPT_DIR/build_wisdom_site.py"

# 3. 部署到 Cloudflare Pages（用 API Token 认证）
echo "[2/2] 部署到 Cloudflare Pages (project: wisdom-1986318)..."
cd "$WORK_DIR"  # 关键！cwd 必须在 /tmp，绕过 iCloud 锁
$WRANGLER_CMD pages deploy /tmp/wisdom_site --project-name wisdom-1986318 --commit-dirty=true

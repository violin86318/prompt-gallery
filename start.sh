#!/bin/bash
# 启动提示词画廊 + 每日箴言画廊服务
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/src/serve.py"

#!/usr/bin/env python3
"""每日箴言画廊静态站构建器
- 读取 wisdom_gallery.json
- 渲染成单文件 index.html（**内嵌 JSON 数据，不依赖 /api/**）
- 拷贝 7 张 wisd_*.png 到 wisdom_site/images/
- 输出目录：daily-wisdom-gallery/wisdom_site/
- 配合 wrangler pages deploy 部署到 Cloudflare Pages
"""

import json, shutil, sys
from pathlib import Path

# --- Paths ---
SCRIPT_DIR = Path(__file__).parent
PROMPT_GALLERY = SCRIPT_DIR.parent  # prompt-gallery/
BASE = PROMPT_GALLERY / "daily-wisdom"  # daily-wisdom/
GALLERY_DATA = BASE / "wisdom_gallery.json"
IMAGES_SRC = BASE  # wisd_*.png 就在 daily-wisdom/

# 输出到 /tmp/wisdom_site/（iCloud 锁 ~/Desktop/，必须用 /tmp）
import os
SITE_DIR = Path("/tmp/wisdom_site")
IMAGES_DST = SITE_DIR  # 图片直接放根目录（HTML 用 './' + item.image 相对路径）

TEMPLATE_HTML = SCRIPT_DIR / "index.html"     # 用 14.5KB 那个美版（带 Paper texture、Noto Serif SC）


def main():
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DST.mkdir(parents=True, exist_ok=True)

    # 1. 加载数据
    if not GALLERY_DATA.exists():
        print(f"[ERR] {GALLERY_DATA} 不存在", file=sys.stderr)
        sys.exit(1)
    with open(GALLERY_DATA, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"[1/3] 已加载 {len(data)} 条箴言", flush=True)

    # 2. 拷贝图片（iCloud 锁区里，源已存在则跳过 copy2 覆盖）
    copied = 0
    skipped = 0
    for entry in data:
        img_name = entry.get("image")
        if not img_name:
            continue
        src = IMAGES_SRC / img_name
        dst = IMAGES_DST / img_name
        if not src.exists():
            continue
        # 已存在且大小相同：跳过（iCloud 锁区不可覆盖）
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            skipped += 1
            continue
        try:
            shutil.copy2(src, dst)
            copied += 1
        except PermissionError as e:
            # iCloud 锁区 iCloud 文件不可覆写——清掉重新拷
            try:
                dst.unlink()
            except Exception:
                pass
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception as e2:
                print(f"[WARN] 拷贝 {img_name} 失败: {e2}", flush=True)
    print(f"[2/3] 已拷贝 {copied} 张图片（{skipped} 张已存在跳过）", flush=True)

    # 3. 渲染 HTML — 把数据内嵌进 index.html
    if not TEMPLATE_HTML.exists():
        print(f"[ERR] 模板 {TEMPLATE_HTML} 不存在", file=sys.stderr)
        sys.exit(1)
    html = TEMPLATE_HTML.read_text(encoding="utf-8")

    # 整段替换 loadData 函数体：直接赋值，不走 fetch
    embedded_js = json.dumps(data, ensure_ascii=False)

    # 用精确字符串匹配替换整个 loadData 函数
    old_block = '''async function loadData() {
  try {
    // 尝试从 API 加载
    const res = await fetch('/api/wisdoms');
    if (res.ok) {
      wisdoms = await res.json();
      return;
    }
  } catch(e) {}

  try {
    // 备用：直接加载 JSON 文件
    const res = await fetch('./wisdom_gallery.json');
    if (res.ok) {
      wisdoms = await res.json();
      return;
    }
  } catch(e) {}

  // 内嵌数据兜底
  wisdoms = [];
}'''
    new_block = 'async function loadData() {\n  wisdoms = ' + embedded_js + ';\n}'
    if old_block in html:
        html_v2 = html.replace(old_block, new_block)
        n_sub = 1
    else:
        print('[WARN] 未找到原始 loadData 函数，跳过替换', file=sys.stderr)
        html_v2 = html
        n_sub = 0

    print(f"[3/3] 替换 loadData 函数 {n_sub} 处", flush=True)

    # 写输出（iCloud 锁区不可覆写，unlink 后重建）
    out = SITE_DIR / "index.html"
    if out.exists():
        try:
            out.unlink()
        except PermissionError:
            pass
    out.write_text(html_v2, encoding="utf-8")
    print(f"✅ 静态站已构建: {SITE_DIR}/", flush=True)
    print(f"   - index.html ({out.stat().st_size // 1024}KB)", flush=True)
    print(f"   - {copied} 张 PNG（与 index.html 同目录）", flush=True)


if __name__ == "__main__":
    main()

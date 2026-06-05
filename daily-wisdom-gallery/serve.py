#!/usr/bin/env python3
"""每日箴言画廊 HTTP 服务 — 端口 8894

功能：
  - 静态文件服务（HTML/CSS/JS）
  - /api/wisdoms — 返回画廊 JSON 数据
  - /api/rebuild  — 从 wisdom_gallery.json + 图片目录重建
  - 自动 symlink 图片目录

启动：
  python3 serve.py
  python3 serve.py --port 8894
"""

import http.server, json, os, sys, argparse
from pathlib import Path

# BASE 直接指向 daily-wisdom/，这样图片和 JSON 都在 BASE 里
# 避免在 daily-wisdom-gallery/ 下建 images/（iCloud provenance 限制）
BASE = Path(__file__).parent.parent / "daily-wisdom"
DATA_DIR = BASE  # BASE 就是数据目录
GALLERY_DATA = BASE / "wisdom_gallery.json"
IMAGES_DIR = BASE  # 图片就在 BASE 里

PORT = 8895


class WisdomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def do_GET(self):
        if self.path == "/api/wisdoms":
            self._serve_wisdoms()
        elif self.path == "/api/stats":
            self._serve_stats()
        else:
            super().do_GET()

    def _serve_wisdoms(self):
        data = self._load_data()
        self._json_response(data)

    def _serve_stats(self):
        data = self._load_data()
        stats = {
            "total": len(data),
            "latest": data[-1] if data else None,
        }
        self._json_response(stats)

    def _load_data(self):
        if GALLERY_DATA.exists():
            with open(GALLERY_DATA, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _json_response(self, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[serve] {args[0]}")


def ensure_image_symlink():
    """图片在 BASE 目录里，无需 symlink/copy（iCloud provenance 限制下不建子目录）"""
    # 检查 BASE 里是否已有 wisd_*.png
    pngs = list(IMAGES_DIR.glob("wisd_*.png"))
    if not pngs:
        print(f"[warn] {IMAGES_DIR} 里没有 wisd_*.png", flush=True)
    else:
        print(f"[serve] {len(pngs)} 张图片已就位", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()

    ensure_image_symlink()

    if not GALLERY_DATA.exists():
        print(f"[warn] {GALLERY_DATA} not found, gallery will be empty")

    with http.server.HTTPServer((args.bind, args.port), WisdomHandler) as httpd:
        print(f"📜 每日箴言画廊 → http://localhost:{args.port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] stopped")


if __name__ == "__main__":
    main()

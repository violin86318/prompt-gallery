#!/usr/bin/env python3
"""Prompt Gallery HTTP server (port 8893) with /admin backend API."""

import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from datetime import datetime

PORT = 8893
BASE = Path(__file__).resolve().parent.parent
SITE_DIR = BASE / "site"
DATA_DIR = BASE / "data"
PROMPTS_FILE = DATA_DIR / "prompts.json"
TESTS_DIR = SITE_DIR / "assets" / "tests"
ADMIN_HTML = BASE / "admin.html"


def load_prompts():
    """Load prompts.json."""
    return json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))


def save_prompts(prompts):
    """Save prompts.json atomically."""
    tmp = PROMPTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PROMPTS_FILE)


def rebuild_site():
    """Run build_all.py to regenerate static site."""
    r = subprocess.run(
        [sys.executable, str(BASE / "src" / "build_all.py")],
        capture_output=True, text=True, timeout=120,
        cwd=str(BASE),
    )
    return {"ok": r.returncode == 0, "stdout": r.stdout[-500:], "stderr": r.stderr[-200:]}


def scan_test_images():
    """Scan disk for test images and return mapping number → tests."""
    mapping = {}
    if not TESTS_DIR.exists():
        return mapping
    for f in TESTS_DIR.iterdir():
        if not f.is_file():
            continue
        m = re.match(r"(gcli|bizyair)_(\d+)\.png$", f.name)
        if m:
            prefix, num = m.group(1), int(m.group(2))
            model = "Nano Banana 2" if prefix == "gcli" else "GPT Image 2"
            mapping.setdefault(num, {})[model] = {
                "image": f"assets/tests/{f.name}",
                "size": f"{f.stat().st_size // 1024}KB",
            }
    return mapping


class GalleryHandler(http.server.SimpleHTTPRequestHandler):
    """Serve static site + /admin API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    # ── Routing ──────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/admin" or path == "/admin/":
            self._serve_admin_html()
        elif path == "/wisdom-admin" or path == "/wisdom-admin/":
            self._serve_wisdom_admin()
        elif path.startswith("/api/wisdom"):
            self._handle_wisdom_api("GET", path, parsed.query)
        elif path.startswith("/api/"):
            self._handle_api("GET", path, parsed.query)
        elif path.startswith("/wisdom"):
            self._serve_wisdom(path)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if parsed.path.startswith("/api/wisdom"):
            self._handle_wisdom_api("POST", parsed.path, body)
        elif parsed.path.startswith("/api/"):
            self._handle_api("POST", parsed.path, body)
        else:
            self.send_error(404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if parsed.path.startswith("/api/wisdom"):
            self._handle_wisdom_api("PUT", parsed.path, body)
        elif parsed.path.startswith("/api/"):
            self._handle_api("PUT", parsed.path, body)
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/wisdom"):
            self._handle_wisdom_api("DELETE", parsed.path, "")
        elif parsed.path.startswith("/api/"):
            self._handle_api("DELETE", parsed.path, "")
        else:
            self.send_error(404)

    # ── Wisdom Gallery ──────────────────────────────────

    WISDOM_DIR = BASE / "daily-wisdom"

    def _serve_wisdom(self, path):
        """Serve daily-wisdom gallery files under /wisdom/"""
        # /wisdom/ or /wisdom → index.html
        if path in ("/wisdom", "/wisdom/"):
            fpath = self.WISDOM_DIR / "index.html"
        else:
            rel = path[len("/wisdom/"):]
            fpath = self.WISDOM_DIR / rel

        if fpath.exists() and fpath.is_file():
            ct = "text/html" if fpath.suffix == ".html" else \
                 "application/json" if fpath.suffix == ".json" else \
                 "image/png"
            self.send_response(200)
            self.send_header("Content-Type", f"{ct}; charset=utf-8" if ct == "text/html" else ct)
            self.send_header("Content-Length", fpath.stat().st_size)
            self.end_headers()
            self.wfile.write(fpath.read_bytes())
        else:
            self.send_error(404)

    # ── Admin HTML ───────────────────────────────────────

    def _serve_admin_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(ADMIN_HTML.read_bytes())

    # ── API Router ───────────────────────────────────────

    def _handle_api(self, method, path, payload):
        try:
            if path == "/api/prompts" and method == "GET":
                self._api_list_prompts()
            elif path == "/api/prompts/stats" and method == "GET":
                self._api_stats()
            elif re.match(r"^/api/prompts/(\d+)$", path) and method == "GET":
                num = int(re.search(r"/(\d+)$", path).group(1))
                self._api_get_prompt(num)
            elif re.match(r"^/api/prompts/(\d+)$", path) and method == "PUT":
                num = int(re.search(r"/(\d+)$", path).group(1))
                self._api_update_prompt(num, payload)
            elif path == "/api/prompts" and method == "POST":
                self._api_add_prompt(payload)
            elif re.match(r"^/api/prompts/(\d+)$", path) and method == "DELETE":
                num = int(re.search(r"/(\d+)$", path).group(1))
                self._api_delete_prompt(num)
            elif path == "/api/rebuild" and method == "POST":
                self._api_rebuild()
            elif path == "/api/scan-images" and method == "POST":
                self._api_scan_images()
            elif path == "/api/export" and method == "GET":
                self._api_export()
            elif path == "/api/generate-image" and method == "POST":
                self._api_generate_image(payload)
            else:
                self._json_response(404, {"error": "Not found"})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    # ── API Endpoints ────────────────────────────────────

    def _api_list_prompts(self):
        """GET /api/prompts — list all prompts (summary)."""
        prompts = load_prompts()
        disk_images = scan_test_images()
        summary = []
        for p in prompts:
            num = p["number"]
            # Merge disk scan results
            tests = disk_images.get(num, p.get("tests", {}))
            summary.append({
                "number": num,
                "title": p.get("title", ""),
                "category": p.get("category", ""),
                "heat": p.get("heat", ""),
                "structureType": p.get("structureType", ""),
                "hasTests": bool(tests),
                "testCount": len(tests),
                "date": p.get("date", ""),
                "postUrl": p.get("postUrl", ""),
            })
        self._json_response(200, summary)

    def _api_stats(self):
        """GET /api/prompts/stats — dashboard stats."""
        prompts = load_prompts()
        disk_images = scan_test_images()

        total = len(prompts)
        categories = {}
        for p in prompts:
            cat = p.get("category", "未分类")
            categories[cat] = categories.get(cat, 0) + 1

        gcli_count = sum(1 for n in disk_images if "Nano Banana 2" in disk_images[n])
        bizyair_count = sum(1 for n in disk_images if "GPT Image 2" in disk_images[n])
        missing_gcli = [p["number"] for p in prompts if p["number"] not in disk_images or "Nano Banana 2" not in disk_images[p["number"]]]
        missing_bizyair = [p["number"] for p in prompts if p["number"] not in disk_images or "GPT Image 2" not in disk_images[p["number"]]]

        # Latest prompts
        sorted_p = sorted(prompts, key=lambda x: x.get("date", ""), reverse=True)
        latest = [{"number": p["number"], "title": p.get("title", ""), "date": p.get("date", "")} for p in sorted_p[:5]]

        self._json_response(200, {
            "total": total,
            "categories": categories,
            "nanoBanana2": {"count": gcli_count, "total": total, "missing": missing_gcli},
            "gptImage2": {"count": bizyair_count, "total": total, "missing": missing_bizyair},
            "latest": latest,
        })

    def _api_get_prompt(self, number):
        """GET /api/prompts/:number — full prompt detail."""
        prompts = load_prompts()
        disk_images = scan_test_images()
        for p in prompts:
            if p["number"] == number:
                p["tests"] = disk_images.get(number, p.get("tests", {}))
                self._json_response(200, p)
                return
        self._json_response(404, {"error": f"Prompt #{number} not found"})

    def _api_update_prompt(self, number, payload):
        """PUT /api/prompts/:number — update prompt fields."""
        prompts = load_prompts()
        data = json.loads(payload) if isinstance(payload, bytes) else json.loads(payload)
        for p in prompts:
            if p["number"] == number:
                # Update allowed fields
                for key in ["title", "category", "subcategory", "heat", "type",
                            "needsRefImage", "refDesc", "postUrl", "structureDesc",
                            "innovation", "scenes", "exampleSpice", "avoidList",
                            "identity", "structureType", "date"]:
                    if key in data:
                        p[key] = data[key]
                if "structure" in data:
                    p["structure"] = data["structure"]
                save_prompts(prompts)
                self._json_response(200, {"ok": True, "prompt": p})
                return
        self._json_response(404, {"error": f"Prompt #{number} not found"})

    def _api_add_prompt(self, payload):
        """POST /api/prompts — add new prompt."""
        prompts = load_prompts()
        data = json.loads(payload) if isinstance(payload, bytes) else json.loads(payload)

        # Auto-assign next number
        max_num = max(p["number"] for p in prompts) if prompts else 0
        number = data.get("number", max_num + 1)

        # Check duplicate
        if any(p["number"] == number for p in prompts):
            self._json_response(409, {"error": f"Prompt #{number} already exists"})
            return

        title = data.get("title", f"新提示词 #{number}")
        import re as _re
        safe_title = _re.sub(r'[^\w]+', '-', title).strip('-')[:40]
        slug = f"{number}-{safe_title}"

        new_prompt = {
            "slug": slug,
            "number": number,
            "title": title,
            "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
            "category": data.get("category", "美学实验"),
            "subcategory": data.get("subcategory", ""),
            "identity": data.get("identity", ""),
            "needsRefImage": data.get("needsRefImage", False),
            "structureType": data.get("structureType", "broth-spice"),
            "structure": data.get("structure", {"broth": "", "spice": "", "catalyst": "", "full": ""}),
            "avoidList": data.get("avoidList", []),
            "scenes": data.get("scenes", ""),
            "tests": {},
            "related": data.get("related", {}),
            "stats": data.get("stats", {}),
            "heat": data.get("heat", "★★"),
            "type": data.get("type", "文生图"),
            "refDesc": data.get("refDesc", "❌"),
            "postUrl": data.get("postUrl", ""),
            "structureDesc": data.get("structureDesc", ""),
            "innovation": data.get("innovation", ""),
            "exampleSpice": data.get("exampleSpice", ""),
        }
        prompts.append(new_prompt)
        prompts.sort(key=lambda x: x["number"], reverse=True)
        save_prompts(prompts)
        self._json_response(201, {"ok": True, "prompt": new_prompt})

    def _api_delete_prompt(self, number):
        """DELETE /api/prompts/:number — delete prompt."""
        prompts = load_prompts()
        new_prompts = [p for p in prompts if p["number"] != number]
        if len(new_prompts) == len(prompts):
            self._json_response(404, {"error": f"Prompt #{number} not found"})
            return
        save_prompts(new_prompts)
        self._json_response(200, {"ok": True})

    def _api_rebuild(self):
        """POST /api/rebuild — rebuild static site."""
        result = rebuild_site()
        self._json_response(200, result)

    def _api_scan_images(self):
        """POST /api/scan-images — rescan disk images."""
        disk_images = scan_test_images()
        prompts = load_prompts()
        updated = 0
        for p in prompts:
            num = p["number"]
            if num in disk_images:
                p["tests"] = disk_images[num]
                updated += 1
        save_prompts(prompts)
        self._json_response(200, {"ok": True, "updated": updated, "total": len(disk_images)})

    def _api_export(self):
        """GET /api/export — download full prompts.json."""
        data = PROMPTS_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Disposition", "attachment; filename=prompts.json")
        self.end_headers()
        self.wfile.write(data)

    def _api_generate_image(self, payload):
        """POST /api/generate-image — trigger image generation for a prompt."""
        data = json.loads(payload) if isinstance(payload, bytes) else json.loads(payload)
        number = data.get("number")
        model = data.get("model", "gpt-image")  # or "banana"
        prompt_text = data.get("prompt", "")

        if not number or not prompt_text:
            self._json_response(400, {"error": "Missing number or prompt"})
            return

        cli_path = BASE / "../remio/skills/bizyair-skill/scripts/cli.py"
        endpoint = "bza-image-o2-base/text-to-image" if model == "gpt-image" else "bza-image-b2-base/text-to-image"
        prefix = "bizyair" if model == "gpt-image" else "gcli"
        output_path = TESTS_DIR / f"{prefix}_{number}.png"

        TESTS_DIR.mkdir(parents=True, exist_ok=True)

        # Truncate long prompts
        if len(prompt_text) > 2000:
            prompt_text = prompt_text[:2000]

        try:
            r = subprocess.run(
                [sys.executable, str(cli_path), "modelzoo-run", endpoint,
                 "--param", f"prompt={prompt_text}",
                 "--param", "width=1024", "--param", "height=1024",
                 "--output", str(output_path)],
                capture_output=True, text=True, timeout=600,
                cwd=str(cli_path.parent.parent.parent),
            )
            if output_path.exists() and output_path.stat().st_size > 1000:
                self._json_response(200, {
                    "ok": True,
                    "image": f"assets/tests/{output_path.name}",
                    "size": f"{output_path.stat().st_size // 1024}KB",
                    "model": "GPT Image 2" if model == "gpt-image" else "Nano Banana 2",
                })
            else:
                self._json_response(500, {"ok": False, "error": r.stderr[-300:] or "No image generated"})
        except subprocess.TimeoutExpired:
            self._json_response(504, {"ok": False, "error": "Generation timeout (600s)"})
        except Exception as e:
            self._json_response(500, {"ok": False, "error": str(e)})

    # ── Helpers ──────────────────────────────────────────

    def _json_response(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Wisdom Admin HTML ───────────────────────────────

    def _serve_wisdom_admin(self):
        """Serve the wisdom gallery admin page."""
        admin_file = BASE / "wisdom-admin.html"
        if admin_file.exists():
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(admin_file.read_bytes())
        else:
            self.send_error(404, "wisdom-admin.html not found")

    # ── Wisdom API ───────────────────────────────────────

    def _handle_wisdom_api(self, method, path, payload):
        """Handle /api/wisdom/* CRUD operations."""
        try:
            if path == "/api/wisdoms" and method == "GET":
                self._wisdom_api_list()
            elif path == "/api/wisdoms" and method == "POST":
                self._wisdom_api_add(payload)
            elif re.match(r"^/api/wisdoms/(\d+)$", path) and method == "GET":
                idx = int(re.search(r"/(\d+)$", path).group(1))
                self._wisdom_api_get(idx)
            elif re.match(r"^/api/wisdoms/(\d+)$", path) and method == "PUT":
                idx = int(re.search(r"/(\d+)$", path).group(1))
                self._wisdom_api_update(idx, payload)
            elif re.match(r"^/api/wisdoms/(\d+)$", path) and method == "DELETE":
                idx = int(re.search(r"/(\d+)$", path).group(1))
                self._wisdom_api_delete(idx)
            elif path == "/api/wisdoms/generate-caption" and method == "POST":
                self._wisdom_api_generate_caption(payload)
            elif path == "/api/wisdoms/regenerate-image" and method == "POST":
                self._wisdom_api_regenerate_image(payload)
            else:
                self._json_response(404, {"error": "Not found"})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _load_wisdoms(self):
        f = self.WISDOM_DIR / "wisdom_gallery.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        return []

    def _save_wisdoms(self, data):
        f = self.WISDOM_DIR / "wisdom_gallery.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)

    def _wisdom_api_list(self):
        data = self._load_wisdoms()
        self._json_response(200, data)

    def _wisdom_api_get(self, idx):
        data = self._load_wisdoms()
        if 0 <= idx < len(data):
            self._json_response(200, data[idx])
        else:
            self._json_response(404, {"error": "Not found"})

    def _wisdom_api_add(self, payload):
        body = json.loads(payload) if isinstance(payload, bytes) else payload
        data = self._load_wisdoms()
        entry = {
            "date": body.get("date", ""),
            "char": body.get("char", ""),
            "image": body.get("image", ""),
            "captions": body.get("captions", {"v1_life": "", "v2_opinion": "", "v3_quote": ""}),
            "created_at": body.get("created_at", ""),
        }
        data.append(entry)
        self._save_wisdoms(data)
        self._json_response(200, {"ok": True, "index": len(data) - 1})

    def _wisdom_api_update(self, idx, payload):
        body = json.loads(payload) if isinstance(payload, bytes) else payload
        data = self._load_wisdoms()
        if 0 <= idx < len(data):
            data[idx].update(body)
            self._save_wisdoms(data)
            self._json_response(200, {"ok": True})
        else:
            self._json_response(404, {"error": "Not found"})

    def _wisdom_api_delete(self, idx):
        data = self._load_wisdoms()
        if 0 <= idx < len(data):
            data.pop(idx)
            self._save_wisdoms(data)
            self._json_response(200, {"ok": True})
        else:
            self._json_response(404, {"error": "Not found"})

    def _wisdom_api_generate_caption(self, payload):
        """Placeholder: In real use, this would call GLM API."""
        body = json.loads(payload) if isinstance(payload, bytes) else payload
        char = body.get("char", "")
        self._json_response(200, {
            "ok": True,
            "captions": {
                "v1_life": f"（{char}）的生活分享文案占位",
                "v2_opinion": f"（{char}）的观点输出文案占位",
                "v3_quote": f"（{char}）的金句占位",
            }
        })

    def _wisdom_api_regenerate_image(self, payload):
        """Placeholder: In real use, this would call BizyAir."""
        self._json_response(200, {"ok": False, "error": "请在服务器端运行 daily_wisdom.py 生成图片"})


if __name__ == "__main__":
    os.chdir(str(SITE_DIR))
    with http.server.HTTPServer(("0.0.0.0", PORT), GalleryHandler) as httpd:
        print(f"🎨 Prompt Gallery serving on http://localhost:{PORT}")
        print(f"   📊 Admin panel: http://localhost:{PORT}/admin")
        print(f"   📁 Static dir: {SITE_DIR}")
        print(f"   📦 Data: {PROMPTS_FILE}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 Stopped")

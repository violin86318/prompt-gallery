#!/usr/bin/env python3
"""
Prompt Gallery 批量图片生成脚本
=================================
双模型批量生成：Nano Banana 2 (gcli2api) + GPT Image 2 (BizyAir)

用法:
  # 生成所有缺失的图片（两个模型都跑）
  python batch_gen.py

  # 只生成 Nano Banana 2
  python batch_gen.py --model gcli

  # 只生成 GPT Image 2
  python batch_gen.py --model bizyair

  # 只生成指定编号
  python batch_gen.py --numbers 31,48,74

  # 强制重新生成（覆盖已有图片）
  python batch_gen.py --force

  # 并发数（默认 1，串行更稳定）
  python batch_gen.py --concurrency 2

  # 从指定编号开始（断点续传）
  python batch_gen.py --start 50

  # 指定宽高比
  python batch_gen.py --aspect 16:9
"""

import argparse, base64, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
SITE_DIR = BASE / "site"
TESTS_DIR = SITE_DIR / "assets" / "tests"
LOG_DIR = BASE / "logs"

# ── API Config ─────────────────────────────────────────────────────────────
GCLI_API_URL = "http://192.168.50.188:7861"
GCLI_API_KEY = "violin"
GCLI_MODEL = "gemini-3.1-flash-image"

BIZYAIR_API_URL = "https://api.bizyair.cn/w/v1/webapp/task/openapi/create"
BIZYAIR_WEB_APP_ID = 52416
BIZYAIR_PROXY = "http://127.0.0.1:7890"


def get_bizyair_key():
    """从 .zshrc 读取 BizyAir API key"""
    import subprocess
    r = subprocess.run(
        ['zsh', '-c', "grep BIZYAIR_API_KEY ~/.zshrc | head -1 | cut -d\"'\" -f2"],
        capture_output=True, text=True
    )
    key = r.stdout.strip()
    if not key:
        print("❌ 无法从 ~/.zshrc 读取 BIZYAIR_API_KEY")
        sys.exit(1)
    return key


# ── Nano Banana 2 (gcli2api) ──────────────────────────────────────────────
def gen_gcli(prompt: str, output_path: str, aspect: str = "1:1") -> dict:
    """调用 gcli2api Antigravity 端点生成图片"""
    aspect_map = {
        "1:1": "", "16:9": "-16x9", "9:16": "-9x16",
        "4:3": "-4x3", "3:4": "-3x4", "21:9": "-21x9"
    }
    suffix = aspect_map.get(aspect, "")
    full_model = f"{GCLI_MODEL}{suffix}"
    endpoint = f"{GCLI_API_URL}/antigravity/v1/models/{full_model}:generateContent"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    headers = {
        "x-goog-api-key": GCLI_API_KEY,
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    for attempt in range(3):
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0

            if "candidates" not in result:
                return {"ok": False, "error": "无 candidates", "elapsed": elapsed}

            parts = result["candidates"][0].get("content", {}).get("parts", [])
            for p in parts:
                if "inlineData" in p:
                    img_data = base64.b64decode(p["inlineData"]["data"])
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(img_data)
                    size_kb = len(img_data) / 1024
                    return {
                        "ok": True, "path": output_path,
                        "size_kb": round(size_kb), "elapsed": round(elapsed, 1),
                        "model": full_model
                    }

            return {"ok": False, "error": "API 未返回图片数据", "elapsed": elapsed}

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                wait = (attempt + 1) * 15
                print(f"      HTTP {e.code}, {wait}s 后重试...")
                time.sleep(wait)
                continue
            return {"ok": False, "error": f"HTTP {e.code}: {body}", "elapsed": 0}
        except Exception as e:
            if attempt < 2:
                time.sleep((attempt + 1) * 10)
                continue
            return {"ok": False, "error": str(e), "elapsed": 0}

    return {"ok": False, "error": "达到最大重试次数", "elapsed": 0}


# ── GPT Image 2 (BizyAir) ────────────────────────────────────────────────
def gen_bizyair(prompt: str, output_path: str, api_key: str, aspect: str = "1:1") -> dict:
    """调用 BizyAir API 生成图片"""
    import subprocess

    payload = json.dumps({
        "web_app_id": BIZYAIR_WEB_APP_ID,
        "suppress_preview_output": False,
        "input_values": {
            "4:BizyAir_GPT_IMAGE_2_T2I_API.prompt": prompt,
            "4:BizyAir_GPT_IMAGE_2_T2I_API.aspect_ratio": aspect
        }
    })

    tmpfile = f"/tmp/bizyair_resp_{int(time.time())}.json"
    t0 = time.time()

    for attempt in range(3):
        try:
            r = subprocess.run([
                'curl', '-s', '-X', 'POST',
                '-x', BIZYAIR_PROXY,
                '--connect-timeout', '30', '-m', '300',
                BIZYAIR_API_URL,
                '-H', 'Content-Type: application/json',
                '-H', f'Authorization: Bearer {api_key}',
                '-d', payload,
                '-o', tmpfile,
                '-w', '%{http_code}'
            ], capture_output=True, text=True, timeout=310)

            elapsed = time.time() - t0
            http_code = r.stdout.strip()

            if http_code != '200':
                if http_code in ('429', '500', '502', '503') and attempt < 2:
                    wait = (attempt + 1) * 20
                    print(f"      HTTP {http_code}, {wait}s 后重试...")
                    time.sleep(wait)
                    continue
                return {"ok": False, "error": f"HTTP {http_code}", "elapsed": round(elapsed, 1)}

            with open(tmpfile) as f:
                resp = json.load(f)

            if resp.get('status') != 'Success':
                return {"ok": False, "error": f"status={resp.get('status')}", "elapsed": round(elapsed, 1)}

            outputs = resp.get('outputs', [])
            if not outputs:
                return {"ok": False, "error": "no outputs", "elapsed": round(elapsed, 1)}

            img_url = outputs[0].get('object_url', '')
            if not img_url:
                return {"ok": False, "error": "empty image URL", "elapsed": round(elapsed, 1)}

            # Download image
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            dl = subprocess.run([
                'curl', '-s', '-x', BIZYAIR_PROXY,
                '--connect-timeout', '30', '-m', '120',
                '-o', output_path, img_url
            ], capture_output=True, text=True, timeout=130)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                size_kb = os.path.getsize(output_path) / 1024
                return {
                    "ok": True, "path": output_path,
                    "size_kb": round(size_kb), "elapsed": round(elapsed, 1),
                    "model": "GPT Image 2"
                }
            return {"ok": False, "error": "下载失败", "elapsed": round(elapsed, 1)}

        except subprocess.TimeoutExpired:
            if attempt < 2:
                time.sleep((attempt + 1) * 15)
                continue
            return {"ok": False, "error": "curl timeout", "elapsed": round(time.time() - t0, 1)}
        except Exception as e:
            if attempt < 2:
                time.sleep((attempt + 1) * 10)
                continue
            return {"ok": False, "error": str(e), "elapsed": round(time.time() - t0, 1)}

    return {"ok": False, "error": "达到最大重试次数", "elapsed": 0}


# ── Main Logic ─────────────────────────────────────────────────────────────
def load_prompts():
    """加载 prompts.json"""
    path = DATA_DIR / "prompts.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_existing_images():
    """扫描已有测试图片"""
    existing = {"gcli": set(), "bizyair": set()}
    if TESTS_DIR.exists():
        for f in TESTS_DIR.iterdir():
            name = f.stem
            if name.startswith("gcli_"):
                existing["gcli"].add(int(name.replace("gcli_", "")))
            elif name.startswith("bizyair_"):
                existing["bizyair"].add(int(name.replace("bizyair_", "")))
    return existing


def build_task_list(prompts, existing, model_filter, number_filter, start_from, force):
    """构建待生成任务列表"""
    tasks = []

    for p in prompts:
        num = p["number"]
        text = p.get("structure", {}).get("full", "").strip()
        if not text:
            continue  # 跳过无提示词文本的条目

        # Filter by number
        if number_filter and num not in number_filter:
            continue
        if start_from and num < start_from:
            continue

        # Determine prompt for generation — use full text, truncate if too long
        gen_prompt = text[:2000] if len(text) > 2000 else text

        # Nano Banana 2 task
        if model_filter in ("all", "gcli"):
            if force or num not in existing["gcli"]:
                tasks.append({
                    "number": num,
                    "model": "gcli",
                    "model_label": "Nano Banana 2",
                    "prefix": "gcli_",
                    "prompt": gen_prompt,
                    "output": str(TESTS_DIR / f"gcli_{num}.png"),
                })

        # GPT Image 2 task
        if model_filter in ("all", "bizyair"):
            if force or num not in existing["bizyair"]:
                tasks.append({
                    "number": num,
                    "model": "bizyair",
                    "model_label": "GPT Image 2",
                    "prefix": "bizyair_",
                    "prompt": gen_prompt,
                    "output": str(TESTS_DIR / f"bizyair_{num}.png"),
                })

    # Sort by number desc (newest first), gcli before bizyair
    tasks.sort(key=lambda t: (-t["number"], 0 if t["model"] == "gcli" else 1))
    return tasks


def run_batch(tasks, aspect):
    """执行批量生成"""
    if not tasks:
        print("✅ 没有需要生成的任务（所有图片已存在）")
        return []

    print(f"\n📋 待生成: {len(tasks)} 张图片")
    gcli_tasks = [t for t in tasks if t["model"] == "gcli"]
    bizyair_tasks = [t for t in tasks if t["model"] == "bizyair"]
    print(f"   Nano Banana 2: {len(gcli_tasks)} 张")
    print(f"   GPT Image 2:   {len(bizyair_tasks)} 张")
    print(f"   预计耗时: ~{len(tasks) * 1.5:.0f} 分钟（串行）\n")

    bizyair_key = get_bizyair_key() if bizyair_tasks else None
    results = []
    start_all = time.time()

    for i, task in enumerate(tasks, 1):
        num = task["number"]
        label = task["model_label"]
        print(f"[{i}/{len(tasks)}] #{num} {label} — {task['prompt'][:60]}...")

        if task["model"] == "gcli":
            result = gen_gcli(task["prompt"], task["output"], aspect)
        else:
            result = gen_bizyair(task["prompt"], task["output"], bizyair_key, aspect)

        result["number"] = num
        result["model"] = task["model_label"]
        result["task_index"] = i
        results.append(result)

        if result["ok"]:
            print(f"      ✅ {result['size_kb']}KB, {result['elapsed']}s")
        else:
            print(f"      ❌ {result['error']}")

        # Rate limit: 2s between requests
        if i < len(tasks):
            time.sleep(2)

    elapsed_total = time.time() - start_all
    success = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    print(f"\n{'='*60}")
    print(f"🎉 批量生成完成! 总耗时: {elapsed_total/60:.1f} 分钟")
    print(f"   ✅ 成功: {len(success)}")
    print(f"   ❌ 失败: {len(failed)}")

    if failed:
        print(f"\n失败列表:")
        for r in failed:
            print(f"  #{r['number']} {r['model']}: {r['error']}")

    return results


def save_log(results):
    """保存生成日志"""
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"batch_{ts}.json"

    log_data = {
        "timestamp": ts,
        "total": len(results),
        "success": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    print(f"📝 日志: {log_path}")


def print_status():
    """打印当前图片覆盖率状态"""
    prompts = load_prompts()
    existing = get_existing_images()

    total = len(prompts)
    with_gcli = len(existing["gcli"])
    with_bizyair = len(existing["bizyair"])

    print(f"\n📊 Prompt Gallery 图片覆盖率")
    print(f"{'='*40}")
    print(f"总提示词: {total}")
    print(f"Nano Banana 2: {with_gcli}/{total} ({with_gcli*100//total}%)")
    print(f"GPT Image 2:   {with_bizyair}/{total} ({with_bizyair*100//total}%)")

    # Missing
    all_nums = {p["number"] for p in prompts}
    missing_gcli = sorted(all_nums - existing["gcli"])
    missing_bizyair = sorted(all_nums - existing["bizyair"])

    print(f"\n缺失 Nano Banana 2 ({len(missing_gcli)}): {missing_gcli[:20]}{'...' if len(missing_gcli) > 20 else ''}")
    print(f"缺失 GPT Image 2   ({len(missing_bizyair)}): {missing_bizyair[:20]}{'...' if len(missing_bizyair) > 20 else ''}")


def main():
    parser = argparse.ArgumentParser(description="Prompt Gallery 批量图片生成")
    parser.add_argument("--model", choices=["all", "gcli", "bizyair"], default="all",
                        help="生成模型: all=两个都跑, gcli=Nano Banana 2, bizyair=GPT Image 2")
    parser.add_argument("--numbers", type=str, default=None,
                        help="指定编号，逗号分隔: 31,48,74")
    parser.add_argument("--start", type=int, default=None,
                        help="从指定编号开始（断点续传）")
    parser.add_argument("--force", action="store_true",
                        help="强制重新生成（覆盖已有图片）")
    parser.add_argument("--aspect", default="1:1",
                        help="宽高比: 1:1, 16:9, 9:16, 4:3 (默认 1:1)")
    parser.add_argument("--status", action="store_true",
                        help="只显示覆盖率状态，不生成")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示任务列表，不实际生成")
    args = parser.parse_args()

    # Load data
    prompts = load_prompts()
    existing = get_existing_images()

    if args.status:
        print_status()
        return

    # Parse number filter
    number_filter = None
    if args.numbers:
        number_filter = set(int(n.strip()) for n in args.numbers.split(","))

    # Build task list
    tasks = build_task_list(
        prompts, existing, args.model,
        number_filter, args.start, args.force
    )

    if args.dry_run:
        print(f"\n📋 Dry run: {len(tasks)} 个任务")
        for t in tasks:
            print(f"  #{t['number']} {t['model_label']} → {t['output']}")
        return

    if not tasks:
        print("✅ 所有图片已生成，无待处理任务。用 --force 重新生成。")
        print_status()
        return

    # Run
    results = run_batch(tasks, args.aspect)
    if results:
        save_log(results)

    print(f"\n💡 运行 python {Path(__file__).parent / 'build_all.py'} 重新构建网站")


if __name__ == "__main__":
    main()

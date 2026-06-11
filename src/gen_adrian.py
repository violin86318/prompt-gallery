#!/usr/bin/env python3
"""
Adrian 测试图批量生成 — 带完整任务追踪 + 429 限流重试
========================================
- 逐个串行生成（不并发）
- 每张图记录: request_id, prompt, model, 图片路径, 耗时, 状态
- 追踪数据库: data/adrian_tasks.json
- 支持断点续传（跳过已成功的）
- 429 限流自动退避重试（等 60s / 120s / 180s）

用法:
  python3 src/gen_adrian.py                # 跑全部
  python3 src/gen_adrian.py --model gcli   # 只跑 gcli
  python3 src/gen_adrian.py --model bizyair # 只跑 bizyair
  python3 src/gen_adrian.py --numbers 1,2,3 # 指定编号
  python3 src/gen_adrian.py --status       # 查看进度
  python3 src/gen_adrian.py --retry-failed # 重试失败任务
"""

import argparse, base64, json, os, sys, time, subprocess, re, urllib.request
from pathlib import Path
from datetime import datetime

# ── gcli_archive 归档 ──────────────────────────────────────────────────────
sys.path.insert(0, os.path.expanduser("~/gcli_archive"))
try:
    import gcli_archive as _archive
except ImportError:
    _archive = None

# ── Paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
TESTS_DIR = BASE / "site" / "assets" / "tests"
TRACKER_PATH = DATA_DIR / "adrian_tasks.json"
SKILL_DIR = BASE.parent / "remio" / "skills" / "bizyair-skill" / "scripts"

# Model endpoints
# Nano Banana 2 → 本地 NAS gcli2api（免费，不走 bizyair）
GCLI_API = "http://192.168.50.188:7861"
GCLI_KEY = "violin"
GCLI_MODEL = "gemini-3.1-flash-image"
ENDPOINT_NANO = f"{GCLI_API}/antigravity/v1/models/{GCLI_MODEL}-16x9:generateContent"
# GPT Image 2 → bizyair（需代理）
ENDPOINT_GPT = "bza-image-o2-base/text-to-image"

# ── Tracker ────────────────────────────────────────────────────────────────
def load_tracker():
    if TRACKER_PATH.exists():
        with open(TRACKER_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"tasks": {}, "stats": {"total": 0, "success": 0, "failed": 0}}

def save_tracker(tracker):
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)

def record_task(tracker, key, request_id, model, prompt, output_path, status, size_kb=0, elapsed=0, error=""):
    tracker["tasks"][key] = {
        "request_id": request_id,
        "model": model,
        "prompt": prompt[:500],
        "output": str(output_path),
        "status": status,
        "size_kb": size_kb,
        "elapsed": round(elapsed, 1),
        "error": error[:200] if error else "",
        "ts": datetime.now().isoformat(),
    }
    tasks = tracker["tasks"]
    tracker["stats"] = {
        "total": len(tasks),
        "success": sum(1 for t in tasks.values() if t["status"] == "ok"),
        "failed": sum(1 for t in tasks.values() if t["status"] == "failed"),
    }
    save_tracker(tracker)

# ── Generator (with retry) ─────────────────────────────────────────────────
HELPER_TEMPLATE = r'''#!/usr/bin/env python3
import sys, os, json, subprocess, time
sys.path.insert(0, "{skill_dir}")
import api, modelzoo

key = api.require_api_key(None)
prompt = os.environ["_PROMPT"]
endpoint = "{endpoint}"
output = os.environ["_OUTPUT"]

t0 = time.time()
last_error = ""

for attempt in range(1, 4):  # max 3 attempts
    try:
        detail_result = modelzoo.get_detail(key, endpoint)
        detail_data = (detail_result.get("data") or {{}}).get("data") or detail_result.get("data") or {{}}
        payload = modelzoo.build_task_payload(detail_data, {{"prompt": prompt, "aspect_ratio": "1:1"}})

        create_result = modelzoo.create_task(key, endpoint, payload)

        # Check for rate limit (429)
        if isinstance(create_result, dict):
            status_code = create_result.get("status") or create_result.get("code")
            err_msg = ""
            if isinstance(create_result.get("error"), dict):
                err_msg = create_result["error"].get("message", "")
            elif isinstance(create_result.get("message"), str):
                err_msg = create_result["message"]
            if status_code == 429 or "限制" in err_msg or "rate" in err_msg.lower():
                wait = 60 * attempt
                print("429 rate limit, waiting " + str(wait) + "s (attempt " + str(attempt) + "/3)", file=sys.stderr)
                sys.stderr.flush()
                time.sleep(wait)
                continue

        create_data = (create_result.get("data") or {{}}).get("data") or create_result.get("data") or {{}}
        request_id = create_data.get("request_id")

        if not request_id:
            err = json.dumps(create_result, ensure_ascii=False)[:200]
            print(json.dumps({{"ok": False, "request_id": "", "error": "create failed: " + err}}))
            sys.exit(0)

        final = modelzoo.poll_until_done(key, request_id)
        status = final.get("status")
        outputs = final.get("outputs") or {{}}

        if status == "Success":
            urls = outputs.get("images", [])
            if urls:
                subprocess.run(["curl", "-sS", "--connect-timeout", "15", "--max-time", "120", "-o", output, urls[0]],
                              capture_output=True, timeout=130)
                sz = os.path.getsize(output)//1024 if os.path.exists(output) else 0
                elapsed = time.time() - t0
                print(json.dumps({{"ok": True, "request_id": request_id, "size_kb": sz, "elapsed": round(elapsed, 1)}}))
            else:
                print(json.dumps({{"ok": False, "request_id": request_id, "error": "no images"}}))
        else:
            print(json.dumps({{"ok": False, "request_id": request_id, "error": status + ": " + str(final.get("message",""))[:100]}}))
        sys.exit(0)

    except Exception as e:
        last_error = str(e)[:200]
        if attempt < 3:
            time.sleep(30)
            continue

elapsed = time.time() - t0
print(json.dumps({{"ok": False, "error": last_error, "elapsed": round(elapsed, 1)}}))
'''

def gen_gcli(prompt_text, output_path):
    """通过本地 NAS gcli2api (Gemini) 生成图片，免费不走 bizyair"""
    import base64, urllib.request, urllib.error
    _stem = Path(output_path).stem if output_path else "unknown"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    headers = {
        "x-goog-api-key": GCLI_KEY,
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(
        ENDPOINT_NANO,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    t0 = time.time()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for part in parts:
                if "inlineData" in part:
                    img_data = base64.b64decode(part["inlineData"]["data"])
                    with open(output_path, "wb") as f:
                        f.write(img_data)
                    sz = len(img_data) // 1024
                    # 归档到 gcli_archive
                    if _archive:
                        try:
                            _archive._upsert_task(
                                f"adrian_{_stem}",
                                datetime.now().isoformat(), prompt_text,
                                GCLI_MODEL + "-16x9", ENDPOINT_NANO, "success",
                                image_path=str(output_path),
                                file_size_kb=sz, duration=elapsed,
                                metadata={"source": "gen_adrian"}
                            )
                        except Exception:
                            pass
                    return {"ok": True, "size_kb": sz, "elapsed": round(elapsed, 1), "request_id": "gcli_local"}
            return {"ok": False, "error": "no image in response", "elapsed": round(elapsed, 1)}
        except Exception as e:
            if attempt < 2:
                time.sleep(10)
                continue
            return {"ok": False, "error": str(e)[:200], "elapsed": round(time.time()-t0, 1)}


def gen_bizyair(prompt_text, output_path):
    """通过 bizyair modelzoo 生成图片"""
    helper = '/tmp/_gen_one_bizy.py'
    with open(helper, 'w') as f:
        f.write(HELPER_TEMPLATE.format(
            skill_dir=str(SKILL_DIR),
            endpoint=ENDPOINT_GPT,
        ))
    env = os.environ.copy()
    env["_PROMPT"] = prompt_text
    env["_OUTPUT"] = str(output_path)
    r = subprocess.run([sys.executable, helper], capture_output=True, text=True, timeout=600, env=env)
    try:
        return json.loads(r.stdout.strip())
    except:
        return {"ok": False, "error": f"parse error: {r.stdout[:100:]} {r.stderr[:100:]}"}


def gen_image(prompt_text, output_path, endpoint):
    """根据 endpoint 分发到 gcli 或 bizyair"""
    if "antigravity" in endpoint:
        return gen_gcli(prompt_text, output_path)
    else:
        return gen_bizyair(prompt_text, output_path)

# ── Data ───────────────────────────────────────────────────────────────────
def load_adrian():
    with open(DATA_DIR / "adrian_prompts.json", encoding="utf-8") as f:
        return json.load(f)

def get_wrapped_prompt(p):
    """Adrian prompt 是系统指令型，需要包装成生成指令"""
    title = p.get("sampleText", p.get("title", ""))
    prompt = p.get("fullPrompt", "")
    if prompt.startswith("你是") or prompt.startswith("你是一名"):
        return f'请立即根据以下提示词生成一张图片，使用主题词 "{title}" 作为画面核心文字，默认使用 1:1 正方形比例。直接生成图片，不要回复文字。\n\n---\n{prompt}'
    return prompt

# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Adrian 测试图批量生成")
    parser.add_argument("--model", default="all", help="gcli / bizyair / all")
    parser.add_argument("--numbers", type=str, default=None, help="指定编号: 1,2,3")
    parser.add_argument("--status", action="store_true", help="查看进度")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败任务")
    args = parser.parse_args()

    adrian = load_adrian()
    tracker = load_tracker()

    if args.status:
        print_status(tracker, adrian)
        return

    number_filter = None
    if args.numbers:
        number_filter = set(int(n.strip()) for n in args.numbers.split(","))

    tasks = []
    for p in adrian:
        num = p["number"]
        if number_filter and num not in number_filter:
            continue

        prompt = get_wrapped_prompt(p)
        title = p.get("sampleText", p.get("title", ""))

        for model_name, label, key_suffix, endpoint in [
            ("gcli", "Nano Banana 2", "_gcli", ENDPOINT_NANO),
            ("bizyair", "GPT Image 2", "_bizyair", ENDPOINT_GPT),
        ]:
            if args.model not in ("all", model_name):
                continue
            key = f"adrian_{num}{key_suffix}"
            if args.retry_failed:
                t = tracker["tasks"].get(key, {})
                if t.get("status") == "ok":
                    continue
            else:
                if key in tracker["tasks"] and tracker["tasks"][key].get("status") == "ok":
                    continue
            tasks.append({
                "number": num, "model": model_name, "label": label,
                "key": key, "prompt": prompt, "title": title,
                "output": str(TESTS_DIR / f"{key_suffix.strip('_')}_{num}.png"),
                "endpoint": endpoint,
            })

    if not tasks:
        print("✅ 无待处理任务")
        print_status(tracker, adrian)
        return

    tasks.sort(key=lambda t: (t["number"], 0 if t["model"] == "gcli" else 1))

    print(f"📋 待生成: {len(tasks)} 张")
    est_min = len(tasks) * 2.5
    print(f"   预计耗时: ~{est_min:.0f} 分钟 ({est_min/60:.1f}h)\n")

    success = 0
    failed = 0
    t_start = time.time()

    for i, task in enumerate(tasks, 1):
        num = task["number"]
        label = task["label"]
        pct = i * 100 // len(tasks)

        if i > 1:
            avg = (time.time() - t_start) / (i - 1)
            eta_min = round(avg * (len(tasks) - i + 1) / 60)
            eta_str = f"ETA ~{eta_min}min"
        else:
            eta_str = ""

        print(f"[{i}/{len(tasks)}] {pct:3d}% {eta_str:>12s}  #{num} {label} [{task['title']}]")

        t0 = time.time()
        result = gen_image(task["prompt"], task["output"], task["endpoint"])
        elapsed = time.time() - t0

        if result.get("ok"):
            success += 1
            rid = result.get("request_id", "")
            sz = result.get("size_kb", 0)
            print(f"      ✅ {sz}KB, {elapsed:.0f}s, rid={rid[:16]}...")
            record_task(tracker, task["key"], rid, label, task["prompt"],
                       task["output"], "ok", sz, elapsed)
        else:
            failed += 1
            err = result.get("error", "unknown")
            rid = result.get("request_id", "")
            print(f"      ❌ {err[:120]}")
            record_task(tracker, task["key"], rid, label, task["prompt"],
                       task["output"], "failed", 0, elapsed, err)

        # 10s between tasks (avoid hourly rate limit)
        if i < len(tasks):
            time.sleep(10)

    total_min = (time.time() - t_start) / 60
    print(f"\n{'='*60}")
    print(f"🎉 完成! 总耗时: {total_min:.1f} 分钟")
    print(f"   ✅ 成功: {success}  ❌ 失败: {failed}")
    print_status(tracker, adrian)

def print_status(tracker, adrian):
    tasks = tracker.get("tasks", {})
    stats = tracker.get("stats", {})
    total_adrian = len(adrian) * 2

    print(f"\n📊 Adrian 测试图进度")
    print(f"{'='*50}")
    print(f"总任务: {total_adrian} (106 gcli + 106 bizyair)")
    print(f"成功: {stats.get('success', 0)}")
    print(f"失败: {stats.get('failed', 0)}")
    print(f"未开始: {total_adrian - stats.get('total', 0)}")

    gcli_ok = set()
    biz_ok = set()
    for key, t in tasks.items():
        if t.get("status") == "ok":
            m = int(re.search(r'adrian_(\d+)_', key).group(1))
            if key.endswith("_gcli"):
                gcli_ok.add(m)
            else:
                biz_ok.add(m)

    missing_gcli = sorted(set(range(1, 107)) - gcli_ok)
    missing_biz = sorted(set(range(1, 107)) - biz_ok)

    print(f"\ngcli:   ✅ {len(gcli_ok)}/106  缺: {missing_gcli[:20]}{'...' if len(missing_gcli)>20 else ''}")
    print(f"bizyair: ✅ {len(biz_ok)}/106  缺: {missing_biz[:20]}{'...' if len(missing_biz)>20 else ''}")

    failed = {k: v for k, v in tasks.items() if v.get("status") == "failed"}
    if failed:
        print(f"\n❌ 失败任务 ({len(failed)}):")
        for k, v in sorted(failed.items()):
            print(f"  {k}: {v.get('error','')[:80]}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
r"""
Prompt Gallery · 终端批量生图脚本
=================================
使用 BizyAir Skill CLI (ModelZoo) 调用 GPT Image 2 和 Nano Banana 2。

用法:
  cd ~/Library/Application\ Support/remio/Users/F2313D5DDFE8FCF316DC1149F06BB14B/agent/prompt-gallery

  # 查看 status
  python3 src/batch_gen_terminal.py --status

  # 只跑 GPT Image 2
  python3 src/batch_gen_terminal.py --model gpt-image

  # 只跑 Nano Banana 2
  python3 src/batch_gen_terminal.py --model banana

  # 两个都跑
  python3 src/batch_gen_terminal.py

  # 指定编号
  python3 src/batch_gen_terminal.py --model gpt-image --numbers 10,13

  # 从指定编号开始（断点续传）
  python3 src/batch_gen_terminal.py --model gpt-image --start 50

  # 强制重新生成
  python3 src/batch_gen_terminal.py --model gpt-image --force

  # 指定宽高比
  python3 src/batch_gen_terminal.py --model gpt-image --aspect 16:9

  # dry run（只看任务列表）
  python3 src/batch_gen_terminal.py --model gpt-image --dry-run

输出图片命名: gcli_<编号>.png (Nano Banana 2) / bizyair_<编号>.png (GPT Image 2)
"""

import argparse, json, os, sys, time, subprocess
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
TESTS_DIR = BASE / "site" / "assets" / "tests"
LOG_DIR = BASE / "logs"

# BizyAir Skill CLI
BIZYAIR_CLI = str(
    Path(__file__).resolve().parent.parent.parent
    / "remio" / "skills" / "bizyair-skill" / "scripts" / "cli.py"
)

# ModelZoo endpoints
ENDPOINT_GPT_IMAGE = "bza-image-o2-base/text-to-image"        # GPT Image 2
ENDPOINT_BANANA = "bza-image-b2-base/text-to-image"            # Nano Banana 2

# ── Colors ─────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log_ts():
    return f"{DIM}[{datetime.now().strftime('%H:%M:%S')}]{RESET}"


# ── Generic BizyAir ModelZoo generator ────────────────────────────────────
def gen_bizyair_modelzoo(prompt, output_path, endpoint, aspect="1:1"):
    """通过 BizyAir Skill CLI (modelzoo-run) 生成图片"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    for attempt in range(3):
        try:
            t0 = time.time()
            r = subprocess.run([
                sys.executable, BIZYAIR_CLI,
                "modelzoo-run", endpoint,
                "--param", f"prompt={prompt[:4000]}",
                "--param", f"aspect_ratio={aspect}",
            ], capture_output=True, text=True, timeout=600)

            elapsed = time.time() - t0
            stdout = r.stdout.strip()

            if r.returncode != 0:
                err = (r.stderr or stdout)[:200]
                # Check for rate limit or transient errors
                if any(k in err.lower() for k in ('rate', 'limit', 'busy', '429', '500', '502', '503')):
                    wait = (attempt + 1) * 30
                    if attempt < 2:
                        print(f"      {YELLOW}服务暂不可用，{wait}s 后重试...{RESET}")
                        time.sleep(wait)
                        continue
                return {"ok": False, "error": f"CLI error: {err[:100]}"}

            # Parse output to find image URL
            img_url = None
            for line in stdout.split('\n'):
                line = line.strip()
                if line.startswith('[images]'):
                    img_url = line.split('[images]', 1)[1].strip()
                    break
                # Also check for direct URL
                if line.startswith('http') and ('storage.bizyair.cn' in line or 'siliconflow' in line):
                    if any(ext in line.lower() for ext in ('.jpg', '.png', '.webp')):
                        img_url = line.strip()
                        break

            if not img_url:
                # Try to find any URL in output
                import re
                urls = re.findall(r'https?://\S+\.(?:jpg|png|webp)', stdout)
                if urls:
                    img_url = urls[0]

            if not img_url:
                if attempt < 2:
                    print(f"      {YELLOW}未找到图片 URL，{20}s 后重试...{RESET}")
                    time.sleep(20)
                    continue
                return {"ok": False, "error": f"no image URL in output: {stdout[-200:]}"}

            # Download image via curl (reliable, handles redirects)
            dl_result = subprocess.run([
                'curl', '-sS', '--connect-timeout', '15', '--max-time', '120',
                '-o', output_path, img_url
            ], capture_output=True, text=True, timeout=130)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return {
                    "ok": True,
                    "size_kb": os.path.getsize(output_path) // 1024,
                    "elapsed": round(elapsed, 1)
                }
            else:
                if attempt < 2:
                    print(f"      {YELLOW}下载失败，{15}s 后重试...{RESET}")
                    time.sleep(15)
                    continue
                return {"ok": False, "error": "下载失败"}

        except subprocess.TimeoutExpired:
            if attempt < 2:
                wait = (attempt + 1) * 30
                print(f"      {YELLOW}超时，{wait}s 后重试...{RESET}")
                time.sleep(wait)
                continue
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            if attempt < 2:
                time.sleep(15)
                continue
            return {"ok": False, "error": str(e)[:100]}

    return {"ok": False, "error": "达到最大重试次数"}


# Convenience wrappers
def gen_gpt_image(prompt, output_path, aspect="1:1"):
    return gen_bizyair_modelzoo(prompt, output_path, ENDPOINT_GPT_IMAGE, aspect)


def gen_banana(prompt, output_path, aspect="1:1"):
    return gen_bizyair_modelzoo(prompt, output_path, ENDPOINT_BANANA, aspect)


# ── Data ───────────────────────────────────────────────────────────────────
def load_prompts():
    path = DATA_DIR / "prompts.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_existing():
    existing = {"gcli": set(), "bizyair": set()}
    if TESTS_DIR.exists():
        for f in TESTS_DIR.iterdir():
            name = f.stem
            if name.startswith("gcli_"):
                try: existing["gcli"].add(int(name.replace("gcli_", "")))
                except: pass
            elif name.startswith("bizyair_"):
                try: existing["bizyair"].add(int(name.replace("bizyair_", "")))
                except: pass
    return existing


def build_tasks(prompts, existing, model_filter, number_filter, start_from, force):
    tasks = []
    for p in prompts:
        num = p["number"]
        text = p.get("structure", {}).get("full", "").strip()
        if not text:
            continue
        if number_filter and num not in number_filter:
            continue
        if start_from and num > start_from:
            continue

        gen_prompt = text[:2000]

        # Nano Banana 2 → saves as gcli_<num>.png
        if model_filter in ("all", "banana"):
            if force or num not in existing["gcli"]:
                tasks.append({
                    "number": num, "model": "banana",
                    "label": "Nano Banana 2",
                    "prompt": gen_prompt,
                    "output": str(TESTS_DIR / f"gcli_{num}.png"),
                })

        # GPT Image 2 → saves as bizyair_<num>.png
        if model_filter in ("all", "gpt-image"):
            if force or num not in existing["bizyair"]:
                tasks.append({
                    "number": num, "model": "gpt-image",
                    "label": "GPT Image 2",
                    "prompt": gen_prompt,
                    "output": str(TESTS_DIR / f"bizyair_{num}.png"),
                })

    # Sort: newest first, banana before gpt-image per number
    tasks.sort(key=lambda t: (-t["number"], 0 if t["model"] == "banana" else 1))
    return tasks


def run_batch(tasks, aspect):
    banana_tasks = [t for t in tasks if t["model"] == "banana"]
    gpt_tasks = [t for t in tasks if t["model"] == "gpt-image"]

    print(f"\n{BOLD}📋 待生成: {len(tasks)} 张图片{RESET}")
    if banana_tasks:
        print(f"   {CYAN}Nano Banana 2: {len(banana_tasks)} 张{RESET}")
    if gpt_tasks:
        print(f"   {CYAN}GPT Image 2:   {len(gpt_tasks)} 张{RESET}")
    est_min = len(tasks) * 3  # ~3min per image (ModelZoo can be slower)
    print(f"   {DIM}预计耗时: ~{est_min} 分钟{RESET}\n")

    results = []
    start_all = time.time()
    success = 0
    failed = 0

    for i, task in enumerate(tasks, 1):
        num = task["number"]
        label = task["label"]
        pct = i * 100 // len(tasks)
        elapsed_total = time.time() - start_all

        # ETA
        if i > 1:
            avg_per = elapsed_total / (i - 1)
            eta_min = round(avg_per * (len(tasks) - i + 1) / 60)
            eta_str = f"ETA ~{eta_min}min"
        else:
            eta_str = ""

        print(f"{log_ts()} {BOLD}[{i}/{len(tasks)}]{RESET} {pct:3d}% {eta_str:>12s}  #{num} {label}")

        t0 = time.time()

        if task["model"] == "banana":
            result = gen_banana(task["prompt"], task["output"], aspect)
        else:
            result = gen_gpt_image(task["prompt"], task["output"], aspect)

        result["number"] = num
        result["model_label"] = label
        results.append(result)

        gen_time = time.time() - t0

        if result["ok"]:
            success += 1
            print(f"      {GREEN}✅ {result['size_kb']}KB, {result['elapsed']}s{RESET}")
        else:
            failed += 1
            print(f"      {RED}❌ {result['error']}{RESET}")

        # Rate limit
        if i < len(tasks):
            time.sleep(2)

    total_min = (time.time() - start_all) / 60
    print(f"\n{'='*60}")
    print(f"{BOLD}🎉 批量生成完成!{RESET} 总耗时: {total_min:.1f} 分钟")
    print(f"   {GREEN}✅ 成功: {success}{RESET}")
    if failed:
        print(f"   {RED}❌ 失败: {failed}{RESET}")
        print(f"\n{RED}失败列表:{RESET}")
        for r in results:
            if not r["ok"]:
                print(f"  #{r['number']} {r['model_label']}: {r['error']}")

    # Save log
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"batch_{ts}.json"
    log_data = {
        "timestamp": ts,
        "total": len(results),
        "success": success,
        "failed": failed,
        "elapsed_min": round(total_min, 1),
        "results": results,
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    print(f"\n📝 日志: {log_path}")
    print(f"\n{DIM}💡 运行以下命令重新构建网站:{RESET}")
    print(f"   python3 {BASE}/src/build_all.py")

    return results


def print_status():
    prompts = load_prompts()
    existing = get_existing()
    total = len(prompts)

    gcli_count = len(existing["gcli"])
    bizyair_count = len(existing["bizyair"])

    print(f"\n{BOLD}📊 Prompt Gallery 图片覆盖率{RESET}")
    print(f"{'='*50}")
    print(f"总提示词:      {total}")
    print(f"Nano Banana 2: {gcli_count}/{total} ({gcli_count*100//total}%)")
    print(f"GPT Image 2:   {bizyair_count}/{total} ({bizyair_count*100//total}%)")

    all_nums = {p["number"] for p in prompts}
    missing_gcli = sorted(all_nums - existing["gcli"])
    missing_bizyair = sorted(all_nums - existing["bizyair"])

    if missing_gcli:
        print(f"\n缺失 Nano Banana 2 ({len(missing_gcli)}):")
        print(f"  {missing_gcli}")
    if missing_bizyair:
        print(f"\n缺失 GPT Image 2 ({len(missing_bizyair)}):")
        print(f"  {missing_bizyair}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Prompt Gallery · 批量生图 (BizyAir Skill CLI)")
    parser.add_argument("--model", default="all",
        help="生成模型: all=全部, gpt-image=GPT Image 2, banana=Nano Banana 2 (default: all)")
    parser.add_argument("--numbers", type=str, default=None,
                        help="指定编号，逗号分隔: 31,48,74")
    parser.add_argument("--start", type=int, default=None,
                        help="从指定编号开始（包含该编号，按编号降序）")
    parser.add_argument("--force", action="store_true",
                        help="强制重新生成")
    parser.add_argument("--aspect", default="1:1",
                        help="宽高比 (default: 1:1)")
    parser.add_argument("--status", action="store_true",
                        help="只显示覆盖率")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示任务列表")
    args = parser.parse_args()

    prompts = load_prompts()
    existing = get_existing()

    if args.status:
        print_status()
        return

    number_filter = None
    if args.numbers:
        number_filter = set(int(n.strip()) for n in args.numbers.split(","))

    tasks = build_tasks(
        prompts, existing, args.model,
        number_filter, args.start, args.force
    )

    if args.dry_run:
        print(f"\n{BOLD}📋 Dry run: {len(tasks)} 个任务{RESET}")
        for t in tasks:
            print(f"  #{t['number']} {t['label']} → {Path(t['output']).name}")
        return

    if not tasks:
        print(f"{GREEN}✅ 所有图片已生成，无待处理任务。{RESET}")
        print_status()
        return

    results = run_batch(tasks, args.aspect)


if __name__ == "__main__":
    main()

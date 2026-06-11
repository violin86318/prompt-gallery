#!/usr/bin/env python3
"""
Prompt Gallery 批量生图脚本
74 条提示词 × 2 版本 (Nano Banana 2 + GPT Image 2) = 最多 148 张
支持断点续传：已有图片自动跳过
"""

import json, os, sys, time, base64, subprocess, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

# ── gcli_archive 归档 ──────────────────────────────────────────────────────
sys.path.insert(0, os.path.expanduser("~/gcli_archive"))
try:
    import gcli_archive as _archive
except ImportError:
    _archive = None

# ─── 配置 ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "prompts.json"
TEST_DIR = BASE_DIR / "site" / "assets" / "tests"
TEST_DIR.mkdir(parents=True, exist_ok=True)

# gcli2api (Nano Banana 2) — 本地 NAS，无需代理
GCLI_API = "http://192.168.50.188:7861"
GCLI_KEY = "violin"
GCLI_MODEL = "gemini-3.1-flash-image"

# BizyAir (GPT Image 2) — 需代理
PROXY = "http://127.0.0.1:7890"
# 从 .zshrc 读 BizyAir key
def get_bizyair_key():
    r = subprocess.run(
        ['zsh', '-c', "source ~/.zshrc 2>/dev/null; echo $BIZYAIR_API_KEY"],
        capture_output=True, text=True
    )
    key = r.stdout.strip()
    if not key:
        # fallback: grep from .zshrc
        r2 = subprocess.run(
            ['zsh', '-c', "grep BIZYAIR_API_KEY ~/.zshrc | head -1 | cut -d\"'\" -f2"],
            capture_output=True, text=True
        )
        key = r2.stdout.strip()
    return key

BIZYAIR_KEY = get_bizyair_key()
BIZYAIR_URL = "https://api.bizyair.cn/w/v1/webapp/task/openapi/create"
BIZYAIR_APP_ID = 52416

# ─── 加载数据 ───────────────────────────────────────────
with open(DATA_FILE, encoding="utf-8") as f:
    prompts = json.load(f)

# 按 number 排序
prompts.sort(key=lambda p: p["number"])

print(f"📦 加载 {len(prompts)} 条提示词")
print(f"   输出目录: {TEST_DIR}")


# ─── 提取完整提示词用于生图 ─────────────────────────────
def get_full_prompt(p):
    """从 prompt 对象中提取可用于生图的完整提示词"""
    # 优先用 structure.full
    full = p.get("structure", {}).get("full", "").strip()
    if full:
        return full
    
    # 拼接 broth + spice + catalyst
    struct = p.get("structure", {})
    parts = []
    broth = struct.get("broth", "").strip()
    spice = struct.get("spice", "").strip()
    catalyst = struct.get("catalyst", "").strip()
    
    if broth:
        parts.append(broth)
    if spice:
        parts.append(spice)
    if catalyst:
        parts.append(f"【{catalyst}】")
    
    if parts:
        return "\n".join(parts)
    
    # 最后 fallback：用标题
    return f"请生成一张关于「{p['title']}」的创意设计图"


# ─── Nano Banana 2 (gcli2api) ─────────────────────────
def gen_nanobanana2(number, prompt_text):
    """调用 gcli2api Antigravity 端点生成图片"""
    output_path = TEST_DIR / f"gcli_{number}.png"
    if output_path.exists() and output_path.stat().st_size > 10000:
        return True, str(output_path), 0, "already exists"
    
    # 16:9 比例后缀
    full_model = f"{GCLI_MODEL}-16x9"
    endpoint = f"{GCLI_API}/antigravity/v1/models/{full_model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    headers = {
        "x-goog-api-key": GCLI_KEY,
        "Content-Type": "application/json"
    }
    
    for attempt in range(3):
        try:
            t0 = time.time()
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            
            elapsed = time.time() - t0
            parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            
            for part in parts:
                if "inlineData" in part:
                    img_data = base64.b64decode(part["inlineData"]["data"])
                    with open(output_path, "wb") as f:
                        f.write(img_data)
                    # 归档到 gcli_archive
                    if _archive:
                        try:
                            _archive._upsert_task(
                                f"pg_{number}_{full_model}",
                                datetime.now().isoformat(), prompt_text,
                                full_model, endpoint, "success",
                                image_path=str(output_path),
                                file_size_kb=len(img_data) // 1024,
                                duration=elapsed,
                                metadata={"source": "batch_generate", "number": number}
                            )
                        except Exception:
                            pass
                    return True, str(output_path), elapsed, f"{len(img_data)//1024}KB"
            
            return False, None, elapsed, "API 未返回图片数据"
            
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                print(f"      重试 {attempt+1}/3 (HTTP {e.code})...")
                time.sleep((attempt + 1) * 15)
                continue
            return False, None, 0, f"HTTP {e.code}: {body}"
        except Exception as e:
            if attempt < 2:
                time.sleep((attempt + 1) * 10)
                continue
            return False, None, 0, str(e)
    
    return False, None, 0, "达到最大重试次数"


# ─── GPT Image 2 (BizyAir) ───────────────────────────
def gen_gptimage2(number, prompt_text):
    """调用 BizyAir GPT Image 2 API 生成图片"""
    output_path = TEST_DIR / f"bizyair_{number}.png"
    if output_path.exists() and output_path.stat().st_size > 10000:
        return True, str(output_path), 0, "already exists"
    
    payload = json.dumps({
        "web_app_id": BIZYAIR_APP_ID,
        "suppress_preview_output": False,
        "input_values": {
            "4:BizyAir_GPT_IMAGE_2_T2I_API.prompt": prompt_text,
            "4:BizyAir_GPT_IMAGE_2_T2I_API.aspect_ratio": "16:9"
        }
    })
    
    tmpfile = f"/tmp/bizyair_prompt_gallery_{number}.json"
    
    for attempt in range(3):
        t0 = time.time()
        try:
            r = subprocess.run([
                'curl', '-s', '-X', 'POST',
                '-x', PROXY,
                '--connect-timeout', '30', '-m', '300',
                BIZYAIR_URL,
                '-H', 'Content-Type: application/json',
                '-H', f'Authorization: Bearer {BIZYAIR_KEY}',
                '-d', payload,
                '-o', tmpfile,
                '-w', '%{http_code}'
            ], capture_output=True, text=True, timeout=310)
            
            elapsed = time.time() - t0
            http_code = r.stdout.strip()
            
            if http_code != '200':
                if http_code in ('429', '500', '502', '503') and attempt < 2:
                    print(f"      重试 {attempt+1}/3 (HTTP {http_code})...")
                    time.sleep((attempt + 1) * 20)
                    continue
                return False, None, elapsed, f"HTTP {http_code}"
            
            with open(tmpfile) as f:
                resp = json.load(f)
            
            if resp.get('status') != 'Success':
                return False, None, elapsed, f"status={resp.get('status')}"
            
            outputs = resp.get('outputs', [])
            if not outputs:
                return False, None, elapsed, "no outputs"
            
            img_url = outputs[0].get('object_url', '')
            if not img_url:
                return False, None, elapsed, "no image url"
            
            # 下载图片
            r2 = subprocess.run([
                'curl', '-s', '-x', PROXY,
                '--connect-timeout', '30', '-m', '120',
                '-o', str(output_path), img_url
            ], capture_output=True, text=True, timeout=130)
            
            if output_path.exists() and output_path.stat().st_size > 5000:
                return True, str(output_path), elapsed, f"{output_path.stat().st_size//1024}KB"
            else:
                return False, None, elapsed, "download failed"
                
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            if attempt < 2:
                print(f"      超时重试 {attempt+1}/3...")
                time.sleep(10)
                continue
            return False, None, elapsed, "timeout"
        except Exception as e:
            elapsed = time.time() - t0
            if attempt < 2:
                time.sleep(10)
                continue
            return False, None, elapsed, str(e)
    
    return False, None, 0, "达到最大重试次数"


# ─── 主流程 ─────────────────────────────────────────────
def main():
    # 统计当前状态
    nano_have = 0
    gpt_have = 0
    nano_need = []
    gpt_need = []
    
    for p in prompts:
        num = p["number"]
        nano_path = TEST_DIR / f"gcli_{num}.png"
        gpt_path = TEST_DIR / f"bizyair_{num}.png"
        
        if nano_path.exists() and nano_path.stat().st_size > 10000:
            nano_have += 1
        else:
            nano_need.append(num)
        
        if gpt_path.exists() and gpt_path.stat().st_size > 10000:
            gpt_have += 1
        else:
            gpt_need.append(num)
    
    print(f"\n📊 当前状态:")
    print(f"   Nano Banana 2: {nano_have}/74 已有, {len(nano_need)} 待生成")
    print(f"   GPT Image 2:   {gpt_have}/74 已有, {len(gpt_need)} 待生成")
    print(f"   总计待生成: {len(nano_need) + len(gpt_need)} 张")
    
    if not nano_need and not gpt_need:
        print("\n✅ 全部图片已存在，无需生成")
        return
    
    # ─── 选择模式 ───────────────────────────────────────
    mode = "both"
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    
    if mode not in ("nano", "gpt", "both"):
        print(f"\n用法: python {sys.argv[0]} [nano|gpt|both]")
        print(f"  nano = 只生成 Nano Banana 2 版本")
        print(f"  gpt  = 只生成 GPT Image 2 版本")
        print(f"  both = 两个版本都生成（默认）")
        sys.exit(1)
    
    print(f"\n🚀 生成模式: {mode}")
    print(f"{'='*60}")
    
    results = []
    start_all = time.time()
    
    # Build number → prompt text map
    prompt_map = {}
    for p in prompts:
        prompt_map[p["number"]] = get_full_prompt(p)
    
    # ─── 生成 Nano Banana 2 ─────────────────────────────
    if mode in ("nano", "both") and nano_need:
        print(f"\n🎨 Phase 1: Nano Banana 2 ({len(nano_need)} 张)")
        print(f"   API: {GCLI_API}")
        
        for i, num in enumerate(sorted(nano_need)):
            prompt_text = prompt_map[num]
            title = next((p["title"] for p in prompts if p["number"] == num), "?")
            print(f"\n  [{i+1}/{len(nano_need)}] #{num} {title}")
            print(f"      提示词: {prompt_text[:80]}...")
            
            ok, path, elapsed, msg = gen_nanobanana2(num, prompt_text)
            status = "✅" if ok else "❌"
            print(f"      {status} {msg} ({elapsed:.1f}s)")
            results.append(("Nano Banana 2", num, ok, path, elapsed, msg))
            
            # 礼貌延迟
            if ok and i < len(nano_need) - 1:
                time.sleep(2)
    
    # ─── 生成 GPT Image 2 ──────────────────────────────
    if mode in ("gpt", "both") and gpt_need:
        print(f"\n🎨 Phase 2: GPT Image 2 ({len(gpt_need)} 张)")
        print(f"   API: BizyAir ({BIZYAIR_URL})")
        print(f"   代理: {PROXY}")
        print(f"   ⏱ 预计每张 60-225s，总计 ~{len(gpt_need)*2} 分钟")
        
        for i, num in enumerate(sorted(gpt_need)):
            prompt_text = prompt_map[num]
            title = next((p["title"] for p in prompts if p["number"] == num), "?")
            print(f"\n  [{i+1}/{len(gpt_need)}] #{num} {title}")
            print(f"      提示词: {prompt_text[:80]}...")
            
            ok, path, elapsed, msg = gen_gptimage2(num, prompt_text)
            status = "✅" if ok else "❌"
            print(f"      {status} {msg} ({elapsed:.1f}s)")
            results.append(("GPT Image 2", num, ok, path, elapsed, msg))
            
            # GPT Image 2 比较慢，不需要额外延迟
    
    # ─── 汇总 ──────────────────────────────────────────
    elapsed_total = time.time() - start_all
    success = [r for r in results if r[2]]
    failed = [r for r in results if not r[2]]
    
    print(f"\n{'='*60}")
    print(f"🏁 生成完成! 总耗时: {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")
    print(f"   成功: {len(success)} | 失败: {len(failed)}")
    
    if failed:
        print(f"\n❌ 失败列表:")
        for model, num, ok, path, elapsed, msg in failed:
            print(f"   {model} #{num}: {msg}")
    
    # ─── 更新 prompts.json ──────────────────────────────
    print(f"\n📝 更新 prompts.json...")
    updated = 0
    for p in prompts:
        num = p["number"]
        tests = {}
        
        nano_path = TEST_DIR / f"gcli_{num}.png"
        if nano_path.exists() and nano_path.stat().st_size > 10000:
            tests["Nano Banana 2"] = {
                "image": f"assets/tests/gcli_{num}.png",
                "size": f"{nano_path.stat().st_size // 1024}KB"
            }
        
        gpt_path = TEST_DIR / f"bizyair_{num}.png"
        if gpt_path.exists() and gpt_path.stat().st_size > 10000:
            tests["GPT Image 2"] = {
                "image": f"assets/tests/bizyair_{num}.png",
                "size": f"{gpt_path.stat().st_size // 1024}KB"
            }
        
        if tests != p.get("tests", {}):
            p["tests"] = tests
            updated += 1
    
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)
    
    print(f"   更新了 {updated} 条记录")
    
    # ─── 提示重新构建 ──────────────────────────────────
    print(f"\n🔄 运行以下命令重新构建网站:")
    print(f"   cd {BASE_DIR}")
    print(f"   python src/build_all.py")
    print(f"   python src/serve.py")


if __name__ == "__main__":
    main()

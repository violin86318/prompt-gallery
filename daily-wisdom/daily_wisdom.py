#!/usr/bin/env python3
"""每日箴言·一字美学 — 独立 crontab 脚本
每天选一个哲理单字，用 BizyAir GPT Image 2 生成东方美学海报，
用 SiliconFlow (Nex-N2-Pro) 动态生成 3 版朋友圈文案，发到 Telegram，记录到画廊数据。

用法:
    python3 daily_wisdom.py              # 自动选字
    python3 daily_wisdom.py --char 澄    # 指定字
    python3 daily_wisdom.py --dry-run    # 只选字不生图
    python3 daily_wisdom.py --caption-only 澄  # 只生成文案（跳过图片）
"""

import subprocess, sys, os, json, time, re, random, urllib.request, urllib.error, base64
from pathlib import Path
from datetime import datetime

# ── 路径 ──────────────────────────────────────────────
AGENT = Path(os.path.expanduser(
    "~/Library/Application Support/remio/Users/F2313D5DDFE8FCF316DC1149F06BB14B/agent"
))
CLI = AGENT / "remio/skills/bizyair-skill/scripts/cli.py"
OUTPUT_DIR = AGENT / "prompt-gallery/daily-wisdom"
GALLERY_DIR = AGENT / "prompt-gallery/daily-wisdom-gallery"
MEMORY_DIR = AGENT / "memory"
GALLERY_DATA = OUTPUT_DIR / "wisdom_gallery.json"
ENDPOINT = "bza-image-o2-base/text-to-image"

# ── Telegram ──────────────────────────────────────────
TG_BOT = "8650394988:AAEXYZe4AZekKfE1xjVDpG0t1fjgglxjsdA"
TG_CHAT = "6428839227"

# ── SiliconFlow API ──────────────────────────────────
SF_API_KEY = os.environ.get("SF_API_KEY", "sk-huvpjmcreuvzixvgmfhdpksfpgifknuwwpinkfligycaaxxw")
SF_BASE = "https://api.siliconflow.cn/v1"
SF_CAPTION_MODEL = "nex-agi/Nex-N2-Pro"     # 文案生成
SF_VISION_MODEL = "Qwen/Qwen3-VL-8B-Instruct"  # OCR 验证

# ── 字库 ──────────────────────────────────────────────
CHAR_POOL = [
    "悟", "归", "澄", "拙", "虚", "韵", "朴", "宁", "渡", "寂",
    "静", "禅", "觉", "舍", "淡", "素", "影", "岚", "渺", "幽",
    "墨", "渊", "远", "闲", "逸", "观", "微", "照", "寂", "隐",
    "寻", "栖", "泊", "凝", "溯", "融", "化", "涵", "蓄", "敛",
    "恒", "笃", "慎", "恕", "慈", "悲", "愿", "净", "空", "明",
    "清", "柔", "和", "安", "简", "真", "如", "初", "善", "礼",
    "宽", "厚", "温", "良", "恭", "让", "逊", "谦", "敬", "诚",
    "信", "坚", "韧", "达", "通", "畅", "舒", "缓", "徐",
]

# ── 提示词模板 ────────────────────────────────────────
PROMPT_TEMPLATE_FULL = """请围绕用户提供的"主题"，设计一张具有收藏级质感的高端东方美学海报 / 信息图 / 邀请函 / PPT视觉封面。整张画面必须达到专业设计展作品级别，而不是普通模板拼贴。

【核心创作逻辑】
1. 从用户输入的主题中，自动提炼一个最能代表主题精神、同时最适合视觉化呈现的"核心字"或"核心词"。
2. 以这个核心字作为整张海报的主视觉骨架，使它成为画面的中心符号。
3. 采用"字中有画、画中有意、意中有信息"的方式进行构图：让核心字既是文字、也是图像容器、也是主题隐喻。
4. 整体不是简单插画，也不是普通排版，而是"汉字结构 + 插画叠底 + 信息设计 + 东方留白美学"的综合作品。

【视觉风格要求】
- 整体风格：高级、克制、典雅、专业、安静、耐看、具有东方哲思与文化气息
- 背景材质：宣纸、旧纸、细腻纸张肌理、淡淡水痕、朦胧花影、古籍质感
- 色彩系统：低饱和配色，以米白、茶褐、灰绿、淡墨、浅赭为主
- 气质方向：宋代美学、文人气、书卷气、东方展览视觉

用户输入主题：【{char}】"""

PROMPT_TEMPLATE = PROMPT_TEMPLATE_FULL  # 保持函数签名兼容

# ── 文案生成 Prompt ──────────────────────────────────
CAPTION_SYSTEM = """你是一位精通东方美学与生活哲学的文案大师。你的风格：克制、有画面感、不鸡汤、不说教。
像一篇好的散文诗，每个字都有重量。读者看完会觉得「安静了一下」。"""

CAPTION_USER = """请为今日箴言字【{char}】生成 3 版朋友圈文案，严格按以下格式：

## 版本1：生活分享型
（适合日常发朋友圈，带一点生活气息，100字以内）

## 版本2：观点输出型
（像一个有洞察的人说的观点，不鸡汤但有深度，80字以内）

## 版本3：金句型
（极简，一句话击中人心，30字以内）

要求：
- 每个版本末尾自然融入「{char}」这个字
- 不要用感叹号，不要用 emoji
- 语气是「对自己说话」，不是「对世界宣告」
- 要有具体画面，不要抽象概念"""


# ── 核心函数 ──────────────────────────────────────────

def load_recent_chars(days=14):
    """从 wisdom_gallery.json 读取已用过的字（比 memory 文件更可靠）"""
    used = set()
    if GALLERY_DATA.exists():
        try:
            data = json.loads(GALLERY_DATA.read_text(encoding="utf-8"))
            for entry in data:
                c = entry.get("char", "")
                if c:
                    used.add(c)
        except Exception:
            pass
    # 兜底：也读 memory 文件
    for i in range(days):
        d = datetime.now().strftime("%Y%m%d") if i == 0 else \
            time.strftime("%Y%m%d", time.localtime(time.time() - i * 86400))
        mem_file = MEMORY_DIR / f"MEM-{d}.md"
        if mem_file.exists():
            content = mem_file.read_text(encoding="utf-8")
            matches = re.findall(r"每日箴言.*?【(.)】", content)
            used.update(matches)
    return used


def pick_char(specified=None):
    """选一个不重复的字"""
    if specified:
        return specified
    used = load_recent_chars()
    available = [c for c in CHAR_POOL if c not in used]
    if not available:
        available = CHAR_POOL
    return random.choice(available)


def _simplify_chinese(text):
    """OpenCC 繁简转换（可选依赖）。不可用则跳过。"""
    try:
        import opencc
        converter = opencc.OpenCC('t2s')
        return converter.convert(text)
    except ImportError:
        return text


def verify_image_char(image_path, expected_char, timeout=60, max_attempts=2):
    """OCR 验证图片上的字是否和预期一致。返回 (True/False, 实际识别到的字)。
    自动处理简繁转换（阈、闲/閒、坚/堅 等）。
    用 SiliconFlow Qwen3-VL-8B-Instruct。"""
    if not SF_API_KEY:
        return True, expected_char

    for attempt in range(1, max_attempts + 1):
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            b64_size_mb = len(b64) / 1024 / 1024
            if attempt == 1:
                print(f"[OCR] 图片 base64: {b64_size_mb:.1f}MB, 超时={timeout}s", flush=True)

            payload = json.dumps({
                "model": SF_VISION_MODEL,
                "max_tokens": 50,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text": "请直接输出图片中间那个最大的汉字，只输出一个字。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]}
                ]
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{SF_BASE}/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {SF_API_KEY}"
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                actual = body["choices"][0]["message"]["content"].strip()
                actual = re.sub(r"[^\u4e00-\u9fff]", "", actual)[:1]

            if not actual:
                if attempt < max_attempts:
                    print(f"[OCR] 返回为空，重试 {attempt+1}/{max_attempts}", flush=True)
                    time.sleep(2)
                    continue
                else:
                    print(f"[WARN] OCR 多次返回为空，默认通过", flush=True)
                    return True, expected_char

            # 繁简统一比较
            actual_normalized = _simplify_chinese(actual)
            expected_normalized = _simplify_chinese(expected_char)
            if actual_normalized == expected_normalized:
                return True, actual
            else:
                return False, actual

        except Exception as e:
            if attempt < max_attempts:
                print(f"[OCR] 调用失败（{type(e).__name__}），重试 {attempt+1}/{max_attempts}", flush=True)
                time.sleep(2)
            else:
                print(f"[WARN] OCR 验证失败（{e}），默认通过", flush=True)
                return True, expected_char

    return True, expected_char


def generate_image(char, output_path):
    """用 BizyAir ModelZoo CLI 生成图片。返回 (success, actual_char)"""
    prompt = PROMPT_TEMPLATE.format(char=char)
    if len(prompt) > 4000:
        prompt = prompt[:4000]

    print(f"[1/4] 生成图片中... 字=【{char}】", flush=True)

    full_prompt = PROMPT_TEMPLATE_FULL.format(char=char)
    # 只用中文完整版 prompt，不降级
    img_url = None
    for attempt in range(1, 4):  # 最多重试 3 次
        print(f"  中文完整版 第{attempt}次...", flush=True)
        r = subprocess.run(
            [sys.executable, str(CLI), "modelzoo-run", ENDPOINT,
             "--param", f"prompt={full_prompt[:2000]}",
             "--param", "aspect_ratio=1:1"],
            capture_output=True, text=True, timeout=600
        )
        for line in r.stdout.split("\n"):
            if "[images]" in line:
                img_url = line.split("[images]", 1)[1].strip()
                break
        if img_url:
            break
        print(f"  第{attempt}次失败，重试...", flush=True)

    if not img_url:
        print(f"[FAIL] 3次均失败", flush=True)
        print(f"[STDOUT] {r.stdout[-300:]}", flush=True)
        return False, char

    print(f"[1/4] 下载图片: {img_url[:80]}...", flush=True)
    dl = subprocess.run(
        ["curl", "-sS", "--connect-timeout", "15", "--max-time", "120",
         "-o", str(output_path), img_url],
        capture_output=True, timeout=130
    )

    if output_path.exists() and output_path.stat().st_size > 1000:
        size_kb = output_path.stat().st_size // 1024
        print(f"[OK] {output_path.name} ({size_kb}KB)", flush=True)
        return True, char
    else:
        print(f"[FAIL] 下载失败", flush=True)
        return False, char


def generate_captions_llm(char):
    """用 SiliconFlow Nex-N2-Pro 动态生成 3 版朋友圈文案"""
    if not SF_API_KEY:
        print("[WARN] SF_API_KEY 未设置，使用通用文案", flush=True)
        return _fallback_captions(char)

    print(f"[2/4] SiliconFlow 生成文案中... 模型={SF_CAPTION_MODEL} 字=【{char}】", flush=True)

    payload = json.dumps({
        "model": SF_CAPTION_MODEL,
        "messages": [
            {"role": "system", "content": CAPTION_SYSTEM},
            {"role": "user", "content": CAPTION_USER.format(char=char)}
        ],
        "temperature": 0.85,
        "max_tokens": 2000
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{SF_BASE}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SF_API_KEY}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            text = body["choices"][0]["message"].get("content", "") or ""
            finish_reason = body["choices"][0].get("finish_reason", "")

        if not text.strip():
            print(f"[WARN] LLM 返回空 content (finish_reason={finish_reason})，使用通用文案", flush=True)
            return _fallback_captions(char)

        if finish_reason == "length":
            print(f"[WARN] LLM 响应被截断 (finish_reason=length)，可能影响文案质量", flush=True)

        # 解析 3 个版本
        versions = {"v1": "", "v2": "", "v3": ""}
        sections = re.split(r"##\s*版本[123]", text)
        if len(sections) >= 4:
            versions["v1"] = _clean_caption(sections[1])
            versions["v2"] = _clean_caption(sections[2])
            versions["v3"] = _clean_caption(sections[3])
        else:
            parts = [p.strip() for p in text.split("\n\n") if p.strip()]
            if len(parts) >= 3:
                versions["v1"] = parts[0]
                versions["v2"] = parts[1]
                versions["v3"] = parts[2]
            else:
                print(f"[WARN] LLM 响应解析不足 3 段（仅 {len(parts)} 段），使用通用文案", flush=True)
                return _fallback_captions(char)

        if not all(versions.values()):
            print(f"[WARN] LLM 解析后有空 caption，使用通用文案", flush=True)
            return _fallback_captions(char)

        print(f"[OK] 文案生成成功 ({len(text)}字)", flush=True)
        return [versions["v1"], versions["v2"], versions["v3"]]

    except Exception as e:
        print(f"[WARN] SiliconFlow 调用失败: {e}，使用通用文案", flush=True)
        return _fallback_captions(char)


def _clean_caption(text):
    """清理文案：去掉标题行、多余空行"""
    lines = [l.strip() for l in text.strip().split("\n")
             if l.strip() and not l.strip().startswith("#")
             and not l.strip().startswith("版本")]
    return "\n".join(lines)


def _fallback_captions(char):
    """通用兜底文案"""
    return [
        f"有些字，看一眼就安静了。\n【{char}】\n不必多说，心领神会。",
        f"世界太吵了，一个字就够了。\n{char}，退一步的注视。",
        f"真正有力量的字，都不喧哗。\n{char}。",
    ]


def send_telegram(image_path, char, captions):
    """发送图片 + 3 版文案到 Telegram。返回 (bool, list[失败原因])"""
    print(f"[3/4] 发送到 Telegram...", flush=True)
    today = datetime.now().strftime("%Y-%m-%d")
    caption = f"📜 每日箴言 · {today}\n\n今日字：【{char}】\n\n— 一字美学 · 中式秩序美感"

    failures = []

    # 发送图片（重试 2 次）
    photo_ok = False
    for attempt in (1, 2):
        try:
            r = subprocess.run(
                ["curl", "-sS", "--max-time", "60",
                 f"https://api.telegram.org/bot{TG_BOT}/sendPhoto",
                 "-F", f"chat_id={TG_CHAT}",
                 "-F", f"photo=@{image_path}",
                 "-F", f"caption={caption}"],
                capture_output=True, text=True, timeout=70
            )
            result = json.loads(r.stdout) if r.stdout else {}
            if result.get("ok"):
                print(f"[OK] Telegram 图片发送成功 (第{attempt}次)", flush=True)
                photo_ok = True
                break
            else:
                err = result.get("description", str(result))[:200]
                print(f"[FAIL] Telegram 图片第{attempt}次: {err}", flush=True)
                failures.append(f"photo-attempt{attempt}: {err}")
                time.sleep(2)
        except Exception as e:
            print(f"[FAIL] Telegram 图片第{attempt}次异常: {e}", flush=True)
            failures.append(f"photo-attempt{attempt}: {e}")
            time.sleep(2)

    if not photo_ok:
        # 全部失败 → 保存兜底到本地
        fallback = OUTPUT_DIR / f"FAILED_{today}.json"
        fallback.write_text(json.dumps({
            "date": today, "char": char, "image": image_path.name,
            "captions": {"v1_life": captions[0], "v2_opinion": captions[1], "v3_quote": captions[2]},
            "failures": failures,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[FALLBACK] 兜底保存: {fallback}", flush=True)
        return False, failures

    # 发送 3 版文案
    labels = ["版本1 · 生活分享", "版本2 · 观点输出", "版本3 · 金句"]
    msg_failures = 0
    for i, (label, text) in enumerate(zip(labels, captions)):
        msg = f"✍️ {label}\n\n{text}"
        try:
            r = subprocess.run(
                ["curl", "-sS", "--max-time", "30",
                 f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
                 "-d", f"chat_id={TG_CHAT}",
                 "-d", f"text={msg}"],
                capture_output=True, text=True, timeout=40
            )
            result = json.loads(r.stdout) if r.stdout else {}
            if result.get("ok"):
                print(f"[OK] 文案 {i+1} 发送成功", flush=True)
            else:
                err = result.get("description", str(result))[:150]
                print(f"[FAIL] 文案 {i+1}: {err}", flush=True)
                msg_failures += 1
                failures.append(f"text-{i+1}: {err}")
        except Exception as e:
            print(f"[FAIL] 文案 {i+1} 异常: {e}", flush=True)
            msg_failures += 1
            failures.append(f"text-{i+1}: {e}")
        time.sleep(0.5)

    # 文案失败过半不算彻底成功
    return msg_failures < 2, failures


def save_gallery_data(char, captions, image_path, actual_char=None):
    """保存到画廊 JSON 数据。actual_char 是图片上实际画的字（以防与预期不一致）"""
    today = datetime.now().strftime("%Y-%m-%d")

    # 如果实际画的字和预期不一样，记录在 entry 里但用 actual_char
    final_char = actual_char if actual_char else char
    if actual_char and actual_char != char:
        print(f"[WARN] 实际图字【{actual_char}】与预期【{char}】不同，以图为准", flush=True)

    # 加载已有数据
    if GALLERY_DATA.exists():
        with open(GALLERY_DATA, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []

    # 检查是否已存在
    existing = [e for e in data if e.get("date") == today]
    if not existing:
        entry = {
            "date": today,
            "char": final_char,
            "expected_char": char,
            "image": image_path.name,
            "captions": {
                "v1_life": captions[0],
                "v2_opinion": captions[1],
                "v3_quote": captions[2],
            },
            "created_at": datetime.now().isoformat(),
        }
        data.append(entry)

        with open(GALLERY_DATA, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[4/4] 画廊数据已保存 ({len(data)} 条) 字=【{final_char}】", flush=True)
    else:
        print(f"[4/4] 今日画廊数据已存在，跳过", flush=True)


def deploy_static_site():
    """重新构建静态站并部署到 Cloudflare Pages（best-effort，不中断主流程）"""
    deploy_script = GALLERY_DIR / "deploy_wisdom.sh"
    if not deploy_script.exists():
        print(f"[WARN] 部署脚本不存在: {deploy_script}", flush=True)
        return
    try:
        import subprocess
        result = subprocess.run(
            ["bash", str(deploy_script)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            print("[DEPLOY] 静态站部署成功", flush=True)
            if result.stdout:
                # 只打印最后 5 行
                tail = '\n'.join(result.stdout.strip().split('\n')[-5:])
                print(tail, flush=True)
        else:
            print(f"[DEPLOY-FAIL] 返回码 {result.returncode}", flush=True)
            if result.stderr:
                print(result.stderr[:500], flush=True)
    except subprocess.TimeoutExpired:
        print("[DEPLOY-TIMEOUT] 部署超时（>180s）", flush=True)
    except Exception as e:
        print(f"[DEPLOY-ERR] {e}", flush=True)


def record_char(char, captions):
    """记录到 memory/MEM-今天.md"""
    today = datetime.now().strftime("%Y%m%d")
    mem_file = MEMORY_DIR / f"MEM-{today}.md"

    caption_preview = captions[2][:50] if captions and len(captions) > 2 else ""
    entry = f"\n- 📜 每日箴言：【{char}】— 已发送 Telegram\n  金句：{caption_preview}\n"

    if mem_file.exists():
        content = mem_file.read_text(encoding="utf-8")
        if f"每日箴言" not in content:
            with open(mem_file, "a", encoding="utf-8") as f:
                f.write(entry)
    else:
        with open(mem_file, "w", encoding="utf-8") as f:
            f.write(f"# MEM-{today}\n\n{entry}\n")

    print(f"[OK] 已记录到 {mem_file.name}", flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--char", help="指定字")
    parser.add_argument("--dry-run", action="store_true", help="只选字不生图")
    parser.add_argument("--caption-only", action="store_true", help="只生成文案（跳过图片）")
    parser.add_argument("--backfill-date", help="补全指定日期的 gallery（如 2026-06-03）")
    args = parser.parse_args()

    # 锁文件防并发（同一时间不能跑两个 daily_wisdom）
    import fcntl
    lock_path = Path("/tmp/daily_wisdom.lock")
    lock_fp = open(lock_path, "w")
    try:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[LOCK] 另一个 daily_wisdom 实例正在运行，直接退出", flush=True)
        sys.exit(0)

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "logs").mkdir(exist_ok=True)  # 强制确保日志目录存在
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / f"wisd_{today}.png"

    # 选字
    char = pick_char(args.char)
    print(f"═══════════════════════════════════════", flush=True)
    print(f"📜 每日箴言 · {today}", flush=True)
    print(f"   今日字：【{char}】", flush=True)
    print(f"═══════════════════════════════════════", flush=True)

    if args.dry_run:
        print("[DRY-RUN] 结束", flush=True)
        return

    # 补全模式：只补 gallery 记录，不重发 Telegram
    if args.backfill_date:
        backfill_date = args.backfill_date
        bp = OUTPUT_DIR / f"wisd_{backfill_date}.png"
        if not bp.exists():
            print(f"[ERR] 补全失败：{bp} 不存在", flush=True)
            sys.exit(1)
        # 读取现有 gallery 检查是否已有
        data = json.loads(GALLERY_DATA.read_text(encoding="utf-8")) if GALLERY_DATA.exists() else []
        if any(e.get("date") == backfill_date for e in data):
            print(f"[SKIP] {backfill_date} 已在 gallery 中", flush=True)
            return
        # OCR 验证图片实际是什么字（以图为准）
        if SF_API_KEY:
            ok, detected_char = verify_image_char(bp, char)
            actual_bf = detected_char
            print(f"[BACKFILL] OCR 验证: 图字=【{detected_char}】", flush=True)
        else:
            actual_bf = char
        # 补全文案（以实际图字生成）
        fallback = OUTPUT_DIR / f"FAILED_{backfill_date}.json"
        if fallback.exists():
            fb = json.loads(fallback.read_text(encoding="utf-8"))
            captions = [fb["captions"]["v1_life"], fb["captions"]["v2_opinion"], fb["captions"]["v3_quote"]]
            print(f"[BACKFILL] 使用兜底文案", flush=True)
        else:
            captions = generate_captions_llm(actual_bf)
            print(f"[BACKFILL] 重新生成文案", flush=True)
        save_gallery_data(actual_bf, captions, bp, actual_char=actual_bf)
        print(f"✅ 补全完成: {backfill_date} -> 字【{actual_bf}】", flush=True)
        return

    # 文案按最终确定的字生成（如果换了字需要重新生成）
    if actual_char != char or not captions:
        captions = generate_captions_llm(actual_char)

    if args.caption_only:
        print(f"\n✍️ 文案预览：", flush=True)
        labels = ["生活分享", "观点输出", "金句"]
        for label, text in zip(labels, captions):
            print(f"\n【{label}】\n{text}", flush=True)
        return

    # 生图 + OCR 验证循环
    # 策略：同一个字重画最多 3 次，都不过才换字（最多换 2 轮）
    actual_char = char
    char_confirmed = False

    for char_round in range(3):  # 最多换 3 个字
        img_ok_for_this_char = False
        for img_attempt in range(3):  # 同字重画最多 3 次
            if output_path.exists() and output_path.stat().st_size > 1000:
                print(f"[SKIP] 今日图片已存在: {output_path}", flush=True)
            else:
                success, _ = generate_image(char, output_path)
                if not success:
                    sys.exit(1)

            ok, detected = verify_image_char(output_path, char)
            if ok:
                actual_char = char
                char_confirmed = True
                print(f"[OCR] 图片字正确: 【{detected}】 ✅", flush=True)
                break
            else:
                print(f"[OCR] 图字【{detected}】与预期【{char}】不符 (同字第{img_attempt+1}次)", flush=True)
                # 备份错图
                backup_path = OUTPUT_DIR / f"wisd_{today}_wrong_{char}_{detected}_r{char_round}a{img_attempt}.png"
                output_path.rename(backup_path)
                print(f"[BACKUP] → {backup_path.name}", flush=True)

        if char_confirmed:
            break

        # 同字 3 次都不过，换字
        if char_round < 2:
            new_char = pick_char()
            print(f"[RETRY] 【{char}】3次均不通过，换字 → 【{new_char}】", flush=True)
            char = new_char
            captions = generate_captions_llm(char)
        else:
            # 最后一轮也不通过，以最后一次 OCR 结果为准
            actual_char = detected
            print(f"[WARN] 3轮均未确认，以图字【{detected}】为准", flush=True)

    # 发送 Telegram（即使失败也继续保存 gallery）
    print(f"[3/4] 发送到 Telegram...", flush=True)
    try:
        tg_ok, tg_failures = send_telegram(output_path, actual_char, captions)
    except Exception as e:
        print(f"[ERR] Telegram 发送异常: {e}", flush=True)
        tg_ok, tg_failures = False, [str(e)]

    # 保存画廊数据（以实际图字为准）
    try:
        save_gallery_data(char, captions, output_path, actual_char=actual_char)
    except Exception as e:
        print(f"[ERR] 保存 gallery 失败: {e}", flush=True)

    # 部署静态站（best-effort）
    print("[5/5] 重新构建并部署静态站...", flush=True)
    try:
        deploy_static_site()
    except Exception as e:
        print(f"[DEPLOY-ERR] {e}", flush=True)

    # 记录
    try:
        record_char(actual_char, captions)
    except Exception as e:
        print(f"[ERR] 记录 MEM 失败: {e}", flush=True)

    # 总结
    print(f"\n═══════════════════════════════════════", flush=True)
    if tg_ok:
        print(f"✅ 每日箴言完成！字=【{actual_char}】 Telegram 发送成功", flush=True)
    else:
        print(f"⚠️ 每日箴言完成（本地）！字=【{actual_char}】", flush=True)
        print(f"   Telegram 发送失败 ({len(tg_failures)} 个错误)", flush=True)
        print(f"   Gallery 已保存，下次 cron 可重试", flush=True)
    print(f"═══════════════════════════════════════", flush=True)

    # Telegram 失败不中断 cron（本地已有图片）
    if not tg_ok:
        sys.exit(0)  # 不告警，依赖下次重试或人工补发


if __name__ == "__main__":
    main()

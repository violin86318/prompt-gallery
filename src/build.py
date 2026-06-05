#!/usr/bin/env python3
"""Prompt Gallery static site builder.
Reads prompt data from remio KB, generates static HTML."""

import json
import os
import re
import shutil
from pathlib import Path

# --- Paths ---
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
SITE_DIR = BASE / "site"
TEMPLATE_DIR = BASE / "templates"
ASSETS_DIR = SITE_DIR / "assets" / "tests"

# --- Category mapping ---
CATEGORY_MAP = {
    "信息可视化": ["信息图", "知识图鉴", "流程图", "数据可视化", "信息简化", "图鉴", "图表"],
    "海报设计": ["海报", "城市", "电影", "音乐", "品牌", "名片", "高桥流", "线稿城市", "线条艺术", "窗棂", "剪影", "窗口", "窗景"],
    "PPT 演示": ["PPT", "课件", "编辑感", "颗粒", "东方编辑"],
    "美学实验": ["美学", "几何", "水墨", "水彩", "空气感", "丝网", "印刷", "光", "容器", "破框", "三角", "记忆窗口"],
    "实用工具": ["电商", "名片", "二维码", "植物", "Logo", "Banner", "详情页", "邀请函", "乐高"],
    "人物肖像": ["掌纹", "面相", "头像", "穿搭", "穿衣", "肖像", "情头", "表情包", "线条头像"],
}


def auto_category(title: str, subcategory: str = "") -> str:
    """Auto-detect category from title/subcategory."""
    text = f"{title} {subcategory}".lower()
    for cat, keywords in CATEGORY_MAP.items():
        for kw in keywords:
            if kw.lower() in text:
                return cat
    return "美学实验"  # default


def parse_prompt_sections(full_text: str, number: int) -> dict:
    """Parse a full prompt into broth/spice/catalyst/avoid sections.
    For #1-#30 (classic), return as single block."""
    if number <= 30:
        # Classic: no structure, extract avoid list only
        avoid_lines = []
        for line in full_text.split("\n"):
            stripped = line.strip()
            if re.match(r'^(不要|避免|禁止|❌|×|不可)', stripped):
                avoid_lines.append(re.sub(r'^[❌×]\s*', '', stripped))
        return {
            "structureType": "classic",
            "structure": {
                "broth": "",
                "spice": "",
                "catalyst": "",
                "full": full_text,
            },
            "avoidList": avoid_lines,
        }

    # Structured prompt (#31+): attempt split
    lines = full_text.split("\n")

    avoid_lines = []
    non_avoid_lines = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^(不要|避免|禁止|❌|×|不可)', stripped):
            avoid_lines.append(re.sub(r'^[❌×]\s*', '', stripped))
        else:
            non_avoid_lines.append(line)

    # Look for catalyst markers 【...】
    catalyst = ""
    catalyst_pattern = re.compile(r'【([^】]+)】')
    catalyst_matches = catalyst_pattern.findall(full_text)
    if catalyst_matches:
        catalyst = " · ".join(catalyst_matches)

    # Try to split by "本次用户输入" or "本次主题" or "用户输入"
    broth_lines = []
    spice_lines = []
    in_spice = False

    spice_markers = ["本次用户输入", "本次主题", "用户输入：", "本次要处理的", "如下代码块"]
    for line in non_avoid_lines:
        stripped = line.strip()
        is_spice_start = any(stripped.startswith(m) or m in stripped for m in spice_markers)
        if is_spice_start and not in_spice:
            in_spice = True
            spice_lines.append(line)
        elif in_spice:
            spice_lines.append(line)
        else:
            broth_lines.append(line)

    broth = "\n".join(broth_lines).strip()
    spice = "\n".join(spice_lines).strip()

    # If no clear split found, put everything in broth
    if not spice:
        broth = "\n".join(non_avoid_lines).strip()

    return {
        "structureType": "broth-spice",
        "structure": {
            "broth": broth,
            "spice": spice,
            "catalyst": catalyst,
            "full": full_text,
        },
        "avoidList": avoid_lines,
    }


def get_test_images(number: int) -> dict:
    """Check what test images exist for a prompt number."""
    tests = {}
    for prefix, label in [("gcli_", "gcli2api"), ("bizyair_", "bizyair")]:
        path = ASSETS_DIR / f"{prefix}{number}.png"
        if path.exists():
            tests[label] = {
                "image": f"assets/tests/{prefix}{number}.png",
                "size": f"{path.stat().st_size // 1024}KB",
            }
    # Also check test_ prefix for early tests
    test_path = ASSETS_DIR / f"test_{number}.png"
    if test_path.exists() and "gcli2api" not in tests:
        tests["gcli2api"] = {
            "image": f"assets/tests/test_{number}.png",
            "size": f"{test_path.stat().st_size // 1024}KB",
        }
    return tests


def generate_slug(number: int, title: str) -> str:
    """Generate URL slug from number and title."""
    # Remove emoji and special chars, keep CJK
    clean = re.sub(r'[^\w\s\u4e00-\u9fff·]', '', title)
    clean = re.sub(r'\s+', '-', clean).strip('-')
    return f"{number}-{clean}"


def build_prompts_json(manual_prompts: list[dict]) -> str:
    """Build the final prompts.json from manually curated data."""
    output = []

    for p in manual_prompts:
        number = p["number"]
        title = p["title"]
        full_prompt = p.get("fullPrompt", "")
        date = p.get("date", "")
        subcategory = p.get("subcategory", "")
        identity = p.get("identity", "")
        needs_ref = p.get("needsRefImage", False)
        scenes = p.get("scenes", [])
        heat = p.get("heat", "")

        # Parse structure
        parsed = parse_prompt_sections(full_prompt, number)

        # Auto category
        category = p.get("category") or auto_category(title, subcategory)

        # Test images
        tests = get_test_images(number)

        # Related
        related = p.get("related", {"series": [], "brothReuse": [], "upstream": [], "downstream": []})

        # Stats
        stats = p.get("stats", {})

        slug = generate_slug(number, title)

        entry = {
            "slug": slug,
            "number": number,
            "title": title,
            "date": date,
            "category": category,
            "subcategory": subcategory,
            "identity": identity,
            "needsRefImage": needs_ref,
            "structureType": parsed["structureType"],
            "structure": parsed["structure"],
            "avoidList": parsed["avoidList"],
            "scenes": scenes,
            "tests": tests,
            "related": related,
            "stats": stats,
            "heat": heat,
        }
        output.append(entry)

    # Sort by number descending
    output.sort(key=lambda x: x["number"], reverse=True)

    out_path = DATA_DIR / "prompts.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ prompts.json: {len(output)} prompts → {out_path}")
    return str(out_path)


if __name__ == "__main__":
    # This will be called from the main builder with data from remio KB
    print("Use build_all.py to run the full pipeline")

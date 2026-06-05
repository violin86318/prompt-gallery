#!/usr/bin/env python3
"""Prompt Gallery full build pipeline.
Reads data → generates static HTML → outputs to site/."""

import json
import os
import sys
import http.server
import threading
from pathlib import Path

# Setup path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

# extract import removed — prompts.json is the source of truth now

# Jinja2 setup
try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    print("Installing jinja2...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "jinja2", "-q"])
    from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = BASE / "templates"
SITE_DIR = BASE / "site"


def render_site():
    """Full build: extract data → render all pages."""
    # 1. Load data from multiple sources
    data_path = BASE / "data" / "prompts.json"
    adrian_path = BASE / "data" / "adrian_prompts.json"
    print(f"📦 Step 1: Loading data...")

    with open(data_path, encoding="utf-8") as f:
        prompts = json.load(f)
    # Tag 小小东 collection
    for p in prompts:
        p.setdefault("collection", "xiaoxiaodong")
        p.setdefault("author", "小小东")
        p.setdefault("authorUrl", "https://x.com/xiaoxiaodong01")

    # Load AdrianPunk collection if exists
    adrian_prompts = []
    if adrian_path.exists():
        with open(adrian_path, encoding="utf-8") as f:
            adrian_prompts = json.load(f)
        # Map fullPrompt → structure.full for template compatibility
        for p in adrian_prompts:
            if "fullPrompt" in p and "structure" not in p:
                p["structure"] = {"full": p["fullPrompt"], "broth": "", "spice": "", "catalyst": ""}
        print(f"   📦 AdrianPunk: {len(adrian_prompts)} prompts")

    # Merge all
    all_prompts = prompts + adrian_prompts
    # Sort by number descending (newest/highest number first)
    all_prompts.sort(key=lambda p: p.get("number", 0), reverse=True)
    print(f"   📦 Total: {len(all_prompts)} prompts ({len(prompts)} 小小东 + {len(adrian_prompts)} AdrianPunk)")

    # 1.5 Scan disk for test images and update tests field
    tests_dir = BASE / "site" / "assets" / "tests"
    for p in all_prompts:
        num = p["number"]
        coll = p.get("collection", "xiaoxiaodong")
        # Use prefix for non-xiaoxiaodong collections to avoid filename collisions
        if coll == "xiaoxiaodong":
            prefix = ""
        else:
            prefix = f"{coll}_"
        gcli_path = tests_dir / f"{prefix}gcli_{num}.png"
        bizyair_path = tests_dir / f"{prefix}bizyair_{num}.png"
        test_path = tests_dir / f"{prefix}test_{num}.png"
        tests = {}
        if gcli_path.exists():
            tests["Nano Banana 2"] = {
                "image": f"assets/tests/{prefix}gcli_{num}.png",
                "size": f"{gcli_path.stat().st_size // 1024}KB",
            }
        if bizyair_path.exists():
            tests["GPT Image 2"] = {
                "image": f"assets/tests/{prefix}bizyair_{num}.png",
                "size": f"{bizyair_path.stat().st_size // 1024}KB",
            }
        if test_path.exists() and "Nano Banana 2" not in tests:
            tests["Nano Banana 2"] = {
                "image": f"assets/tests/{prefix}test_{num}.png",
                "size": f"{test_path.stat().st_size // 1024}KB",
            }
        p["tests"] = tests
        # For AdrianPunk: also set refImage to a category-level image
        if coll == "adrian-punk" and p.get("refImage") is None:
            # Try to find the category image based on category num
            cat_num = ((p["number"] - 1) // 4) + 1
            cat_img = tests_dir / "adrian_refs" / f"cat_{cat_num}.jpg"
            if cat_img.exists():
                p["refImage"] = f"assets/tests/adrian_refs/cat_{cat_num}.jpg"

    updated_with_images = sum(1 for p in all_prompts if p["tests"])
    gcli_count = sum(1 for p in all_prompts if "Nano Banana 2" in p["tests"])
    bizyair_count = sum(1 for p in all_prompts if "GPT Image 2" in p["tests"])
    print(f"   📸 Disk scan: {gcli_count} Nano Banana 2, {bizyair_count} GPT Image 2")
    print(f"   📸 {updated_with_images}/{len(all_prompts)} prompts with test images")

    # 2. Setup Jinja2
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    # Don't escape JSON in script tags
    env.policies['ext.do'] = True

    # 3. Prepare template data
    categories = []
    seen = set()
    for p in all_prompts:
        if p["category"] not in seen:
            categories.append(p["category"])
            seen.add(p["category"])

    total = len(all_prompts)
    with_images = sum(1 for p in all_prompts if p["tests"])
    latest = all_prompts[0] if all_prompts else None

    # All slugs for random navigation
    all_slugs = [p["slug"] for p in all_prompts]

    # Category counts
    cat_counts = {}
    for p in all_prompts:
        cat_counts[p["category"]] = cat_counts.get(p["category"], 0) + 1

    # Collections (for tab switching)
    collections = []
    seen_coll = set()
    for p in all_prompts:
        coll = p.get("collection", "xiaoxiaodong")
        if coll not in seen_coll:
            collections.append({"id": coll, "author": p.get("author", "")})
            seen_coll.add(coll)

    # 4. Render index
    print("🏗️  Step 2: Rendering index page...")
    index_tmpl = env.get_template("index.html")
    index_html = index_tmpl.render(
        prompts=all_prompts,
        categories=categories,
        cat_counts=cat_counts,
        total=total,
        with_images=with_images,
        latest=latest,
        collections=collections,
    )
    index_path = SITE_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    print(f"  ✓ {index_path}")

    # 5. Render detail pages
    print("📄 Step 3: Rendering detail pages...")
    detail_tmpl = env.get_template("detail.html")
    prompt_dir = SITE_DIR / "prompt"
    prompt_dir.mkdir(exist_ok=True)

    # Build slug-to-index map for prev/next navigation (within same collection)
    slug_map = {}
    for i, p in enumerate(all_prompts):
        slug_map[p["slug"]] = i

    rendered = 0
    for i, p in enumerate(all_prompts):
        # Navigate within same collection
        coll = p.get("collection", "xiaoxiaodong")
        coll_prompts = [pp for pp in all_prompts if pp.get("collection", "xiaoxiaodong") == coll]
        coll_idx = next((j for j, pp in enumerate(coll_prompts) if pp["slug"] == p["slug"]), 0)
        prev_p = coll_prompts[coll_idx + 1] if coll_idx + 1 < len(coll_prompts) else None
        next_p = coll_prompts[coll_idx - 1] if coll_idx - 1 >= 0 else None

        detail_html = detail_tmpl.render(
            prompt=p,
            prev_prompt=prev_p,
            next_prompt=next_p,
            all_slugs=all_slugs,
        )
        detail_path = prompt_dir / f"{p['slug']}.html"
        detail_path.write_text(detail_html, encoding="utf-8")
        rendered += 1

    print(f"  ✓ {rendered} detail pages")

    # 6. Summary
    print(f"\n✅ Build complete!")
    print(f"   {total} prompts, {with_images} with test images")
    print(f"   Categories: {', '.join(categories)}")
    print(f"   Output: {SITE_DIR}/")
    print(f"\n   Start server: python {BASE / 'src' / 'serve.py'}")
    return SITE_DIR


if __name__ == "__main__":
    render_site()

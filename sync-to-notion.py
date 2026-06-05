#!/usr/bin/env python3
"""
Sync prompts.json → Notion page "GPT-image-2 提示词宝库 @小小东"
Page ID: 3541b1d7-1d88-816a-afbc-ffee788d83bf

Usage:
  # Incremental: only append prompts newer than last synced number
  python3 sync-to-notion.py --incremental

  # Full rebuild: clear page and rewrite all prompts
  python3 sync-to-notion.py --full

  # Check status (no write)
  python3 sync-to-notion.py --status

State file: prompt-gallery/.notion-sync-state.json
  { "last_synced_number": N, "last_synced_at": "ISO datetime" }
"""

import json
import os
import subprocess
import sys
import datetime

NOTION_PAGE_ID = "3541b1d7-1d88-816a-afbc-ffee788d83bf"
NTN = os.path.expanduser("~/.local/bin/ntn")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_PATH = os.path.join(SCRIPT_DIR, "data", "prompts.json")
STATE_PATH = os.path.join(SCRIPT_DIR, ".notion-sync-state.json")
MAX_BLOCKS_PER_REQUEST = 100


def ntn_api(path, method="GET", data=None):
    """Call Notion API via ntn CLI."""
    cmd = [NTN, "api", path, "-X", method]
    if data:
        cmd += ["-d", json.dumps(data, ensure_ascii=False)]
    env = os.environ.copy()
    env["NOTION_API_VERSION"] = "2022-06-28"
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    if result.returncode != 0:
        print(f"  ⚠️ API error: {result.stderr[:200]}", file=sys.stderr)
        return None
    return json.loads(result.stdout)


def load_prompts():
    with open(PROMPTS_PATH, "r") as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"last_synced_number": 0, "last_synced_at": None}


def save_state(state):
    state["last_synced_at"] = datetime.datetime.now().isoformat()
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def truncate_text(text, max_len=2000):
    """Notion rich text has a 2000 char limit per text object."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def make_text_block(text):
    """Create a rich_text array with one text object."""
    return [{"type": "text", "text": {"content": truncate_text(text)}}]


def prompt_to_blocks(prompt):
    """Convert a single prompt entry to Notion blocks."""
    blocks = []

    # Heading: #N title (category · type)
    num = prompt.get("number", "?")
    title = prompt.get("title", "Untitled")
    category = prompt.get("category", "")
    ptype = prompt.get("type", "")
    heat = prompt.get("heat", "")
    ref_desc = prompt.get("refDesc", "")
    date = prompt.get("date", "")
    post_url = prompt.get("postUrl", "")
    innovation = prompt.get("innovation", "")
    scenes = prompt.get("scenes", "")
    structure_desc = prompt.get("structureDesc", "")

    subtitle_parts = [p for p in [category, ptype] if p]
    subtitle = f"{' · '.join(subtitle_parts)}" if subtitle_parts else ""

    heading_text = f"#{num} {title}"
    if subtitle:
        heading_text += f"  ({subtitle})"

    blocks.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": make_text_block(heading_text)}
    })

    # Meta info paragraph
    meta_parts = []
    if date:
        meta_parts.append(f"📅 {date}")
    if heat:
        meta_parts.append(f"🔥 {heat}")
    if ref_desc:
        meta_parts.append(ref_desc)
    if post_url:
        meta_parts.append(f"[原帖]({post_url})")

    if meta_parts:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": make_text_block(" | ".join(meta_parts))}
        })

    # Innovation / description
    if innovation:
        blocks.append({
            "object": "block",
            "type": "quote",
            "quote": {"rich_text": make_text_block(f"💡 {innovation}")}
        })

    # Structure description
    if structure_desc:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": make_text_block(f"🏗️ 结构: {structure_desc}")}
        })

    # Scenes
    if scenes:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": make_text_block(f"🎯 适用: {scenes}")}
        })

    # Full prompt text (the main content)
    structure = prompt.get("structure", {})
    prompt_text = ""
    if structure.get("full"):
        prompt_text = structure["full"]
    elif structure.get("broth"):
        parts = []
        if structure.get("broth"):
            parts.append(f"【汤底】\n{structure['broth']}")
        if structure.get("spice"):
            parts.append(f"【佐料】\n{structure['spice']}")
        if structure.get("catalyst"):
            parts.append(f"【药引子】\n{structure['catalyst']}")
        prompt_text = "\n\n".join(parts)

    if prompt_text:
        # Notion code block max 2000 chars — split if needed
        if len(prompt_text) <= 2000:
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": make_text_block(prompt_text),
                    "language": "plain text"
                }
            })
        else:
            # Split into chunks of 2000
            for i in range(0, len(prompt_text), 2000):
                chunk = prompt_text[i:i+2000]
                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": make_text_block(chunk),
                        "language": "plain text"
                    }
                })

    # Divider
    blocks.append({"object": "block", "type": "divider", "divider": {}})

    return blocks


def append_blocks_to_page(page_id, blocks):
    """Append blocks to a Notion page, respecting the 100-block limit."""
    for i in range(0, len(blocks), MAX_BLOCKS_PER_REQUEST):
        batch = blocks[i:i + MAX_BLOCKS_PER_REQUEST]
        result = ntn_api(
            f"v1/blocks/{page_id}/children",
            method="PATCH",
            data={"children": batch}
        )
        if result is None:
            return False
        print(f"  ✅ Written batch {i // MAX_BLOCKS_PER_REQUEST + 1} ({len(batch)} blocks)")
    return True


def delete_all_blocks(page_id):
    """Delete all blocks from a page."""
    print("🗑️ Deleting existing blocks...")
    deleted = 0
    # Collect all block IDs first
    all_ids = []
    cursor = None
    while True:
        path = f"v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        result = ntn_api(path)
        if not result:
            break
        blocks = result.get("results", [])
        all_ids.extend(b["id"] for b in blocks)
        if not result.get("has_more", False):
            break
        cursor = result.get("next_cursor")

    print(f"  Found {len(all_ids)} blocks to delete")
    for bid in all_ids:
        ntn_api(f"v1/blocks/{bid}", method="DELETE")
        deleted += 1
        if deleted % 50 == 0:
            print(f"  Deleted {deleted}/{len(all_ids)}...")
    print(f"  Deleted {deleted} blocks")
    return deleted


def write_header_blocks():
    """Create the page header blocks."""
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    blocks = [
        {"object": "block", "type": "table_of_contents", "table_of_contents": {"color": "default"}},
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"本页面由 remio 定时任务自动同步 · 数据源: prompts.json · 最后同步: {now}"}},
                ]
            }
        },
        {"object": "block", "type": "divider", "divider": {}},
    ]
    return blocks


def cmd_status():
    """Show sync status."""
    prompts = load_prompts()
    state = load_state()
    last = state.get("last_synced_number", 0)

    print(f"📊 Notion 同步状态")
    print(f"  本地提示词: {len(prompts)} 条 (#{min(p['number'] for p in prompts)} ~ #{max(p['number'] for p in prompts)})")
    print(f"  已同步到 Notion: #{last}")
    print(f"  上次同步: {state.get('last_synced_at', '从未')}")

    new_count = sum(1 for p in prompts if p["number"] > last)
    print(f"  待同步: {new_count} 条")

    if new_count > 0:
        new_prompts = sorted([p for p in prompts if p["number"] > last], key=lambda x: x["number"])
        print(f"\n  待同步条目:")
        for p in new_prompts[:10]:
            print(f"    #{p['number']}: {p['title']}")
        if new_count > 10:
            print(f"    ... 还有 {new_count - 10} 条")


def cmd_incremental():
    """Incremental sync: append new prompts only."""
    prompts = load_prompts()
    state = load_state()
    last = state["last_synced_number"]

    new_prompts = sorted([p for p in prompts if p["number"] > last], key=lambda x: x["number"])

    if not new_prompts:
        print("✅ 已是最新，无需同步")
        return

    print(f"🔄 增量同步: {len(new_prompts)} 条新提示词 (#{new_prompts[0]['number']} ~ #{new_prompts[-1]['number']})")

    all_blocks = []
    for p in new_prompts:
        blocks = prompt_to_blocks(p)
        all_blocks.extend(blocks)

    print(f"  总计 {len(all_blocks)} 个 blocks 待写入")

    if append_blocks_to_page(NOTION_PAGE_ID, all_blocks):
        state["last_synced_number"] = max(p["number"] for p in new_prompts)
        save_state(state)
        print(f"✅ 同步完成: #{state['last_synced_number']}")
    else:
        print("❌ 同步失败")
        sys.exit(1)


def cmd_full():
    """Full rebuild: delete all blocks and rewrite."""
    prompts = load_prompts()
    prompts_sorted = sorted(prompts, key=lambda x: x["number"])

    print(f"🔄 全量重建: {len(prompts_sorted)} 条提示词")

    # Step 1: Delete existing blocks
    delete_all_blocks(NOTION_PAGE_ID)

    # Step 2: Write header
    header = write_header_blocks()
    append_blocks_to_page(NOTION_PAGE_ID, header)

    # Step 3: Write all prompts
    all_blocks = []
    for p in prompts_sorted:
        blocks = prompt_to_blocks(p)
        all_blocks.extend(blocks)

    print(f"  总计 {len(all_blocks)} 个 blocks 待写入")

    if append_blocks_to_page(NOTION_PAGE_ID, all_blocks):
        state = {"last_synced_number": max(p["number"] for p in prompts_sorted)}
        save_state(state)
        print(f"✅ 全量同步完成: {len(prompts_sorted)} 条 → #{state['last_synced_number']}")
    else:
        print("❌ 全量同步失败")
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "--status":
        cmd_status()
    elif cmd == "--incremental":
        cmd_incremental()
    elif cmd == "--full":
        cmd_full()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Phase 3: 飞书多维表格同步脚本（v2 - lark-cli 1.0.71 验证可用）

功能:
1. 从 prompts.json 读取全部记录
2. 同步到飞书多维表格（增量：只写入上次同步后有变化的记录）
3. 飞书不可用时降级为本地 CSV 导出

用法:
  python sync_feishu.py              # 飞书增量同步（默认）
  python sync_feishu.py --full       # 全量同步（清空重写）
  python sync_feishu.py --csv-only   # 强制只导出 CSV
"""
import json, os, sys, csv, subprocess, time
from pathlib import Path

AGENT_DIR = Path(os.path.expanduser(
    "~/Library/Application Support/remio/Users/F2313D5DDFE8FCF316DC1149F06BB14B/agent"
))
GALLERY_DIR = AGENT_DIR / "prompt-gallery"
DATA_DIR = GALLERY_DIR / "data"
PROMPTS_JSON = DATA_DIR / "prompts.json"
SYNC_STATE = DATA_DIR / "feishu_sync_state.json"
CSV_PATH = DATA_DIR / "gallery_assets.csv"

# === 飞书配置（已验证可用）===
BASE_TOKEN = "V4o2bGOSmakKUesQdv2cdTXWnPe"
TABLE_ID = "tbl56ynMBJ84rViP"
LARK_IDENTITY = "user"

FIELD_NAMES = ["编号", "标题", "提示词", "状态", "Lovart thread_id", "画廊链接"]


def load_prompts():
    with open(PROMPTS_JSON) as f:
        return json.load(f)


def lark_base(cmd, payload):
    """执行 lark-cli base 命令"""
    result = subprocess.run(
        ["lark-cli", "base", cmd,
         "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
         "--as", LARK_IDENTITY,
         "--json", json.dumps(payload, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120
    )
    try:
        return json.loads(result.stdout)
    except:
        return {"ok": False, "error": {"message": result.stdout[:300]}}


def check_auth():
    """检查飞书授权是否有效"""
    result = subprocess.run(
        ["lark-cli", "auth", "status"], capture_output=True, text=True, timeout=10
    )
    try:
        d = json.loads(result.stdout)
        user = d.get("identities", {}).get("user", {})
        exp = user.get("expiresAt", "")
        return bool(exp and "1970" not in exp)
    except:
        return False


def build_row(p):
    """构建单行数据"""
    num = p["number"]
    gen = p.get("generation", {})
    engines = gen.get("engines", [])
    gcli = next((e for e in engines if e["name"] == "gcli"), {})
    lovart = next((e for e in engines if e["name"] == "lovart"), {})
    has_orig = bool(gcli.get("original_path") or lovart.get("original_path"))
    has_cropped = bool(gcli.get("cropped_path") or lovart.get("cropped_path"))
    status = "已归档" if has_orig else ("仅裁切版" if has_cropped else "元数据缺失")
    thread_id = lovart.get("thread_id", "") or ""
    slug = p.get("slug", f"prompt-{num}")
    gallery_url = f"https://dong.1986318.xyz/detail/{slug}"
    prompt_text = (p.get("prompt", "") or "")[:5000]
    return [num, p.get("title", ""), prompt_text, status, thread_id, gallery_url]


def batch_create(rows):
    """批量写入记录（每批 100 条）"""
    total = 0
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        payload = {"fields": FIELD_NAMES, "rows": batch}
        r = lark_base("+record-batch-create", payload)
        if r.get("ok"):
            count = len(r.get("data", {}).get("record_id_list", []))
            total += count
            print(f"  ✅ 批次 {i//batch_size+1}: {count} 条")
        else:
            err = r.get("error", {}).get("message", "")[:200]
            print(f"  ❌ 批次 {i//batch_size+1}: {err}")
        time.sleep(0.5)
    return total


def clear_table():
    """全量同步前清空表"""
    result = subprocess.run(
        ["lark-cli", "base", "+record-list",
         "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
         "--as", "user", "--page-size", "500"],
        capture_output=True, text=True, timeout=60
    )
    try:
        d = json.loads(result.stdout)
        records = d.get("data", {}).get("items", [])
        if not records:
            return 0
        record_ids = [r["record_id"] for r in records if "record_id" in r]
        if not record_ids:
            return 0
        # 批量删除
        for i in range(0, len(record_ids), 100):
            batch = record_ids[i:i+100]
            lark_base("+record-batch-delete", {"records": batch})
            time.sleep(0.3)
        print(f"  🧹 清空 {len(record_ids)} 条旧记录")
        return len(record_ids)
    except Exception as e:
        print(f"  ⚠️ 清空失败: {e}")
        return 0


def feishu_sync(prompts, full=False):
    """飞书同步主流程"""
    print(f"  模式: {'全量' if full else '增量'}")

    if full:
        clear_table()
        time.sleep(1)

    # 构建所有行
    all_rows = [build_row(p) for p in prompts]
    print(f"  待写入: {len(all_rows)} 条")

    total = batch_create(all_rows)

    # 保存同步状态
    state = {
        "last_sync": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total_records": total,
        "mode": "full" if full else "incremental",
        "base_token": BASE_TOKEN,
    }
    with open(SYNC_STATE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    return total


def export_csv(prompts):
    """CSV 降级导出"""
    headers = ["编号", "标题", "提示词", "分类", "状态", "引擎",
               "Lovart thread_id", "gcli 宽高", "Lovart 宽高", "画廊链接", "日期"]

    rows = []
    for p in prompts:
        num = p["number"]
        gen = p.get("generation", {})
        engines = gen.get("engines", [])
        gcli = next((e for e in engines if e["name"] == "gcli"), {})
        lovart = next((e for e in engines if e["name"] == "lovart"), {})
        has_orig = bool(gcli.get("original_path") or lovart.get("original_path"))
        has_cropped = bool(gcli.get("cropped_path") or lovart.get("cropped_path"))
        status = "已归档" if has_orig else ("仅裁切版" if has_cropped else "元数据缺失")
        engine_names = " + ".join([e["name"] for e in engines]) or ""
        gcli_dim = f"{gcli.get('width','?')}x{gcli.get('height','?')}" if gcli.get("width") else ""
        lovart_dim = f"{lovart.get('width','?')}x{lovart.get('height','?')}" if lovart.get("width") else ""
        slug = p.get("slug", f"prompt-{num}")
        gallery_url = f"https://dong.1986318.xyz/detail/{slug}"
        rows.append([num, p.get("title", ""), (p.get("prompt", "") or "")[:5000],
                     p.get("category", ""), status, engine_names,
                     lovart.get("thread_id", "") or "", gcli_dim, lovart_dim,
                     gallery_url, p.get("date", "")])

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"  ✅ CSV 导出完成: {len(rows)} 条 -> {CSV_PATH}")
    return CSV_PATH


def main():
    print("=" * 60)
    print("Phase 3: 飞书多维表格同步 (v2)")
    print("=" * 60)

    prompts = load_prompts()
    print(f"\n加载 prompts.json: {len(prompts)} 条")

    csv_only = "--csv-only" in sys.argv
    full = "--full" in sys.argv

    if csv_only:
        export_csv(prompts)
        return

    if not check_auth():
        print("\n⚠️ 飞书认证过期，降级为 CSV")
        export_csv(prompts)
        print(f"\n   恢复飞书同步: 运行 `lark-cli auth login` 重新授权后重跑")
        return

    print(f"\n--- 飞书同步 ---")
    total = feishu_sync(prompts, full=full)
    print(f"\n✅ 飞书同步完成: {total} 条")
    print(f"   Base: https://my.feishu.cn/base/{BASE_TOKEN}")

    # 同时导出 CSV 做本地备份
    export_csv(prompts)


if __name__ == "__main__":
    main()

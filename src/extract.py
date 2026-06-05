#!/usr/bin/env python3
"""Extract prompt data from remio KB and build prompts.json.
This is the data pipeline (M1)."""

import json
import os
import re
import sys

# We'll import from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from build import build_prompts_json, ASSETS_DIR

# --- Hardcoded prompt metadata from main note (mov604kk7kdqjpkbyg7) ---
# This covers #1-#74 with title, date, heat, ref image status
# Full prompt text will be extracted from the main note content

PROMPTS_META = [
    {"number": 1, "title": "掌纹算命", "needsRefImage": True, "heat": "★★★"},
    {"number": 2, "title": "面相算命", "needsRefImage": True, "heat": "★★★"},
    {"number": 3, "title": "信息卡片·万能推荐", "needsRefImage": False, "heat": "★★★"},
    {"number": 4, "title": "自媒体封面", "needsRefImage": False, "heat": "★★★"},
    {"number": 5, "title": "字体美学·单词视觉化", "needsRefImage": False, "heat": "★★★"},
    {"number": 6, "title": "以假乱真·纪实摄影", "needsRefImage": False, "heat": "★★☆"},
    {"number": 7, "title": "抽象表情包", "needsRefImage": True, "heat": "★★★"},
    {"number": 8, "title": "抽象圆润风", "needsRefImage": True, "heat": "★★☆"},
    {"number": 9, "title": "情头·万物可情头", "needsRefImage": True, "heat": "★★☆"},
    {"number": 10, "title": "进化史信息图", "needsRefImage": False, "heat": "★★☆"},
    {"number": 11, "title": "城市宣传海报", "needsRefImage": False, "heat": "★★☆"},
    {"number": 12, "title": "国风唐诗宋词", "needsRefImage": False, "heat": "★★☆"},
    {"number": 13, "title": "国宝文物图鉴", "needsRefImage": False, "heat": "★★☆"},
    {"number": 14, "title": "建筑速写知识图", "needsRefImage": False, "heat": "★★☆"},
    {"number": 15, "title": "名著经典海报", "needsRefImage": False, "heat": "★☆☆"},
    {"number": 16, "title": "景点建筑信息图", "needsRefImage": False, "heat": "★☆☆"},
    {"number": 17, "title": "Logo 设计", "needsRefImage": False, "heat": "★★☆"},
    {"number": 18, "title": "报纸头条", "needsRefImage": False, "heat": "★☆☆"},
    {"number": 19, "title": "天空手绘修图", "needsRefImage": True, "heat": "★☆☆"},
    {"number": 20, "title": "中式窗景", "needsRefImage": False, "heat": "★★☆"},
    {"number": 21, "title": "线条艺术", "needsRefImage": False, "heat": "★★★"},
    {"number": 22, "title": "微缩模型", "needsRefImage": False, "heat": "★★☆"},
    {"number": 23, "title": "乐高文字", "needsRefImage": False, "heat": "★★☆"},
    {"number": 24, "title": "抽象头像", "needsRefImage": True, "heat": "★★☆"},
    {"number": 25, "title": "天空变萌萌", "needsRefImage": True, "heat": "★★☆"},
    {"number": 26, "title": "印象派信息图", "needsRefImage": False, "heat": "★★☆"},
    {"number": 27, "title": "电商广告 Banner", "needsRefImage": False, "heat": "★★☆"},
    {"number": 28, "title": "清冷油墨风", "needsRefImage": False, "heat": "★★☆"},
    {"number": 29, "title": "中文字形设计", "needsRefImage": False, "heat": "★★☆"},
    {"number": 30, "title": "看面相·垂直提问版", "needsRefImage": True, "heat": "★★★"},
    # #31+ have broth-spice structure
    {"number": 31, "title": "流程图信息图重构", "date": "2026-05-08", "needsRefImage": False, "heat": "★★★"},
    {"number": 32, "title": "小红书卡片系列海报", "date": "2026-05-09", "needsRefImage": False, "heat": "★★★"},
    {"number": 33, "title": "电商一键整套详情页", "date": "2026-05-10", "needsRefImage": False, "heat": "★★★"},
    {"number": 34, "title": "植物识别", "date": "2026-05-10", "needsRefImage": True, "heat": "★★☆"},
    {"number": 35, "title": "记忆忠告概念卡片", "date": "2026-05-11", "needsRefImage": False, "heat": "★★☆"},
    {"number": 36, "title": "漫画日记", "date": "2026-05-11", "needsRefImage": False, "heat": "★★★"},
    {"number": 37, "title": "极简线条头像·山顶洞人进化版", "date": "2026-05-11", "needsRefImage": True, "heat": "★★★"},
    {"number": 38, "title": "线稿城市海报·人民币般美感", "date": "2026-05-12", "needsRefImage": False, "heat": "★★★"},
    {"number": 39, "title": "留白线条·审美疲劳的洗眼器", "date": "2026-05-12", "needsRefImage": False, "heat": "★★☆"},
    {"number": 40, "title": "胎儿四维照片·AI推测还原长相", "date": "2026-05-12", "needsRefImage": True, "heat": "★★☆"},
    {"number": 41, "title": "文本转视觉·长文速览海报", "date": "2026-05-13", "needsRefImage": False, "heat": "★★★"},
    {"number": 42, "title": "城市拼音海报·收藏级主题视觉", "date": "2026-05-13", "needsRefImage": False, "heat": "★★★"},
    {"number": 43, "title": "教学PPT万能海报·治愈系配色", "date": "2026-05-14", "needsRefImage": False, "heat": "★★★"},
    {"number": 44, "title": "时尚陈列型信息海报", "date": "2026-05-14", "needsRefImage": False, "heat": "★★★"},
    {"number": 45, "title": "手相升级版·垂直提问万能版", "date": "2026-05-14", "needsRefImage": True, "heat": "★★★"},
    {"number": 46, "title": "通用邀请函·万能情境兼容", "date": "2026-05-15", "needsRefImage": False, "heat": "★★★"},
    {"number": 47, "title": "一字美学·中式秩序美感", "date": "2026-05-15", "needsRefImage": False, "heat": "★★★"},
    {"number": 48, "title": "十二生肖IP图·3×4网格系列", "date": "2026-05-15", "needsRefImage": False, "heat": "★★★"},
    {"number": 49, "title": "涂鸦变抱枕·亲子艺术衍生品", "date": "2026-05-15", "needsRefImage": True, "heat": "★★★"},
    {"number": 50, "title": "十二星座IP图·3×4网格系列", "date": "2026-05-16", "needsRefImage": False, "heat": "★★★"},
    {"number": 51, "title": "数据转图表·奶油风可视化", "date": "2026-05-16", "needsRefImage": False, "heat": "★★★"},
    {"number": 52, "title": "电子零配件变乐高·五金创意图", "date": "2026-05-17", "needsRefImage": False, "heat": "★★★"},
    {"number": 53, "title": "高桥流海报设计", "date": "2026-05-18", "needsRefImage": False, "heat": "★★★"},
    {"number": 54, "title": "万能信息简化图", "date": "2026-05-18", "needsRefImage": False, "heat": "★★★"},
    {"number": 55, "title": "山海经/古文古画实景摄影", "date": "2026-05-18", "needsRefImage": False, "heat": "★★★"},
    {"number": 56, "title": "穿衣打扮·泳衣穿搭提案", "date": "2026-05-18", "needsRefImage": False, "heat": "★★★"},
    {"number": 57, "title": "古画还原·极简版提示词", "date": "2026-05-18", "needsRefImage": True, "heat": "★★★"},
    {"number": 58, "title": "万能PPT·东方编辑感美学", "date": "2026-05-19", "needsRefImage": False, "heat": "★★★"},
    {"number": 59, "title": "蓝白颗粒文字背景PPT·现代编辑感", "date": "2026-05-20", "needsRefImage": False, "heat": "★★★"},
    {"number": 60, "title": "琥珀温润材质PPT·岁月沉积美学", "date": "2026-05-20", "needsRefImage": False, "heat": "★★★"},
    {"number": 61, "title": "纪念碑谷风格·批量24节气卡片", "date": "2026-05-21", "needsRefImage": False, "heat": "★★★"},
    {"number": 62, "title": "东方留白感·万能知识图鉴汤底", "date": "2026-05-21", "needsRefImage": False, "heat": "★★★"},
    {"number": 63, "title": "东方水彩风·早安晚安问候卡片", "date": "2026-05-22", "needsRefImage": False, "heat": "★★★"},
    {"number": 64, "title": "景深美学·节气城市问候卡片", "date": "2026-05-22", "needsRefImage": False, "heat": "★★★"},
    {"number": 65, "title": "PPT一键成型·无限风格换肤", "date": "2026-05-22", "needsRefImage": False, "heat": "★★★"},
    {"number": 66, "title": "年轮·知识生命系统", "date": "2026-05-23", "needsRefImage": False, "heat": "★★★"},
    {"number": 67, "title": "东方水墨动画气质·课本插画", "date": "2026-05-23", "needsRefImage": False, "heat": "★★★"},
    {"number": 68, "title": "丝网印刷风·被时间保存的印刷物", "date": "2026-05-24", "needsRefImage": False, "heat": "★★★"},
    {"number": 69, "title": "童趣手绘·情绪文案壁纸", "date": "2026-05-24", "needsRefImage": False, "heat": "★★★"},
    {"number": 70, "title": "会流动会发光会呼吸·水彩空气感", "date": "2026-05-24", "needsRefImage": False, "heat": "★★★"},
    {"number": 71, "title": "光的容器·中式窗棂剪影海报", "date": "2026-05-25", "needsRefImage": False, "heat": "★★★"},
    {"number": 72, "title": "局部破框·几何情绪窗口", "date": "2026-05-25", "needsRefImage": False, "heat": "★★★"},
    {"number": 73, "title": "三角形跳出窗口·自定义几何裁切", "date": "2026-05-25", "needsRefImage": False, "heat": "★★★"},
    {"number": 74, "title": "旅行记忆窗口·高铁窗景", "date": "2026-05-25", "needsRefImage": False, "heat": "★★★"},
]

# --- Full prompts text (from main note, #31-#74 only; #1-#30 stored as classic) ---
# This dict holds the full prompt text extracted from the main note
# For the initial build, we include the prompts we've already read

FULL_PROMPTS = {
    53: """苹果设计师思维，顶级海报大师思维，用高桥流思路 呈现海报设计 输入一段或多段长文本 智能理解文本内容，不必逐字照搬 自动分析用户理解流程，按认知逻辑梳理信息 提炼文本的核心价值、关键知识点、中心思想和亮点观点 按照人脑阅读和理解顺序呈现信息，让用户自然 get 核心内容 压缩长文本为可在30-45秒内快速理解的精华内容 文字在手机端默认显示状态下清晰可读，字体大小、行距、层次合理 用超大字或重点标注突出核心信息，避免冗长或晦涩表达 智能判定配色逻辑、排版结构和信息层次，保证视觉呼吸感 打平用户理解成本，让信息简单明了，一眼就抓住重点 消除理解障碍，确保读者读完海报后能快速掌握中心思想 不要额外添加无关文字 保持海报抓人、直击人心的表现力 如下代码块中是，本次要处理的原始文字 ``` 请理解图片上的文字信息，把其中文本当作我们要处理的信息 ``` 额外要求 原文 标题 垂直大字排列 在 画面中间，很震撼 人文关怀主义设计，文字醒目，标记重点和彩色文字强调重点 巧妙的插画。 其他文字，较大 且醒目""",
    54: """（汤底复用高桥流基底）...在重构海报信息时，必须优先保留原文中最有争议、最有冲突感、最能让人停下来的表达作为主标题或第一视觉入口；正文可以提炼重组，但不要把标题改成过于理性、中性或公益化的概念句。 如下代码块中是，本次要处理的原始文字 ``` 识别图片上的文字标题和正文 ``` 额外要求 提供更适合原图的信息呈现方式，醒目、美观""",
    55: """请根据用户提供的源材料，创作一张真实存在、由顶级摄影师拍到的收藏级摄影作品。源材料可以是中国古画、古文、古籍记载、诗文、题跋、游记、志怪、神话、传说描述。不要把任务理解为"把古画画成照片"，应把源材料视为古人对真实世界的一次提炼、取舍、压缩与重组，再反向还原为那个世界本身。""",
    56: """穿衣打扮 x 提示词。本次用户输入：一套灵感来自柠檬的泳衣穿搭 提案 左侧大图，右侧细节展示，各种层次的信息点展示""",
    57: """请根据用户上传的中国古画图像，创作一张真实存在、由顶级摄影师拍到的收藏级摄影作品。不要把任务理解为"把古画画成照片"，应把古画视为古代创作者对真实世界的一次提炼、取舍、压缩与重组，再反向还原成他当时真正看到的景象。""",
    58: """请把画面处理成一种安静、克制、带有东方编辑感的高级视觉：它像一页被精心排过的纸本册页，又能自然适应现代信息设计。整体不要追求炫技和饱满，而要让留白成为主要结构，让内容在米纸、浅灰、淡墨、温润木色之间缓慢显形。画面可以有一两个柔和的图像窗口，像拱门、月洞、折扇或被风掀开的纸页，以大曲线切开空间。色彩保持温和而有层次，主色接近宣纸和陈木。避免复古仿品感、茶文化套壳、空洞禅意、AI油亮质感。本次主题：____ 用途：____""",
    59: """请把画面处理成一种克制、清洁、带有纸面触感的高级视觉：背景不是空白，而是一层有呼吸感的浅色材质。文字要成为画面结构的一部分，使用超大尺度的主标题作为背景骨架，通过颗粒化、网点扩散变成视觉压力。色彩系统以低饱和浅底作为空气，深主色承担结构，点睛色只占很小面积。版式要有明显的前后景关系。本次主题：____ 用途：ppt、课件 最少10页""",
    # Placeholder for prompts where we haven't extracted full text yet
    # These will be populated from the main note in a future iteration
}


def extract():
    """Build prompts.json from metadata + full prompts."""
    prompts = []

    for meta in PROMPTS_META:
        num = meta["number"]
        entry = {
            "number": num,
            "title": meta["title"],
            "date": meta.get("date", "2026-05-07"),  # default to collection start
            "needsRefImage": meta.get("needsRefImage", False),
            "heat": meta.get("heat", ""),
            "fullPrompt": FULL_PROMPTS.get(num, ""),
            "category": meta.get("category"),
            "subcategory": meta.get("subcategory", ""),
            "identity": meta.get("identity", ""),
            "scenes": meta.get("scenes", []),
            "stats": meta.get("stats", {}),
            "related": meta.get("related", {}),
        }
        prompts.append(entry)

    path = build_prompts_json(prompts)
    return path


if __name__ == "__main__":
    path = extract()
    print(f"Done: {path}")

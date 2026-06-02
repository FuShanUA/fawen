"""
cover_illustrator.py

Agent 4: Generates the specialized prompt for rendering a 16:9 article cover.
Now utilizes Orchestrator / API mode to tap into actual LLM reading comprehension.
"""

import sys
import os
import re
import json
from common_utils import log_prompt
import urllib.request

def call_gemini_api(prompt_text):
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable is not set. Use orchestrator mode (default) instead.")
        sys.exit(1)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro:generateContent?key={api_key}"
    data = {"contents": [{"parts": [{"text": prompt_text}]}]}
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})

    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode('utf-8'))
            return response_data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"API Error: {e}")
        sys.exit(1)

def run_orchestrator_mode():
    print("### ORCHESTRATOR MODE (Antigravity): Please act as the Brain for this step.")
    print("1. Read the article Markdown.")
    print("2. Extract a SHORT TITLE (max 6-10 chars) that sets the primary readable context (e.g. '数据认责痛点').")
    print("3. Extract exactly 3 ultra-short, highly specific Chinese keywords (max 6 chars each).")
    print("4. Create a unique, text-specific visual metaphor suggestion.")
    print('\n[When ready, seamlessly re-run this script dynamically using your tool:]')
    print('python cover_illustrator.py <md_file> --json \'{"short_title": "核心认责痛点", "keywords": ["词1", "词2", "词3"], "metaphor": "具体隐喻..."}\'')
    sys.exit(0)

def main():
    if len(sys.argv) < 2:
        print("Usage: python cover_illustrator.py <md_file> [--api | --json '...']")
        sys.exit(1)

    md_path = sys.argv[1]
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Robust title extraction (handles YAML title:, case-insensitive Title:, or Markdown H1)
    title_cn_match = re.search(r'^(?:#|title:\s*["\']?|Title:\s*)(.+?)(?:["\']?$|$)', content, re.M | re.I)
    title_cn = title_cn_match.group(1).strip() if title_cn_match else "Untitled"

    use_api = False
    json_data = None

    for i in range(2, len(sys.argv)):
        if sys.argv[i] == "--api":
            use_api = True
        elif sys.argv[i] == "--json" and i + 1 < len(sys.argv):
            try:
                json_data = json.loads(sys.argv[i+1])
            except Exception as e:
                print(f"JSON Parse Error: {e}")
                sys.exit(1)

    if not use_api and not json_data:
        run_orchestrator_mode()

    if use_api:
        api_prompt = f"""You are a professional B2B tech editorial director. Read the following article and extract:
1. MAIN TITLE (max 12 chars). RULE: Use the original title directly if short. If it's too long (>12 chars), identify a logical split point (e.g. at a colon '：' or dash '——') and put the primary hook in MAIN TITLE.
2. SUBTITLE (max 20 chars). If the original title was split, put the remaining part here. If it was short, leave this empty.
3. Exactly 3 ultra-short Chinese keywords (max 6 characters each).
4. A descriptive visual metaphor matching the content.

Output ONLY pure JSON in this exact format:
{{"main_title": "...", "sub_title": "...", "keywords": ["...", "...", "..."], "metaphor": "..."}}

ARTICLE:
{content[:3000]}
"""
        result_text = call_gemini_api(api_prompt)
        try:
            json_str = result_text.replace('```json', '').replace('```', '').strip()
            json_data = json.loads(json_str)
        except Exception as e:
            print(f"Failed to parse API result. Raw:\n{result_text}")
            sys.exit(1)

    main_title = json_data.get('main_title', title_cn)
    sub_title = json_data.get('sub_title', "")

    # Local split logic fallback (if not from API)
    if not use_api and len(main_title) > 12:
        for delim in ["：", "——", ":", " - ", "—"]:
            if delim in main_title:
                parts = main_title.split(delim, 1)
                main_title = parts[0].strip()
                sub_title = parts[1].strip()
                break

    labels = ", ".join(json_data.get('keywords', ['数据管理', 'AI落地', '体系建设'])[:3])
    metaphor = json_data.get('metaphor', "abstract floating ecosystem with data streams")

    import hashlib
    import random
    seed_val = int(hashlib.md5(title_cn.encode('utf-8')).hexdigest(), 16)
    r = random.Random(seed_val)
    palette = "Industrial Amber: #FFBF00 (Amber Gold), #E2725B (Terracotta), #F5F5F0 (Ivory Background), #1A1A1A (Technical Black outlines)"

    style_desc = (
        f"(16:9 比例) 一张为高端 B2B 技术/商业期刊设计的 16:9 宽屏专业插图，用于文章《{title_cn}》的封面。 "
        "主题：数据管理 / 前沿科技 / 人工智能。 "
        "色调：" + palette + "。（核心要求：必须保持明亮、清新、专业的商务色调。绝对禁止使用暗黑、阴沉、科幻或神秘风格）。 "
        "构图：画面中心必须包含一个独特的视觉隐喻，表现核心概念：[" + metaphor + "]。 "
        "风格：极简主义扁平化矢量图或现代数字 B2B 插画风格。整体感官应当高端、简洁且极具空间感（呼吸感）。 "
        "背景设计：必须采用‘工业或建筑图纸 (Industrial/Architectural Blueprint)’风格的底纹，包含干净的几何线、技术网格或结构草图，增强专业厚重感。 "
        "文字渲染要求：你必须在画面的视觉核心位置，以极其醒目的大号字体渲染以下简体中文主标题："
        f"《{main_title}》。 "
        + (f"紧随主标题其后，以较小的规格渲染副标题：《{sub_title}》。 " if sub_title else "") +
        f"并在显著位置标注以下标签文字：{labels}。 "
        "排版要求：文字必须作为核心视觉元素。字体必须使用‘思源宋体 (Source Han Serif)’，展现端庄的现代出版质感。 "
        "文字呈现：结构稳定且极其清晰。禁止添加任何未要求的乱码文字、拼音或英文词汇。 "
        "限制：\n"
        "1. 严禁出现任何英文单词、乱码字母或拼音。\n"
        "2. 严禁出现任何公司名称占位符 (如 'Company Name') 或 Logo 占位符、图标占位符。\n"
        "3. 严禁出现人物面孔、宗教符号或政治隐喻。仅保持纯粹的商业逻辑与架构美感。 --ar 16:9. Aspect Ratio: 16:9 (Widescreen)."
    )

    prompt = f"[Tech B2B Cover] PROMPT: A 16:9 widescreen professional illustration for '{title_cn}'. {style_desc} --ar 16:9. Aspect Ratio: 16:9 (Widescreen). Wide horizontal composition. "

    # Save prompt to file
    log_prompt(md_path, "cover", prompt)
    print("NOTE: The generated cover MUST be placed at the VERY FRONT of the markdown article `![封面图](assets/cover.png)`.")
    print(prompt)

if __name__ == "__main__":
    main()
"""
infographic_illustrator.py

Agent 5: Generates the specialized prompt for rendering a 16:9 infographic.
Now utilizes Orchestrator / API mode to perform intelligent contextual insertion.
"""

import sys
import os
import re
import json
from common_utils import log_prompt

def run_orchestrator_mode():
    print("### ORCHESTRATOR MODE (Antigravity): Please act as the Brain for this step.")
def run_orchestrator_mode():
    print("### ORCHESTRATOR MODE (Antigravity): Please act as the Brain for this step.")
    print("1. Read the article Markdown. You MUST SMARTLY JUDGE if an infographic is needed smoothly based on a COMPREHENSIVE ratio of ARTICLE LENGTH vs IMAGE COUNT. Do not just count images blindly. (e.g. A very long article with only 1 image at the top definitely needs an infographic midway, while a short summary with 2 images won't).")
    print("2. If generating, deliberately select 1 or 2 specific paragraphs explaining complex architectures or pain points that TRULY benefit from visualization.")
    print("3. Automatically edit the Markdown file to inject `![插图](assets/infographic_N.png)` near those specific paragraphs.")
    print("4. IMPORTANT STYLE RULE: If the original article HAS existing images, ANY injected infographic MUST MATCH their visual style (colors/tone) seamlessly to avoid clashing. You must deduce their style and pass it as 'style_override'. If the article has NO images, omit 'style_override' to default to our standard 'baoyu-infographic skill' aesthetic (Data-tech, Warm/Earthy palettes). In all cases, use 100% CHINESE TEXT.")
    print("5. Extract highly informative, explanatory Chinese sentences (15-20 chars each) that provide real interpretation ('解读为主').")
    print("\n[When done, seamlessly re-run this script dynamically using your tool:]")
    print("python infographic_illustrator.py <md_file> --json '[{\"id\": \"v7\", \"keywords\": [\"中文长句解释1\"], \"style_override\": \"Minimalist blue vector style\"}]'")
    sys.exit(0)

def main():
    if len(sys.argv) < 2:
        print("Usage: python infographic_illustrator.py <md_file> [--api | --json '[...]']")
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
        print("Warning: Fully automated API markdown insertion is currently best driven by the conversational agent. Provide --json manually for now.")
        sys.exit(1)

    for item in json_data:
        idx = item['id']
        labels = " // ".join(item['keywords'][:5])

        import hashlib
        import random
        seed_val = int(hashlib.md5(title_cn.encode('utf-8')).hexdigest(), 16)
        r = random.Random(seed_val)
        palettes = [
            "Warm & Earthy: Terracotta, Deep Amber, Cream, Muted Gold",
            "Warm & Energetic: Vivid Orange, Soft Coral, Bright Yellow, White",
            "Elegant Copper: Copper, Bronze, Vanilla, Gold",
            "Warm Pastel: Soft Peach, Warm Beige, Muted Orange, White"
        ]
        palette = r.choice(palettes)

        style_override = item.get('style_override', "None")
        if style_override and style_override != "None":
            style = f"Conceptual infographic seamlessly matching the specific visual style/colors of the original article assets: {style_override}."
            color_rule = f"COLORS: Strictly follow the style_override ({style_override})."
        else:
            style = "baoyu-infographic skill style, pristine modern digital B2B data-tech illustration, bright and professional business aesthetics."
            color_rule = "COLORS: Warm tones, carefully curated warm B2B data-tech palettes (e.g. Terracotta, Cream, Amber). ENFORCE a bright, clear, and professional tone. STRICTLY NO dark, gloomy, sci-fi, or mysterious styles."

        style_desc = (
            f"(16:9 比例) 一张为文章《{title_cn}》设计的 16:9 宽屏深度技术信息图。 "
            "主题：数据管理 / 技术架构 / 人工智能。 "
            "布局：一个极其精细且具备逻辑美感的结构化分析图表。画面必须通过清晰的连线、层级或对比，直观解读核心业务逻辑。 "
            "风格：" + style + "。 强调视觉解释力与逻辑密度。 "
            + color_rule + " "
            "文字渲染要求：你必须在画面的对应逻辑节点，极其清晰地嵌入以下简体中文解释性文字：[" + labels + "]。 "
            "排版要求：所有中文字体必须清晰可辨，直接指向图中的逻辑节点，呈现出高端研究报告的质感。 "
            "限制：\n"
            "1. 严禁出现任何英文标题、单词或乱码。必须使用 100% 简体中文。\n"
            "2. 严禁出现外国/白人面孔、宗教符号或政治隐喻。 --ar 16:9. Aspect Ratio: 16:9 (Widescreen). Horizontal cinematic layout."
        )

        print(f"=== Infographic {idx} ===")
        print(f"[Tech B2B Infographic] PROMPT: {style_desc}\n")

        # Save prompt to file
        log_prompt(md_path, f"infographic_{idx}", style_desc)

if __name__ == "__main__":
    main()
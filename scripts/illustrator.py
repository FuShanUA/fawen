"""
illustrator.py - Postfdry Illustration & Infographic Prompt Generator

Orchestrates the visual style for Postfdry 2.0.
Supports dynamic "Industrial Amber Schematic" and custom styles.
"""

import sys
import os
import re
import argparse
import shutil
import datetime

def extract_key_points(md_path):
    """Extract all core points from the article body (headers)."""
    if not os.path.exists(md_path):
        return None

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract numbered headers (e.g., "1. XXX")
    points = re.findall(r'^#+\s*(\d+\..*?)$', content, re.M)

    # If not found, try any level 2 or 3 headers that look like section titles
    if len(points) < 3:
        points = re.findall(r'^#+ (?!Title|EngTitle|Url|Date|Source)(.{5,40})$', content, re.M)

    return [p for p in points if not p.startswith("Extracted from")][:10]

def get_style_identity(style_name="Industrial Amber"):
    """
    Defines the visual DNA for a given style.
    Default: 'Industrial Amber Schematic'
    """
    if style_name.lower() == "industrial amber":
        return (
            "【视觉风格 - 工业琥珀视觉简图 (Industrial Amber Schematic)】\n"
            "- 核心审美: 极致专业、高净值 B2B 咨询感、工业建筑美学。画面应具有高度的“结构化思维”与“信息密度”，而非简单的几何堆砌。\n"
            "- 构图规范: 16:9 比例，保留 40-50% 的留白 (Negative Space)。构图需具有逻辑引导性，采用“逻辑拓扑”或“系统架构”布局。\n"
            "- 视觉背景: 背景使用带有极细【等轴侧网格 (Isometric Grid)】或【技术坐标系】纹理的亮奶油白 (#FDF5E6)，营造出在专业工程纸或蓝图上绘图的质感。\n"
            "- 色彩标准: 主体线条使用深琥珀色 (#B86505)；点缀色与核心路径使用铁锈红 (#E2725B)；重要的节点可使用暗金色填充。\n"
            "- 细节密度 (Technical Density): 画面需包含丰富的工业构件感（如：圆角矩形容器、虚线连接通路、微型节点图标、数据细线等）。通过线条的粗细变化 (Stroke Weight Variation) 展现逻辑层级。严禁纯科幻感、严禁 3D 渲染、严禁写实插图。\n"
            "- **内容禁令 (CRITICAL)**: 严禁在画面中使用任何【虚拟公司名称】、虚拟商标 (Logo)、虚构的项目代号或无意义的英文占位符。所有文字必须基于文章实际标题。\n"
            "- 字体规范: 主标题使用优雅的【思源宋体 (Source Han Serif)】；副标签与节点标注使用现代清爽的【思源黑体 (Source Han Sans)】。"
        )
    else:
        # Fallback/Generic professional style
        return f"风格: {style_name}。要求: 极致专业、商务排版、16:9、高留白。"

def clean_node_labels(points):
    """提取并清洗适合做节点标签的超短核心术语（限制 2-6 字，且过滤掉问句和长句）。"""
    if not points:
        return ""
    cleaned = []
    for p in points:
        p = p.strip()
        # 过滤问句或包含“如何”、“为什么”、“什么”的长句
        if any(q in p for q in ["？", "?", "为什么", "如何", "什么", "怎么"]):
            continue
        # 剥离序号，例如 "1. 接入" -> "接入"
        p = re.sub(r'^\d+\s*[\.\、\:\：]\s*', '', p)
        # 进一步提取前缀或括号内容，例如 "第一层：接入" -> "接入"
        if "：" in p:
            p = p.split("：")[1]
        elif ":" in p:
            p = p.split(":")[1]
        
        # 针对传输/加工等层级进行清理，剥离破折号之后的具体内容，例如 "传输——系统间流转" -> "传输"
        if "——" in p:
            p = p.split("——")[0]
        elif "—" in p:
            p = p.split("—")[0]
        elif "-" in p:
            p = p.split("-")[0]
            
        # 剥离括号，例如 "接入（Ingestion）" -> "接入"
        p = re.sub(r'[\(\（].*?[\)\）]', '', p).strip()
        p = p.strip("“”\"'")
        
        # 长度限制在 2-6 个字之间
        if 2 <= len(p) <= 6:
            cleaned.append(p)
    return " / ".join(cleaned[:5])

def generate_cover_prompt(points, title_cn, style_name):
    """
    Dynamic Cover Prompt Generator.
    Conceives a content-relevant metaphor expressed in the requested style.
    """
    identity = get_style_identity(style_name)
    labels = clean_node_labels(points)

    label_instruction = f"，并在关键节点处以【思源黑体】标注标签‘{labels}’" if labels else ""

    prompt_body = (
        f"### 任务目标\n"
        f"请为专题文章《{title_cn}》构思并描述一个符合“{style_name}”视觉体系的封面插画。\n\n"
        f"### 风格基石\n{identity}\n\n"
        f"### 画面构思要求\n"
        f"1. **核心隐喻 (Metaphor)**: 请基于文章标题及其核心要点（{labels}），构思一个契合主题的“系统性/架构性”视觉隐喻。\n"
        f"2. **呈现形态**: 使用上述风格标准描述该隐喻。强调几何精准度与抽象艺术感的结合。\n"
        f"3. **文字系统与排版 (Typography - HIGH PRIORITY)**:\n"
        f"   - **主标题**: 标题‘{title_cn}’必须作为画面绝对重心，字号要【极大】（比常规大两圈），占据画面上方或中央显著位置。\n"
        f"   - **辅助标题**: 如果标题较长，请将其拆分为“主标题”与“副标题”两行展示，增强层次感。\n"
        f"   - **标签**: 在关键节点处以【思源黑体】标注标签‘{labels}’。\n"
        f"   - **禁忌**: 严禁生成任何 AI 幻觉产生的虚假公司名或 Logo。\n\n"
        f"### 输出要求\n"
        f"请直接输出一段用于绘图的 PROMPT，描述画面构成、线条走势与细节。保持 16:9 比例。"
    )

    return f"[{style_name} Cover Style] PROMPT: {prompt_body}"

def generate_infographic_prompt(logic_type, summary, facts, labels, style_name):
    """
    Explicit Infographic Prompt Generator based on Logic Types.
    """
    identity = get_style_identity(style_name)

    layout_map = {
        "对比": "采用【双轴对比】或【分屏镜像】布局。左侧表现 A 状态，右侧表现 B 状态，中间以逻辑虚线连接，突出差异点。",
        "因果": "采用【线流拓扑】布局。箭头从左向右引导，强调从『事实输入』到『最终结果』的推导路径。",
        "过程": "采用【环形流】或【阶梯式】布局。展示步骤的递进感，每个节点配以微型工业图标。",
        "并列": "采用【等轴侧网格分布】布局。各模块以独立容器形式平铺，通过留白展现平行关系。",
        "层级": "采用【金字塔】或【剥洋葱】布局。从底层基础支撑向上层业务价值逐层递进。"
    }
    layout_instruction = layout_map.get(logic_type, "采用【逻辑拓扑】结构。确保信息流向清晰。")

    infographic_specs = (
        f"### 任务目标\n"
        f"请设计一张专业的逻辑信息图 (Infographic)。\n"
        f"【逻辑类型】: {logic_type}\n"
        f"【核心逻辑提炼】: {summary}\n"
        f"【核心事实数据】: {facts}\n\n"
        f"### 风格基石\n{identity}\n\n"
        f"### 画面设计要求\n"
        f"1. **视觉布局**: {layout_instruction}\n"
        f"2. **文字处理 (事实唯一来源)**: 画面中必须准确体现关键事实：‘{facts}’。关键节点使用【思源黑体】标注标签：‘{labels}’。\n"
        f"3. **构图密度**: 具有咨询白皮书的高信息量感。严禁出现与上述事实无关的视觉元素。\n\n"
        f"### 输出要求\n"
        f"请直接输出一段用于绘图的 PROMPT，描述该逻辑结构的层级、连接方式与标注。保持 16:9 比例。"
    )

    return f"[{style_name} Infographic Style] PROMPT: {infographic_specs}"

def main():
    parser = argparse.ArgumentParser(description="Postfdry Illustrator 2.0")
    parser.add_argument("input", help="Source Markdown file")
    parser.add_argument("--assets", default="assets", help="Path to save assets")
    parser.add_argument("--cover-style", default="Industrial Amber", help="Style for cover image")
    parser.add_argument("--info-style", default="Industrial Amber", help="Style for infographics")
    parser.add_argument("--gen-images", action="store_true", help="Generate actual images via skill CLI")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="LLM model for prompt refinement")
    parser.add_argument("--image-model", default="vertex", help="Image generation model/engine")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ 找不到输入文件: {args.input}")
        sys.exit(1)

    md_path = args.input
    project_assets = args.assets

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Prioritize frontmatter title or search for primary header
    title_cn = "未命名文章"
    frontmatter_title = re.search(r'^title:\s*(.+)$', content, re.M | re.I)
    if frontmatter_title:
        title_cn = frontmatter_title.group(1).strip().strip('"').strip("'")
    else:
        title_cn_match = re.search(r'^(?:#\s*)(.+)$', content, re.M)
        if title_cn_match:
            title_cn = title_cn_match.group(1).strip()

    points = extract_key_points(md_path)
    all_prompts = []

    def log_and_print(text):
        print(text)
        all_prompts.append(text)

    # Add common to path to load llm_utils
    common_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common'))
    if common_dir not in sys.path:
        sys.path.insert(0, common_dir)

    agents_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'agents'))
    if agents_dir not in sys.path:
        sys.path.insert(0, agents_dir)

    from llm_utils import get_client
    client = get_client()
    model_name = args.model or "gemini-3-flash-preview"

    # 1. Generate Cover
    log_and_print("\n" + "="*40)
    log_and_print(f"ASSET: ARTICLE COVER (头图) [Style: {args.cover_style}]")
    log_and_print("="*40)
    cover_prompt = generate_cover_prompt(points, title_cn, args.cover_style)
    log_and_print(cover_prompt)
    log_and_print(f"\n[SAVE_AS] {project_assets}/cover.png")

    # 2. Scan for Infographic markers [AI_GEN_IMG: type | summary | facts | labels]
    inline_markers = re.findall(r'\[AI_GEN_IMG:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\]', content)
    infographic_tasks = []
    if inline_markers:
        log_and_print("\n" + "="*40)
        log_and_print(f"ASSETS: INLINE INFOGRAPHICS (信息图 - 共 {len(inline_markers)} 张) [Style: {args.info_style}]")
        log_and_print("="*40)
        for i, (l_type, summary, facts, labels) in enumerate(inline_markers, 1):
            filename = f"infographic_{i}.png"
            log_and_print(f"\n--- 图表 {i} ({filename}) ---")
            info_prompt = generate_infographic_prompt(l_type, summary, facts, labels, args.info_style)
            log_and_print(info_prompt)
            log_and_print(f"[SAVE_AS] {project_assets}/{filename}")
            infographic_tasks.append((filename, info_prompt))
    else:
        log_and_print("\n[INFO] 未在文中发现 [AI_GEN_IMG] 标记。")

    # 3. OPTIONAL: Direct Generation via 'baoyu-image-gen' Skill (16:9 宽屏)
    if args.gen_images:
        import subprocess
        print("\n🖼️  正在通过 'baoyu-image-gen' Skill (16:9) 生成图片资产...")

        # Skill path configuration
        skill_base = r"/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-image-gen"
        script_path = os.path.join(skill_base, "scripts", "main.ts")

        # Setup prompt directory
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(md_path)))
        prompt_dir = os.path.join(project_root, "prompts")
        if not os.path.exists(prompt_dir): os.makedirs(prompt_dir)

        client = get_client()

        # Helper to generate via skill CLI
        def handle_gen_skill(prompt, target_base, model_name=model_name):
            style_id = get_style_identity(args.cover_style)

            # 1. Refine prompt via LLM to get a high-quality DALL-E/Midjourney style English prompt
            refinement_prompt = f"""
            You are a senior AI prompt engineer for B2B industrial design.

            ### TASK:
            Translate AND refine the following visual description into a high-quality, precise English prompt for image generation (Gemini/DALL-E).

            ### CORE REQUIREMENT:
            - **Cultural Alignment**: The metaphor must remain faithful to the original Chinese context provided in the input.
            - **Labeling Logic & Length (CRITICAL)**:
                - If the input contains text labels (标注标签) in the '画面设计要求' section, you MUST translate them into **Simplified Chinese (简体中文)** in the final prompt if they are currently in English.
                - **Label Length & Noise Reduction (HIGH PRIORITY)**:
                    - Keep structural/node text labels extremely short (typically 2-4 Simplified Chinese characters each).
                    - If the input contains long phrases or questions (e.g. "为什么数据管道如此重要？" or "什么是..."), you MUST summarize or truncate them into short technical nouns (e.g. "技术重要性" or "五层架构" or simply "数据接入", "传输", "处理", "存储", "编排").
                    - The prompt must explicitly instruct the AI generator to render these specific Chinese characters at the logical nodes.
                    - Strictly avoid rendering long sentences, questions, or generic phrases inside diagram nodes or labels.

            ### VISUAL IDENTITY:
            {style_id}

            ### INPUT DESCRIPTION:
            {prompt}

            ### OUTPUT REQUIREMENTS:
            - Language: English (for the tool), but instruction for text *inside* the image MUST specify Simplified Chinese characters.
            - Visual Style: Must strictly adhere to the 'Industrial Amber Schematic' identity (Industrial blueprint, technical grid, negative space, amber/rust color palette).
            - Keywords: Isometric, schematic, blueprint, high-detail, technical drawing, professional, minimalist.
            - Result: Return ONLY the refined English prompt string. No conversational filler.
            """
            print(f"  [Skill] Refining prompt for {target_base} [Model: {model_name}]...")
            clean_en_prompt = client.generate_content(refinement_prompt, model_name=model_name)

            # Audit logging
            from common_utils import log_prompt
            log_prompt(None, f"04_visual_{target_base}", clean_en_prompt, project_root=project_root)

            # 2. Record prompt (this will be used as the source file for the skill)
            # Use project_root from outer scope
            prompt_filename = f"{target_base}_prompt.md"
            prompt_file_path = os.path.join(prompt_dir, prompt_filename)

            # Versioning: Backup existing prompt if it exists
            if os.path.exists(prompt_file_path):
                now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                bak_prompt = os.path.join(prompt_dir, f"{target_base}_prompt_bak_{now}.md")
                shutil.copy2(prompt_file_path, bak_prompt)

            with open(prompt_file_path, 'w', encoding='utf-8') as f:
                f.write(clean_en_prompt)

            # 3. Call skill via bun using --promptfiles for robustness
            target_path = os.path.join(project_assets, f"{target_base}.png")

            # Versioning: Backup existing image if it exists
            if os.path.exists(target_path):
                now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                bak_path = os.path.join(project_assets, f"{target_base}_bak_{now}.png")
                print(f"  📦 Backing up previous version to: {os.path.basename(bak_path)}")
                shutil.move(target_path, bak_path)

            print(f"  🎨 正在使用 --promptfiles 调用 baoyu-image-gen 绘制: {os.path.basename(target_path)} (16:9)...")

            # Resolve executable based on environment availability
            bun_path = shutil.which('bun')
            norm_script = os.path.normpath(script_path)
            norm_target = os.path.normpath(target_path)
            norm_prompt_file = os.path.normpath(prompt_file_path)

            # Enforce Vertex provider for all models as agreed
            provider = "vertex"
            target_model = args.image_model if args.image_model != "vertex" else None

            # Use --promptfiles instead of --prompt to avoid character escaping issues
            if bun_path:
                cmd = [bun_path, norm_script]
            else:
                npx_path = shutil.which('npx') or "npx"
                cmd = [npx_path, "-y", "bun", norm_script]

            cmd.extend([
                "--promptfiles", norm_prompt_file,
                "--image", norm_target,
                "--provider", provider,
                "--ar", "16:9",
                "--imageSize", "4K",
                "--quality", "2k"
            ])
            if target_model:
                cmd.extend(["--model", target_model])

            try:
                # Use list-style subprocess.run (shell=False) for maximum argument safety
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', cwd=os.path.dirname(md_path))
                if result.returncode == 0:
                    print(f"  ✅ Image saved: {target_path}")
                else:
                    print(f"  ❌ Skill execution failed for {target_base}. Return code: {result.returncode}")
                    print(f"     Out: {result.stdout[:200]}")
                    print(f"     Err: {result.stderr[:200]}")
            except Exception as e:
                print(f"  ❌ Exception during skill run: {e}")

        # Generate for Cover
        handle_gen_skill(cover_prompt, "cover", model_name=model_name)

        # Generate for Infographics
        for filename, prompt in infographic_tasks:
            # Strip extension for target_base
            base = os.path.splitext(filename)[0]
            handle_gen_skill(prompt, base, model_name=model_name)

    print(f"\n🚀 All image assets are documented in the 'prompts/' and 'assets/' directories.")

if __name__ == "__main__":
    main()
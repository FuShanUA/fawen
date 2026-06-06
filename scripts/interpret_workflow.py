"""
interpret_workflow.py [Postfdry 2.0 Workflow]

解读模式 (Interpretation Mode): Accurate translation followed by deep rewriting.
- Input: English Markdown
- Steps:
  1. Atomic Translation (Translator Skill)
  2. Atomic Rewriting (Rewriter Skill)
  3. Full-text Lead-in (Lead-in Agent)
  4. Visual Asset Prompts (Illustrator)
  5. Packaging & Publishing
"""

import os
import sys
import argparse
import re
import subprocess
import shutil
import pathlib
from datetime import datetime

# Correct path for agents and scripts
POSTFDRY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
agents_dir = os.path.join(POSTFDRY_ROOT, "agents")
scripts_dir = os.path.join(POSTFDRY_ROOT, "scripts")

for d in [scripts_dir, agents_dir]:
    if d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)

from common_utils import extract_clean_body, deterministic_scrub
import translator_agent
import rewriter_agent
import lead_in_agent
import illustrator
import extractor
import localizer_agent
import yaml
from common_utils import deterministic_scrub, load_style_guide, extract_clean_body

# Refined CSS Patch
CSS_PATCH = """<style>
    h1, .h1 { display: block !important; font-size: 2.2em; font-weight: 800; color: #1a1a1a; margin-bottom: 0.5em; line-height: 1.2; }
    blockquote { border-left: 4px solid #ddd !important; }
    .original-chart { margin: 2.5em auto; text-align: center; max-width: 95%; }
    .original-chart img { max-width: 100%; height: auto; border-radius: 12px; border: 1px solid #eee; }
    .chart-caption { font-size: 0.85em; color: #888; margin-top: 12px; font-weight: 500; letter-spacing: 0.5px; }
</style>"""

# Add agents to path (Hardened absolute path)
POSTFDRY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
agents_dir = os.path.join(POSTFDRY_ROOT, "agents")
if agents_dir not in sys.path:
    sys.path.insert(0, agents_dir)

try:
    import common_utils
    # print(f"DEBUG: Loaded common_utils from {common_utils.__file__}")
    from common_utils import deterministic_scrub, build_de_ai_protocol, log_prompt
except ImportError as e:
    print(f"DEBUG: Initial import failed: {e}. Attempting dynamic load...")
    import importlib.util
    spec = importlib.util.spec_from_file_location("common_utils", os.path.join(agents_dir, "common_utils.py"))
    common_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common_utils)
    deterministic_scrub = common_utils.deterministic_scrub
    build_de_ai_protocol = common_utils.build_de_ai_protocol
    log_prompt = common_utils.log_prompt

import translator_agent
import rewriter_agent
import lead_in_agent

def run_interpret_workflow(input_file, project_root=None, text_style="formal", cover_style="Industrial Amber", info_style="Industrial Amber", type_selection="trend", unslop_domain="中国政企特色数据治理", thoughts="", gen_images=False, model_name="gemini-3-flash-preview", image_model="vertex", target_title="", reuse_translation=False, localize_images=False, force_relocalize=False, non_interactive=False, summary_mode="preset", summary_prompt="", generate_summary=None, narrative_theme="", author=""):
    if generate_summary is not None:
        summary_mode = "explicit" if generate_summary else "none"
    if summary_mode == "preset":
        summary_mode = "explicit"
    elif summary_mode == "auto":
        summary_mode = "implicit"
    # Ensure project root is used for outputs
    project_root = project_root or os.path.dirname(input_file)
    output_dir = os.path.join(project_root, "output")
    wip_dir = os.path.join(project_root, "wip")

    import json
    config_path = os.path.join(wip_dir, "project_config.json")
    project_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                project_config = json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load project config: {e}")
    assets_dir = os.path.join(project_root, "assets")
    for d in [output_dir, wip_dir, assets_dir]:
        if not os.path.exists(d): os.makedirs(d)

    print(f"\n🚀 [Workflow] Starting INTERPRET MODE for: {os.path.basename(input_file)}")
    print(f"📍 Project Root: {project_root}")

    # 1. Atomic Translation (Draft only)
    print(f"  STEP 1: Atomic Translation (Draft only) [Style: {text_style}]...")

    # NEW: Interactive check for existing translation
    wip_translated = os.path.join(wip_dir, "translated.md")
    source_translated = input_file.replace(".md", "_translated.md")

    should_translate = True
    if os.path.exists(wip_translated) and os.path.getsize(wip_translated) > 200:
        if reuse_translation:
            print(f"      ♻️  自动复用现有翻译稿 (reuse_translation=True)。")
            translated_file = wip_translated
            should_translate = False
        else:
            print(f"  ⚠️  检测到已有翻译稿 (wip/translated.md)")
            ans = input(f"      是否重新翻译？ (重新翻译将保留原有版本) [y/N]: ").strip().lower()
            if ans != 'y':
                print(f"      ♻️  跳过翻译步骤，沿用现有翻译稿。")
                translated_file = wip_translated
                should_translate = False
            else:
                from common_utils import get_versioned_path
                bak_path = get_versioned_path(wip_translated)
                shutil.move(wip_translated, bak_path)
                print(f"      📦 已将旧版翻译备份至: {os.path.basename(bak_path)}")
    elif os.path.exists(source_translated) and os.path.getsize(source_translated) > 200:
        print(f"  ♻️  检测到源目录已有翻译稿 ({os.path.basename(source_translated)}), 自动同步并跳过翻译步骤...")
        shutil.copy2(source_translated, wip_translated)
        translated_file = wip_translated
        should_translate = False

    if should_translate:
        # Get the raw translated MD for the rewriter
        translated_file = translator_agent.run_atomic_translation(input_file, style=text_style, project_root=project_root, model_name=model_name)

    if not translated_file or not os.path.exists(translated_file):
        print("⚠️ Atomic Translation failed.")
        sys.exit(1)

    # Standardize translated file for rewriter internal use
    if translated_file != wip_translated:
        shutil.copy2(translated_file, wip_translated)
    translated_file = wip_translated

    # Load original metadata to get author/date (early resolution so it can be passed to rewriter and lead-in agents)
    from common_utils import MetadataEngine
    trans_meta = None
    trans_content = ""
    if os.path.exists(translated_file):
        try:
            with open(translated_file, 'r', encoding='utf-8') as f:
                trans_content = f.read()
            trans_meta = MetadataEngine(trans_content)
        except Exception as e:
            print(f"⚠️ Failed to load trans_meta: {e}")

    # Determine default author (always "数据治理研究院" as signature, no "前沿科技智库" creation)
    default_author = "数据治理研究院"

    # Resolve final author: parameter 'author' -> config 'author' -> trans_meta 'author' -> default_author
    author = author or project_config.get('author') or (trans_meta.get('author') if trans_meta else "") or default_author
    date = datetime.now().strftime('%Y-%m-%d')

    # 2. Atomic Rewriting
    project_slug = os.path.basename(project_root)
    dest_file = os.path.join(output_dir, f"{project_slug}.解读.md")

    should_rewrite = True
    should_repackage = True

    if os.path.exists(dest_file) and os.path.getsize(dest_file) > 100:
        if non_interactive:
            from common_utils import get_versioned_path
            bak_path = get_versioned_path(dest_file)
            shutil.move(dest_file, bak_path)
            print(f"      📦 [Non-Interactive] 已将旧版改写备份至: {os.path.basename(bak_path)}")
            should_rewrite = True
        else:
            print(f"  ⚠️  检测到已有改写稿 (interpreted.md)")
            print("      [y] 重新改写 (调用 AI)")
            print("      [p] 仅重新排版 (不调用 AI，只生成 HTML/PDF)")
            print("      [n] 彻底跳过 (直接结束)")
            ans = input(f"      请选择 [y/p/N]: ").strip().lower()

            if ans == 'y':
                from common_utils import get_versioned_path
                bak_path = get_versioned_path(dest_file)
                shutil.move(dest_file, bak_path)
                print(f"      📦 已将旧版改写备份至: {os.path.basename(bak_path)}")
            elif ans == 'p':
                print(f"      ♻️  跳过 AI 改写，仅执行排版组装...")
                rewritten_file = dest_file
                should_rewrite = False
            else:
                print(f"      ⏩ 彻底跳过解读流程。")
                return dest_file # Early Exit

    if should_rewrite:
        print(f"  STEP 2: Market-oriented Rewriting (Rewriter Skill as '{type_selection}') [Style: {text_style}]...")

        # CLEANUP: Strip all translation headers/covers before rewrite
        # 2. Atomic Rewriting (Deep Interpretation)
        print(f"  [Skill] Atomic Rewriting (Deep Interpretation) [Type: {type_selection}]...")
        rewritten_file = rewriter_agent.run(
            translated_file,
            project_root=project_root,
            style=type_selection,
            unslop_domain=unslop_domain,
            thoughts=thoughts,
            target_title=target_title,
            model_name=model_name,
            summary_mode=summary_mode,
            summary_prompt=summary_prompt,
            generate_summary=generate_summary,
            narrative_theme=narrative_theme,
            author=author
        )

        # Move to output/
        if os.path.exists(rewritten_file):
            shutil.move(rewritten_file, dest_file)
            rewritten_file = dest_file

    with open(rewritten_file, 'r', encoding='utf-8') as f:
        rewritten_raw = f.read()

    # Ensure rewritten text is ALSO clean (sometimes LLMs add their own hulls)
    rewritten_text = extract_clean_body(rewritten_raw)

    # 3. Lead-in Generation (Full Text of Rewritten Article)
    lead_in_md = ""
    if not should_rewrite:
        # Try to extract existing lead-in from the file
        print(f"  STEP 3: Attempting to extract existing Lead-in from {os.path.basename(dest_file)}...")
        # Lead-in is usually between the cover marker and the horizontal rule
        lead_match = re.search(r'>\s*\*\*导读：\*\*(.*?)(?:\n\s*---|(?:\r?\n){2,})', rewritten_raw, re.DOTALL | re.IGNORECASE)
        if lead_match:
            lead_in_md = f"> **导读：**{lead_match.group(1).strip()}"
            print(f"      ♻️  成功复用现有导读内容。")
        else:
            print(f"      ⚠️  未能提取到现有导读，将重新生成...")

    if not lead_in_md:
        print(f"  STEP 3: Synthesizing Lead-in (Lead-in Agent)...")
        lead_in_md = lead_in_agent.generate_lead_in(rewritten_text, thoughts, project_root=project_root, model_name=model_name, type_selection=type_selection, narrative_theme=narrative_theme, author=author)

    # 4. Packaging Layout (NEW: Title at top, NO YAML in body, Default Author)
    print(f"  STEP 4: Packaging article with NEW layout (H1 + Author)...")

    # 1. First check if rewriter output has any heading as title
    title = target_title or "无标题"
    # Find any heading at the very beginning that looks like a title (up to 3 hashes)
    h_match = re.search(r'^#{1,3}\s*(.*)$', rewritten_raw, re.MULTILINE)
    if h_match:
        # NEW: Clean up leading hashes from the subgroup to avoid "# ##" issues
        if not target_title:
            title = re.sub(r'^#+\s*', '', h_match.group(1)).strip()
        # Clean the title line from body
        body = re.sub(r'^#{1,3}\s*.*$\n*', '', rewritten_raw, count=1, flags=re.MULTILINE).strip()
    else:
        # Check if rewriter sent YAML (leaked)
        meta_match = re.search(r'^---\s*(.*?)\s*---', rewritten_raw, re.DOTALL)
        if meta_match:
            try:
                fm = yaml.safe_load(meta_match.group(1))
                if not target_title:
                    title = fm.get('title', title)
                body = (rewritten_raw[:meta_match.start()] + rewritten_raw[meta_match.end():]).strip()
            except:
                body = rewritten_raw
        else:
            body = rewritten_raw

    # NEW: Aggressive Body Cleaning for re-runs (Prevent Stacking)
    # 1. Strip previous H1 + Author
    body = re.sub(r'^#\s+.*?\n+\s*-\s*作者：.*?\n+', '', body, flags=re.DOTALL | re.MULTILINE)

    # 2. Strip any leading images (Original Cover Displacement)
    # If the body starts with an image before any H2, we strip it to make room for our styled cover
    body = re.sub(r'^\s*(!\[.*?\]\(.*?\)|<img.*?>)\s*', '', body, count=1, flags=re.IGNORECASE | re.DOTALL)

    # 3. Strip other placeholders
    body = re.sub(r'^\s*(!\[Cover\].*?|\[ARTICLE_COVER_HERE\]).*?\n+', '', body, flags=re.IGNORECASE)
    # Strip any existing lead-in blocks
    body = re.sub(r'>\s*\*\*导读：\*\*.*?(\n---|\n#|$)', '', body, flags=re.DOTALL | re.IGNORECASE)
    # Strip leading/trailing horizontal rules and meta blocks
    body = re.sub(r'^---\s*.*?\s*---\s*', '', body, flags=re.DOTALL | re.MULTILINE)
    body = re.sub(r'^---\s*', '', body, flags=re.MULTILINE)

    body = body.strip()

    # Metadata Cleanup: Remove residual Key-Value metadata leaking into body
    body = re.sub(r'^- 作者：.*$\n*', '', body, flags=re.MULTILINE).strip()
    body = re.sub(r'^```yaml\s*.*?\s*```', '', body, flags=re.DOTALL | re.MULTILINE | re.IGNORECASE).strip()
    body = re.sub(r'^(?:Title|Author|Date|Publish_Date|Published_Date|Source|EngTitle|Url)\s*[:：]\s*.*$', '', body, flags=re.MULTILINE | re.IGNORECASE)
    body = body.strip()

    # EXTRACT COVER PLACEHOLDER FROM BODY (Look for COVER_METAPHOR)
    cover_marker = "[AI_GEN_IMG: COVER_METAPHOR | 封面图自动生成]"
    cover_match = re.search(r'\[AI_GEN_IMG:\s*COVER_METAPHOR\s*\|.*?\]', body, re.IGNORECASE)
    if cover_match:
        cover_marker = cover_match.group(0)
        # Remove it from body to avoid duplicates
        body = (body[:cover_match.start()] + body[cover_match.end():]).strip()

    # REBUILD BODY with Title and Author at top
    # Final Structure: Header + Cover + LeadIn + Body
    header_part = f"# {title}\n\n- 作者：{author}\n\n"

    final_content_md = f"{header_part}\n\n{cover_marker}\n\n{lead_in_md}\n\n---\n\n{body}"

    # Metadata Cleanup: STRIP ALL broken characters for meta description
    short_desc = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', lead_in_md).strip()[:150].replace('\n', ' ').replace('\r', ' ') + "..."

    # Save a hidden meta block for system tracking at the VERY TOP
    meta_block = f"---\ntitle: {title}\nauthor: {author}\ndate: {date}\ndescription: {short_desc}\ncover: ../assets/cover.png\n---"
    final_body = f"{meta_block}\n\n{final_content_md}"

    # Load original metadata to generate standard filename YYYYMMDD_Author，Source_ChineseTitle.解读
    from common_utils import generate_standard_filename, get_versioned_path, MetadataEngine
    # Re-parse if not already done, though it should be
    if 'trans_meta' not in locals() or trans_meta is None:
        try:
            with open(translated_file, 'r', encoding='utf-8') as f:
                trans_content = f.read()
            trans_meta = MetadataEngine(trans_content)
        except:
            trans_meta = None

    meta_for_name = {
        'date': project_config.get('date') or (trans_meta.get('date') or trans_meta.get('publish_date') if trans_meta else None),
        'author': project_config.get('author') or (trans_meta.get('author') if trans_meta else None),
        'source': project_config.get('source') or (trans_meta.get('source') if trans_meta else None),
        'title': title
    }
    standard_name = generate_standard_filename(meta_for_name, mode="解读")
    base_dest_path = os.path.join(output_dir, f"{standard_name}.md")
    final_dest_path = get_versioned_path(base_dest_path)

    # Clean up temporary non-standard rewritten file
    if os.path.exists(rewritten_file) and rewritten_file != final_dest_path:
        try: os.remove(rewritten_file)
        except: pass

    rewritten_file = final_dest_path
    with open(rewritten_file, 'w', encoding='utf-8') as f:
        f.write(final_body)

    # 5. Illustrator (Cover + Infographics Prompts) - Runs on placeholders
    print(f"  STEP 5: Generating Visual Prompts (Illustrator)...")
    illustrator_path = os.path.join(os.path.dirname(__file__), "illustrator.py")
    cmd = [
        sys.executable, illustrator_path, rewritten_file,
        "--assets", assets_dir,
        "--cover-style", cover_style,
        "--info-style", info_style,
        "--model", model_name,
        "--image-model", image_model
    ]
    if gen_images: cmd.append("--gen-images")

    subprocess.run(cmd, check=True)

    # [POST-ILLUSTRATOR] If cover.png was NOT generated (gen_images=False), substitute with first original image
    cover_png = os.path.join(assets_dir, "cover.png")
    if not os.path.exists(cover_png):
        orig_dir = os.path.join(assets_dir, "original")
        fallback_cover = None
        if os.path.exists(orig_dir):
            # Pick first image file that looks like an article image (not author/thumbnail)
            candidates = sorted([
                f for f in os.listdir(orig_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                and not any(skip in f.lower() for skip in ['author', 'thumblarge', 'avatar', 'logo'])
            ])
            if candidates:
                fallback_cover = os.path.join(orig_dir, candidates[0])
        if fallback_cover:
            import shutil as _shutil
            _shutil.copy2(fallback_cover, cover_png)
            print(f"  [Cover Fallback] cover.png not generated, using: {os.path.basename(fallback_cover)}")
        else:
            print(f"  [Cover Fallback] No suitable fallback found — cover.png will be absent.")

    # 7. Final Polish: interpreted.md is already in output/
    # Ensure asset paths are relative to output/ (i.e., ../assets/)
    asset_rel_path = "../assets"

    with open(rewritten_file, 'r', encoding='utf-8') as f:
        final_content = f.read()

    # 7.1 Replace placeholders
    img_counter = 1
    def marker_replacer(match):
        nonlocal img_counter
        content = match.group(0)
        if "COVER_METAPHOR" in content:
            if os.path.exists(os.path.join(assets_dir, "cover.png")):
                return f"![Cover]({asset_rel_path}/cover.png)"
            return ""
        else:
            filename = f"infographic_{img_counter}.png"
            if os.path.exists(os.path.join(assets_dir, filename)):
                tag = f"![Infographic {img_counter}]({asset_rel_path}/{filename})"
                img_counter += 1
                return tag
            img_counter += 1
            return ""

    # Updated regex for 4-field markers and optional AI-generated trailing bracket junk
    final_content = re.sub(r'\[AI_GEN_IMG:.*?\](?:\s*[,，]?\s*\[\s*[^\]]+?\]+\s*)?', marker_replacer, final_content)

    # 7.2 Asset Materializer: Final check for remote images to download them to assets/original
    print(f"  STEP 7.2: Materializing all referenced images...")

    # Simple regex to find all images
    all_imgs = re.findall(r'!\[.*?\]\((https?://.*?)\)', final_content)
    if all_imgs:
        orig_dir = os.path.join(assets_dir, "original")
        if not os.path.exists(orig_dir): os.makedirs(orig_dir)
        for img_url in all_imgs:
            print(f"    - Downloading remote image: {img_url[:60]}...")
            local_name = extractor.download_image(img_url, orig_dir)
            if local_name:
                # Replace remote URL with local assets/original path
                final_content = final_content.replace(img_url, f"../assets/original/{local_name}")
    # 7.2.5 自动图表汉化 (Infographic Localization) - Only if requested
    localized_map = {}
    if localize_images:
        print(f"  STEP 7.2.5: 正在对所有引用图表执行同构汉化...")
        localized_map = localizer_agent.run_batch_localization(project_root, model_name=model_name, force=force_relocalize)
    else:
        print(f"  STEP 7.2.5: ⏩ 跳过图表汉化 (根据配置要求)")

    if localized_map:
        for orig_img, loc_img in localized_map.items():
            old_path = f"../assets/original/{orig_img}"
            new_path = f"../assets/localized/{loc_img}"
            final_content = final_content.replace(old_path, new_path)
            print(f"    ✨ 已替换汉化图: {orig_img} -> {loc_img}")

    # 7.3 Convert Markdown Images to HTML for professional rendering with robustness check
    def img_replacer(match):
        alt = match.group(1).strip()
        path = match.group(2)
        # Robustly check if it's an asset path
        normalized_path = path.replace('\\', '/')

        # Style ALL project assets (cover, infographics, original/localized source images)
        if "assets/" in normalized_path:
            # [CRITICAL] Final safety check: if the image doesn't exist on disk, comment it out
            # Path might be relative (../assets/...) or absolute (file:///...)
            # We try to resolve it relative to the project root
            clean_rel_path = re.sub(r'^.*?assets/', 'assets/', normalized_path)
            abs_path = os.path.join(project_root, clean_rel_path)

            if not os.path.exists(abs_path):
                print(f"  [WARN] Image asset missing on disk: {clean_rel_path}. Commenting out to prevent broken link.")
                return f"<!-- Asset Missing: {clean_rel_path} -->"

            # Skip redundant captions for decorative/structural images
            caption_html = ""
            is_generic = alt.lower() in ["image", "img", "chart", "[image]", "图片", "图表", "cover"]
            if not is_generic and not alt.startswith("Infographic") and not alt.startswith("Cover"):
                caption_html = f'\n  <p class="chart-caption">{alt}</p>'

            # Ensure src uses forward slashes
            return f'\n<div class="original-chart">\n  <img src="{normalized_path}" alt="{alt}">{caption_html}\n</div>\n'
        return match.group(0)

    # Strip outer markdown links surrounding images to prevent broken brackets
    final_content = re.sub(r'\[\s*(!\[.*?\]\(.*?\))\s*\]\(.*?\)', r'\1', final_content)

    final_content = re.sub(r'!\[(.*?)\]\((.*?)\)', img_replacer, final_content)

    with open(rewritten_file, 'w', encoding='utf-8') as f:
        f.write(final_content)
    # 8. HTML Conversion in output
    print(f"  STEP 8: Generating professional Interpreted HTML in output/...")
    html_file = generate_html(rewritten_file, keep_title=True)

    # Inject CSS fix to HTML:
    # 1. Hide default numbering (1. 1. fix)
    if html_file and os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # DESTRUCTIVE BUT ROBUST HEAD CORRECTION
        # The underlying tool has bugs in meta-description extraction that break the <head>
        new_head = f"""<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="author" content="{author}">
  <meta name="description" content="{short_desc}">
  {CSS_PATCH}
</head>"""
        # Replace everything from <head> to <body> with our clean version
        html_content = re.sub(r'<head>.*?</head>', new_head, html_content, flags=re.DOTALL | re.IGNORECASE)
        # Also cleanup some themes that put divs in head or before head
        html_content = re.sub(r'</title>.*?(?=<head>|<body>)', f'</title>\n  {CSS_PATCH}\n', html_content, flags=re.DOTALL | re.IGNORECASE)

        # Ensure no weird leakage from the previous broken description
        html_content = re.sub(r'<!doctype.*?>.*?<body', f'<!doctype html>\n<html>\n{new_head}\n<body', html_content, count=1, flags=re.DOTALL | re.IGNORECASE)

        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    # STEP 9: PDF Generation (Disabled per User Request)
    print(f"  STEP 9: PDF Generation explicitly disabled for Interpretation mode.")

    print(f"\n✅ [Workflow] INTERPRET COMPLETE: {os.path.basename(rewritten_file)}")
    return rewritten_file

def generate_html(markdown_file, keep_title=False):
    """Call the baoyu-markdown-to-html tool via local integration."""
    html_skill_dir = r"/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-markdown-to-html"
    main_ts = os.path.join(html_skill_dir, "scripts", "main.ts")

    if not os.path.exists(main_ts):
        print(f"Warning: HTML generator tool skip: {main_ts} not found.")
        return None

    # Robust Fix: Create a clean MD without frontmatter for the tool to avoid metadata leakage bugs
    if markdown_file.endswith(".md"):
        clean_md = markdown_file[:-3] + ".clean.md"
    else:
        clean_md = markdown_file + ".clean.md"
    with open(markdown_file, "r", encoding="utf-8") as f:
        md_content = f.read()

    # Strip frontmatter (Anchored to the very start of the string)
    md_no_fm = re.sub(r'\A---\s*.*?\s*---\s*', '', md_content, flags=re.DOTALL)

    # [FIX] Keep asset paths as-is — relative paths work correctly for both
    # local HTML preview and wechat-api upload (baseDir resolution).
    # Do NOT convert to file:// URIs — wechat-api cannot handle them.
    project_root = pathlib.Path(markdown_file).parent.parent
    def make_abs(match):
        alt = match.group(1)
        rel = match.group(2)
        # Keep ../assets paths as relative — they resolve correctly from output/
        return match.group(0)

    md_no_fm = re.sub(r'!\[(.*?)\]\((.*?)\)', make_abs, md_no_fm)

    with open(clean_md, "w", encoding="utf-8") as f:
        f.write(md_no_fm)

    # Redirect output to same directory as md
    html_cmd = ["npx", "-y", "bun", main_ts, clean_md, "--theme", "grace"]
    if keep_title:
        html_cmd.append("--keep-title")

    try:
        subprocess.run(html_cmd, check=True, capture_output=True, shell=False)
        root_html = clean_md.replace(".md", ".html")
        final_html = markdown_file.replace(".md", ".html")
        if os.path.exists(root_html):
            if os.path.exists(final_html): os.remove(final_html)
            os.rename(root_html, final_html)
            try: os.remove(clean_md)
            except: pass
            print(f"📍 HTML generated at: {final_html}")
            return final_html
    except Exception as e:
        print(f"⚠️ HTML conversion failed for {markdown_file}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Postfdry 2.0 Interpretation Workflow")
    parser.add_argument("input", help="Source Markdown file")
    parser.add_argument("--project-root", help="Project root directory")
    parser.add_argument("--text-style", default="formal", help="Translation style")
    parser.add_argument("--cover-style", default="Industrial Amber", help="Cover visual style")
    parser.add_argument("--info-style", default="Industrial Amber", help="Infographic visual style")
    parser.add_argument("--type", default="trend", choices=["paper", "trend", "policy", "product", "standard"], help="Article type")
    parser.add_argument("--unslop", default="中国政企特色数据治理", help="Unslop domain domain")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="LLM model name")
    parser.add_argument("--image-model", type=str, default="vertex", help="Image generation model/engine")
    parser.add_argument("--thoughts", default="", help="Editor thoughts/instructions")
    parser.add_argument("--target-title", default="", help="Forced title for the article")
    parser.add_argument("--gen-images", action="store_true", help="Generate actual images via Gemini API")
    parser.add_argument("--localize-images", action="store_true", help="Enable visual localization")
    parser.add_argument("--force-relocalize", action="store_true", help="Force generating new versions of localized images")
    parser.add_argument("--no-spawn", action="store_true", help="Suppress new PowerShell window spawning")
    parser.add_argument("--reuse-translation", action="store_true", help="Automatically reuse existing translation in wip/ without asking")
    parser.add_argument("--non-interactive", action="store_true", help="Non-interactive mode")
    parser.add_argument("--skip-summary", action="store_true", help="Skip generating summary ending")
    parser.add_argument("--summary-mode", default="explicit", choices=["explicit", "implicit", "none", "preset", "auto"], help="Summary generation mode")
    parser.add_argument("--summary-prompt", default="", help="Prompt for preset summary mode")
    parser.add_argument("--narrative-theme", default="", help="Narrative/business theme keywords")
    parser.add_argument("--author", default="", help="Author signature override")
    parser.add_argument("--internal-run", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # 0. Handle spawning a new window (Windows/PowerShell specific)
    if os.name == 'nt' and not args.no_spawn and not args.internal_run:
        print("🚩 正在启动新终端进行独立执行 (Interpret Mode)...")
        new_argv = sys.argv + ["--internal-run"]
        new_argv[0] = os.path.abspath(new_argv[0])
        def quote_ps(arg):
            if re.match(r'^[a-zA-Z0-9_\-\./:]+$', arg) and not arg.startswith('http'):
                return arg
            # Replace inner double quotes with escaped quotes for PowerShell
            safe_arg = str(arg).replace('"', '`"')
            return f'"{safe_arg}"'

        cmd_str = f'& "{sys.executable}" ' + ' '.join([quote_ps(a) for a in new_argv])
        import base64
        encoded_cmd = base64.b64encode(cmd_str.encode('utf-16-le')).decode('utf-8')
        spawn_cmd = ["powershell.exe", "-NoProfile", "-Command", f"Start-Process powershell.exe -ArgumentList '-NoExit', '-EncodedCommand', '{encoded_cmd}'"]
        subprocess.Popen(spawn_cmd)
        sys.exit(0)

    sum_mode = args.summary_mode
    if args.skip_summary:
        sum_mode = "none"

    run_interpret_workflow(
        args.input,
        project_root=args.project_root,
        text_style=args.text_style,
        cover_style=args.cover_style,
        info_style=args.info_style,
        type_selection=args.type,
        unslop_domain=args.unslop,
        thoughts=args.thoughts,
        gen_images=args.gen_images,
        model_name=args.model,
        image_model=args.image_model,
        target_title=args.target_title,
        reuse_translation=args.reuse_translation,
        localize_images=args.localize_images,
        force_relocalize=args.force_relocalize,
        non_interactive=args.non_interactive,
        summary_mode=sum_mode,
        summary_prompt=args.summary_prompt,
        narrative_theme=args.narrative_theme,
        author=args.author
    )

    # FINAL CLEANUP: Remove .bak files from project output
    if args.project_root:
        import glob
        output_dir = os.path.join(args.project_root, "output")
        for bak in glob.glob(os.path.join(output_dir, "*.bak-*")):
            try: os.remove(bak)
            except: pass
        print(f"Cleaned up redundant backups in {output_dir}")
import os
import sys
import argparse
import subprocess
import re
import shutil
import time
from datetime import datetime

# macOS desktop environment PATH bootstrap
if sys.platform == "darwin":
    extra_paths = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.npm-global/bin")
    ]
    current_path = os.environ.get("PATH", "")
    all_paths = extra_paths + current_path.split(os.pathsep) if current_path else extra_paths
    seen = set()
    clean_paths = []
    for p in all_paths:
        if p not in seen:
            seen.add(p)
            clean_paths.append(p)
    os.environ["PATH"] = os.path.pathsep.join(clean_paths)

# Correct path for agents and scripts
POSTFDRY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Standalone fallback support: use local common directory if present, otherwise fallback to project-wide common
local_common = os.path.abspath(os.path.join(POSTFDRY_ROOT, "common"))
common_dir = local_common if os.path.exists(local_common) else os.path.abspath(os.path.join(POSTFDRY_ROOT, "..", "common"))

# Ensure agents and scripts are at the front of sys.path to take import priority over common_dir
for d in [common_dir, os.path.join(POSTFDRY_ROOT, "scripts"), os.path.join(POSTFDRY_ROOT, "agents")]:
    if d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)

import crawler_agent
from common_utils import MetadataEngine, deterministic_scrub

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def bootstrap_model_selection(default_model="gemini-3-flash-preview"):
    """Quick model selection at the very start to avoid unconfigured AI calls."""
    clear_screen()
    print("="*60)
    print(" 🤖 POSTFDRY 智力引擎预设 (LLM Bootstrap)")
    print("="*60)
    print(" 系统准备开始解析/抓取文章，请先选择要调用的智力引擎：")
    print("-" * 60)

    available_models = ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-2.0-flash-exp"]

    for i, m in enumerate(available_models, 1):
        label = f" [{i}] {m}"
        if m == default_model: label += " (推荐/默认 ✨)"
        print(label)

    choice = input(f"\n 请选择模型 [1-{len(available_models)}, 默认 1]: ").strip() or "1"
    try:
        return available_models[int(choice)-1]
    except:
        return default_model

class ProjectManager:
    def __init__(self, input_path):
        self.input_path = input_path
        self.project_root = None
        self.source_dir = None
        self.wip_dir = None
        self.output_dir = None
        self.assets_dir = None
        self.config_path = None

    def _slugify(self, text):
        # Basic slugify for directory names
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_-]+', '_', text).strip('_')
        return text[:50]

    def rename_project_if_needed(self, new_title):
        """Renames the project root directory based on a new title if it differs."""
        if not new_title:
            return self.project_root, os.path.join(self.source_dir, "source.md")

        new_name = self._slugify(new_title)
        if not new_name or new_name in ["untitled", "untitled_article", "untitled-article", "web-project", "web_project"]:
            return self.project_root, os.path.join(self.source_dir, "source.md")

        # Get projects_base from parent of project_root
        projects_base = os.path.dirname(os.path.abspath(self.project_root))
        current_name = os.path.basename(os.path.abspath(self.project_root))

        if new_name != current_name:
            new_root = os.path.abspath(os.path.join(projects_base, new_name))
            
            # Avoid overwriting if new_root already exists and is not empty
            if os.path.exists(new_root):
                has_files = False
                for r, d, files in os.walk(new_root):
                    if files:
                        has_files = True
                        break
                if has_files:
                    print(f"⚠️ 目标目录已存在且包含文件: {new_root}，跳过重命名。")
                    return self.project_root, os.path.join(self.source_dir, "source.md")
                else:
                    print(f"ℹ️ 目标目录已存在但无实际内容，正在删除并准备重命名: {new_root}")
                    try:
                        shutil.rmtree(new_root)
                    except Exception as e:
                        print(f"⚠️ 无法清除空的历史目录: {e}")

            print(f"🔄 正在重命名项目目录: {self.project_root} -> {new_root}")
            try:
                # If target exists but is empty, remove it first
                if os.path.exists(new_root):
                    os.rmdir(new_root)
                
                shutil.move(self.project_root, new_root)
                
                # Update path properties
                self.project_root = new_root
                self.source_dir = os.path.join(self.project_root, "source")
                self.wip_dir = os.path.join(self.project_root, "wip")
                self.output_dir = os.path.join(self.project_root, "output")
                self.assets_dir = os.path.join(self.project_root, "assets")
                self.config_path = os.path.join(self.wip_dir, "project_config.json")
            except Exception as e:
                print(f"❌ 重命名目录失败: {e}")
        return self.project_root, os.path.join(self.source_dir, "source.md")

    def init_project(self):
        """Identifies project paths and creates structure (No AI/Crawling yet)."""
        # 1. Initial Sniff to get a folder name
        if self.input_path.startswith(('http://', 'https://')):
            print(f"🌐 正在初步分析 URL: {self.input_path}...")
            # Use sniff_metadata for a quick title check (Lightweight, no AI)
            metadata = crawler_agent.sniff_metadata(self.input_path)
            title = metadata.get('title', 'Untitled_Article')
            slug = self._slugify(title)
            self.expected_eng_title = title
        else:
            # Local file
            ext = os.path.splitext(self.input_path)[1].lower()
            if ext in ['.html', '.htm']:
                metadata = crawler_agent.sniff_metadata(self.input_path)
                title = metadata.get('title', '')
                if not title:
                    title = os.path.splitext(os.path.basename(self.input_path))[0]
            elif ext in ['.txt', '.md']:
                title = os.path.basename(self.input_path).replace('.md', '')
                if os.path.exists(self.input_path):
                    # Try to extract title from YAML if local file
                    try:
                        with open(self.input_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        meta_eng = MetadataEngine(content)
                        title = meta_eng.get('title', title)
                    except: pass
            else:
                title = os.path.splitext(os.path.basename(self.input_path))[0]
            
            slug = self._slugify(title)
            self.expected_eng_title = title

        # 2. Setup Directories (dynamic base projects dir)
        if "PostOS_2.0_Standalone" in POSTFDRY_ROOT:
            base_projects_dir = os.path.join(POSTFDRY_ROOT, "Projects")
        else:
            base_projects_dir = r"/Users/shanfu/cc/Projects"

        # Check if we are already in an existing project structure
        input_abs = os.path.abspath(self.input_path)
        if input_abs.startswith(base_projects_dir):
            current_parent = os.path.dirname(input_abs)
            while current_parent and current_parent != base_projects_dir and current_parent != os.path.dirname(base_projects_dir):
                if os.path.exists(os.path.join(current_parent, "source")) or os.path.exists(os.path.join(current_parent, "wip")):
                    self.project_root = current_parent
                    print(f"📁 检测到已有项目结构，沿用根目录: {self.project_root}")
                    break
                current_parent = os.path.dirname(current_parent)

        # 1.5 Smart scan for renamed folders to map URL/Local File to renamed Projects/<folder>
        if not self.project_root and os.path.exists(base_projects_dir):
            import json
            target_path_abs = os.path.abspath(self.input_path)
            for folder in os.listdir(base_projects_dir):
                folder_path = os.path.join(base_projects_dir, folder)
                if os.path.isdir(folder_path):
                    # Check source/source.md first
                    source_md_path = os.path.join(folder_path, "source", "source.md")
                    if os.path.exists(source_md_path):
                        try:
                            with open(source_md_path, "r", encoding="utf-8") as sf:
                                sf_content = sf.read()
                            meta_eng = MetadataEngine(sf_content)
                            
                            # Check URL mapping
                            if self.input_path.startswith(("http://", "https://")):
                                existing_url = meta_eng.get("url")
                                if existing_url and existing_url.strip() == self.input_path.strip():
                                    self.project_root = folder_path
                                    self.matched_by_precise_key = True
                                    print(f"✨ [URL Mapping] 发现已匹配此 URL 的历史项目文件夹: {self.project_root}")
                                    break
                            
                            # Check Local File mapping
                            else:
                                orig_path = meta_eng.get("original_path")
                                if orig_path and os.path.abspath(orig_path) == target_path_abs:
                                    self.project_root = folder_path
                                    self.matched_by_precise_key = True
                                    print(f"✨ [Local File Mapping] 发现已匹配此本地文件的历史项目文件夹: {self.project_root}")
                                    break
                                
                                # Fallback: Check title match
                                existing_eng_title = meta_eng.get("eng_title") or meta_eng.get("title")
                                if existing_eng_title:
                                    new_title_clean = re.sub(r"[^a-zA-Z0-9]", "", self.expected_eng_title).lower()
                                    old_title_clean = re.sub(r"[^a-zA-Z0-9]", "", existing_eng_title).lower()
                                    if new_title_clean and new_title_clean == old_title_clean:
                                        self.project_root = folder_path
                                        print(f"✨ [Title Mapping] 发现匹配相同英文/原文标题的历史项目文件夹: {self.project_root}")
                                        break
                        except Exception as e:
                            pass
                    
                    # Fallback: check project_config.json
                    if not self.project_root:
                        config_json_path = os.path.join(folder_path, "wip", "project_config.json")
                        if os.path.exists(config_json_path):
                            try:
                                with open(config_json_path, "r", encoding="utf-8") as jf:
                                    cfg_data = json.load(jf)
                                if self.input_path.startswith(("http://", "https://")):
                                    if cfg_data.get("url") and cfg_data.get("url").strip() == self.input_path.strip():
                                        self.project_root = folder_path
                                        self.matched_by_precise_key = True
                                        print(f"✨ [URL Mapping via Config] 发现已匹配此 URL 的历史项目文件夹: {self.project_root}")
                                        break
                                else:
                                    orig_path = cfg_data.get("original_path")
                                    if orig_path and os.path.abspath(orig_path) == target_path_abs:
                                        self.project_root = folder_path
                                        self.matched_by_precise_key = True
                                        print(f"✨ [Local File Mapping via Config] 发现已匹配此本地文件的历史项目文件夹: {self.project_root}")
                                        break
                            except:
                                pass

        if not self.project_root:
            self.project_root = os.path.join(base_projects_dir, slug)

        self.source_dir = os.path.join(self.project_root, "source")
        self.wip_dir = os.path.join(self.project_root, "wip")
        self.output_dir = os.path.join(self.project_root, "output")
        self.assets_dir = os.path.join(self.project_root, "assets")
        self.config_path = os.path.join(self.wip_dir, "project_config.json")

        # Smart Check: If source.md already exists, check if English title matches
        source_file = os.path.join(self.source_dir, "source.md")
        if os.path.exists(source_file) and os.path.getsize(source_file) > 100:
            if getattr(self, "matched_by_precise_key", False):
                print(f"ℹ️  [Smart Check] 精确匹配成功，直接沿用现有项目结构，免除元数据强校验。")
            else:
                try:
                    with open(source_file, 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                    meta_eng = MetadataEngine(existing_content)
                    existing_eng_title = meta_eng.get('eng_title') or meta_eng.get('title')
                    if existing_eng_title:
                        # Avoid trigger if expected title is a generic placeholder due to sniff/network failure
                        new_clean = re.sub(r'[^a-zA-Z0-9]', '', self.expected_eng_title).lower()
                        if new_clean and new_clean not in ["untitledarticle", "untitled", ""]:
                            new_title_clean = new_clean
                            old_title_clean = re.sub(r'[^a-zA-Z0-9]', '', existing_eng_title).lower()
                            if new_title_clean != old_title_clean:
                                print(f"⚠️  [Smart Check] 检测到已有源文件元数据英文标题 '{existing_eng_title}' 与当前期望标题 '{self.expected_eng_title}' 不匹配！正在清空项目目录进行重新初始化...")
                                # Delete folders and config
                                for path in [self.source_dir, self.wip_dir, self.output_dir, self.assets_dir]:
                                    if os.path.exists(path):
                                        shutil.rmtree(path, ignore_errors=True)
                                if os.path.exists(self.config_path):
                                    try: os.remove(self.config_path)
                                    except: pass
                except Exception as e:
                    print(f"⚠️  [Smart Check] 元数据校验异常: {e}")

        for d in [self.source_dir, self.wip_dir, self.output_dir, self.assets_dir]:
            if not os.path.exists(d): os.makedirs(d)

        source_file = os.path.join(self.source_dir, "source.md")
        return self.project_root, source_file

    def materialize_source(self, model_name="gemini-3-flash-preview"):
        """Performs the actual crawling and AI refinement."""
        source_file = os.path.join(self.source_dir, "source.md")
        is_html = self.input_path.lower().endswith('.html') or self.input_path.lower().endswith('.htm')
        is_pdf = self.input_path.lower().endswith('.pdf')
        if self.input_path.startswith(('http://', 'https://')) or is_html or is_pdf:
            if os.path.exists(source_file) and os.path.getsize(source_file) > 100:
                print(f"ℹ️  [Smart Check] 源文件已存在且非空，跳过重新抓取以保留修改后的元数据。")
            else:
                print(f"🚀 正在抓取并利用 AI 优化原文内容...")
                crawler_agent.run(self.input_path, output_file=source_file, model_name=model_name)
        else:
            if os.path.abspath(self.input_path) != os.path.abspath(source_file):
                print(f"📂 正在同步本地文件到项目目录...")
                shutil.copy2(self.input_path, source_file)
                # Write original_path to source.md frontmatter!
                try:
                    with open(source_file, "r", encoding="utf-8") as f:
                        sf_content = f.read()
                    from common_utils import MetadataEngine
                    meta_eng = MetadataEngine(sf_content)
                    clean_body = meta_eng.clean_body(sf_content, keep_cover=True)
                    new_yaml = dict(meta_eng.raw_meta)
                    new_yaml["original_path"] = os.path.abspath(self.input_path)
                    import yaml
                    yaml_block = f"---\n{yaml.dump(new_yaml, allow_unicode=True)}---\n\n"
                    with open(source_file, "w", encoding="utf-8") as f:
                        f.write(yaml_block + clean_body)
                except Exception as e:
                    print(f"⚠️ Failed to write original_path metadata: {e}")
        return source_file

    def save_config(self, config):
        import json
        existing = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except: pass
        existing.update(config)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)

    def load_config(self):
        import json
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

class OnboardingAssistant:
    def __init__(self, source_file, model_name="gemini-3-flash-preview", narrative_theme=None):
        self.source_file = source_file
        self.model_name = model_name
        self.narrative_theme = narrative_theme

    def get_recommendation(self):
        """Asks Gemini to analyze the article and recommend mode/style."""
        print(" 🤔 正在利用 AI 分析文章特色并拟定出版建议...")
        with open(self.source_file, 'r', encoding='utf-8') as f:
            content = f.read()[:10000] # First 10k for analysis

        from llm_utils import get_client
        client = get_client()

        theme = self.narrative_theme if self.narrative_theme is not None else ""
        if not theme or theme == "无特定主题":
            narrative_section = "本次解读没有特定的业务主题限制，请总编辑完全根据文章本身的内容、技术痛点和行业价值进行解读推荐。"
        else:
            narrative_section = f"本次解读的宏观叙事主题背景是：【{theme}】。"

        prompt = f"""
你是一名资深的【出版总编】。请分析以下文章内容，并给出出版建议。
{narrative_section}

文章内容：
{content}

请以 JSON 格式输出建议：
{{
  "standard_title": "你为这篇文章拟定的专业、直译的中文标题 (用于译介版)",
  "catchy_title": "你为这篇文章拟定的具有行业深度、吸睛的解读标题 (用于解读版)",
  "text_style": "formal", "business", "storytelling", "technical", "elegant" 之一,
  "cover_style": "Industrial Amber",
  "article_type": "trend", "paper", "policy", "product", "standard" 之一,
  "thoughts": "结合上述宏观叙事主题背景和本文章的核心要义，为修改者拟定推荐的解读思路/编辑思路/导读引导观点（30字以内）",
  "justification": "出版建议理由或特色剖析（20字以内）"
}}
"""
        try:
            response = client.generate_content(prompt, model_name=self.model_name)
            # Find JSON block
            import json
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            print(f" ⚠️ AI 建议获取失败: {e}")
        return {}

def metadata_onboarding(source_file, recommendation=None):
    """Interactive CLI to verify and edit article metadata."""
    from common_utils import MetadataEngine
    from crawler_agent import normalize_source

    recommendation = recommendation or {}

    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()

    meta_eng = MetadataEngine(content)

    # Initial fields
    eng_title = meta_eng.get('title', 'Unknown Title')
    chn_title = meta_eng.get('标题', '') or recommendation.get('standard_title', '')
    author = meta_eng.get('author', 'Unknown')
    date = meta_eng.get('date') or meta_eng.get('publish_date') or ''
    source = meta_eng.get('source', 'Unknown')
    url = meta_eng.get('url', '')

    # [Rule] Normalize source to 【Author, Platform】 for personal/platform posts
    source = normalize_source(author, source)

    while True:
        clear_screen()
        print("="*60)
        print(" 🔍 正在核对文章元数据 (Project Metadata Check)")
        print(" [关键：译介模式的专业性基石]")
        print("="*60)
        print(f" [1] 原文标题 (EnTitle): {eng_title}")
        print(f" [2] 中文标题 (CnTitle): {chn_title if chn_title else '（待定）'}")
        print(f" [3] 作者 (Author):     {author}")
        print(f" [4] 发布日期 (Date):   {date}")
        print(f" [5] 发布机构 (Source): {source}")
        print("-" * 60)
        print(f" [U] 原文链接 (URL):    {url}")
        print("-" * 60)
        print(" 输入序号 [1-5] 进行修改，或直接按 [Enter] 确认并继续")
        print("="*60)

        choice = input(" > ").strip().lower()

        if not choice:
            break
        elif choice == '1':
            eng_title = input(" 请输入正确的原文标题: ").strip() or eng_title
        elif choice == '2':
            chn_title = input(" 请输入正确的中文标题: ").strip() or chn_title
        elif choice == '3':
            author = input(" 请输入作者名字: ").strip() or author
        elif choice == '4':
            date = input(" 请输入发布日期 (YYYY-MM-DD): ").strip() or date
        elif choice == '5':
            source = input(" 请输入发布机构: ").strip() or source

    # Rebuild YAML and update source file
    clean_body = meta_eng.clean_body(content, keep_cover=True)
    new_yaml = {
        'title': chn_title or eng_title,
        'eng_title': eng_title,
        'author': author,
        'date': date,
        'source': source,
        'url': url
    }

    import yaml
    yaml_block = f"---\n{yaml.dump(new_yaml, allow_unicode=True)}---\n\n"
    with open(source_file, 'w', encoding='utf-8') as f:
        f.write(yaml_block + clean_body)

    print(" ✅ 元数据已确认。")
    return new_yaml

def pre_flight_check(input_file, recommendation=None, current_model="gemini-3-flash-preview"):
    """Interactive CLI to configure the run."""
    clear_screen()
    print("="*60)
    print(" 🚀 POSTFDRY-OS 2.0 | 发布中心 (Publishing Hub)")
    print("="*60)
    print(f" 📂 待处理稿件: {os.path.basename(input_file)}")
    print("-" * 60)

    # Load existing metadata for default titles
    from common_utils import MetadataEngine
    with open(input_file, 'r', encoding='utf-8') as f:
        meta = MetadataEngine(f.read())
    current_std_title = meta.get('title') or recommendation.get('standard_title', '未命名译介文章')

    # Check for custom style profile
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    user_style_path = os.path.join(base_dir, "config", "styles", "user_style.md")
    has_custom = os.path.exists(user_style_path)

    # 1. Select Mode
    print("\n --- ❶ 任务模式 (Task Mode) ---")
    modes = [
        ("translate", "专业译介 (Professional Translation)"),
        ("interpret", "深度解读 (Deep Interpretation)"),
        ("both", "双模式并行 (Dual-Mode Publishing)")
    ]

    for i, (m, label) in enumerate(modes, 1):
        print(f" [{i}] {label}")

    mode_choice = input(f"\n 请选择模式 [1-3, 默认 3]: ").strip() or "3"
    try:
        mode = modes[int(mode_choice)-1][0]
    except:
        mode = "both"

    # 1.5 Reuse Translation Check
    reuse_translation = False
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(input_file)))
    wip_translated = os.path.join(project_root, "wip", "translated.md")
    if os.path.exists(wip_translated):
        print(f"\n --- ❶.❺ 检测到现有翻译 (Existing Translation) ---")
        print(f" 发现: {os.path.basename(wip_translated)}")
        reuse_choice = input(" 是否直接沿用此翻译而不重新调用 LLM? [Y/n, 默认 Y]: ").strip().lower()
        if reuse_choice != 'n':
            reuse_translation = True

    # Initialize variables with defaults
    gen_images = True if mode in ["interpret", "both"] else False
    pdf_gen = True if mode in ["translate", "both"] else False
    article_type = "trend"
    image_model = "gemini-3-pro-image-preview"
    pdf_template = "Federation"
    localize_images = False

    # 2. Text Style
    print("\n --- ❷ 写作风格 (Writing Style) ---")
    styles = ["custom", "formal", "business", "storytelling", "technical", "elegant"]
    if not has_custom: styles.remove("custom")

    for i, s in enumerate(styles, 1):
        label = f" [{i}] {s}"
        if i == 1: label += " (默认)"
        print(label)

    style_choice = input(f"\n 请选择风格 [1-{len(styles)}, 默认 1]: ").strip() or "1"
    try:
        text_style = styles[int(style_choice)-1]
    except:
        text_style = styles[0]

    # 3. Visual Styles
    print("\n --- ❸ 视觉设计风格 (Visual DNA) ---")
    visual_presets = ["Industrial Amber", "Corporate Blue", "Minimalist White", "Elegant Gold"]
    if mode == "translate":
        visual_presets.insert(0, "Federation")

    for i, v in enumerate(visual_presets, 1):
        label = f" [{i}] {v}"
        if v == "Federation": label = f" [{i}] Federation (研究院制图风)"
        if i == 1: label += " (默认)"
        print(label)

    v_choice = input(f"\n 请选择视觉风格 [1-{len(visual_presets)}, 默认 1]: ").strip() or "1"
    try:
        cover_style = visual_presets[int(v_choice)-1]
    except:
        cover_style = visual_presets[0]
    info_style = cover_style

    # 3.5 PDF Template
    if pdf_gen:
        print("\n --- ❹ PDF 输出模板 (PDF Template) ---")
        pdf_templates = ["Federation"]
        for i, t in enumerate(pdf_templates, 1):
            label = f" [{i}] {t}"
            if t == "Federation": label += " (研究院标准模板 ✨)"
            if i == 1: label += " (默认)"
            print(label)

        pdf_choice = input("\n 请选择 PDF 模板 [1-1, 默认 1]: ").strip() or "1"
        try:
            pdf_template = pdf_templates[int(pdf_choice)-1]
        except:
            pdf_template = "Federation"

    # 4. Article Type
    if mode in ["interpret", "both"]:
        print("\n --- ❺ 内容重构架构 (Article Type) ---")
        types_map = [
            ("trend", "行业趋势 (看未来、谈影响)"),
            ("paper", "深度报告 (直击痛点、落地建议)"),
            ("policy", "政策规制 (实战视角、合规边界)"),
            ("product", "产品解析 (硬核场景、去PPT味)"),
            ("standard", "执行手册 (落地步骤、避坑指南)")
        ]

        rec_type = recommendation.get('article_type', 'trend') if recommendation else 'trend'
        for i, (t, desc) in enumerate(types_map, 1):
            label = f" [{i}] {desc}"
            if recommendation and t == rec_type: label += " (AI推荐 ✨)"
            elif i == 1: label += " (默认)"
            print(label)

        type_choice = input("\n 选择内容重构架构 [1-5, 默认 1]: ").strip() or "1"
        try:
            article_type = types_map[int(type_choice)-1][0]
        except:
            article_type = types_map[0][0]

    # 6. 译者洞察
    thoughts = ""
    if mode in ["interpret", "both"]:
        print("\n --- ❻ 译者/编辑洞察 (Editor's Input) ---")
        default_thoughts = recommendation.get('thoughts', '') if recommendation else ''
        print(f" AI 建议: {default_thoughts}")
        user_input = input(f" > (回车沿用建议, 或输入新洞察): ").strip()
        thoughts = user_input if user_input else default_thoughts

    # 7. 生图引擎
    if gen_images:
        print("\n --- ❼ 生图引擎 (Visual Engine) ---")
        img_engines = [
            ("gemini-3-pro-image-preview", "Nano Banana Pro (Gemini 3 Pro 旗舰生图)"),
            ("gemini-3.1-flash-image-preview", "Nano Banana 2 (Gemini 3 Flash 极速生图)"),
            ("imagen-3", "Imagen 3 (Vertex AI 专业绘画模型)")
        ]
        for i, (m, label) in enumerate(img_engines, 1):
            print(f" [{i}] {label}")

        img_choice = input("\n 请选择生图模型 [1-3, 默认 1]: ").strip() or "1"
        try:
            image_model = img_engines[int(img_choice)-1][0]
        except:
            image_model = "gemini-3-pro-image-preview"

    # 8. Confirm Titles
    std_title = current_std_title
    cat_title = recommendation.get('catchy_title', '未命名解读文章') if recommendation else "未命名解读文章"

    if mode in ["translate", "both"]:
        print(f"\n --- ❽ 译介版标题确认 (Standard Title) ---")
        print(f" 建议标题: {std_title}")
        user_std_title = input(f" > (回车沿用建议, 或输入新标题): ").strip()
        if user_std_title: std_title = user_std_title

    if mode in ["interpret", "both"]:
        print(f"\n --- ❾ 解读版标题确认 (Catchy Title) ---")
        print(f" 建议标题: {cat_title}")
        user_cat_title = input(f" > (回车沿用建议, 或输入新标题): ").strip()
        if user_cat_title: cat_title = user_cat_title

    # 11. Summary Generation Mode
    summary_mode = "preset"
    summary_prompt = ""
    if mode in ["interpret", "both"]:
        print(f"\n --- ⓫ 总结模式 (Summary Mode) ---")
        print(" [1] 按预设总结 (默认)")
        print(" [2] 根据文章上下文自动总结")
        print(" [3] 无总结")
        summary_choice = input("\n 请选择总结模式 [1-3, 默认 1]: ").strip() or "1"
        if summary_choice == "2":
            summary_mode = "auto"
        elif summary_choice == "3":
            summary_mode = "none"
        else:
            summary_mode = "preset"

        if summary_mode == "preset":
            print("\n  预设总结指令:")
            default_prompt = "不要进行机械的“板块化”总结。如果需要为最后一部分设置标题，【绝对不要】以“终局思考”、“实战思考”、“写在最后”或“实战视角的思考”这类虚空套话命名，而是应该使用：“总结：[具体的核心提炼]”的句式（例如，若是关于混合云，则可以使用“总结：混合云下的技术收敛”；若是关于平台采购，则使用“总结：回归系统合规与稳定性”）。请直接陈述实战层面的观点，结尾严禁出现强行升华。"
            print(f"  {default_prompt}")
            user_prompt = input("\n  请输入自定义总结指令 (直接回车沿用预设): ").strip()
            summary_prompt = user_prompt if user_prompt else default_prompt

    # Final Confirmation Summary
    clear_screen()
    print("\n" + "="*50)
    print("         🚀 POSTFDRY 2.0 任务确认 (Task Ready)")
    print("="*50)
    print(f" 📂 目标文件: {os.path.basename(input_file)}")
    mode_label = {"translate": "【专业译介】", "interpret": "【深度解读】", "both": "【双模式并行】"}.get(mode, mode)
    print(f" 🛠️  任务模式: {mode_label}")
    print(f" ✍️  写作风格: {text_style}")
    print(f" 🎨 视觉风格: {cover_style}")
    print(f" 🤖 智力引擎: {current_model}")
    if mode in ["translate", "both"]:
        print(f" 📌 译介标题: {std_title}")
    if mode in ["interpret", "both"]:
        print(f" 🏗️  重构架构: {article_type}")
        print(f" 📌 解读标题: {cat_title}")
        print(f" 🎨 生图引擎: {image_model}")
        mode_desc = {"preset": "按预设总结", "auto": "自动总结", "none": "无总结"}.get(summary_mode, summary_mode)
        print(f" 📝 总结模式: {mode_desc}")
    if pdf_gen:
        print(f" 📄 PDF 模板: {pdf_template}")
    print(f" 🖼️  图片汉化: {'开启 ✅' if localize_images else '关闭 ❌'}")
    print("="*50)

    confirm = input("\n 确认启动流水线? [Y/n, 默认 Y]: ").strip().lower()
    if confirm == "n":
        print("❌ 任务已取消。")
        sys.exit(0)

    # Final Return
    final_model = current_model
    return mode, text_style, cover_style, info_style, pdf_template, article_type, thoughts, gen_images, pdf_gen, final_model, image_model, std_title, cat_title, localize_images, reuse_translation, summary_mode, summary_prompt

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Postfdry-OS: Professional Publishing Dispatcher")
    parser.add_argument("input", help="URL or local Markdown file path")
    parser.add_argument("--mode", choices=["translate", "interpret", "both"], help="Execution mode override")
    parser.add_argument("--text-style", help="Writing style override")
    parser.add_argument("--cover-style", help="Visual cover style override")
    parser.add_argument("--info-style", help="Infographic style override")
    parser.add_argument("--type", help="Article type override (for interpretation)")
    parser.add_argument("--thoughts", help="Editor's thoughts override")
    parser.add_argument("--gen-images", action="store_true", help="Generate images override")
    parser.add_argument("--pdf", dest="pdf", action="store_true", default=None, help="Generate PDF override")
    parser.add_argument("--no-pdf", dest="pdf", action="store_false", help="Disable PDF generation override")
    parser.add_argument("--localize-images", action="store_true", help="Enable visual localization")
    parser.add_argument("--force-relocalize", action="store_true", help="Force relocalize existing images")
    parser.add_argument("--model", help="LLM model override")
    parser.add_argument("--non-interactive", action="store_true", help="Skip all interactive prompts")
    parser.add_argument("--reuse-translation", action="store_true", help="Reuse existing translation in wip/")
    parser.add_argument("--skip-summary", action="store_true", help="Skip generating summary ending")
    parser.add_argument("--summary-mode", default="explicit", choices=["explicit", "implicit", "none", "preset", "auto"], help="Summary generation mode")
    parser.add_argument("--summary-prompt", default="", help="Prompt for preset summary mode")
    parser.add_argument("--narrative-theme", default="", help="Narrative/business theme keywords")
    parser.add_argument("--image-model", help="Image generation model/engine override")
    parser.add_argument("--target-title", help="Forced target title override")
    parser.add_argument("--catchy-title", help="Forced catchy title override for interpretation")
    parser.add_argument("--author", default="", help="Author signature override")
    parser.add_argument("--internal-run", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # 0. Handle spawning a new window (Windows/PowerShell specific)
    if os.name == 'nt' and not args.internal_run:
        print("🚩 正在启动新终端进行独立执行 (Interactive Mode)...")
        new_argv = sys.argv + ["--internal-run"]
        new_argv[0] = os.path.abspath(new_argv[0])
        def quote_ps(arg):
            if re.match(r'^[a-zA-Z0-9_\-\./:]+$', arg) and not arg.startswith('http'):
                return arg
            safe_arg = arg.replace('"', '`"')
            return f'"{safe_arg}"'

        cmd_str = f'& "{sys.executable}" ' + ' '.join([quote_ps(a) for a in new_argv])
        import base64
        encoded_cmd = base64.b64encode(cmd_str.encode('utf-16-le')).decode('utf-8')
        spawn_cmd = ["powershell.exe", "-NoProfile", "-Command", f"Start-Process powershell.exe -ArgumentList '-NoExit', '-EncodedCommand', '{encoded_cmd}'"]
        subprocess.Popen(spawn_cmd)
        sys.exit(0)

    # 1. Bootstrap Model Selection
    selected_model = args.model
    if not selected_model and not args.non_interactive:
        selected_model = bootstrap_model_selection()
    else:
        selected_model = selected_model or "gemini-3-flash-preview"

    # 2. Identify Project (Minimal Sniffing)
    pm = ProjectManager(args.input)
    project_root, source_file = pm.init_project()

    # 2.5 Check for History
    history = pm.load_config()
    use_history = False

    if history and not args.non_interactive:
        print("\n" + "="*50)
        print(" 🕵️  检测到该项目的历史任务配置 (History Found)")
        print("="*60)
        mode = history.get('mode', 'N/A')
        print(f" 📍 模式: {mode}")
        print(f" ✍️  风格: {history.get('text_style', 'N/A')}")
        print(f" 🎨 视觉: {history.get('cover_style', 'N/A')}")
        print(f" 🤖 模型: {history.get('llm_model', 'N/A')}")
        if history.get('pdf_gen'):
            print(f" 📄 模板: {history.get('pdf_template', 'N/A')}")

        if mode in ["translate", "both"]:
            print(f" 📌 译介标题: {history.get('standard_title', 'N/A')}")
        if mode in ["interpret", "both"]:
            print(f" 🏗️  类型: {history.get('article_type', 'N/A')}")
            print(f" 📌 解读标题: {history.get('catchy_title', 'N/A')}")
            print(f" 🎨 生图: {history.get('image_model', 'N/A')}")

        print(f" 🖼️  汉化: {'开启 ✅' if history.get('localize_images') else '关闭 ❌'}")
        print(f" 📄 PDF:  {'生成 ✅' if history.get('pdf_gen') else '跳过 ❌'}")
        print(f" 📅 上次: {history.get('last_run', 'N/A')}")
        print("="*60)
        ans = input("\n 是否直接沿用历史配置启动？ [Y/n, 默认 Y]: ").strip().lower()
        if ans != 'n':
            use_history = True

    materialized_source = source_file
    recommendation = {}

    if use_history:
        # If using history, check if source.md exists. If not, materialize it.
        if not os.path.exists(source_file):
            pm.materialize_source(model_name=selected_model)

        mode = history.get('mode', 'translate')
        text_style = history.get('text_style', 'formal')
        cover_style = history.get('cover_style', 'Industrial Amber')
        info_style = history.get('info_style', 'Industrial Amber')
        pdf_template = history.get('pdf_template', 'Federation')
        article_type = history.get('article_type', 'trend')
        thoughts = history.get('thoughts', '')
        gen_images = history.get('gen_images', False)
        pdf_gen = history.get('pdf_gen', True)
        final_model = history.get('llm_model', selected_model)
        image_model = history.get('image_model', 'gemini-3-pro-image-preview')
        std_title = history.get('standard_title', '')
        cat_title = history.get('catchy_title', '')
        localize_images = history.get('localize_images', False)
        reuse_translation = True # For history runs, always reuse by default
        summary_mode = history.get('summary_mode')
        if not summary_mode:
            summary_mode = "explicit" if history.get('gen_summary', True) else "none"
        if summary_mode == "preset":
            summary_mode = "explicit"
        elif summary_mode == "auto":
            summary_mode = "implicit"
        summary_prompt = history.get('summary_prompt', '')
        narrative_theme = history.get('narrative_theme', "")
        if narrative_theme == "无特定主题":
            narrative_theme = ""
        author = args.author or history.get('author') or ""
    elif args.non_interactive:
        # Always materialize in non-interactive cold start
        materialized_source = pm.materialize_source(model_name=selected_model)

        mode = args.mode or "translate"
        text_style = args.text_style or "formal"
        cover_style = args.cover_style or "Industrial Amber"
        info_style = args.info_style or "Industrial Amber"
        pdf_template = "Federation"
        article_type = args.type or "trend"
        thoughts = args.thoughts or ""
        gen_images = args.gen_images
        pdf_gen = args.pdf if args.pdf is not None else (mode != "interpret")
        final_model = args.model or "gemini-3-flash-preview"
        image_model = args.image_model or "vertex"
        std_title = args.target_title or ""
        cat_title = args.catchy_title or args.target_title or ""
        localize_images = args.localize_images
        force_relocalize = args.force_relocalize
        reuse_translation = args.reuse_translation
        summary_mode = args.summary_mode
        if summary_mode == "preset":
            summary_mode = "explicit"
        elif summary_mode == "auto":
            summary_mode = "implicit"
        if args.skip_summary:
            summary_mode = "none"
        summary_prompt = args.summary_prompt
        narrative_theme = args.narrative_theme
        if narrative_theme == "无特定主题":
            narrative_theme = ""
        author = args.author or ""

        # Rename project directory based on target title if available
        target_title = std_title or cat_title
        if not target_title:
            from common_utils import MetadataEngine
            try:
                with open(materialized_source, 'r', encoding='utf-8') as f:
                    content = f.read()
                meta_eng = MetadataEngine(content)
                target_title = meta_eng.get('title') or meta_eng.get('eng_title')
            except Exception as e:
                print(f"⚠️ 无法从原文提取标题用于重命名: {e}")
        
        if target_title:
            project_root, source_file = pm.rename_project_if_needed(target_title)
            materialized_source = source_file
    else:
        # Full Onboarding Flow (Cold Start)
        materialized_source = pm.materialize_source(model_name=selected_model)
        narrative_theme = args.narrative_theme
        if narrative_theme == "无特定主题":
            narrative_theme = ""

        # 3. AI Onboarding (Recommendations)
        assistant = OnboardingAssistant(materialized_source, model_name=selected_model, narrative_theme=args.narrative_theme)
        recommendation = assistant.get_recommendation()

        # 4. Interactive Metadata Onboarding
        metadata_onboarding(materialized_source, recommendation=recommendation)

        # 5. Full Configuration Phase
        mode, text_style, cover_style, info_style, pdf_template, article_type, thoughts, gen_images, pdf_gen, final_model, image_model, std_title, cat_title, localize_images, reuse_translation, summary_mode, summary_prompt = pre_flight_check(materialized_source, recommendation, current_model=selected_model)

        target_title = std_title or cat_title
        if target_title:
            project_root, source_file = pm.rename_project_if_needed(target_title)
            materialized_source = source_file
        author = args.author or (history.get('author') if history else "") or ""

    # 2.9 Signal: Visual Localization Decision
    force_relocalize = args.force_relocalize
    if localize_images and not args.non_interactive:
        localized_dir = os.path.join(project_root, "assets", "localized")
        if os.path.exists(localized_dir) and any(f.endswith("_L10Ned_v1.png") for f in os.listdir(localized_dir)):
            print(f"\n --- ❷.❾ 视觉内容汉化信号 (Visual Localization Signal) ---")
            print(f" 发现已有汉化版本。")
            redo_choice = input(" 是否在流水线执行中强制重新汉化 (生成新版本)? [y/N, 默认 N]: ").strip().lower()
            if redo_choice == 'y':
                force_relocalize = True
                print(" 📌 信号已设置：流水线将生成新版本的汉化图。")
            else:
                print(" 📌 信号已设置：流水线将优先复用现有汉化。")

    # Save config
    pm.save_config({
        'mode': mode,
        'text_style': text_style,
        'cover_style': cover_style,
        'info_style': info_style,
        'pdf_template': pdf_template,
        'article_type': article_type,
        'thoughts': thoughts,
        'gen_images': gen_images,
        'standard_title': std_title,
        'catchy_title': cat_title,
        'image_model': image_model,
        'localize_images': localize_images,
        'pdf_gen': pdf_gen,
        'llm_model': final_model,
        'summary_mode': summary_mode,
        'summary_prompt': summary_prompt,
        'gen_summary': summary_mode != "none",
        'author': author,
        'narrative_theme': narrative_theme,
        'last_run': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    # 3. Dispatch to workflow scripts
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    modes_to_run = [mode] if mode != "both" else ["translate", "interpret"]

    for current_run_mode in modes_to_run:
        print(f"\n🚀 正在启动 {current_run_mode.upper()} 流水线...")
        if current_run_mode == "translate":
            wf_script = os.path.join(scripts_dir, "translate_workflow.py")
            cmd = [
                sys.executable, wf_script, materialized_source,
                "--project-root", project_root,
                "--cover-style", pdf_template,
                "--model", final_model,
                "--no-spawn"
            ]
            if localize_images: cmd.append("--localize-images")
            if force_relocalize: cmd.append("--force-relocalize")
            if reuse_translation: cmd.append("--reuse-translation")
            if args.non_interactive: cmd.append("--non-interactive")
            if thoughts: cmd.extend(["--thoughts", thoughts])
            if std_title: cmd.extend(["--target-title", std_title])
            if pdf_gen: cmd.append("--pdf")
            if gen_images:
                cmd.append("--gen-images")
                cmd.extend(["--image-model", image_model])
        else:
            wf_script = os.path.join(scripts_dir, "interpret_workflow.py")
            cmd = [
                sys.executable, wf_script, materialized_source,
                "--project-root", project_root,
                "--text-style", text_style,
                "--cover-style", cover_style,
                "--thoughts", thoughts,
                "--type", article_type,
                "--model", final_model,
                "--target-title", cat_title,
                "--reuse-translation",
                "--no-spawn"
            ]
            if localize_images: cmd.append("--localize-images")
            if args.non_interactive: cmd.append("--non-interactive")
            cmd.extend(["--summary-mode", summary_mode])
            if summary_mode in ["explicit", "implicit"] and summary_prompt:
                cmd.extend(["--summary-prompt", summary_prompt])
            if narrative_theme is not None:
                cmd.extend(["--narrative-theme", narrative_theme])
            if author:
                cmd.extend(["--author", author])
            if gen_images:
                cmd.append("--gen-images")
                cmd.extend(["--image-model", image_model])

        print(f"📍 项目根目录: {project_root}")
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print(f"❌ {current_run_mode.upper()} 流水线执行失败 (错误码: {res.returncode})，主调度程序已终止。")
            sys.exit(res.returncode)
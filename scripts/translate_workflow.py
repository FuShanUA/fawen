import os
import sys
import argparse
import subprocess
import re
import json
from datetime import datetime
from pathlib import Path

# Add agents and common to path
scripts_dir = os.path.dirname(os.path.abspath(__file__))
postfdry_root = os.path.dirname(scripts_dir)
agents_dir = os.path.join(postfdry_root, "agents")
common_dir = os.path.abspath(os.path.join(postfdry_root, "..", "common"))

# Ensure agents_dir is at the front of sys.path to take import priority over common_dir
for d in [common_dir, agents_dir]:
    if d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)

from common_utils import MetadataEngine, deterministic_scrub
import translator_agent
import localizer_agent

# Dynamic import for crawler_agent to support asset materialization
try:
    import crawler_agent
except ImportError:
    sys.path.append(os.path.join(postfdry_root, "agents"))
    import crawler_agent

class ProfessionalAssembler:
    """负责将翻译后的内容组装成出版级的 HTML 文档。"""

    # 核心视觉样式 (Postfdry Gold Standard)
    STYLE_SYSTEM = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Noto+Serif+SC:wght@400;700&display=swap');

    :root {
        --primary-color: #003366;
        --accent-color: #FFBF00;
        --text-color: #222;
        --meta-color: #666;
        --bg-color: #fff;
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif;
        line-height: 1.8;
        color: var(--text-color);
        max-width: 850px;
        margin: 0 auto;
        padding: 40px 20px;
        background-color: var(--bg-color);
    }

    /* 封面及页眉信息 */
    .article-header {
        text-align: center;
        margin-bottom: 50px;
        border-bottom: 2px solid var(--primary-color);
        padding-bottom: 30px;
    }

    .article-title {
        font-size: 2.5em;
        color: var(--primary-color);
        margin-bottom: 10px;
        line-height: 1.2;
    }

    .article-eng-title {
        font-size: 1.2em;
        color: var(--meta-color);
        font-style: italic;
        margin-bottom: 20px;
    }

    .article-meta {
        font-size: 0.95em;
        color: var(--meta-color);
        display: flex;
        justify-content: center;
        gap: 20px;
        flex-wrap: wrap;
    }

    .meta-item b { color: var(--primary-color); }

    /* 正文样式加固 */
    h1, h2, h3 { color: var(--primary-color); margin-top: 1.5em; }

    /* 屏蔽 baoyu 工具自动生成的 YAML 表格 (我们在 Header 中手动处理) */
    table:first-of-type { display: none; }
    /* 恢复正常的表格显示 */
    .content table, table[border], table:not(:first-of-type) {
        display: table !important;
        width: 100%;
        border-collapse: collapse;
        margin: 20px 0;
    }
    th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
    th { background-color: #f4f4f4; }

    blockquote {
        margin: 25px 0;
        padding: 15px 25px;
        background-color: #f9f9f9;
        border-left: 4px solid #ddd !important;
        font-style: italic;
    }

    img {
        max-width: 100%;
        height: auto;
        display: block;
        margin: 30px auto;
        border-radius: 4px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }

    .footer {
        margin-top: 60px;
        padding-top: 20px;
        border-top: 1px solid #eee;
        font-size: 0.9em;
        color: var(--meta-color);
        text-align: center;
    }

    /* PDF 专用排版微调 */
    @media print {
        body { padding: 0; font-family: 'Inter', 'STKaiti', '华文楷体', 'SimKai', '楷体', 'Noto Serif SC', serif !important; }
        .article-header { page-break-after: avoid; }
        blockquote { page-break-inside: avoid; }
    }
</style>
"""

    def __init__(self, meta_engine):
        self.meta_engine = meta_engine
        self._load_inside_style()

    def _load_inside_style(self):
        """尝试读取 styler_federation.json 中的 inside 样式。"""
        # postfdry_root should be available in global scope if loaded correctly
        self.no_spawn = False
        self.localize_images = False
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "styler_federation.json")
        self.inside_style = {
            "font": "STKaiti",
            "article_title_size": 24,
            "chapter_title_size": 20,
            "body_size": 16
        }
        if os.path.exists(config_path):
            try:
                import json
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "inside" in data:
                        self.inside_style.update(data["inside"])
            except: pass

    def build_header(self):
        title = self.meta_engine.get('title')
        eng_title = self.meta_engine.get('eng_title')
        author = self.meta_engine.get('author')
        source = self.meta_engine.get('source')
        date = self.meta_engine.get('date')
        url = self.meta_engine.get('url')

        header = f'<div class="article-header">'
        header += f'<h1 class="article-title">{title}</h1>'
        if eng_title and eng_title != title:
            header += f'<div class="article-eng-title">{eng_title}</div>'

        meta_items = []
        if author and author.lower() != 'none':
            meta_items.append(f'<span class="meta-item"><b>译者：</b>{author}</span>')
        if source:
            meta_items.append(f'<span class="meta-item"><b>出处：</b>{source}</span>')
        if date:
            meta_items.append(f'<span class="meta-item"><b>日期：</b>{date}</span>')

        header += f'<div class="article-meta">{" | ".join(meta_items)}</div>'
        header += '</div>'
        return header

    def build_footer(self):
        url = self.meta_engine.get('url')
        # 这里的 metadata 是融合后的字典，优先取显式指定的 eng_title，否则取备存的 eng_title
        eng_title = self.meta_engine.get('eng_title')

        if not url: return ""

        # 构建显式的“原文”区块，包含标题和可点击的链接文本，增强 PDF 兼容性
        footer_html = '<div class="article-source-link">'
        footer_html += f'<p><b>原文标题：</b>{eng_title}</p>'
        footer_html += f'<p><b>原文链接：</b><a href="{url}">{url}</a></p>'
        footer_html += '</div>'
        return footer_html

    def assemble_html(self, body_html):
        """将各部分组合成完整的 HTML 文档。"""
        full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self.meta_engine.get('title')}</title>
    {self.STYLE_SYSTEM}
    <style>
        body, .content, .content p, .content li, .content section, .content div, .content span, .content td {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif !important;
            font-size: 16px !important; /* 微信黄金阅读字号 */
            line-height: 1.8 !important;
            color: #222222 !important;
        }}
        @media print {{
            body, .content, .content p, .content li, .content section, .content div, .content span, .content td {{
                font-family: 'Inter', '{self.inside_style.get('font', 'STKaiti')}', '华文楷体', 'SimKai', 'Noto Serif SC', serif !important;
                font-size: {self.inside_style.get('body_size', 16)}px !important;
                line-height: 1.75 !important;
                color: #333333 !important;
            }}
        }}
        .article-title {{
            font-size: {self.inside_style.get('article_title_size', 24)}pt !important;
        }}
        h2 {{
            font-size: {self.inside_style.get('chapter_title_size', 20)}pt !important;
        }}
        .article-source-link {{
            margin-top: 40px !important;
            padding-top: 20px !important;
            border-top: 1px solid #efefef !important;
            font-size: 14px !important;
            color: #666 !important;
        }}
        .article-source-link a {{
            color: #0073bb !important;
            text-decoration: underline !important;
            cursor: pointer !important;
        }}
    </style>
</head>
<body>
    {self.build_header()}
    <div class="content">
        {body_html}
    </div>
    {self.build_footer()}
</body>
</html>"""
        return full_html

class TranslationWorkflow:
    def __init__(self, input_file, project_root=None, cover_style="Federation", model_name="gemini-3-flash-preview", target_title="", reuse_translation=False, localize_images=False, force_relocalize=False, non_interactive=False):
        self.input_file = Path(input_file)
        self.project_root = Path(project_root) if project_root else self.input_file.parent.parent
        self.output_dir = self.project_root / "output"
        self.wip_dir = self.project_root / "wip"
        self.assets_dir = self.project_root / "assets"
        self.cover_style = cover_style
        self.model_name = model_name
        self.target_title = target_title
        self.reuse_translation = reuse_translation
        self.localize_images = localize_images
        self.force_relocalize = force_relocalize
        self.non_interactive = non_interactive
        self.interactive = False # Launch interactive styler?

        for d in [self.output_dir, self.wip_dir, self.assets_dir]:
            d.mkdir(parents=True, exist_ok=True)

        with open(self.input_file, 'r', encoding='utf-8') as f:
            self.metadata_engine = MetadataEngine(f.read())

    def run(self, publish_pdf=True):
        print(f"🚀 [Postfdry 2.0] 启动译介管线: {self.input_file.name}")

        # 1. 翻译核心正文
        print("  [Step 1/4] 调用 Translator Agent (1:1 翻译)...")
        wip_translated = self.wip_dir / "translated.md"

        should_translate = True
        if wip_translated.exists() and wip_translated.stat().st_size > 200:
            if self.reuse_translation:
                print(f"      ♻️  自动复用现有翻译稿 (reuse_translation=True)。")
                translated_md_path = str(wip_translated)
                should_translate = False
            elif self.non_interactive:
                # Auto-backup and re-translate in non-interactive mode
                from common_utils import get_versioned_path
                bak_path = get_versioned_path(str(wip_translated))
                import shutil
                shutil.move(str(wip_translated), bak_path)
                print(f"      📦 [Non-Interactive] 已将旧版翻译备份至: {os.path.basename(bak_path)}")
                should_translate = True
            else:
                print(f"  ⚠️  检测到已有翻译稿 (wip/translated.md)")
                ans = input(f"      是否重新翻译？ (重新翻译将保留原有版本) [y/N]: ").strip().lower()
                if ans != 'y':
                    print(f"      ♻️  跳过翻译步骤，沿用现有翻译稿。")
                    translated_md_path = str(wip_translated)
                    should_translate = False
                else:
                    from common_utils import get_versioned_path
                    bak_path = get_versioned_path(str(wip_translated))
                    import shutil
                    shutil.move(str(wip_translated), bak_path)
                    print(f"      📦 已将旧版翻译备份至: {os.path.basename(bak_path)}")

        if should_translate:
            translated_md_path = translator_agent.run_atomic_translation(
                str(self.input_file),
                style="formal",  # 译介模式采用标准 formal 翻译风格
                project_root=str(self.project_root),
                model_name=self.model_name
            )
            # Ensure it is also mirrored to wip/translated.md for consistency
            if Path(translated_md_path).resolve() != wip_translated.resolve():
                import shutil
                shutil.copy2(translated_md_path, str(wip_translated))
                translated_md_path = str(wip_translated)

        # 2. 融合元数据 (Source of Truth: Original Metadata)
        with open(translated_md_path, 'r', encoding='utf-8') as f:
            trans_content = f.read()
        trans_meta = MetadataEngine(trans_content)
        body = trans_meta.clean_body(trans_content, keep_cover=True).strip()

        # Load project config if exists to merge manual adjustments
        import json
        config_path = self.wip_dir / "project_config.json"
        project_config = {}
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    project_config = json.load(f)
            except Exception as e:
                print(f"⚠️ Failed to load project config: {e}")

        # 复制原始元数据作为基础 (这是最可靠的数据源)
        final_meta = self.metadata_engine.raw_meta.copy()
        for k in ['title', 'eng_title', 'author', 'source', 'date']:
            if project_config.get(k):
                final_meta[k] = project_config[k]

        # 1. 备份原标题为 eng_title (仅当原标题为英文时，防止二次改写导致中文存入英文位)
        orig_title = self.metadata_engine.get('title')
        if orig_title:
            if not re.search(r'[\u4e00-\u9fff]', orig_title):
                final_meta['eng_title'] = orig_title
            else:
                # 如果原标题就是中文，尝试取备份的 eng_title 键
                potential_eng = self.metadata_engine.get('eng_title')
                if potential_eng and not re.search(r'[\u4e00-\u9fff]', potential_eng):
                    final_meta['eng_title'] = potential_eng

        # Step A: Priority - Use provided target_title if available
        if self.target_title:
            final_meta['title'] = self.target_title
            print(f"  [Skill] 使用确认的标准标题 (std_title): {final_meta['title']}")
            found_chinese = True
        else:
            # Step B: Check if translation metadata already has a Chinese title
            trans_title = trans_meta.get('title')
            found_chinese = False

            if trans_title and re.search(r'[\u4e00-\u9fff]', trans_title):
                 final_meta['title'] = trans_title
                 print(f"  [Skill] 使用翻译器生成的中文标题: {final_meta['title']}")
                 found_chinese = True

        # Step B: Fallback to Body H1 if metadata title is English (very common)
        if not found_chinese:
            # 搜索正文前几行，寻找第一行 H1 (# 标题 或 ### 标题)
            lines = body.split('\n')
            for line in lines[:5]: # Only check first 5 lines
                line = line.strip()
                if line.startswith('# ') or line.startswith('### '):
                    # Strip markers
                    pot_title = re.sub(r'^#+\s*', '', line).strip()
                    if re.search(r'[\u4e00-\u9fff]', pot_title):
                        print(f"  [Skill] 从正文提取到中文标题: {pot_title}")
                        final_meta['title'] = pot_title
                        found_chinese = True
                        break

        # Step C: Ultimate Fallback - Force translation if still English
        if not found_chinese:
             print(f"  [Skill] 标题仍为英文: '{final_meta.get('title', orig_title)}', 执行强制翻译...")
             from translator_agent import translate_string
             # Try to translate orig_title or current title
             input_title = final_meta.get('title', orig_title) or "Untitled"
             final_meta['title'] = translate_string(input_title, force_chinese=True, model_name=self.model_name)
             print(f"  [Skill] 强制翻译完成: {final_meta['title']}")

        # 元数据字段标准化映射 (锁定 publish_date 为 date)
        orig_date = final_meta.get('date') or final_meta.get('publish_date')
        if orig_date:
            final_meta['date'] = str(orig_date)

        # 确保 Original Title 被正确备份为 eng_title
        # 确保 Original Title 被正确备份为 eng_title (如果此时还不存在)
        if not final_meta.get('eng_title'):
             final_meta['eng_title'] = orig_title

        # 清洗正文杂质
        body = deterministic_scrub(body)

        # 确保没有残留的 H1 标题（由组装器负责添加）
        body = re.sub(r'^#\s+.*?\n+', '', body, count=1).strip()

        # 2.5 资产固化 (Asset Materializer): 确保翻译后的正文中引用的远程图片已下载到本地
        print("  [Step 2.5] 固化翻译正文中的远程图片资产...")
        assets_dir = self.project_root / "assets" / "original"
        assets_dir.mkdir(parents=True, exist_ok=True)

        remote_imgs = re.findall(r'!\[.*?\]\((https?://.*?)\)', body)
        for img_url in remote_imgs:
            print(f"    - 下载远程图片: {img_url[:60]}...")
            local_name = crawler_agent.download_image(img_url, str(assets_dir))
            if local_name:
                # 替换为本地路径
                body = body.replace(img_url, f"../assets/original/{local_name}")

        # 2.6 自动视觉汉化 (Infographic Localization) - Only if requested
        localized_map = {}
        if self.localize_images:
            print(f"  [Step 2.6] 正在执行信息图汉化 (Visual Localization)...")
            try:
                localized_map = localizer_agent.run_batch_localization(str(self.project_root), force=self.force_relocalize)
            except Exception as e:
                print(f"  ⚠️ 视觉汉化失败: {e}")
        else:
            print(f"  [Step 2.6] ⏩ 跳过视觉汉化 (按配置要求)")

        if localized_map:
            for orig_img, loc_img in localized_map.items():
                # 将路径从 original 切换到 localized
                old_path = f"../assets/original/{orig_img}"
                new_path = f"../assets/localized/{loc_img}"
                body = body.replace(old_path, new_path)
                print(f"    ✨ 已替换汉化图: {orig_img} -> {loc_img}")

            # 补丁：处理可能已经变成 assets/localized 的路径（针对多次执行的情况）
            # 确保即使 orig_img 已经在正文中了也能被正确引用

        # 3. 组装 Markdown 并生成 HTML (版本化管理 & 规范化命名)
        print("  [Step 2/4] 组装并规范化 Markdown 命名...")

        # 重新构造具备完整元数据的 trans_meta 用于输出
        trans_meta.raw_meta = final_meta
        final_md_content = f"{trans_meta.to_yaml()}\n\n{body}"

        # Generate standard filename under: YYYYMMDD_Author，Source_ChineseTitle.[译介/解读]
        from common_utils import generate_standard_filename
        standard_base_name = generate_standard_filename(final_meta, mode="译介")
        base_md_path = self.output_dir / f"{standard_base_name}.md"

        # 使用版本化路径 (如果规范名已存在则加 _v1, _v2...)
        from common_utils import get_versioned_path
        final_md_path = Path(get_versioned_path(str(base_md_path)))

        with open(final_md_path, 'w', encoding='utf-8') as f:
            f.write(final_md_content)

        print(f"  [Step 3/4] 组装专业级 HTML: {final_md_path.name}")
        html_content = self.generate_professional_html(final_md_path, trans_meta)

        # 保持 HTML 与 MD 路径风格一致
        final_html_path = final_md_path.with_suffix(".html")
        with open(final_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # 4. 生成 PDF
        if publish_pdf:
            print("  [Step 4/4] 导出出版级 PDF...")
            self.generate_pdf(final_md_path)

        print(f"✅ [Done] 翻译任务完成。产出目录: {self.output_dir}")
        return str(final_md_path)

    def generate_professional_html(self, md_path, meta_engine):
        """调用工具生成基础 HTML，然后使用 Assembler 进行专业增强。"""
        try:
            from common_utils import resolve_tool_path
            html_skill_dir = resolve_tool_path("baoyu-markdown-to-html")
        except Exception as e:
            print(f"  [Warning] Failed to resolve baoyu-markdown-to-html path dynamically: {e}")
            html_skill_dir = None

        if not html_skill_dir or not os.path.exists(html_skill_dir):
            html_skill_dir = r"/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-markdown-to-html"

        main_ts = os.path.join(html_skill_dir, "scripts", "main.ts")

        # 先生成基础 HTML
        cmd = f'npx -y bun "{main_ts}" "{md_path}" --theme grace'
        subprocess.run(cmd, shell=True, check=True, capture_output=True)

        temp_html = str(md_path).replace(".md", ".html")
        with open(temp_html, 'r', encoding='utf-8') as f:
            raw_html = f.read()

        # 提取 <body> 中的内容
        body_match = re.search(r'<body[^>]*>(.*?)</body>', raw_html, re.DOTALL | re.IGNORECASE)
        body_inner = body_match.group(1).strip() if body_match else raw_html

        # 修复重复编号 (Duplicate Numbering Fix): 移除 <li> 内容起始处冗余的 1. 2. 等序号
        body_inner = re.sub(r'(<li[^>]*>)\s*(\d+\.|[a-zA-Z]\.|[一二三四五六七八九十]+\.)\s*', r'\1', body_inner)

        # 【核心修复】图片样式增强：支持汉化图 (assets/localized)
        def img_styler(match):
            tag = match.group(0)
            if 'src="../assets/original' in tag or 'src="../assets/localized' in tag:
                return f'<div class="original-chart">{tag}</div>'
            return tag
        body_inner = re.sub(r'<img[^>]+>', img_styler, body_inner)

        # 【核心修复】移除所有标签中的内联 font-family 和 font-size 样式
        body_inner = re.sub(r'font-family:[^;"]*;?', '', body_inner, flags=re.IGNORECASE)
        body_inner = re.sub(r'font-size:[^;"]*;?', '', body_inner, flags=re.IGNORECASE)

        # 使用 Assembler 重新包装
        assembler = ProfessionalAssembler(meta_engine)
        return assembler.assemble_html(body_inner)

    def generate_pdf(self, md_path):
        """调用重构后的 pdf_generator.py。"""
        pdf_gen_script = os.path.join(scripts_dir, "pdf_generator.py")

        # [FIX] 为 PDF 引擎提供绝对路径的 MD 副本，确保图片加载不报错
        abs_md = Path(md_path).with_suffix(".abs.md")
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        project_root = Path(md_path).parent.parent
        def make_abs(match):
            alt = match.group(1)
            rel = match.group(2)
            if rel.startswith('../assets'):
                abs_p = (project_root / rel.lstrip('./')).resolve()
                return f'![{alt}]({abs_p.as_uri()})'
            return match.group(0)

        abs_content = re.sub(r'!\[(.*?)\]\((.*?)\)', make_abs, content)
        with open(abs_md, 'w', encoding='utf-8') as f:
            f.write(abs_content)

        # [NEW] Generate matching HTML for the absolute MD to satisfy pdf_generator requirements
        abs_html_content = self.generate_professional_html(abs_md, self.metadata_engine)
        abs_html_path = abs_md.with_suffix(".html")
        with open(abs_html_path, 'w', encoding='utf-8') as f:
            f.write(abs_html_content)

        try:
            # 使用副本生成，生成后副本会自动被 Playwright 逻辑中的 html 同名文件覆盖或处理
            visual_style = self.cover_style.lower() if self.cover_style.lower() in ["federation", "industrial amber", "corporate blue", "minimalist white", "elegant gold"] else "federation"
            final_pdf_path = Path(md_path).with_suffix(".pdf")
            cmd = [sys.executable, pdf_gen_script, str(abs_md), "--style", visual_style, "--output", str(final_pdf_path)]
            if self.interactive:
                cmd.append("--interactive")
            subprocess.run(cmd, check=True)
            # 清理副本
            if abs_md.exists(): abs_md.unlink()
            abs_html = abs_md.with_suffix(".html")
            if abs_html.exists(): abs_html.unlink()
        except Exception as e:
            print(f"⚠️ PDF 生成失败: {e}")

def run_translation_workflow(input_file, project_root=None, text_style="formal", cover_style="Federation", model_name="gemini-3-flash-preview", target_title="", reuse_translation=False, non_interactive=False):
    """Entry point for postfdry-os dispatcher."""
    wf = TranslationWorkflow(input_file, project_root=project_root, cover_style=cover_style, model_name=model_name, target_title=target_title, reuse_translation=reuse_translation, non_interactive=non_interactive)
    return wf.run(publish_pdf=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Postfdry 2.0 Translation Workflow")
    parser.add_argument("input", help="Source Markdown file")
    parser.add_argument("--project-root", help="Project root directory")
    parser.add_argument("--cover-style", default="Federation", help="PDF Visual Template Style (e.g., Federation, Industrial Amber)")
    parser.add_argument("--info-style", default="Federation", help="Infographic visual style")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="LLM model name")
    parser.add_argument("--thoughts", default="", help="Editor thoughts (ignored in translate mode)")
    parser.add_argument("--target-title", type=str, default="", help="Target title (ignored in translate mode)")
    parser.add_argument("--image-model", type=str, default="gemini-3-pro-image-preview", help="Image model to use")
    parser.add_argument("--localize-images", action="store_true", help="Enable visual localization")
    parser.add_argument("--force-relocalize", action="store_true", help="Force generating new versions of localized images")
    parser.add_argument("--gen-images", action="store_true", help="Generate actual images")
    parser.add_argument("--pdf", action="store_true", default=False, help="Generate PDF")
    parser.add_argument("--no-pdf", action="store_false", dest="pdf", help="Disable PDF generation")
    parser.add_argument("--no-spawn", action="store_true", help="Suppress new PowerShell window spawning")
    parser.add_argument("--reuse-translation", action="store_true", help="Automatically reuse existing translation in wip/ without asking")
    parser.add_argument("--non-interactive", action="store_true", help="Non-interactive mode")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive styler")
    parser.add_argument("--internal-run", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()
    wf = TranslationWorkflow(args.input, project_root=args.project_root, cover_style=args.cover_style, model_name=args.model, target_title=args.target_title, reuse_translation=args.reuse_translation, localize_images=args.localize_images, force_relocalize=args.force_relocalize, non_interactive=args.non_interactive)
    wf.interactive = args.interactive
    wf.run(publish_pdf=args.pdf)
import os
import sys
import re
import pathlib
import json
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

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

from common_utils import MetadataEngine, get_versioned_path

def generate_pdf(input_path, output_path=None, style="federation", interactive=False):
    """
    Postfdry 2.0 PDF Generator (Chromium/Playwright + Template Assembly).
    支持标准 HTML 渲染及高级模板组装 (如 Federation)。
    """
    input_path = Path(input_path)
    html_path = input_path.with_suffix(".html")

    if not html_path.exists():
        print(f"⚠️ 未找到配套 HTML: {html_path.name}")
        return

    # 1. 提取元数据 (使用增强后的 MetadataEngine)
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    meta_engine = MetadataEngine(content)

    # 构造标准化的 metadata 字典供后续引擎使用
    metadata = {
        'title': meta_engine.get('title'),
        'eng_title': meta_engine.get('eng_title'),
        'author': meta_engine.get('author'),
        'source': meta_engine.get('source'),
        'date': meta_engine.get('date'),
        'publish_date': meta_engine.get('publish_date'),
        'url': meta_engine.get('url')
    }

    # 2. 交互式确认 (仅在 Federation 模式且开启交互时)
    if style.lower() == "federation" and interactive:
        styler_script = os.path.join(scripts_dir, "interactive_styler.py")
        print("🚀 正在弹出新终端窗口以确认样式和元数据...")
        try:
            # 在 Windows 下使用 CREATE_NEW_CONSOLE 弹出独立窗口
            creation_flags = 0
            if sys.platform == "win32":
                import subprocess
                creation_flags = subprocess.CREATE_NEW_CONSOLE

            # 使用 wait() 等待用户在新窗口中完成操作并关闭
            proc = subprocess.Popen([sys.executable, styler_script, str(input_path)], creationflags=creation_flags)
            proc.wait()
        except Exception as e:
            print(f"⚠️ 无法启动交互式配置: {e}")

    # 3. 确定输出路径
    if not output_path:
        out_dir = input_path.parent
        # 如果父目录不是 'output'，则创建一个 output 子目录
        if out_dir.name.lower() == "output":
            final_out_dir = out_dir
        else:
            final_out_dir = out_dir / "output"
            if not final_out_dir.exists(): final_out_dir.mkdir(parents=True, exist_ok=True)

        # 提取规范化文件名前缀: YYYYMMDD_Publisher_Title
        date_str = meta_engine.get('date', '00000000').replace('-', '').replace('/', '')
        source_str = meta_engine.get('source', 'Unknown').replace(' ', '_')
        title_str = meta_engine.get('title', 'Untitled').replace(' ', '_')

        # 限制长度并移除非法字符
        safe_source = re.sub(r'[\\/:*?"<>|]', '', source_str)[:20]
        safe_title = re.sub(r'[\\/:*?"<>|]', '', title_str)[:50]

        filename = f"{date_str}_{safe_source}_{safe_title}.pdf"
        output_path = get_versioned_path(final_out_dir / filename)

    # 4. 如果是标准模式，直接渲染
    if style.lower() != "federation":
        print(f"📄 [Standard] 正在基于浏览器渲染 PDF: {input_path.name}...")
        _render_html_to_pdf(html_path, output_path)
    else:
        # 5. 如果是联合会模式，先渲染中间件，再进行组装
        print(f"📄 [Federation] 正在开启高级模板渲染管线: {input_path.name}...")
        temp_content_pdf = str(output_path).replace(".pdf", "_content_raw.pdf")

        # 渲染内容时，隐藏 HTML 自身的页眉页脚 (由模板替代)
        _render_html_to_pdf(html_path, temp_content_pdf, hide_metadata=True)

        # 调用组装引擎
        try:
            import pdf_federation_engine
            pdf_federation_engine.assemble_federation_pdf(temp_content_pdf, str(output_path), metadata)
        except Exception as e:
            print(f"❌ 组装引擎执行失败: {e}")

        # 清理中间件 (Debug: Temporarily disabled to verify links)
        # if os.path.exists(temp_content_pdf):
        #     try: os.remove(temp_content_pdf)
        #     except: pass

    return str(output_path)

def _render_html_to_pdf(html_path, output_path, hide_metadata=False):
    """Playwright 核心渲染逻辑。"""
    html_abs = html_path.absolute()
    base_dir = html_abs.parent

    # Pre-process HTML to fix relative paths for Playwright on Windows
    # Robust regex for src attributes (handles single and double quotes)
    with open(html_abs, 'r', encoding='utf-8') as f:
        html_content = f.read()

    def path_replacer(match):
        quote = match.group(1)
        rel_path = match.group(2)
        if rel_path.startswith(('http', 'data:', 'file:')):
            return match.group(0)
        # Resolve relative to HTML location
        # On Windows, path.resolve() is usually enough, but we want file:/// URI
        try:
            abs_img_path = (base_dir / rel_path).resolve()
            if abs_img_path.exists():
                return f'src={quote}{abs_img_path.as_uri()}{quote}'
            else:
                print(f"  [PDF] WARNING: Image not found at {abs_img_path}")
                return match.group(0)
        except Exception:
            return match.group(0)

    fixed_html = re.sub(r'src=([\'"])(.*?)\1', path_replacer, html_content)

    # Overwrite with absolute paths to ensure Playwright can always find assets
    with open(html_abs, 'w', encoding='utf-8') as f:
        f.write(fixed_html)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 1280, 'height': 720}, device_scale_factor=2)
        page = context.new_page()

        # Use goto with file URI for superior local asset rendering (bypasses security blocks)
        page.goto(html_abs.as_uri(), wait_until='networkidle', timeout=60000)

        if hide_metadata:
            page.add_style_tag(content=".article-header { display: none !important; } .footer { display: none !important; }")

        page.evaluate("async () => { await Promise.all(Array.from(document.images).map(img => { if (img.complete) return; return new Promise((resolve, reject) => { img.addEventListener('load', resolve); img.addEventListener('error', resolve); }); })); }")

        margins = {'top': '40mm', 'right': '25mm', 'bottom': '40mm', 'left': '25mm'} if hide_metadata else {'top': '0', 'right': '0', 'bottom': '0', 'left': '0'}

        page.pdf(
            path=str(output_path),
            format='A4',
            print_background=True,
            margin=margins,
            display_header_footer=False,
            prefer_css_page_size=not hide_metadata
        )
        browser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input MD file")
    parser.add_argument("--style", default="federation", help="PDF visual style")
    parser.add_argument("--output", help="Output path")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive styler")
    args = parser.parse_args()

    generate_pdf(args.input, output_path=args.output, style=args.style, interactive=args.interactive)
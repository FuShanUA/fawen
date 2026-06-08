"""
generate_pdf.py - Playwright-based PDF Generator

Converts markdown with metadata to professionally formatted PDF.
Uses Playwright (Chromium) for accurate CSS rendering.
"""

import sys
import os
import re
import markdown
from playwright.sync_api import sync_playwright
import pathlib
from pathlib import Path


def parse_metadata(text):
    """Extract metadata using the unified MetadataEngine."""
    from common_utils import MetadataEngine, extract_clean_body
    meta_eng = MetadataEngine(text)

    metadata = {
        'title': meta_eng.get('title'),
        'eng_title': meta_eng.get('eng_title'),
        'source': meta_eng.get('source'),
        'date': meta_eng.get('date'),
        'url': meta_eng.get('url'),
        'cover_logo': meta_eng.get('cover_logo'),
        'cover_header': meta_eng.get('cover_header')
    }

    # Format date for cover (YYYY-MM-DD or YYYY-MM)
    date_str = metadata['date']
    if date_str:
        try:
            import re as re_mod
            # Handle YYYY-MM-DD
            match_full = re_mod.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
            if match_full:
                metadata['formatted_date'] = f"{match_full.group(1)}年{int(match_full.group(2))}月{int(match_full.group(3))}日"
            else:
                # Handle YYYY-MM
                match_short = re_mod.match(r'(\d{4})-(\d{2})', date_str)
                if match_short:
                    metadata['formatted_date'] = f"{match_short.group(1)}年{int(match_short.group(2))}月"
                else:
                    metadata['formatted_date'] = date_str
        except:
            metadata['formatted_date'] = date_str
    else:
        metadata['formatted_date'] = 'Unknown'

    return metadata, extract_clean_body(text)


def build_cover_html(metadata):
    """Build cover page HTML with CSS."""
    title = metadata.get('title', 'Untitled')
    eng_title = metadata.get('eng_title', '')
    source = metadata.get('source', 'Unknown')
    date = metadata.get('formatted_date', 'Unknown')

    # Decoupled cover elements
    header_text = metadata.get('cover_header', '数据管理前沿资料译介')
    logo_path = metadata.get('cover_logo', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "logo.png"))

    # Split titles if they contain colons
    cn_main, cn_sub = title, ''
    if '：' in title:
        parts = title.split('：', 1)
        cn_main, cn_sub = parts[0], parts[1]

    eng_main, eng_sub = eng_title, ''
    if ':' in eng_title:
        parts = eng_title.split(':', 1)
        eng_main, eng_sub = parts[0].strip(), parts[1].strip()

    logo_html = ''
    if os.path.exists(logo_path):
        import base64
        try:
            with open(logo_path, "rb") as img_file:
                b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                logo_html = f'<img src="data:image/png;base64,{b64_string}" class="logo" />'
        except Exception as e:
            print(f"Error loading logo: {e}")
    else:
        print(f"Warning: Logo not found at {logo_path}")

    return f'''
    <div class="cover-page">
        <!-- Blue header bar at absolute top -->
        <div class="header-bar"></div>

        <!-- Header with text and logo -->
        <div class="header-content">
            <span class="header-text">{header_text}</span>
            {logo_html}
        </div>

        <!-- Title section -->
        <div class="title-section">
            <h1 class="cn-main">{cn_main}</h1>
            {"<h2 class='cn-sub'>" + cn_sub + "</h2>" if cn_sub else ""}
            <p class="eng-main">{eng_main}</p>
            {"<p class='eng-sub'>" + eng_sub + "</p>" if eng_sub else ""}
        </div>

        <!-- Producer info -->
        <div class="producer-info">
            <p>出品方：{source}</p>
            <p>出品时间：{date}</p>
        </div>
    </div>
    '''


def render_cover_overlay(template_path, output_path, metadata):
    """Directly overlay text on PDF cover using fitz (PyMuPDF) and styler_federation.json."""
    import fitz
    import json
    import os

    # 1. Load config
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "styler_federation.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        # Fallback to defaults if config missing
        config = {
            "cover_cn_font": "STKaiti",
            "title": {"cn_size": 30, "en_size": 18, "color": [0, 0.2, 0.4], "cn_pos": [294, 236, 540, 336], "en_gap": 18},
            "publisher": {"size": 12, "pos": [180, 750, 570, 770]},
            "date": {"size": 12, "pos": [370, 772, 570, 792]}
        }

    doc = fitz.open(template_path)
    page = doc[0] # Assume first page is the cover

    # 注册并加载 Mac 系统本地的高保真华文楷体，强制其应用于 stkaiti 别名
    font_path = "/System/Library/Fonts/Supplemental/STKaiti.ttf"
    if not os.path.exists(font_path):
        font_path = "/Library/Fonts/STKaiti.ttf"
    
    # 针对较新 macOS 系统中高保真字体动态哈希存储的特点进行增强检索
    if not os.path.exists(font_path):
        import glob
        import sys
        if sys.platform == "darwin":
            # 优先匹配 AssetsV2 动态目录
            assets = glob.glob("/System/Library/AssetsV2/com_apple_MobileAsset_Font*/**/*.asset/AssetData/Kaiti.ttc", recursive=True)
            if assets:
                font_path = assets[0]
            else:
                # 兜底匹配 FontServices Subsets 目录
                fs_path = "/System/Library/PrivateFrameworks/FontServices.framework/Versions/A/Resources/Fonts/Subsets/Kaiti.ttc"
                if os.path.exists(fs_path):
                    font_path = fs_path

    if os.path.exists(font_path):
        try:
            page.insert_font(fontname="stkaiti", fontfile=font_path)
        except Exception as fe:
            print(f"Warning: insert_font error: {fe}")

    # 2. Add Title
    title_cn = metadata.get('title', '无标题')
    title_en = metadata.get('eng_title', '')

    t_cfg = config.get("title", {})
    cn_rect = fitz.Rect(t_cfg["cn_pos"])

    # Draw CN Title
    page.insert_textbox(
        cn_rect, title_cn,
        fontsize=t_cfg["cn_size"],
        fontname="stkaiti", # Use system alias for STKaiti
        color=t_cfg["color"],
        align=fitz.TEXT_ALIGN_RIGHT
    )

    # Draw EN Title (below CN with gap)
    if title_en:
        en_rect = fitz.Rect(cn_rect.x0, cn_rect.y1 + t_cfg["en_gap"], cn_rect.x1, cn_rect.y1 + t_cfg["en_gap"] + t_cfg["en_size"] * 2)
        page.insert_textbox(
            en_rect, title_en,
            fontsize=t_cfg["en_size"],
            fontname="helv", # Standard Helvetica for EN
            color=[0.2, 0.2, 0.2],
            align=fitz.TEXT_ALIGN_RIGHT
        )

    # 3. Add Publisher (Source)
    source = metadata.get('source', '')
    if source:
        p_cfg = config.get("publisher", {})
        p_rect = fitz.Rect(p_cfg["pos"])
        # 限制 Rect 宽度在 220 像素内以防止字间距被奇怪拉宽
        if p_rect.x1 - p_rect.x0 > 220:
            p_rect.x0 = p_rect.x1 - 220
        page.insert_textbox(
            p_rect, f"出品方：{source}",
            fontsize=p_cfg["size"],
            fontname="stkaiti",
            color=[0.2, 0.2, 0.2],
            align=fitz.TEXT_ALIGN_RIGHT
        )

    # 4. Add Date
    date = metadata.get('formatted_date', '')
    if date:
        d_cfg = config.get("date", {})
        d_rect = fitz.Rect(d_cfg["pos"])
        # 限制 Rect 宽度在 220 像素内以防止字间距被奇怪拉宽
        if d_rect.x1 - d_rect.x0 > 220:
            d_rect.x0 = d_rect.x1 - 220
        page.insert_textbox(
            d_rect, f"出品时间：{date}",
            fontsize=d_cfg["size"],
            fontname="stkaiti",
            color=[0.2, 0.2, 0.2],
            align=fitz.TEXT_ALIGN_RIGHT
        )

    doc.save(output_path)
    doc.close()
    return True


def build_source_footer(metadata):
    """Build source info footer for the last page."""
    url = metadata.get('url', '')
    eng_title = metadata.get('eng_title', '') or metadata.get('title', 'Original Article')

    if not url:
        return ''

    return f'''
    <div class="source-footer">
        <p>资料来源：<a href="{url}" target="_blank">{eng_title}</a></p>
    </div>
    '''


def extract_executive_summary(text):
    """Extract Executive Summary block marked by HTML comments.

    Looks for <!-- EXECUTIVE_SUMMARY_START --> ... <!-- EXECUTIVE_SUMMARY_END -->
    Returns (summary_html, remaining_text).
    """
    import re
    pattern = r'<!-- EXECUTIVE_SUMMARY_START -->(.*?)<!-- EXECUTIVE_SUMMARY_END -->'
    match = re.search(pattern, text, re.DOTALL)

    if match:
        summary_md = match.group(1).strip()
        remaining = text[:match.start()] + text[match.end():]

        md = markdown.Markdown(extensions=['extra', 'toc', 'tables', 'md_in_html'])
        summary_html = md.convert(summary_md)

        wrapped = f'''
        <div class="executive-summary">
            <h1>内容概览</h1>
            {summary_html}
        </div>
        '''
        return wrapped, remaining.strip()

    return '', text


def build_content_html(markdown_content):
    """Convert markdown to HTML."""
    md = markdown.Markdown(extensions=['extra', 'toc', 'tables', 'md_in_html'])
    return md.convert(markdown_content)


def get_css():
    """Return CSS for the PDF.

    Font strategy: Direct font stack (NO @font-face unicode-range).
    Chromium's PDF renderer handles @font-face with unicode-range poorly
    for CJK, causing each character to render with individual spacing (单字处理).
    Fix: Use 'Calibri' first (covers Latin/digits), then 'STKaiti'/'华文楷体' (covers CJK).
    STKaiti is pre-installed on Windows. No extra font installation needed.
    """
    return '''
    @page {
        size: A4;
        margin: 2.5cm 2cm;
        @bottom-center {
            content: counter(page);
            font-family: 'Calibri', 'Arial', 'STKaiti', '华文楷体', 'KaiTi', sans-serif;
            font-size: 10pt;
        }
    }

    @page cover {
        margin: 0;
        @bottom-center { content: none; }
    }

    @page blank {
        margin: 0;
        @bottom-center { content: none; }
    }

    @page back-cover {
        margin: 0;
        @bottom-center { content: none; }
        background-color: #003366;
    }

    @page exec-summary {
        margin: 2.5cm 2cm;
        @bottom-center { content: none; }
    }

    * {
        box-sizing: border-box;
        letter-spacing: 0 !important;
        font-kerning: none !important;
        font-variant-ligatures: none !important;
        text-rendering: optimizeSpeed;
        -webkit-font-smoothing: antialiased;
    }

    body {
        margin: 0;
        padding: 0;
        /* Robust font stack. Prioritize STKaiti for traditional brand look */
        font-family: '华文楷体', 'STKaiti', '楷体', 'KaiTi', 'Microsoft YaHei', '微软雅黑', 'SimSun', '宋体', 'Calibri', 'Arial', serif;
        font-size: 14pt;
        line-height: 1.3;
        color: #333;
        background-color: transparent !important;
    }

    .content {
        page: auto;
    }

    /* Image Scaling - prevent truncation across page breaks */
    img {
        max-width: 100%;
        max-height: 180pt;     /* Roughly 1/4 of A4 height, ensures compact layout */
        height: auto;
        width: auto;
        object-fit: contain;   /* Maintain aspect ratio */
        display: block;
        margin: 12pt auto;
        page-break-inside: avoid;
    }

    /* Cover page styles */
    .cover-page {
        page: cover;
        width: 100%;
        height: 100vh;
        position: relative;
        display: flex;
        flex-direction: column;
        page-break-after: always;
        overflow: hidden;
    }

    .header-bar {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 36pt;
        background-color: #003366;
    }

    .header-content {
        margin-top: 50pt;
        padding: 0 60pt;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: 12pt;
    }

    .header-text {
        font-family: 'DengXian', 'STKaiti', '华文楷体', 'Microsoft YaHei', sans-serif;
        font-size: 16pt;
        font-style: italic;
        color: #333;
        flex: 1;
    }

    .logo {
        height: 50pt;
        object-fit: contain;
    }

    .title-section {
        flex: 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
        padding: 0 60pt;
        text-align: right;
    }

    .cn-main {
        font-family: 'STKaiti', '华文楷体', 'KaiTi', 'Microsoft YaHei', sans-serif;
        font-size: 30pt;
        font-weight: bold;
        color: #003366;
        margin: 0 0 8pt 0;
        line-height: 1.3;
    }

    .cn-sub {
        font-family: 'STKaiti', '华文楷体', 'KaiTi', 'Microsoft YaHei', sans-serif;
        font-size: 28pt;
        font-weight: bold;
        color: #003366;
        margin: 0 0 16pt 0;
        line-height: 1.3;
    }

    .eng-main, .eng-sub {
        font-family: 'Calibri', 'Segoe UI', 'Arial', sans-serif;
        font-size: 18pt;
        color: #333;
        margin: 4pt 0;
        text-align: right;
    }

    .producer-info {
        padding: 0 60pt 80pt 60pt;
    }

    .producer-info p {
        font-family: 'Calibri', 'STKaiti', '华文楷体', 'Microsoft YaHei', sans-serif;
        font-size: 14pt;
        margin: 2pt 0;
        color: #333;
    }

    /* ===== Executive Summary Page ===== */
    .executive-summary {
        page: exec-summary;
        page-break-before: always;
        page-break-after: always;
    }

    .executive-summary h1 {
        font-family: 'STKaiti', '华文楷体', 'KaiTi', 'Microsoft YaHei', sans-serif;
        font-size: 26pt;
        color: #003366;
        text-align: center;
        margin-top: 20pt;
        margin-bottom: 24pt;
        page-break-before: avoid;
        border-bottom: 3pt solid #003366;
        padding-bottom: 12pt;
    }

    .executive-summary h2 {
        font-family: 'STKaiti', '华文楷体', 'KaiTi', 'Microsoft YaHei', sans-serif;
        font-size: 18pt;
        color: #003366;
        margin-top: 20pt;
        margin-bottom: 10pt;
    }

    .executive-summary blockquote {
        border-left: 4pt solid #c0a040;
        background-color: #faf8f0;
        padding: 10pt 16pt;
        margin: 10pt 0;
        font-style: italic;
        font-size: 13pt;
    }

    /* ===== Content Heading Styles ===== */
    h1 {
        font-family: 'STKaiti', '华文楷体', 'KaiTi', 'SimSun', '宋体', 'Microsoft YaHei', 'Calibri', sans-serif;
        font-size: 24pt;
        color: #003366;
        margin-top: 24pt;
        margin-bottom: 16pt;
        page-break-before: always;
        line-height: 1.3;
    }

    h1:first-of-type {
        page-break-before: avoid;
    }

    h2 {
        font-family: 'STKaiti', '华文楷体', 'KaiTi', 'SimSun', '宋体', 'Microsoft YaHei', 'Calibri', sans-serif;
        font-size: 20pt;
        color: #003366;
        margin-top: 20pt;
        margin-bottom: 12pt;
        line-height: 1.3;
    }

    h3 {
        font-family: 'STKaiti', '华文楷体', 'KaiTi', 'SimSun', '宋体', 'Microsoft YaHei', 'Calibri', sans-serif;
        font-size: 16pt;
        color: #333;
        margin-top: 16pt;
        margin-bottom: 8pt;
        font-weight: bold;
        line-height: 1.3;
    }

    /* ===== Paragraph & Body Text ===== */
    p {
        font-size: 14pt;
        text-align: left;      /* Disable justify to prevent character gaps */
        margin: 12pt 0 6pt 0;
        line-height: 1.3;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin: 12pt 0;
        font-size: 11pt;
    }

    th, td {
        border: 1px solid #ccc;
        padding: 6pt 8pt;
        text-align: left;
    }

    th {
        background-color: #003366;
        color: white;
        font-family: 'Calibri', 'STKaiti', '华文楷体', sans-serif;
    }

    tr:nth-child(even) {
        background-color: #f5f5f5;
    }

    ul, ol {
        margin: 12pt 0 6pt 0;
        padding-left: 24pt;
    }

    li {
        margin: 4pt 0;
        line-height: 1.25;
    }

    blockquote {
        border-left: 4pt solid #003366;
        margin: 12pt 0 6pt 0;
        padding: 8pt 16pt;
        background-color: #f5f5f5;
    }

    code {
        font-family: 'Consolas', monospace;
        background-color: #f0f0f0;
        padding: 2pt 4pt;
        font-size: 10pt;
    }

    pre {
        background-color: #f0f0f0;
        padding: 12pt;
        overflow-x: auto;
        font-size: 10pt;
    }

    /* Blank page style */
    .blank-page {
        page: blank;
        break-before: page;
        width: 100%;
        height: 100%;
    }

    /* Back cover style */
    .back-cover {
        page: back-cover;
        break-before: page;
        width: 100%;
        height: 100%;
    }

    /* Source Footer Style */
    .source-footer {
        margin-top: 48pt;
        border-top: 1px solid #ccc;
        padding-top: 12pt;
        font-size: 10pt;
        color: #666;
    }

    .source-footer a {
        color: #003366;
        text-decoration: underline;
    }
    '''


def generate_pdf(input_path, output_path=None, cover_pdf=None, pack_dir=None):
    """Generate PDF from markdown file."""
    if not os.path.exists(input_path):
        print(f"Error: File {input_path} not found.")
        return

    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    metadata, content = parse_metadata(text)

    # Pack selection logic
    auto_pack_dir = None
    import sys
    sys.path.append(str(pathlib.Path(__file__).parent.parent.parent / "pdfL10N"))
    try:
        import json
        _cfg_path = pathlib.Path(__file__).parent.parent.parent / "pdfL10N" / "config.json"
        if _cfg_path.exists():
            with open(_cfg_path, "r", encoding="utf-8") as f:
                _cfg = json.load(f)
                auto_pack_dir = _cfg.get("TEMPLATE_PACK_DIR")
                default_tpl = _cfg.get("DEFAULT_TEMPLATE")
        else:
            import cover_customizer
            default_tpl = cover_customizer.DEFAULT_TEMPLATE
    except Exception as e:
        print(f"Warning during config auto-discovery: {e}")
        default_tpl = None

    # Determine effective pack directory (priority: CLI > Config)
    eff_pack_dir = pack_dir or auto_pack_dir

    pack_cover = None
    pack_back = None
    pack_inside = None

    if eff_pack_dir and os.path.exists(eff_pack_dir):
        print(f"Template pack discovered at: {eff_pack_dir}")
        pdir = Path(eff_pack_dir)
        if (pdir / "cover.pdf").exists(): pack_cover = str(pdir / "cover.pdf")
        if (pdir / "back.pdf").exists(): pack_back = str(pdir / "back.pdf")
        if (pdir / "inside.pdf").exists(): pack_inside = str(pdir / "inside.pdf")

    # Final priority for cover
    final_cover_template = cover_pdf or default_tpl or pack_cover

    # Build HTML
    # If using PDF cover template, we omit the HTML cover
    cover_html = build_cover_html(metadata) if not final_cover_template else ""

    # Extract Executive Summary (if present in the markdown)
    exec_summary_html, content = extract_executive_summary(content)

    content_html = build_content_html(content)

    # Append source info to content
    source_footer = build_source_footer(metadata)
    if source_footer:
        content_html += source_footer

    # Logic for blank page + Back Cover
    # If using pack_inside, we'll use that instead of a simple blank div
    blank_after_cover = '<div class="blank-page">&nbsp;</div>' if not pack_inside else ""

    # Back cover HTML - omit if using pack_back
    back_cover_html = '<div class="back-cover"><!-- Optional content --></div>' if not pack_back else ""

    # JavaScript to handle odd/even logic before printing?
    # Playwright allows executing JS.
    # We can inject JS to check document.body.scrollHeight or similar, but exact page breaks are hard.
    # Alternative: Generate without back cover, count pages, then regenerate? Slow.
    # CSS paged media has 'page-break-before: always'.
    # 'break-before: right' (CSS Paged Media Level 3) forces start on right page (odd).
    # Playwright/Chromium supports 'break-before: page' but 'right/left' support is partial.
    # Let's try CSS 'break-before: left' for back cover? (Force back cover to be even?)
    # Or just 'break-before: page'.

    # For now, implemented "Blank after Cover" (item 7 part 1).
    # Item 7 part 2 (conditional blank before back) is tricky in HTML-to-PDF without calc.
    # Let's add specific blank page logic if we can, or just standard back cover.

    # Determine Output Path
    if not output_path:
        base_dir = os.path.dirname(input_path)
        title = metadata.get('title', 'output')
        source = metadata.get('source', 'Unknown')
        date = metadata.get('formatted_date', '')
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:50]
        base_name = f"{date}_{source}_{safe_title}"

        # Versioning logic
        version = 1
        output_path = os.path.join(base_dir, f"{base_name}_v{version}.pdf")
        while os.path.exists(output_path):
            version += 1
            output_path = os.path.join(base_dir, f"{base_name}_v{version}.pdf")

    # Double-Pass Logic for Back Cover:
    # 1. Generate PDF WITHOUT Back Cover
    # 2. Count Pages
    # 3. If Odd -> Add Blank + Back Cover; If Even -> Just Back Cover
    # 4. Generate Final PDF

    # Pass 1: Content Only (Including Cover + BlankAfterCover)
    html_pass1 = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>{get_css()}</style>
    </head>
    <body>
        {cover_html}
        {blank_after_cover}
        {exec_summary_html}
        <div class="content">
            {content_html}
        </div>
    </body>
    </html>
    '''

    temp_pdf_path = output_path.replace('.pdf', '_temp.pdf')
    temp_html_path = output_path.replace('.pdf', '_temp.html')

    with open(temp_html_path, 'w', encoding='utf-8') as f:
        f.write(html_pass1)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(pathlib.Path(temp_html_path).as_uri(), wait_until='networkidle')
        page.pdf(
            path=temp_pdf_path,
            format='A4',
            print_background=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'}
        )
        browser.close()

    if os.path.exists(temp_html_path):
        os.remove(temp_html_path)

    # Count Pages
    try:
        from pypdf import PdfReader
        reader = PdfReader(temp_pdf_path)
        page_count = len(reader.pages)
        print(f"Pass 1 Page Count: {page_count}")
    except Exception as e:
        print(f"Error counting pages: {e}. Defaulting to no extra blank.")
        page_count = 0 # Fallback

    # Conditional Logic for Blank/Inside page
    extra_blank_html = ""
    # Structure: [Content Pages] + [Optional Blank/Inside] + [Back Cover]

    # Determine what to use for "extra padding"
    p_inside = pack_inside if pack_inside else None # Path or None

    if page_count > 0 and (page_count % 2 == 0):
        print(f"Page count is {page_count} (Even). Inserting blank page to ensure even total.")
        if not pack_inside:
            extra_blank_html = '<div class="blank-page">&nbsp;</div>'
        # if pack_inside exists, we will handle it in the PDF merge stage, not HTML
    else:
        print(f"Page count is {page_count} (Odd). No extra blank page needed.")
        p_inside_needed = False

    # Pass 2: Final PDF (HTML part only contains content)
    back_cover_html = '<div class="back-cover"></div>' if not pack_back else ""

    full_html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>{get_css()}</style>
    </head>
    <body>
        {cover_html}
        {blank_after_cover}
        {exec_summary_html}
        <div class="content">
            {content_html}
        </div>

        {extra_blank_html}

        {back_cover_html}
    </body>
    </html>
    '''

    # Save Final HTML
    html_path = output_path.replace('.pdf', '.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(full_html)
    print(f"HTML saved to: {html_path}")

    # Generate Final PDF
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(pathlib.Path(html_path).as_uri(), wait_until='networkidle')
        page.pdf(
            path=output_path,
            format='A4',
            print_background=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'}
        )
        browser.close()

    # Cleanup Temp HTML/PDF from Playwright
    if os.path.exists(html_path):
        os.remove(html_path)
    if os.path.exists(temp_pdf_path):
        os.remove(temp_pdf_path)

    # POST-PROCESSING: Merge with PDF Templates if Pack/Cover provided
    try:
        import fitz
        doc_main = fitz.open(output_path)
        final_doc = fitz.open()

        # 1. Add Cover
        if final_cover_template and os.path.exists(final_cover_template):
            print(f"Applying custom cover logic (Direct Fitz Overlay)...")
            try:
                custom_cover_path = pathlib.Path(output_path).parent / "custom_cover.pdf"
                render_cover_overlay(str(final_cover_template), str(custom_cover_path), metadata)
                c_doc = fitz.open(custom_cover_path)
                final_doc.insert_pdf(c_doc)
                c_doc.close()
                # Cleanup custom cover PDF
                if os.path.exists(custom_cover_path):
                    os.remove(custom_cover_path)
            except Exception as e:
                print(f"Warning: PDF cover customization failed: {e}")
                c_doc = fitz.open(final_cover_template)
                final_doc.insert_pdf(c_doc)
                c_doc.close()

        # 2. Prepare Background (Inside style)
        i_bk_doc = None
        i_bg_page = None
        if pack_inside and os.path.exists(pack_inside):
            print(f"Applying {pack_inside} as background to all content pages.")
            i_bk_doc = fitz.open(pack_inside)
            i_bg_page = i_bk_doc[0]

        # 3. Add Content with Background Overlay
        for pno in range(len(doc_main)):
            if i_bg_page:
                # Create a new page with inside template background
                new_page = final_doc.new_page(width=i_bg_page.rect.width, height=i_bg_page.rect.height)
                new_page.show_pdf_page(new_page.rect, i_bk_doc, 0)
                # Overlay content (ensured transparent background in CSS)
                new_page.show_pdf_page(new_page.rect, doc_main, pno, overlay=True)
            else:
                final_doc.insert_pdf(doc_main, from_page=pno, to_page=pno)

        if i_bk_doc:
            i_bk_doc.close()
        doc_main.close()

        # 4. Conditional Inside Page (before back cover)
        # We need to check if we need another blank/inside to keep even pages.
        if (len(final_doc) % 2 == 0) and pack_back:
            print(f"Final doc length is {len(final_doc)} (Even) before back cover. Adding separator to ensure even total.")
            if pack_inside and os.path.exists(pack_inside):
                i_doc = fitz.open(pack_inside)
                final_doc.insert_pdf(i_doc)
                i_doc.close()
            else:
                # Add a truly blank page if no inside.pdf
                final_doc.new_page()

        # 5. Add Back Cover
        if pack_back and os.path.exists(pack_back):
            print(f"Inserting back cover from pack: {pack_back}")
            b_doc = fitz.open(pack_back)
            final_doc.insert_pdf(b_doc)
            b_doc.close()

        # Save to a temporary final file first, then rename to avoid file lock issues
        final_output_path = output_path.replace('.pdf', '_final.pdf')
        final_doc.save(final_output_path, incremental=False, encryption=0, garbage=4, deflate=True)
        final_doc.close()

        # Clean up original and rename
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass # Already handled by rename if needed
        os.rename(final_output_path, output_path)
        print(f"Final PDF structure assembled for {output_path}")

        # CLEANUP ALL INTERMEDIATE FILES
        for tmp in [html_path, temp_pdf_path]:
            if tmp and os.path.exists(tmp):
                try: os.remove(tmp)
                except: pass

        custom_cover_path = pathlib.Path(output_path).parent / "custom_cover.pdf"
        if os.path.exists(custom_cover_path):
            try: os.remove(custom_cover_path)
            except: pass

    except Exception as e:
        print(f"Error in PDF post-processing: {e}")
        # Final desperate cleanup of HTML at least
        if os.path.exists(html_path):
            try: os.remove(html_path)
            except: pass

    return output_path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Generate PDF from Markdown")
    parser.add_argument("input_md", help="Path to input markdown file")
    parser.add_argument("output_pdf", nargs="?", help="Path to output PDF file")
    parser.add_argument("--cover-pdf", help="Path to a PDF cover template to customize and prepend")
    parser.add_argument("--pack-dir", help="Directory containing template pack (cover.pdf, back.pdf, inside.pdf)")

    args = parser.parse_args()
    generate_pdf(args.input_md, args.output_pdf, args.cover_pdf, args.pack_dir)
import fitz
import os
import json
import re
import sys
from pathlib import Path

# --- Constants & Config Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STYLE_CONFIG = os.path.join(BASE_DIR, "config", "styler_federation.json")
_USER_FONTS = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts")

# Template Paths
TEMPLATE_DIR = os.path.join(BASE_DIR, "assets", "templates", "federation")
COVER_TEMPLATE = os.path.join(TEMPLATE_DIR, "cover.pdf")
INSIDE_TEMPLATE = os.path.join(TEMPLATE_DIR, "inside.pdf")
BACK_TEMPLATE = os.path.join(TEMPLATE_DIR, "back.pdf")

_DEFAULT_STYLE = {
    "cover_cn_font": "SourceHanSansCN-Bold",
    "cover_en_font": "SourceHanSansCN-Light",
    "title": {
        "align": "right",
        "cn_size": 42,
        "en_size": 26,
        "color": [0.0, 0.2, 0.4],  # 深蓝
        "color_name": "深蓝",
        "cn_pos": [294.63, 236.57, 540.39, 306.57],
        "en_gap": 18.0
    },
    "publisher": {
        "align": "right",
        "size": 12,
        "pos": [180.0, 750.0, 570.0, 770.0]
    },
    "date": {
        "align": "right",
        "size": 12,
        "pos": [370.0, 772.0, 570.0, 792.0]
    }
}

def _load_style():
    if os.path.exists(_STYLE_CONFIG):
        try:
            with open(_STYLE_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _DEFAULT_STYLE

def _clean_meta_value(val):
    if not val: return ""
    v = str(val).strip().strip("'").strip('"').replace("'''", "").strip()
    # 移除可能残留的冒号
    v = re.sub(r'^[:：]\s*', '', v)

    # 增强：检测日期 YYYY-MM-DD 并格式化为 YYYY年MM月DD日
    if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', v):
        try:
            from datetime import datetime
            dt = datetime.strptime(v, "%Y-%m-%d")
            return dt.strftime("%Y年%m月%d日")
        except: pass

    # 检测日期 YYYY-MM 并格式化为 YYYY年M月
    if re.match(r'^\d{4}-\d{1,2}$', v):
        try:
            from datetime import datetime
            dt = datetime.strptime(v, "%Y-%m")
            return dt.strftime("%Y年%m月")
        except: pass

    return v

def _extract_slug_title(url):
    if not url: return "Original Article"
    clean_url = str(url).rstrip('/').split('://')[-1]
    parts = clean_url.split('/')
    name = parts[-1] if parts[-1] else (parts[-2] if len(parts) > 1 else "Article")
    # 清理 URL slug：将连字符/下划线转换为空格，并应用首字母大写
    name = re.sub(r'[^a-zA-Z0-9]', ' ', name)
    return " ".join([w.capitalize() for w in name.split() if w.lower() not in ['in', 'the', 'of', 'and', 'a', 'an']])

def _find_font(font_name):
    # 【核心修复】排除 Variable Font (VF) 以防止 Acrobat 报错
    # 优先匹配静态字体 (Static OTF/TTF)，在 macOS 下智能匹配系统原生苹方/冬青黑体/华文楷体等
    import glob
    import sys

    font_file_map = {
        "SourceHanSansCN-Bold": [
            "SourceHanSansCN-Bold.otf",
            "Source_Han_Sans_SC_Bold.otf",
            "Hiragino Sans GB.ttc",       # macOS 极其精美的高保真冬青黑体
            "STHeiti Medium.ttc",         # macOS 经典华文黑体
            "PingFang.ttc",               # macOS 苹方
            "msyhbd.ttc",                 # Windows 微软雅黑粗体
            "simhei.ttf"                  # 黑体
        ],
        "SourceHanSansCN-Light": [
            "SourceHanSansCN-Light.otf",
            "STHeiti Light.ttc",          # macOS 经典华文黑体细体
            "Hiragino Sans GB.ttc",
            "PingFang.ttc",
            "msyhl.ttc",                  # Windows 微软雅黑细体
            "calibrib.ttf",
            "msyh.ttc"
        ],
        "华文楷体": [
            "STKAITI.TTF",
            "stkaiti.ttf",
            "STKAITI.OTF",
            "Kaiti.ttc",                  # macOS 高保真系统楷体
            "simkai.ttf",
            "SIMKAI.TTF",
            "楷体"
        ],
        "STKaiti": [
            "STKAITI.TTF",
            "stkaiti.ttf",
            "STKAITI.OTF",
            "Kaiti.ttc",
            "simkai.ttf",
            "SIMKAI.TTF"
        ]
    }

    candidates = font_file_map.get(font_name, [font_name])
    for candidate in candidates:
        if "-VF" in candidate or "_VF" in candidate: continue

        # 尝试的后缀组合
        trials = [candidate]
        if "." not in candidate:
            trials.extend([f"{candidate}.ttf", f"{candidate}.otf", f"{candidate}.ttc", f"{candidate.upper()}.TTF"])

        for trial in trials:
            # 1. macOS AssetsV2 动态查找 (如 Kaiti.ttc, PingFang.ttc)
            if sys.platform == "darwin":
                assets_paths = glob.glob(f"/System/Library/AssetsV2/com_apple_MobileAsset_Font*/**/*.asset/AssetData/{trial}", recursive=True)
                if assets_paths:
                    return assets_paths[0]
                
                # macOS FontServices Subsets 目录
                fs_path = f"/System/Library/PrivateFrameworks/FontServices.framework/Versions/A/Resources/Fonts/Subsets/{trial}"
                if os.path.exists(fs_path):
                    return fs_path
                
                # macOS Reserved 目录
                res_path = f"/System/Library/PrivateFrameworks/FontServices.framework/Versions/A/Resources/Reserved/{trial}"
                if os.path.exists(res_path):
                    return res_path

            # 2. Windows 用户目录
            path = os.path.join(_USER_FONTS, trial)
            if os.path.exists(path): return path

            # 3. Windows 系统目录
            path = os.path.join(r"C:\Windows\Fonts", trial)
            if os.path.exists(path): return path

            # 4. macOS 标准系统目录
            if sys.platform == "darwin":
                for mac_dir in ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]:
                    path = os.path.join(mac_dir, trial)
                    if os.path.exists(path): return path

    return None

def _insert_auto_fit(page, rect, text, **kwargs):
    fontsize = kwargs.get('fontsize', 30)
    # 优先垂直居中并尝试单行放置
    # 增加一个小逻辑：如果高度很小，insert_textbox 会因为无法放置而返回负值，从而触发缩小字号
    while fontsize > 8:
        rc = page.insert_textbox(rect, text, **{**kwargs, "fontsize": fontsize})
        if rc >= 0:
            return rc
        fontsize -= 1.0
    # 实在放不下才允许更小的字号或折行（由底层的 Rect 决定）
    return page.insert_textbox(rect, text, **{**kwargs, "fontsize": 8})

def _mask_placeholders(page):
    areas = [
        fitz.Rect(50, 150, 560, 460), # Title zone
        fitz.Rect(50, 730, 560, 810)  # Footer zone
    ]
    blocks = page.get_text("dict")["blocks"]
    for b in blocks:
        if "lines" in b:
            rect = fitz.Rect(b["bbox"])
            for area in areas:
                if rect.intersects(area):
                    page.add_redact_annot(rect, fill=None)
    for kw in ["年", "月", "机构"]:
        for inst in page.search_for(kw):
            if inst.y0 > 700:
                page.add_redact_annot(inst, fill=None)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    page.clean_contents()

def customize_cover(template_path, output_path, metadata):
    if not os.path.exists(template_path):
        return template_path

    style = _load_style()
    cn_font = _find_font(style["cover_cn_font"])
    en_font = _find_font(style["cover_en_font"])

    src_doc = fitz.open(template_path)
    src_page = src_doc[0]
    _mask_placeholders(src_page)

    title = _clean_meta_value(metadata.get('title', 'Untitled'))
    cn_main = title

    eng_title = _clean_meta_value(metadata.get('eng_title'))
    url = metadata.get('url')

    # 增强检测：如果 eng_title 包含中文字符，则认为它已被错误翻译，触发降级或恢复逻辑
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', eng_title))

    if not eng_title or eng_title == title or has_chinese:
        # 只有在没有 eng_title、与中文标题完全一致或包含中文时才从 URL 提取
        slug = _extract_slug_title(url)
        # 如果从 URL 提取出的是纯数字（推文 ID），则忽略它以防误导
        if slug and not slug.replace(" ", "").isdigit():
            eng_title = slug
        elif has_chinese:
            # 如果无法从 URL 恢复，且原值为中文，则为了封面美观宁可留空也不显示中文
            eng_title = ""

    # 确保 eng_title 最终不会是 ID
    if eng_title and eng_title.replace(" ", "").isdigit():
        eng_title = None

    author = _clean_meta_value(metadata.get('author'))
    source = _clean_meta_value(metadata.get('source', metadata.get('publisher')))

    if author and source and author.lower() not in source.lower():
        publisher_text = f"{author}，{source}"
    elif author:
        publisher_text = author
    elif source:
        publisher_text = source
    else:
        publisher_text = "Postfdry Editorial"

    date = _clean_meta_value(metadata.get('date', metadata.get('publish_date', 'N/A')))

    # 统一标签命名，与模板占位符匹配
    source_text = f"作者/机构： {publisher_text}"
    date_text = f"发布时间： {date}"


    t_style = style["title"]
    p_style = style["publisher"]
    d_style = style["date"]
    align_map = {"right": fitz.TEXT_ALIGN_RIGHT, "center": fitz.TEXT_ALIGN_CENTER, "left": fitz.TEXT_ALIGN_LEFT}
    align = align_map.get(t_style["align"], fitz.TEXT_ALIGN_RIGHT)

    # 【优化】即使没找到指定字体，也通过兜底逻辑确保不使用空值
    cn_kw = {"fontname": "CNBold", "fontfile": cn_font} if cn_font else {"fontname": "china-ss"}
    en_kw = {"fontname": "ENLight", "fontfile": en_font} if en_font else {"fontname": "helv"}

    # 【动态检测】扩大标题盒宽度至页面 2/3 (约 396px)，且优先单行渲染
    # A4 宽约 595.27
    PAGE_WIDTH = 595.27
    MAX_TITLE_WIDTH = PAGE_WIDTH * 2/3

    t_rect = fitz.Rect(t_style["cn_pos"])
    # 锚点在右侧 t_rect.x1，向左扩展
    new_x0 = t_rect.x1 - MAX_TITLE_WIDTH
    # 先尝试单行高，强制触发字号缩小而非换行
    single_line_rect = fitz.Rect(new_x0, t_rect.y0, t_rect.x1, t_rect.y0 + t_style["cn_size"] * 1.3)

    _insert_auto_fit(src_page, single_line_rect, cn_main.strip(), **cn_kw, fontsize=t_style["cn_size"], color=t_style["color"], align=align)

    # y_ptr 指向下一个元素（英文标题）的位置
    y_ptr = single_line_rect.y1 + t_style["en_gap"]

    en_main_rect = fitz.Rect(new_x0, y_ptr, t_rect.x1, y_ptr + 35)
    _insert_auto_fit(src_page, en_main_rect, eng_title.strip(), **en_kw, fontsize=t_style["en_size"], color=t_style["color"], align=align)

    p_rect = fitz.Rect(p_style["pos"])
    if p_rect.x1 - p_rect.x0 > 380:
        p_rect.x0 = p_rect.x1 - 380
    _insert_auto_fit(src_page, p_rect, source_text, **cn_kw, fontsize=p_style["size"], color=t_style["color"], align=align_map.get(p_style["align"], align))

    d_rect = fitz.Rect(d_style["pos"])
    if d_rect.x1 - d_rect.x0 > 380:
        d_rect.x0 = d_rect.x1 - 380
    _insert_auto_fit(src_page, d_rect, date_text, **cn_kw, fontsize=d_style["size"], color=t_style["color"], align=align_map.get(d_style["align"], align))

    src_doc.save(output_path, garbage=4, clean=True, deflate=True)
    src_doc.close()
    return output_path

def assemble_federation_pdf(content_pdf_path, output_path, metadata):
    print(f"🛠️  正在组装研究院风 PDF (Acrobat Compatibility Mode)...")

    temp_cover = "temp_cover.pdf"
    customize_cover(COVER_TEMPLATE, temp_cover, metadata)

    content_doc = fitz.open(content_pdf_path)
    inside_tpl_doc = fitz.open(INSIDE_TEMPLATE)
    back_doc = fitz.open(BACK_TEMPLATE)

    final_doc = fitz.open()
    final_doc.insert_pdf(fitz.open(temp_cover))

    for i in range(len(content_doc)):
        tpl_page = inside_tpl_doc[0]
        new_page = final_doc.new_page(width=tpl_page.rect.width, height=tpl_page.rect.height)
        new_page.show_pdf_page(new_page.rect, inside_tpl_doc, 0)
        new_page.show_pdf_page(new_page.rect, content_doc, i)

    final_doc.insert_pdf(back_doc)
    final_doc.save(output_path, garbage=4, deflate=True)
    final_doc.close()

    if os.path.exists(temp_cover): os.remove(temp_cover)
    print(f"✅ 组装完成")

if __name__ == "__main__":
    pass
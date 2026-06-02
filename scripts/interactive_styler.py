import sys
import os
import json
import re
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt

# Add agents to path for MetadataEngine
scripts_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(os.path.dirname(scripts_dir), "agents")
if agents_dir not in sys.path:
    sys.path.insert(0, agents_dir)

try:
    from common_utils import MetadataEngine
except ImportError:
    MetadataEngine = None

# --- Configuration Constants ---
STYLE_CONFIG_PATH = r"/Users/shanfu/cc/Library/Tools/postfdry/config/styler_federation.json"

DEFAULT_STYLE = {
    "cover_cn_font": "SourceHanSansCN-Bold",
    "cover_en_font": "SourceHanSansCN-Light",
    "title": {
        "align": "right",
        "cn_size": 30,
        "en_size": 18,
        "color": [0.0, 0.2, 0.4],  # 深蓝
        "color_name": "深蓝",
        "cn_pos": [294.63, 236.57, 540.39, 266.57],
        "en_gap": 18.0
    },
    "publisher": {
        "align": "right",
        "size": 12,
        "pos": [245.08, 751.55, 570.64, 763.55]
    },
    "date": {
        "align": "right",
        "size": 12,
        "pos": [443.06, 773.61, 561.82, 785.61]
    },
    "inside": {
        "font": "华文楷体",
        "article_title_size": 24,
        "chapter_title_size": 20,
        "body_size": 14
    }
}

COLOR_MAP = {
    "深蓝": [0.0, 0.2, 0.4],
    "黑": [0.0, 0.0, 0.0],
    "灰": [0.4, 0.4, 0.4],
    "红": [0.8, 0.0, 0.0],
    "蓝": [0.0, 0.0, 1.0],
}

console = Console()

def load_config():
    if os.path.exists(STYLE_CONFIG_PATH):
        try:
            with open(STYLE_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_STYLE.copy()
    return DEFAULT_STYLE.copy()

def save_config(config):
    # Ensure config dir exists
    os.makedirs(os.path.dirname(STYLE_CONFIG_PATH), exist_ok=True)
    with open(STYLE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def display_preview(metadata):
    if not metadata:
        return

    # Process English title fallback
    title = metadata.get("title", "Untitled")
    eng_title = metadata.get("eng_title") or metadata.get("Original Title")
    if not eng_title or eng_title == title:
        # Simple extraction for preview
        url = metadata.get("url", "")
        slug = url.rstrip('/').split('/')[-1]
        eng_title = slug.replace("-", " ").title() if slug else "Original Article"

    preview_table = Table(title="[bold yellow]📄 待生成内容预览 (Metadata Preview)[/bold yellow]", box=None)
    preview_table.add_column("字段", style="cyan")
    preview_table.add_column("内容", style="white")
    preview_table.add_row("10. 中文标题 (Title)", title)
    preview_table.add_row("11. 英文标题 (EngTitle)", eng_title)
    preview_table.add_row("12. 发布机构 (Source)", metadata.get("source", metadata.get("Publisher", "N/A")))
    preview_table.add_row("13. 发布时间 (Date)", metadata.get("date", metadata.get("Published_Date", "N/A")))
    console.print(preview_table)
    console.print("-" * 50)

def save_metadata_to_file(input_file, metadata):
    """将修改后的元数据保存回 Markdown 文件的 YAML 区。"""
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            content = f.read()

        # 使用正则表达式精准替换 YAML 区域
        import yaml
        new_yaml = yaml.dump(metadata, allow_unicode=True, sort_keys=False)

        # 检测原有 YAML 区域
        if content.startswith("---"):
            # 替换现有的 YAML
            new_content = re.sub(r'^---\s*.*?\s*---\s*', f"---\n{new_yaml}---\n\n", content, count=1, flags=re.DOTALL)
        else:
            # 没找到 YAML，直接在前头加
            new_content = f"---\n{new_yaml}---\n\n" + content

        with open(input_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        console.print(f"[red]保存元数据失败: {e}[/red]")
        return False

def display_style(config):
    table = Table(title="[bold cyan]Postfdry PDF 风格配置 (Current Style Config)[/bold cyan]", show_header=True, header_style="bold magenta")
    table.add_column("要素 (Element)", style="dim")
    table.add_column("当前配置 (Current Value)", style="green")

    table.add_row("1. 封面中文字体", config["cover_cn_font"])
    table.add_row("2. 封面英文字体", config["cover_en_font"])
    t = config["title"]
    table.add_row("3. 标题样式", f"对齐: {t['align']}, 中文: {t['cn_size']}pt, 英文: {t['en_size']}pt, 颜色: {t.get('color_name', '自定义')}, 间隔: {t['en_gap']}pt")
    table.add_row("   标题位置", f"CN: {t['cn_pos']}")
    p = config["publisher"]
    table.add_row("4. 发布机构样式", f"对齐: {p['align']}, 字号: {p['size']}, 位置: {p['pos']}")
    d = config["date"]
    table.add_row("5. 发布时间样式", f"对齐: {d['align']}, 字号: {d['size']}, 位置: {d['pos']}")
    i = config["inside"]
    table.add_row("6. 内页字体", i["font"])
    table.add_row("7. 内页字号", f"标题: {i['article_title_size']}, 章节: {i['chapter_title_size']}, 正文: {i['body_size']}")

    console.print(table)

def apply_natural_language(config, metadata, nl_input):
    """
    解析自然语言指令并更新配置或元数据。支持多段指令 (例如: '标题居中, 机构改为 Sequoia')。
    """
    found = False
    # 1. 拆分多段指令 (支持中英文逗号、分号)
    segments = re.split(r'[，,；;]\s*', nl_input)

    meta_map = {
        "中文标题": "title", "标题": "title",
        "英文标题": "eng_title", "原文标题": "eng_title",
        "发布机构": "source", "机构": "source", "来源": "source",
        "发布时间": "date", "时间": "date", "日期": "date"
    }

    for seg in segments:
        seg = seg.strip()
        if not seg: continue

        seg_found = False

        # A. 元数据更新逻辑 - 优先探测
        for kw, field in meta_map.items():
            if kw in seg:
                # 提取 "改为", "设置为", ":" 之后的内容，但只到段落结束
                match = re.search(r'(?:改为|设置为|为|:：)\s*(.*)$', seg)
                if match:
                    val = match.group(1).strip()
                    metadata[field] = val
                    seg_found = True
                    found = True
                    console.print(f"[bold yellow]元数据更新: {kw} -> {val}[/bold yellow]")
                    break

        if seg_found: continue

        # B. 样式修改逻辑
        nums = re.findall(r"\d+\.?\d*", seg)

        # 颜色识别
        for name, values in COLOR_MAP.items():
            if name in seg:
                config["title"]["color"] = values
                config["title"]["color_name"] = name
                seg_found = True
                found = True
                console.print(f"[yellow]已更新颜色为: {name}[/yellow]")

        # 对齐识别
        if "居中" in seg:
            for k in ["title", "publisher", "date"]: config[k]["align"] = "center"
            seg_found = True; found = True
        elif "左对齐" in seg:
            for k in ["title", "publisher", "date"]: config[k]["align"] = "left"
            seg_found = True; found = True
        elif "右对齐" in seg:
            for k in ["title", "publisher", "date"]: config[k]["align"] = "right"
            seg_found = True; found = True

        # 字号识别
        if nums:
            val = float(nums[0])
            if "中文字号" in seg or "主标题字号" in seg:
                config["title"]["cn_size"] = val
                seg_found = True; found = True
            elif "英文字号" in seg or "副标题字号" in seg:
                config["title"]["en_size"] = val
                seg_found = True; found = True
            elif ("机构" in seg or "来源" in seg) and "字号" in seg:
                config["publisher"]["size"] = val
                seg_found = True; found = True
            elif ("时间" in seg or "日期" in seg) and "字号" in seg:
                config["date"]["size"] = val
                seg_found = True; found = True
            elif "正文字号" in seg:
                config["inside"]["body_size"] = val
                seg_found = True; found = True
            elif not seg_found: # 纯数字 fallback
                config["title"]["cn_size"] = val
                seg_found = True; found = True

    if not found:
        console.print("[red]未能识别修改意图。[/red]")
        console.print("[dim]提示: '标题改为...，机构改为...' / '字号32，居中'[/dim]")
    return config, metadata

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config()

    # 初始化元数据
    metadata = {}
    if input_file and os.path.exists(input_file) and MetadataEngine:
        with open(input_file, "r", encoding="utf-8") as f:
            metadata = MetadataEngine(f.read()).raw_meta

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        console.print(Panel("[bold green] Postfdry Federation Style Styler & Metadata Editor [/bold green]"))

        # 显示预览
        display_preview(metadata)
        display_style(config)

        console.print("\n[bold yellow]可用操作:[/bold yellow]")
        console.print(" - 输入 [bold cyan]修改要求[/bold cyan] (例如: '机构改为 Sequoia', '中文字号改为36', '标题居中')")
        console.print(" - 输入 [bold green]Y[/bold green] 或直接 [bold green]回车[/bold green] 确认并保存退出")
        console.print(" - 输入 [bold red]Q[/bold red] 退出但不保存")

        choice = Prompt.ask("\n[bold]待命 >[/bold]", default="Y")

        if choice.upper() == "Y" or choice == "":
            save_config(config)
            if input_file:
                save_metadata_to_file(input_file, metadata)
            console.print("[bold green]✅ 配置与元数据已保存。窗口即将关闭...[/bold green]")
            import time
            time.sleep(1.5)
            break
        elif choice.upper() == "Q":
            console.print("[yellow]已取消修改并退出。[/yellow]")
            break
        else:
            # 视为自然语言指令
            config, metadata = apply_natural_language(config, metadata, choice)
            import time
            time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import sys
import os
import re
import json
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

# Setup Paths
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
POSTFDRY_ROOT = os.path.dirname(CURRENT_DIR)
# Standalone fallback support: use local common directory if present, otherwise fallback to project-wide common
local_common = os.path.abspath(os.path.join(POSTFDRY_ROOT, "common"))
common_dir = local_common if os.path.exists(local_common) else os.path.abspath(os.path.join(POSTFDRY_ROOT, "..", "common"))

# Ensure agents and scripts are at the front of sys.path to take import priority over common_dir
for d in [common_dir, os.path.join(POSTFDRY_ROOT, "scripts"), os.path.join(POSTFDRY_ROOT, "agents")]:
    if d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)

import crawler_agent
from common_utils import MetadataEngine

class PostOSGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PostOS 2.0 - 智能化专家级出版工作流平台")
        self.root.geometry("980x630")

        # Set fonts
        self.ui_font = ("PingFang SC", 12) if sys.platform == "darwin" else ("Microsoft YaHei", 10)
        self.log_font = ("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10)

        # Process control
        self.current_process = None
        self.last_was_progress = False
        self.merged_button_state = "analyze"
        self.catchy_title_history = []
        self.standard_title_history = []

        # Vendor Map to LLMProvider Enum values
        self.vendor_map = {
            "Google Vertex AI": "vertex",
            "Google Gemini": "gemini",
            "OpenAI": "openai",
            "DeepSeek": "deepseek",
            "Silicon Flow": "siliconflow",
            "Zhipu (GLM)": "zhipu",
            "Moonshot (Kimi)": "moonshot",
            "Alibaba (Qwen)": "dashscope",
            "MiniMax": "minimax"
        }

        # Vendor Env Keys Mapping
        self.vendor_env_keys = {
            "Google Vertex AI": "VERTEX_SA_KEY_PATH",
            "Google Gemini": "GEMINI_API_KEY",
            "OpenAI": "OPENAI_API_KEY",
            "DeepSeek": "DEEPSEEK_API_KEY",
            "Silicon Flow": "SILICONFLOW_API_KEY",
            "Zhipu (GLM)": "ZHIPUAI_API_KEY",
            "Moonshot (Kimi)": "MOONSHOT_API_KEY",
            "Alibaba (Qwen)": "DASHSCOPE_API_KEY",
            "MiniMax": "MINIMAX_API_KEY"
        }

        # Load Settings
        self.settings_file = os.path.join(POSTFDRY_ROOT, "wip", "gui_settings.json")
        self.settings = self.load_settings()

        self.setup_ui()

        # Bind global context menus for copy/paste
        self.setup_global_context_menu()

        # Lift window and set Dock icon on macOS
        if sys.platform == "darwin":
            self.root.update_idletasks()
            self.root.lift()
            self.root.focus_force()
            self.root.after(200, self.set_macos_dock_icon)
        
        # Initial async load of models
        self.root.after(500, lambda: self.on_vendor_change(None))

    def set_macos_dock_icon(self):
        try:
            from AppKit import NSApplication, NSImage
            paths = [
                "/Users/shanfu/Desktop/公众号发布 2.0.app/Contents/Resources/AppIcon.icns",
                os.path.join(POSTFDRY_ROOT, "wip", "AppIcon.icns"),
                os.path.join(POSTFDRY_ROOT, "AppIcon.icns"),
            ]
            for path in paths:
                if os.path.exists(path):
                    app = NSApplication.sharedApplication()
                    image = NSImage.alloc().initByReferencingFile_(path)
                    if image and image.isValid():
                        app.setApplicationIconImage_(image)
                        break
        except Exception as e:
            print(f"Failed to set macOS Dock icon: {e}")

    def setup_global_context_menu(self):
        self.bind_context_menu_recursive(self.root)

    def bind_context_menu_recursive(self, parent):
        for child in parent.winfo_children():
            widget_class = child.winfo_class()
            if widget_class in ("Entry", "TEntry", "Text"):
                if sys.platform == "darwin":
                    child.bind("<Button-2>", self.show_context_menu)
                    child.bind("<Button-3>", self.show_context_menu)
                    child.bind("<Control-Button-1>", self.show_context_menu)
                else:
                    child.bind("<Button-3>", self.show_context_menu)
            if child.winfo_children():
                self.bind_context_menu_recursive(child)

    def show_context_menu(self, event):
        widget = event.widget
        try:
            widget.focus_set()
            menu = tk.Menu(widget, tearoff=0)
            menu.add_command(label="剪切 (Cut)", command=lambda: widget.event_generate("<<Cut>>"))
            menu.add_command(label="复制 (Copy)", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="粘贴 (Paste)", command=lambda: widget.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(label="全选 (Select All)", command=lambda: self.select_all(widget))
            menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            print(f"Context menu error: {e}")
        return "break"

    def select_all(self, widget):
        try:
            if hasattr(widget, "selection_range"):
                widget.selection_range(0, tk.END)
            if hasattr(widget, "tag_add"):
                widget.tag_add("sel", "1.0", tk.END)
        except:
            pass

    def load_settings(self):
        defaults = {
            "input": "",
            "mode": "translate",
            "llm_vendor": "Google Vertex AI",
            "model": "gemini-3-flash-preview",
            "text_style": "formal",
            "cover_style": "Industrial Amber",
            "pdf_template": "Federation",
            "article_type": "trend",
            "image_model": "gemini-3-pro-image-preview",
            "localize_images": False,
            "reuse_translation": False,
            "gen_images": False,
            "pdf_gen": True,
            "wechat_sync_enabled": False,
            "wechat_theme": "modern",
            "wechat_author": "",
            "wechat_account_alias": "default"
        }
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as fs:
                    defaults.update(json.load(fs))
            except: pass
        return defaults

    def save_settings(self):
        data = {
            "input": self.input_var.get().strip(),
            "mode": self.mode_var.get(),
            "llm_vendor": self.vendor_var.get(),
            "model": self.model_var.get(),
            "text_style": self.text_style_var.get(),
            "cover_style": self.cover_style_var.get(),
            "pdf_template": self.pdf_template_var.get(),
            "article_type": self.article_type_var.get(),
            "image_model": self.image_model_var.get(),
            "localize_images": self.localize_images_var.get(),
            "reuse_translation": self.reuse_translation_var.get(),
            "gen_images": self.gen_images_var.get(),
            "pdf_gen": self.pdf_gen_var.get(),
            "wechat_sync_enabled": self.wechat_sync_enabled_var.get(),
            "wechat_theme": self.wechat_theme_var.get(),
            "wechat_author": self.wechat_author_var.get().strip(),
            "wechat_account_alias": self.get_selected_wechat_alias()
        }
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save settings: {e}")

        # Auto-save credentials to .env
        self.save_wechat_credentials(self.wechat_appid_var.get().strip(), self.wechat_secret_var.get().strip())

    def setup_ui(self):
        self.main_container = ttk.Frame(self.root, padding=4)
        self.main_container.pack(fill="both", expand=True)

        # Tabbed interface
        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(fill="both", expand=True, pady=2)

        self.tab1 = ttk.Frame(self.notebook, padding=4)
        self.tab2 = ttk.Frame(self.notebook, padding=4)
        self.tab3 = ttk.Frame(self.notebook, padding=4)

        self.notebook.add(self.tab1, text=" 任务配置 (Config) ")
        self.notebook.add(self.tab2, text=" 元数据与标题 (Metadata) ")
        self.notebook.add(self.tab3, text=" 执行日志 (Run Logs) ")

        # --- TAB 1: Configuration ---
        # 1. Input Row
        f1 = ttk.LabelFrame(self.tab1, text=" 输入源与分析 (Input) ", padding=5)
        f1.pack(fill="x", pady=2)
        
        ttk.Label(f1, text="文章 URL/文件:").grid(row=0, column=0, sticky="w", pady=2)
        self.input_var = tk.StringVar(value=self.settings.get("input", ""))
        self.input_entry = ttk.Entry(f1, textvariable=self.input_var, width=50)
        self.input_entry.grid(row=0, column=1, padx=5)
        self.input_entry.bind("<KeyRelease>", self.on_input_changed)
        
        btn_browse = ttk.Button(f1, text="浏览...", command=self.browse_input)
        btn_browse.grid(row=0, column=2, padx=2)

        # 2. Main Parameters Frame Container
        f_param = ttk.Frame(self.tab1, padding=2)
        f_param.pack(fill="x", pady=2)

        # 2.1 Global Config Group
        f_global = ttk.LabelFrame(f_param, text=" 全局基本配置 (Global Config) ", padding=5)
        f_global.pack(fill="x", pady=2)
        
        ttk.Label(f_global, text="任务模式:").grid(row=0, column=0, sticky="w", pady=2)
        self.mode_var = tk.StringVar(value=self.settings.get("mode", "both"))
        self.mode_combo = ttk.Combobox(f_global, textvariable=self.mode_var, values=["translate", "interpret", "both"], width=12, state="readonly")
        self.mode_combo.grid(row=0, column=1, sticky="w", padx=5)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_change)

        ttk.Label(f_global, text="模型厂商:").grid(row=0, column=2, sticky="w", padx=10)
        self.vendor_var = tk.StringVar(value=self.settings.get("llm_vendor", "Google Vertex AI"))
        vendors = list(self.vendor_map.keys())
        self.vendor_combo = ttk.Combobox(f_global, textvariable=self.vendor_var, values=vendors, state="readonly", width=16)
        self.vendor_combo.grid(row=0, column=3, sticky="w")
        self.vendor_combo.bind("<<ComboboxSelected>>", self.on_vendor_change)

        ttk.Label(f_global, text="选择模型:").grid(row=0, column=4, sticky="w", padx=10)
        self.model_var = tk.StringVar(value=self.settings.get("model", "gemini-3-flash-preview"))
        self.model_combo = ttk.Combobox(f_global, textvariable=self.model_var, width=22)
        self.model_combo.grid(row=0, column=5, sticky="w")

        # API Key Row
        ttk.Label(f_global, text="API Key:").grid(row=1, column=0, sticky="w", pady=4)
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(f_global, textvariable=self.api_key_var, width=24, show="*")
        self.api_key_entry.grid(row=1, column=1, columnspan=2, sticky="w", padx=5)

        self.btn_save_key = ttk.Button(f_global, text="保存 Key", command=self.save_api_key)
        self.btn_save_key.grid(row=1, column=3, sticky="w")

        self.btn_test_conn = ttk.Button(f_global, text="测试连通性", command=self.test_connectivity)
        self.btn_test_conn.grid(row=1, column=4, sticky="w", padx=10)

        # 2.2 Translate Config Group
        self.f_translate = ttk.LabelFrame(f_param, text=" 译介 (翻译) 服务专属参数 (Translate Settings) ", padding=5)
        self.f_translate.pack(fill="x", pady=2)

        ttk.Label(self.f_translate, text="写作风格:").grid(row=0, column=0, sticky="w", pady=2)
        self.text_style_var = tk.StringVar(value=self.settings.get("text_style", "formal"))
        self.text_style_combo = ttk.Combobox(self.f_translate, textvariable=self.text_style_var, values=["custom", "formal", "business", "storytelling", "technical", "elegant"], width=12, state="readonly")
        self.text_style_combo.grid(row=0, column=1, sticky="w", padx=5)

        ttk.Label(self.f_translate, text="PDF 输出模板:").grid(row=0, column=2, sticky="w", padx=10)
        self.pdf_template_var = tk.StringVar(value=self.settings.get("pdf_template", "Federation"))
        self.pdf_template_combo = ttk.Combobox(self.f_translate, textvariable=self.pdf_template_var, values=["Federation", "Industrial Amber", "Corporate Blue", "Minimalist White"], width=16, state="readonly")
        self.pdf_template_combo.grid(row=0, column=3, sticky="w")

        self.localize_images_var = tk.BooleanVar(value=self.settings.get("localize_images", False))
        self.chk_localize = ttk.Checkbutton(self.f_translate, text="图片英文文本汉化 (L10N)", variable=self.localize_images_var)
        self.chk_localize.grid(row=1, column=0, columnspan=2, sticky="w", pady=2, padx=5)

        self.reuse_translation_var = tk.BooleanVar(value=self.settings.get("reuse_translation", False))

        self.pdf_gen_var = tk.BooleanVar(value=self.settings.get("pdf_gen", True))
        self.chk_pdf_gen = ttk.Checkbutton(self.f_translate, text="生成专业排版 PDF", variable=self.pdf_gen_var)
        self.chk_pdf_gen.grid(row=1, column=4, sticky="w", pady=2, padx=5)

        # 2.3 Interpret Config Group
        self.f_interpret = ttk.LabelFrame(f_param, text=" 解读 (公众号) 服务专属参数 (Interpret Settings) ", padding=5)
        self.f_interpret.pack(fill="x", pady=2)

        ttk.Label(self.f_interpret, text="重构类型:").grid(row=0, column=0, sticky="w", pady=2)
        self.article_type_var = tk.StringVar(value=self.settings.get("article_type", "trend"))
        self.article_type_combo = ttk.Combobox(self.f_interpret, textvariable=self.article_type_var, values=["trend", "paper", "policy", "product", "standard"], width=12, state="readonly")
        self.article_type_combo.grid(row=0, column=1, sticky="w", padx=5)

        ttk.Label(self.f_interpret, text="视觉风格 (DNA):").grid(row=0, column=2, sticky="w", padx=10)
        self.cover_style_var = tk.StringVar(value=self.settings.get("cover_style", "Industrial Amber"))
        self.cover_style_combo = ttk.Combobox(self.f_interpret, textvariable=self.cover_style_var, values=["Industrial Amber", "Corporate Blue", "Minimalist White", "Elegant Gold", "Federation"], width=16, state="readonly")
        self.cover_style_combo.grid(row=0, column=3, sticky="w")

        ttk.Label(self.f_interpret, text="绘图引擎:").grid(row=0, column=4, sticky="w", padx=10)
        self.image_model_var = tk.StringVar(value=self.settings.get("image_model", "gemini-3-pro-image-preview"))
        self.image_model_combo = ttk.Combobox(self.f_interpret, textvariable=self.image_model_var, values=["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview", "imagen-3"], width=22, state="readonly")
        self.image_model_combo.grid(row=0, column=5, sticky="w")

        self.gen_images_var = tk.BooleanVar(value=self.settings.get("gen_images", False))
        self.chk_gen_images = ttk.Checkbutton(self.f_interpret, text="生成插图/封面 (Gen Images)", variable=self.gen_images_var)
        self.chk_gen_images.grid(row=1, column=0, columnspan=2, sticky="w", pady=2, padx=5)

        # 2.4 WeChat Publication Config Group
        self.f_wechat = ttk.LabelFrame(f_param, text=" 微信公众号同步配置 (WeChat Publish Settings) ", padding=5)
        self.f_wechat.pack(fill="x", pady=2)

        ttk.Label(self.f_wechat, text="AppID:").grid(row=0, column=0, sticky="w", pady=2)
        self.wechat_appid_var = tk.StringVar()
        self.wechat_appid_entry = ttk.Entry(self.f_wechat, textvariable=self.wechat_appid_var, width=20)
        self.wechat_appid_entry.grid(row=0, column=1, sticky="w", padx=5)

        ttk.Label(self.f_wechat, text="AppSecret:").grid(row=0, column=2, sticky="w", padx=10)
        self.wechat_secret_var = tk.StringVar()
        self.wechat_secret_entry = ttk.Entry(self.f_wechat, textvariable=self.wechat_secret_var, width=20, show="*")
        self.wechat_secret_entry.grid(row=0, column=3, sticky="w", padx=5)

        ttk.Label(self.f_wechat, text="选择公众号:").grid(row=1, column=0, sticky="w", pady=2)
        self.wechat_account_combo = ttk.Combobox(self.f_wechat, state="readonly", width=18)
        self.wechat_account_combo.grid(row=1, column=1, sticky="w", padx=5)

        ttk.Label(self.f_wechat, text="排版主题:").grid(row=1, column=2, sticky="w", padx=10)
        self.wechat_theme_var = tk.StringVar(value="modern")
        self.wechat_theme_combo = ttk.Combobox(self.f_wechat, textvariable=self.wechat_theme_var, values=["modern", "default", "elegant", "simple"], state="readonly", width=12)
        self.wechat_theme_combo.grid(row=1, column=3, sticky="w", padx=5)

        ttk.Label(self.f_wechat, text="发布作者:").grid(row=2, column=0, sticky="w", pady=2)
        self.wechat_author_var = tk.StringVar()
        self.wechat_author_entry = ttk.Entry(self.f_wechat, textvariable=self.wechat_author_var, width=20)
        self.wechat_author_entry.grid(row=2, column=1, sticky="w", padx=5)

        self.wechat_sync_enabled_var = tk.BooleanVar(value=self.settings.get("wechat_sync_enabled", False))
        self.chk_wechat_sync = ttk.Checkbutton(self.f_wechat, text="同步至微信草稿箱 (Sync to WeChat)", variable=self.wechat_sync_enabled_var)
        self.chk_wechat_sync.grid(row=2, column=2, columnspan=2, sticky="w", pady=2, padx=10)

        # Dynamic enables based on initial mode selection
        self.on_mode_change(None)

        # Load wechat credentials & accounts
        self.load_wechat_data()

        # --- TAB 2: Metadata & Titles ---
        f_meta = ttk.LabelFrame(self.tab2, text=" 文章元数据 (Metadata) ", padding=10)
        f_meta.pack(fill="x", pady=5)

        ttk.Label(f_meta, text="原文英文标题:").grid(row=0, column=0, sticky="w", pady=5)
        self.eng_title_var = tk.StringVar()
        ttk.Entry(f_meta, textvariable=self.eng_title_var, width=60).grid(row=0, column=1, sticky="w", padx=5, columnspan=2)

        ttk.Label(f_meta, text="标准译介中文标题:").grid(row=1, column=0, sticky="w", pady=5)
        self.std_title_var = tk.StringVar()
        self.std_title_combo = ttk.Combobox(f_meta, textvariable=self.std_title_var, width=58)
        self.std_title_combo.grid(row=1, column=1, sticky="w", padx=5)

        ttk.Label(f_meta, text="吸睛解读中文标题:").grid(row=2, column=0, sticky="w", pady=5)
        self.cat_title_var = tk.StringVar()
        self.cat_title_combo = ttk.Combobox(f_meta, textvariable=self.cat_title_var, width=58)
        self.cat_title_combo.grid(row=2, column=1, sticky="w", padx=5)

        # Regenerate Button in Column 2, spanning Row 1 & 2
        self.btn_regenerate_title = ttk.Button(f_meta, text="标题不够好", command=self.regenerate_titles)
        self.btn_regenerate_title.grid(row=1, column=2, rowspan=2, padx=15, sticky="ns")

        ttk.Label(f_meta, text="文章作者 (Author):").grid(row=3, column=0, sticky="w", pady=5)
        self.author_var = tk.StringVar()
        ttk.Entry(f_meta, textvariable=self.author_var, width=30).grid(row=3, column=1, sticky="w", padx=5, columnspan=2)

        ttk.Label(f_meta, text="发布机构 (Source):").grid(row=4, column=0, sticky="w", pady=5)
        self.source_var = tk.StringVar()
        ttk.Entry(f_meta, textvariable=self.source_var, width=30).grid(row=4, column=1, sticky="w", padx=5, columnspan=2)

        ttk.Label(f_meta, text="发布时间 (Date):").grid(row=5, column=0, sticky="w", pady=5)
        self.date_var = tk.StringVar()
        ttk.Entry(f_meta, textvariable=self.date_var, width=30).grid(row=5, column=1, sticky="w", padx=5, columnspan=2)

        # 沿用缓存翻译
        self.chk_reuse_translation = ttk.Checkbutton(f_meta, text="沿用缓存翻译 (Reuse Translation)", variable=self.reuse_translation_var)
        self.chk_reuse_translation.grid(row=6, column=1, sticky="w", pady=5, padx=5, columnspan=2)

        f_thoughts = ttk.LabelFrame(self.tab2, text=" 译者/编辑核心导读洞察 (Editor Thoughts) ", padding=10)
        f_thoughts.pack(fill="both", expand=True, pady=5)
        self.thoughts_text = tk.Text(f_thoughts, height=6, font=self.ui_font)
        self.thoughts_text.pack(fill="both", expand=True)

        # --- TAB 3: Execution Logs ---
        f_log = ttk.LabelFrame(self.tab3, text=" 实态执行追踪 (Terminal Logs) ", padding=10)
        f_log.pack(fill="both", expand=True, pady=5)
        
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(f_log, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=5)
        
        self.status_label = ttk.Label(f_log, text="等待流水线就绪...")
        self.status_label.pack(pady=2)

        # Container frame for log text and scrollbar
        f_log_container = ttk.Frame(f_log)
        f_log_container.pack(fill="both", expand=True)

        self.log_text = tk.Text(f_log_container, height=15, state="disabled", font=self.log_font, bg="#ffffff", padx=5, pady=5)
        scrollbar = ttk.Scrollbar(f_log_container, orient="vertical", command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        # --- BOTTOM CONTROLS ---
        f_ctrl = ttk.Frame(self.root, padding=10)
        f_ctrl.pack(fill="x", side="bottom")
        
        ttk.Button(f_ctrl, text="退出 (Exit)", command=self.on_exit).pack(side="left", padx=5)
        self.stop_btn = ttk.Button(f_ctrl, text="中止 (Stop)", state="disabled", command=self.stop_process)
        self.stop_btn.pack(side="right", padx=5)
        self.start_btn = ttk.Button(f_ctrl, text="分析并配置流水线 (Analyze & Config)", command=self.handle_main_action)
        self.start_btn.pack(side="right", padx=5)

    def on_input_changed(self, event):
        target = self.input_var.get().strip()
        if hasattr(self, "last_target") and self.last_target != target:
            if self.merged_button_state != "analyze":
                self.reset_merged_button()
                self.status_label.config(text="💡 检测到输入 URL/路径已变更，请点击“分析并配置流水线”重新分析")

    def browse_input(self):
        f = filedialog.askopenfilename(filetypes=[("Markdown files", "*.md"), ("All files", "*.*")])
        if f:
            self.input_var.set(f)
            # Try to pre-read title if local markdown
            self.pre_read_local_metadata(f)
            self.reset_merged_button()
            self.check_existing_translation()

    def pre_read_local_metadata(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as fs:
                content = fs.read()
            meta = MetadataEngine(content)
            self.eng_title_var.set(meta.get('eng_title') or meta.get('title') or "")
            title = meta.get('title') or ""
            self.std_title_var.set(title)
            if title:
                if title not in self.standard_title_history:
                    self.standard_title_history.append(title)
                self.std_title_combo.config(values=self.standard_title_history)
            self.author_var.set(meta.get('author') or "")
            self.source_var.set(meta.get('source') or "")
            self.date_var.set(meta.get('date') or meta.get('publish_date') or "")
        except: pass

    def set_frame_state(self, frame, state):
        for child in frame.winfo_children():
            try:
                if isinstance(child, ttk.Combobox):
                    child.config(state="readonly" if state == "normal" else "disabled")
                else:
                    child.config(state=state)
            except:
                pass

    def check_existing_translation(self):
        target = self.input_var.get().strip()
        if not target:
            return
        
        def slugify(text):
            text = text.lower()
            text = re.sub(r'[^\w\s-]', '', text)
            text = re.sub(r'[\s_-]+', '_', text).strip('_')
            return text[:50]
            
        slug = None
        input_abs = os.path.abspath(target)
        base_projects_dir = "/Users/shanfu/cc/Projects"
        if input_abs.startswith(base_projects_dir):
            rel_path = os.path.relpath(input_abs, base_projects_dir)
            parts = rel_path.split(os.sep)
            if len(parts) > 1:
                slug = parts[0]

        if not slug:
            if not target.startswith(('http://', 'https://')):
                title = os.path.basename(target).replace('.md', '')
                try:
                    with open(target, 'r', encoding='utf-8') as f:
                        content = f.read()
                    meta_eng = MetadataEngine(content)
                    title = meta_eng.get('title', title)
                except: pass
                slug = slugify(title)
            else:
                try:
                    metadata = crawler_agent.sniff_metadata(target)
                    title = metadata.get('title', 'Untitled_Article')
                    slug = slugify(title)
                except: pass

        if not slug:
            slug = "untitled_article"
                
        translated_file = os.path.join(base_projects_dir, slug, "wip", "translated.md")
        if os.path.exists(translated_file):
            self.reuse_translation_var.set(True)
            self.status_label.config(text="💡 检测到已有历史翻译缓存，已自动勾选『沿用缓存翻译』！")
            self.log("💡 [System] 检测到该文章在本地已存在历史翻译缓存（wip/translated.md）。已为你自动勾选『沿用缓存翻译』，以避免重复调用 LLM API 消耗 Token。如需重新翻译，请手动取消勾选。")
        else:
            self.reuse_translation_var.set(False)

    def on_mode_change(self, event):
        m = self.mode_var.get()
        if m == "translate":
            self.set_frame_state(self.f_translate, "normal")
            self.set_frame_state(self.f_interpret, "disabled")
        elif m == "interpret":
            self.set_frame_state(self.f_translate, "disabled")
            self.set_frame_state(self.f_interpret, "normal")
            self.pdf_gen_var.set(False)
        else: # both
            self.set_frame_state(self.f_translate, "normal")
            self.set_frame_state(self.f_interpret, "normal")

    def reset_merged_button(self):
        self.merged_button_state = "analyze"
        self.start_btn.config(text="分析并配置流水线 (Analyze & Config)", state="normal")

    def load_project_manager(self, target):
        import importlib.util
        import sys
        module_path = os.path.join(POSTFDRY_ROOT, "scripts", "postfdry-os.py")
        spec = importlib.util.spec_from_file_location("postfdry_os", module_path)
        postfdry_os = importlib.util.module_from_spec(spec)
        sys.modules["postfdry_os"] = postfdry_os
        spec.loader.exec_module(postfdry_os)
        
        ProjectManager = postfdry_os.ProjectManager
        pm = ProjectManager(target)
        pm.init_project()
        return pm, os.path.join(pm.source_dir, "source.md"), pm.config_path

    def save_source_metadata(self, source_file):
        try:
            if not os.path.exists(source_file):
                return
            with open(source_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            meta_eng = MetadataEngine(content)
            clean_body = meta_eng.clean_body(content)
            
            # Read values from GUI
            # Use GUI date value; fall back to existing metadata; never default to today
            gui_date = self.date_var.get().strip()
            existing_date = meta_eng.get('date') or meta_eng.get('publish_date') or ''
            final_date = gui_date or existing_date

            new_yaml = {
                'title': self.std_title_var.get().strip(),
                'eng_title': self.eng_title_var.get().strip(),
                'author': self.author_var.get().strip(),
                'date': final_date,
                'source': self.source_var.get().strip(),
                'url': meta_eng.get('url') or '',
                'original_path': meta_eng.get('original_path') or ''
            }
            
            import yaml
            yaml_block = f"---\n{yaml.dump(new_yaml, allow_unicode=True)}---\n\n"
            with open(source_file, 'w', encoding='utf-8') as f:
                f.write(yaml_block + clean_body)
            self.log("💾 [GUI] 成功同步元数据至原文 YAML Frontmatter。")
        except Exception as e:
            self.log(f"⚠️ [GUI] 同步元数据至 source.md 失败: {e}")

    def save_project_config(self, config_path, std_title, cat_title, catchy_history=None, standard_history=None):
        # Auto-save GUI settings as well
        self.save_settings()
        config_data = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except: pass
        
        config_data['standard_title'] = std_title
        config_data['catchy_title'] = cat_title
        
        if catchy_history is not None:
            config_data['catchy_title_history'] = catchy_history
        else:
            config_data['catchy_title_history'] = self.catchy_title_history

        if standard_history is not None:
            config_data['standard_title_history'] = standard_history
        else:
            config_data['standard_title_history'] = self.standard_title_history

        config_data['eng_title'] = self.eng_title_var.get().strip()
        config_data['author'] = self.author_var.get().strip()
        config_data['source'] = self.source_var.get().strip()
        config_data['date'] = self.date_var.get().strip()
        target = self.input_var.get().strip()
        if target and not target.startswith(('http://', 'https://')):
            config_data['original_path'] = os.path.abspath(target)
        config_data['mode'] = self.mode_var.get()
        config_data['text_style'] = self.text_style_var.get()
        config_data['cover_style'] = self.cover_style_var.get()
        config_data['info_style'] = self.cover_style_var.get()
        config_data['article_type'] = self.article_type_var.get()
        config_data['image_model'] = self.image_model_var.get()
        config_data['localize_images'] = self.localize_images_var.get()
        config_data['pdf_gen'] = self.pdf_gen_var.get()
        config_data['llm_model'] = self.model_var.get()
        config_data['thoughts'] = self.thoughts_text.get(1.0, tk.END).strip()
        config_data['last_run'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
        except: pass

        # Update source.md frontmatter
        project_root = os.path.dirname(os.path.dirname(config_path))
        source_file = os.path.join(project_root, "source", "source.md")
        self.save_source_metadata(source_file)

    def handle_main_action(self):
        if self.merged_button_state == "completed":
            self.input_var.set("")
            self.eng_title_var.set("")
            self.std_title_var.set("")
            self.cat_title_var.set("")
            self.author_var.set("")
            self.source_var.set("")
            self.date_var.set("")
            self.thoughts_text.delete(1.0, tk.END)
            
            # Reset history combos
            self.catchy_title_history = []
            self.cat_title_combo.config(values=[])
            self.cat_title_combo.set("")
            self.standard_title_history = []
            self.std_title_combo.config(values=[])
            self.std_title_combo.set("")
            
            # Reset to Tab 1
            self.notebook.select(self.tab1)
            
            # Reset logs
            self.log_text.config(state="normal")
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state="disabled")
            
            self.progress_var.set(0)
            self.status_label.config(text="💡 请输入原文 URL 或导入本地 Markdown 文件")
            self.reset_merged_button()
            
            # Automatically focus the input entry
            self.input_entry.focus_set()
            return

        target = self.input_var.get().strip()
        if not target:
            return messagebox.showwarning("警告", "请先输入 URL 或浏览本地 Markdown 文件！")
            
        # Save settings immediately so it is remembered next time
        self.save_settings()
        
        # Reset if target changed
        if hasattr(self, "last_target") and self.last_target != target:
            self.merged_button_state = "analyze"
        self.last_target = target

        if self.merged_button_state == "analyze":
            try:
                pm, _, config_path = self.load_project_manager(target)
                if os.path.exists(config_path):
                    with open(config_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    
                    # Load metadata from source.md if available
                    source_md_path = os.path.join(pm.source_dir, "source.md")
                    eng_title = ""
                    author = ""
                    source = ""
                    std_title = cfg.get('standard_title', '')
                    if os.path.exists(source_md_path):
                        try:
                            with open(source_md_path, 'r', encoding='utf-8') as sf:
                                smeta = MetadataEngine(sf.read())
                            eng_title = smeta.get('eng_title') or smeta.get('title') or ""
                            author = smeta.get('author') or ""
                            source = smeta.get('source') or ""
                            date_val = smeta.get('date') or smeta.get('publish_date') or ""
                            if not std_title:
                                std_title = smeta.get('title') or ""
                        except: pass

                    # Fall back to cfg values if above are still empty
                    if not eng_title: eng_title = cfg.get('eng_title', '')
                    if not author: author = cfg.get('author', 'AI数据治理研究院')
                    if not source: source = cfg.get('source', 'Unknown')

                    self.eng_title_var.set(eng_title)
                    self.std_title_var.set(std_title)
                    self.cat_title_var.set(cfg.get('catchy_title', ''))
                    self.author_var.set(author)
                    self.source_var.set(source)
                    self.date_var.set(date_val if date_val else cfg.get('date', ''))
                    
                                        # Load history
                    self.catchy_title_history = cfg.get("catchy_title_history", [])
                    cat_title = cfg.get("catchy_title")
                    if cat_title and cat_title not in self.catchy_title_history:
                        self.catchy_title_history.append(cat_title)
                    self.cat_title_combo.config(values=self.catchy_title_history)
                    if cat_title:
                        self.cat_title_combo.set(cat_title)

                    self.standard_title_history = cfg.get("standard_title_history", [])
                    if std_title and std_title not in self.standard_title_history:
                        self.standard_title_history.append(std_title)
                    self.std_title_combo.config(values=self.standard_title_history)
                    if std_title:
                        self.std_title_combo.set(std_title)
                    
                    self.check_existing_translation()
                    
                    # Ready to run
                    self.merged_button_state = "review_config"
                    self.start_btn.config(text="确认出版风格并微调元数据 ->")
                else:
                    # First time! Start Onboarding
                    self.merged_button_state = "extracting"
                    self.start_btn.config(text="正在提取...", state="disabled")
                    self.stop_btn.config(state="normal")
                    self.status_label.config(text=" 🤔 正在调用 AI 剖析文章并拟定建议规划...")
                    
                    self.eng_title_var.set("")
                    self.std_title_var.set("")
                    self.cat_title_var.set("")
                    self.author_var.set("")
                    self.source_var.set("")
                    self.date_var.set("")
                    self.thoughts_text.delete(1.0, tk.END)
                    
                    # Reset logs and switch to Execution Logs tab to show background activity
                    self.log_text.config(state="normal")
                    self.log_text.delete(1.0, tk.END)
                    self.log_text.config(state="disabled")
                    self.notebook.select(self.tab3)
                    
                    threading.Thread(target=self.merged_onboarding_thread, args=(target,), daemon=True).start()
            except Exception as e:
                self.log(f"❌ 初始化项目配置失败: {e}")
                self.reset_merged_button()
                
        elif self.merged_button_state == "review_config":
            # Jump to Tab 2 for metadata review after user confirms styles on Tab 1
            # But first do a fast check to see if the target URL/file has changed
            target = self.input_var.get().strip()
            is_same_article = True
            expected_title = ""
            try:
                if target.startswith(('http://', 'https://')):
                    metadata = crawler_agent.sniff_metadata(target)
                    expected_title = metadata.get('title', '')
                else:
                    if os.path.exists(target):
                        with open(target, 'r', encoding='utf-8') as f:
                            meta_eng = MetadataEngine(f.read())
                        expected_title = meta_eng.get('title') or ""
                    if not expected_title:
                        expected_title = os.path.splitext(os.path.basename(target))[0]
                
                if expected_title:
                    new_title_clean = re.sub(r'[^a-zA-Z0-9]', '', expected_title).lower()
                    old_title_clean = re.sub(r'[^a-zA-Z0-9]', '', self.eng_title_var.get()).lower()
                    if new_title_clean != old_title_clean:
                        is_same_article = False
            except Exception as e:
                print(f"⚠️ [Fast check] Mismatch check failed: {e}")

            if is_same_article:
                # Same article! Proceed to Tab 2 normally
                self.notebook.select(self.tab2)
                self.merged_button_state = "confirm"
                self.start_btn.config(text="确认元数据并启动流水线 🚀")
                self.status_label.config(text="📝 请在“元数据与标题”页确认文章标题、作者与发布时间...")
            else:
                # Different article! Start Onboarding
                self.merged_button_state = "extracting"
                self.start_btn.config(text="正在提取...", state="disabled")
                self.stop_btn.config(state="normal")
                self.status_label.config(text=" 🤔 正在调用 AI 剖析文章并拟定建议规划...")
                
                self.eng_title_var.set("")
                self.std_title_var.set("")
                self.cat_title_var.set("")
                self.author_var.set("")
                self.source_var.set("")
                self.date_var.set("")
                self.thoughts_text.delete(1.0, tk.END)
                
                # Reset logs and switch to Execution Logs tab to show background activity
                self.log_text.config(state="normal")
                self.log_text.delete(1.0, tk.END)
                self.log_text.config(state="disabled")
                self.notebook.select(self.tab3)
                
                threading.Thread(target=self.merged_onboarding_thread, args=(target,), daemon=True).start()

        elif self.merged_button_state == "confirm":
            self.start_process()

    def merged_onboarding_thread(self, target):
        try:
            model = self.model_var.get()
            self.log(f"🔄 [AI Onboarding] 正在初始化项目配置，目标: {target}...")
            pm, source_file, config_path = self.load_project_manager(target)
            
            # Auto-materialize source (crawl if URL)
            self.log(f"🌐 [AI Onboarding] 正在抓取/同步原文文件...")
            source_file = pm.materialize_source(model_name=model)
            
            # Fetch AI recommendation
            self.log(f"🤔 [AI Onboarding] 正在调用 AI 剖析文章并拟定建议规划...")
            from postfdry_os import OnboardingAssistant
            assistant = OnboardingAssistant(source_file, model_name=model)
            rec = assistant.get_recommendation()
            
            self.log(f"📝 [AI Onboarding] 元数据获取成功，正在确认与重构项目规划...")
            # Read metadata safely
            with open(source_file, 'r', encoding='utf-8') as f:
                meta = MetadataEngine(f.read())

            # Rename project directory based on crawled title
            target_title = meta.get('title') or meta.get('eng_title')
            if target_title:
                self.log(f"🔄 [AI Onboarding] 正在基于原文标题对项目文件夹进行重命名...")
                project_root, source_file = pm.rename_project_if_needed(target_title)
                config_path = pm.config_path

            def apply_rec():
                self.eng_title_var.set(meta.get('eng_title') or meta.get('title') or rec.get('standard_title', ''))
                self.std_title_var.set(rec.get('standard_title', ''))
                self.cat_title_var.set(rec.get('catchy_title', ''))
                self.author_var.set(meta.get('author') or 'Unknown')
                self.source_var.set(meta.get('source') or 'Unknown')
                self.date_var.set(meta.get('date') or meta.get('publish_date') or '')
                
                # Thoughts
                self.thoughts_text.delete(1.0, tk.END)
                self.thoughts_text.insert(tk.END, rec.get('thoughts', ''))
                
                # Styles
                self.text_style_var.set(rec.get('text_style', 'formal'))
                self.article_type_var.set(rec.get('article_type', 'trend'))
                
                self.on_mode_change(None)
                
                # Seed catchy title history
                curr_cat = rec.get('catchy_title', '')
                self.catchy_title_history = [curr_cat] if curr_cat else []
                self.cat_title_combo.config(values=self.catchy_title_history)
                if curr_cat:
                    self.cat_title_combo.set(curr_cat)

                # Seed standard title history
                curr_std = rec.get('standard_title', '')
                self.standard_title_history = [curr_std] if curr_std else []
                self.std_title_combo.config(values=self.standard_title_history)
                if curr_std:
                    self.std_title_combo.set(curr_std)
                
                self.check_existing_translation()
                
                # Save initial config
                self.save_project_config(config_path, curr_std, curr_cat, self.catchy_title_history, self.standard_title_history)
                
                # Transition button based on which tab is active
                current_tab = self.notebook.index(self.notebook.select())
                if current_tab == 1: # Tab 2 (Metadata)
                    self.merged_button_state = "confirm"
                    self.start_btn.config(text="确认元数据并启动流水线 🚀", state="normal")
                else:
                    self.notebook.select(self.tab1)
                    self.merged_button_state = "review_config"
                    self.start_btn.config(text="确认出版风格并微调元数据 ->", state="normal")
                
                self.stop_btn.config(state="disabled")
                self.status_label.config(text="✅ AI 出版规划推荐解析完成！元数据与风格已更新。")
                
                # Log key metadata extraction status and style recommendations
                ext_title = self.std_title_var.get().strip() or "（未获取）"
                ext_author = self.author_var.get().strip()
                ext_source = self.source_var.get().strip()
                ext_date = self.date_var.get().strip()
                
                log_author = ext_author if (ext_author and ext_author.lower() != "unknown") else "⚠️ 未获取 (默认 Unknown)"
                log_source = ext_source if (ext_source and ext_source.lower() != "unknown") else "⚠️ 未获取 (默认 Unknown)"
                log_date = ext_date if ext_date else "⚠️ 未获取 (默认空)"
                
                style_mapping = {
                    "custom": "自定义风格",
                    "formal": "严肃科技规范 (Formal)",
                    "business": "商业咨询报告风格 (Business)",
                    "storytelling": "故事化叙事风格 (Storytelling)",
                    "technical": "技术深度文档规范 (Technical)",
                    "elegant": "优雅文艺散文风格 (Elegant)"
                }
                type_mapping = {
                    "trend": "行业趋势分析 (Trend)",
                    "paper": "论文深度解读 (Paper)",
                    "policy": "政策战略解读 (Policy)",
                    "product": "产品/技术剖析 (Product)",
                    "standard": "规范与标准解读 (Standard)"
                }
                
                rec_style = rec.get("text_style", "formal")
                rec_type = rec.get("article_type", "trend")
                
                log_style = style_mapping.get(rec_style, rec_style)
                log_type = type_mapping.get(rec_type, rec_type)

                self.log("\n📋 [AI Onboarding] 原文关键元数据抓取情况汇总:")
                self.log(f"  ▪ 原文标题: {ext_title}")
                self.log(f"  ▪ 稿件作者: {log_author}")
                self.log(f"  ▪ 发布机构: {log_source}")
                self.log(f"  ▪ 发布时间: {log_date}")
                
                self.log("\n🎨 [AI Onboarding] 智能出版风格与模式配置汇总:")
                self.log(f"  ▪ 建议写作风格: {log_style}")
                self.log(f"  ▪ 建议文章类型: {log_type}")
                self.log(f"  ▪ 建议导读洞察: {rec.get('thoughts', '无')}")
                self.log(f"  ▪ 智能风格推荐分析理由: {rec.get('justification', '无')}\n")
                
                self.log(f"✅ [AI Onboarding] 出版规划推荐加载成功！\n理由/分析: {rec.get('justification')}")

            self.root.after(0, apply_rec)
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda: self.status_label.config(text=f"❌ AI 解析失败: {err_msg}"))
            self.root.after(0, lambda: self.log(f"❌ AI Onboarding 解析出错:\n{err_msg}"))
            self.root.after(0, lambda: self.notebook.select(self.tab3))
            self.root.after(0, lambda: self.reset_merged_button())
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))

    def regenerate_titles(self):
        target = self.input_var.get().strip()
        if not target:
            return messagebox.showwarning("警告", "请先输入 URL 或浏览本地 Markdown 文件！")
            
        # Auto-save GUI settings as well
        self.save_settings()
        self.btn_regenerate_title.config(state="disabled")
        self.stop_btn.config(state="normal")
        
        # Reset logs and switch to Execution Logs tab to show background activity
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
        self.notebook.select(self.tab3)
        
        thoughts = self.thoughts_text.get(1.0, tk.END).strip()
        threading.Thread(target=self.regenerate_titles_thread, args=(target, thoughts), daemon=True).start()

    def regenerate_titles_thread(self, target, thoughts):
        try:
            self.root.after(0, lambda: self.status_label.config(text=" 🤔 正在结合编辑洞察生成新标题..."))
            self.log("🔄 [Title Re-gen] 正在初始化项目配置，读取原文文件...")
            pm, source_file, config_path = self.load_project_manager(target)
            
            if not os.path.exists(source_file):
                self.root.after(0, lambda: self.log("❌ 找不到原文文件，请先运行分析建议或导入文件！"))
                return
                
            with open(source_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Use LLM to generate titles
            from llm_utils import get_client
            client = get_client()
            model_name = self.model_var.get() or "gemini-3-flash-preview"
            
            prompt = f"""
            你是一位顶级的中文科技媒体/咨询报告总编辑。
            
            请基于以下原文正文以及译者/编辑核心导读洞察（Thoughts），为文章重新拟定两个高质量的中文字头：
            1. **标准译介标题 (Standard Title)**：专业、直译但符合中文习惯，适合行业深度报告或学术译介，突出客观严谨性。
            2. **吸睛解读标题 (Catchy Title)**：极具行业洞察力、观点锐利、极具传播力（适合微信公众号或主流科技媒体）。
            
            【译者/编辑核心导读洞察 (Thoughts)】:
            {thoughts}
            
            【原文正文】:
            {content[:6000]}
            
            请返回符合以下 JSON 格式的字符串（不要有任何 markdown 标记包裹，直接输出 JSON）：
            {{
              "standard_title": "你的标准译介标题",
              "catchy_title": "你的吸睛解读标题"
            }}
            """
            response_text = client.generate_content(prompt, model_name=model_name).strip()
            if response_text.startswith("```"):
                response_text = re.sub(r'^```(?:json)?\n', '', response_text)
                response_text = re.sub(r'\n```$', '', response_text)
            
            res = json.loads(response_text)
            new_std = res.get("standard_title", "").strip()
            new_cat = res.get("catchy_title", "").strip()
            
            if new_std and new_cat:
                def update_ui():
                    # Update standard title history
                    std_hist = self.standard_title_history
                    if new_std not in std_hist:
                        std_hist.append(new_std)
                    self.std_title_combo.config(values=std_hist)
                    self.std_title_combo.set(new_std)
                    self.std_title_var.set(new_std)

                    # Update catchy title history
                    cat_hist = self.catchy_title_history
                    if new_cat not in cat_hist:
                        cat_hist.append(new_cat)
                    self.cat_title_combo.config(values=cat_hist)
                    self.cat_title_combo.set(new_cat)
                    self.cat_title_var.set(new_cat)
                    
                    self.save_project_config(config_path, new_std, new_cat, cat_hist, std_hist)
                    self.status_label.config(text="✅ 标题生成成功！已加入下拉选项中。")
                    self.log(f"✅ [Title Re-gen] 标题重新生成成功！\n标准译介标题: {new_std}\n吸睛解读标题: {new_cat}")
                    
                    # Switch back to Tab 2 for review!
                    self.notebook.select(self.tab2)
                    
                self.root.after(0, update_ui)
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda: self.log(f"❌ 重新生成标题出错: {err_msg}"))
            self.root.after(0, lambda: self.status_label.config(text="❌ 标题重新生成失败"))
        finally:
            self.root.after(0, lambda: self.btn_regenerate_title.config(state="normal"))
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))

    def log(self, msg):
        self.log_text.config(state="normal")
        is_p = "%" in msg or "进度" in msg
        if is_p and self.last_was_progress:
            self.log_text.delete("end-2l", "end-1c")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.last_was_progress = is_p
        
        # Try to capture progress bar percent
        m = re.search(r"(\d+(\.\d+)?)%", msg)
        if m:
            self.progress_var.set(float(m.group(1)))
        
        # Status Label Updates (only show the first line to avoid multi-line duplication)
        if any(e in msg for e in ["🚀", "🧹", "🎨", "✨", "✅", "❌", "📌"]):
            self.status_label.config(text=msg.split('\n')[0].strip())

    def start_process(self):
        target = self.input_var.get().strip()
        if not target:
            return messagebox.showwarning("警告", "请输入文件路径或 URL")

        # Save settings for next run
        self.save_settings()

        # Auto-save current metadata to project config before starting
        try:
            pm, _, config_path = self.load_project_manager(target)
            curr_cat = self.cat_title_var.get().strip()
            if curr_cat and curr_cat not in self.catchy_title_history:
                self.catchy_title_history.append(curr_cat)
                self.cat_title_combo.config(values=self.catchy_title_history)
            
            curr_std = self.std_title_var.get().strip()
            if curr_std and curr_std not in self.standard_title_history:
                self.standard_title_history.append(curr_std)
                self.std_title_combo.config(values=self.standard_title_history)

            self.save_project_config(config_path, curr_std, curr_cat, self.catchy_title_history, self.standard_title_history)
        except Exception as e:
            print(f"Failed to auto-save project config: {e}")

        # Switch to Execution Logs tab automatically
        self.notebook.select(self.tab3)

        # Reset UI controls
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_var.set(0)
        self.status_label.config(text="🚀 正在启动工作流...")
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")

        # Prepare background command line arguments
        venv_python = "/Users/shanfu/cc/.venv/bin/python"
        dispatch_script = os.path.join(POSTFDRY_ROOT, "scripts", "postfdry-os.py")

        cmd = [
            venv_python, "-u", dispatch_script, target,
            "--non-interactive",
            "--mode", self.mode_var.get(),
            "--model", self.model_var.get(),
            "--text-style", self.text_style_var.get(),
            "--cover-style", self.cover_style_var.get(),
            "--type", self.article_type_var.get(),
            "--image-model", self.image_model_var.get()
        ]

        # Metadata overrides
        thoughts = self.thoughts_text.get(1.0, tk.END).strip()
        if thoughts:
            cmd.extend(["--thoughts", thoughts])

        std_title = self.std_title_var.get().strip()
        cat_title = self.cat_title_var.get().strip()
        if std_title:
            cmd.extend(["--target-title", std_title])
        if cat_title:
            cmd.extend(["--catchy-title", cat_title])

        if self.localize_images_var.get():
            cmd.append("--localize-images")
        if self.reuse_translation_var.get():
            cmd.append("--reuse-translation")
        if self.gen_images_var.get():
            cmd.append("--gen-images")
        if self.pdf_gen_var.get():
            cmd.append("--pdf")

        print(f"🚀 [GUI] Running: {' '.join(cmd)}")
        threading.Thread(target=self.run_worker_thread, args=(cmd,), daemon=True).start()

    def run_worker_thread(self, cmd):
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                env=env
            )
            if self.current_process.stdout:
                for line in self.current_process.stdout:
                    self.root.after(0, self.log, line.strip())
            ret_code = self.current_process.wait()
            
            def handle_completion(r):
                if r == 0:
                    self.progress_var.set(100.0)
                    self.status_label.config(text="✅ 工作流执行完成！")
                    self.check_existing_translation()
                    
                    # Auto sync to WeChat if enabled
                    if self.wechat_sync_enabled_var.get():
                        try:
                            base_dir = "/Users/shanfu/cc/Projects"
                            if os.path.exists(base_dir):
                                subdirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir)]
                                subdirs = [d for d in subdirs if os.path.isdir(d)]
                                if subdirs:
                                    most_recent = max(subdirs, key=os.path.getmtime)
                                    output_dir = os.path.join(most_recent, "output")
                                    if os.path.exists(output_dir):
                                        pub_file = self.find_wechat_publish_file(output_dir)
                                        if pub_file:
                                            threading.Thread(target=self.run_wechat_sync_thread, args=(pub_file,), daemon=True).start()
                                        else:
                                            self.log("⚠️ [WeChat] 未找到适合同步的 Markdown 输出文件。")
                        except Exception as ex:
                            self.log(f"⚠️ [WeChat] 自动查找同步输出文件出错: {ex}")
                            
                    self.open_finished_product()
                    self.merged_button_state = "completed"
                    self.start_btn.config(text="完成，再来一篇")
                else:
                    self.status_label.config(text="❌ 执行失败")
            
            self.root.after(0, lambda: handle_completion(ret_code))
        except Exception as e:
            self.root.after(0, self.log, f"❌ 执行过程中发生异常: {str(e)}")
        finally:
            self.current_process = None
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))

    def stop_process(self):
        # 1. 检查是否有核心子进程正在运行（主流水线进程）
        p = self.current_process
        if p:
            if messagebox.askyesno("中止", "确定停止当前流水线及其所有子进程？"):
                try:
                    import psutil
                    parent = psutil.Process(p.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                    self.log("🛑 工作流已被手动中止。")
                except Exception as e:
                    self.log(f"⚠️ 中止失败: {e}")
                finally:
                    self.current_process = None
                    self.reset_merged_button()
                    self.stop_btn.config(state="disabled")
            return

        # 2. 检查是否有微信同步子进程正在运行
        if hasattr(self, "wechat_process") and self.wechat_process:
            wp = self.wechat_process
            if messagebox.askyesno("中止", "确定中止微信公众号同步进程？"):
                try:
                    import psutil
                    parent = psutil.Process(wp.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                    self.log("🛑 微信同步流程已被手动中止。")
                except Exception as e:
                    self.log(f"⚠️ 中止微信同步失败: {e}")
                finally:
                    self.wechat_process = None
                    self.status_label.config(text="🛑 微信同步已被中止")
                    self.stop_btn.config(state="disabled")
                    self.start_btn.config(state="normal")
            return

        # 3. 检查是否正在进行 Onboarding 剖析
        if self.merged_button_state == "extracting":
            if messagebox.askyesno("中止", "确定中止当前的 AI 出版规划建议剖析？"):
                self.log("🛑 AI 剖析已手动中止。")
                self.reset_merged_button()
                self.stop_btn.config(state="disabled")
                self.status_label.config(text="💡 请输入原文 URL 或导入本地 Markdown 文件")
            return

        # 4. 检查是否正在进行标题重新生成
        if hasattr(self, "btn_regenerate_title") and str(self.btn_regenerate_title['state']) == "disabled":
            if messagebox.askyesno("中止", "确定中止标题重新生成进程？"):
                self.log("🛑 标题生成已被中止。")
                self.btn_regenerate_title.config(state="normal")
                self.stop_btn.config(state="disabled")
                self.status_label.config(text="💡 标题重新生成已被中止")
            return

    def on_exit(self):
        if self.current_process:
            if not messagebox.askyesno("退出", "流水线正在运行，确定中止并退出？"):
                return
            self.stop_process()
        self.root.destroy()

    def on_vendor_change(self, event):
        v_name = self.vendor_var.get()
        threading.Thread(target=self.fetch_models_async, args=(v_name,), daemon=True).start()
        self.update_api_key_ui()

    def fetch_models_async(self, v_name):
        try:
            from llm_utils import LLMProvider, LLMClient
            v_id_str = self.vendor_map.get(v_name, "gemini")
            provider = LLMProvider(v_id_str)

            # Show loading state
            self.root.after(0, lambda: self.model_combo.config(values=["正在获取模型列表..."]))
            self.root.after(0, lambda: self.model_var.set("正在获取..."))

            client = LLMClient()
            models = client.list_models_by_provider(provider)
            if models:
                self.root.after(0, lambda: self.model_combo.config(values=models))
                # If current model isn't in the new list, pick the first one
                if self.model_var.get() not in models:
                    self.root.after(0, lambda: self.model_var.set(models[0]))
            else:
                self.root.after(0, lambda: self.model_combo.config(values=["未发现可用模型"]))
                self.root.after(0, lambda: self.model_var.set("无模型"))
                self.root.after(0, lambda: self.log(f"⚠️ 厂商 {v_name} 未返回任何模型"))
        except Exception as e:
            err_msg = f"获取模型失败 ({v_name}): {str(e)}"
            self.root.after(0, lambda: self.model_combo.config(values=["获取失败"]))
            self.root.after(0, lambda: self.model_var.set("错误"))

    def open_finished_product(self):
        try:
            base_dir = "/Users/shanfu/cc/Projects"
            if not os.path.exists(base_dir):
                return
            
            subdirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir)]
            subdirs = [d for d in subdirs if os.path.isdir(d)]
            if not subdirs:
                return
                
            most_recent = max(subdirs, key=os.path.getmtime)
            output_dir = os.path.join(most_recent, "output")
            
            if os.path.exists(output_dir):
                self.log(f"📂 [GUI] 正在打开成品输出目录: {output_dir}")
                subprocess.run(["open", output_dir])
        except Exception as e:
            self.log(f"⚠️ [GUI] 自动打开成品目录失败: {str(e)}")

    def load_wechat_credentials(self):
        app_id = ""
        app_secret = ""
        env_paths = [
            "/Users/shanfu/cc/.baoyu-skills/.env",
            os.path.expanduser("~/.baoyu-skills/.env")
        ]
        for path in env_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    id_match = re.search(r'^WECHAT_APP_ID=(.*)', content, re.M)
                    secret_match = re.search(r'^WECHAT_APP_SECRET=(.*)', content, re.M)
                    if id_match:
                        app_id = id_match.group(1).strip()
                    if secret_match:
                        app_secret = secret_match.group(1).strip()
                    break
                except: pass
        return app_id, app_secret

    def save_wechat_credentials(self, app_id, app_secret):
        env_dir = "/Users/shanfu/cc/.baoyu-skills"
        env_path = os.path.join(env_dir, ".env")
        try:
            os.makedirs(env_dir, exist_ok=True)
            content = ""
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            def set_env_val(key, val, current):
                regex = re.compile(rf'^{key}=.*', re.M)
                if regex.search(current):
                    return regex.sub(f'{key}={val}', current)
                return current.strip() + f'\n{key}={val}'
            
            new_content = set_env_val('WECHAT_APP_ID', app_id, content)
            new_content = set_env_val('WECHAT_APP_SECRET', app_secret, new_content)
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(new_content.strip() + '\n')
        except Exception as e:
            print(f"⚠️ [WeChat] 保存微信凭据失败: {e}")

    def load_wechat_accounts(self):
        accounts = []
        possible_paths = [
            os.path.expanduser("~/.baoyu-skills/baoyu-post-to-wechat/EXTEND.md"),
            "/Users/shanfu/cc/.baoyu-skills/baoyu-post-to-wechat/EXTEND.md"
        ]
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    parts = content.split('accounts:')
                    if len(parts) > 1:
                        accounts_block = parts[1]
                        matches = re.findall(r'-\s*name:\s*(.*?)\n\s*alias:\s*(.*?)(?:\n|$)', accounts_block)
                        for m in matches:
                            accounts.append((m[0].strip(), m[1].strip()))
                    if accounts:
                        break
                except: pass
        if not accounts:
            accounts.append(('默认公众号', 'default'))
        return accounts

    def load_wechat_data(self):
        try:
            appid, secret = self.load_wechat_credentials()
            self.wechat_appid_var.set(appid)
            self.wechat_secret_var.set(secret)
            
            self.wechat_accounts = self.load_wechat_accounts()
            account_values = [f"{name} ({alias})" for name, alias in self.wechat_accounts]
            self.wechat_account_combo.config(values=account_values)
            if account_values:
                saved_alias = self.settings.get("wechat_account_alias", "default")
                matched_idx = 0
                for idx, (name, alias) in enumerate(self.wechat_accounts):
                    if alias == saved_alias:
                        matched_idx = idx
                        break
                self.wechat_account_combo.current(matched_idx)
                
            self.wechat_theme_var.set(self.settings.get("wechat_theme", "modern"))
            self.wechat_author_var.set(self.settings.get("wechat_author", ""))
        except Exception as e:
            print(f"Failed to load wechat data: {e}")

    def get_selected_wechat_alias(self):
        try:
            selected_idx = self.wechat_account_combo.current()
            if selected_idx >= 0 and selected_idx < len(self.wechat_accounts):
                return self.wechat_accounts[selected_idx][1]
        except: pass
        return "default"

    def find_wechat_publish_file(self, output_dir):
        # 优先寻找包含 .解读.md 的改写文件
        for f in os.listdir(output_dir):
            if f.endswith(".解读.md"):
                return os.path.join(output_dir, f)
                
        interp_path = os.path.join(output_dir, "interpreted.md")
        if os.path.exists(interp_path):
            return interp_path
            
        for f in os.listdir(output_dir):
            if f.endswith(".md") and f != "interpreted.md" and not f.endswith(".clean.md"):
                return os.path.join(output_dir, f)
        return None

    def run_wechat_sync_thread(self, file_path):
        try:
            self.root.after(0, lambda: self.status_label.config(text=" 📤 正在同步至微信公众号草稿箱..."))
            self.log("📤 [WeChat] 正在启动微信公众号同步流程...")
            
            theme = self.wechat_theme_var.get() or "modern"
            author = self.wechat_author_var.get().strip() or self.author_var.get().strip() or "AI数据治理研究院"
            alias = self.get_selected_wechat_alias()
            
            cover_path = ""
            project_root = os.path.dirname(os.path.dirname(file_path))
            cover_file = os.path.join(project_root, "assets", "cover.png")
            if not os.path.exists(cover_file):
                cover_file = os.path.join(project_root, "assets", "cover", "cover.png")
            if os.path.exists(cover_file):
                cover_path = cover_file
                self.log(f"📌 [WeChat] 找到本地封面图: {cover_file}")
            
            engine_script = "/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-api.ts"
            
            cmd = ["npx", "-y", "bun", engine_script, file_path, "--theme", theme, "--author", author]
            if alias and alias != "default":
                cmd.extend(["--account", alias])
            if cover_path:
                cmd.extend(["--cover", cover_path])
                
            self.log(f"🚀 [WeChat] 运行命令: {' '.join(cmd)}")
            
            env = os.environ.copy()
            env["WECHAT_APP_ID"] = self.wechat_appid_var.get().strip()
            env["WECHAT_APP_SECRET"] = self.wechat_secret_var.get().strip()
            
            cwd = "/Users/shanfu/cc"
            
            # 开启 stop_btn 并禁用 start_btn 以指示正在进行后台发布
            self.root.after(0, lambda: self.stop_btn.config(state="normal"))
            self.root.after(0, lambda: self.start_btn.config(state="disabled"))
            
            self.wechat_process = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            stdout_data, stderr_data = self.wechat_process.communicate()
            
            # 判断进程是否已被 stop_process 强行关闭 (如果是，wechat_process 已经被设为 None 且已 reset)
            if not hasattr(self, "wechat_process") or self.wechat_process is None:
                # 微信同步已被中止，静默返回，防止报错
                return
                
            ret_code = self.wechat_process.returncode
            self.wechat_process = None
            
            # 恢复按钮状态
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            
            if ret_code == 0:
                self.root.after(0, lambda: self.status_label.config(text="✅ 成功同步至微信草稿箱！"))
                self.log(f"✅ [WeChat] 同步微信草稿箱成功！\n输出日志:\n{stdout_data}")
            else:
                self.root.after(0, lambda: self.status_label.config(text="❌ 微信同步失败"))
                self.log(f"❌ [WeChat] 同步微信草稿箱失败 (Exit Code {ret_code}):\n{stderr_data or stdout_data}")
        except Exception as e:
            self.wechat_process = None
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            self.root.after(0, lambda: self.status_label.config(text="❌ 微信同步异常"))
            self.log(f"❌ [WeChat] 微信同步异常: {e}")

    def get_project_env_path(self):
        # Dynamically locate the project root .env file (two levels up from Library/Tools/postfdry/)
        return os.path.abspath(os.path.join(POSTFDRY_ROOT, "..", "..", ".env"))

    def load_api_key(self, vendor):
        env_key = self.vendor_env_keys.get(vendor)
        if not env_key:
            return ""

        # 1. Try reading from project .env
        env_path = self.get_project_env_path()
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                match = re.search(rf'^{env_key}=(.*)', content, re.M)
                if match:
                    val = match.group(1).strip()
                    if val: return val
            except:
                pass

        # 2. Fallback to ~/.baoyu-skills/.env
        backup_env = os.path.expanduser("~/.baoyu-skills/.env")
        if os.path.exists(backup_env):
            try:
                with open(backup_env, 'r', encoding='utf-8') as f:
                    content = f.read()
                match = re.search(rf'^{env_key}=(.*)', content, re.M)
                if match:
                    val = match.group(1).strip()
                    if val: return val
            except:
                pass

        # 3. Fallback to os.environ
        return os.environ.get(env_key, "")

    def update_api_key_ui(self):
        vendor = self.vendor_var.get()
        key_val = self.load_api_key(vendor)
        if key_val:
            # Display as asterisks to indicate existence
            self.api_key_var.set("*" * 16)
        else:
            self.api_key_var.set("")

    def save_api_key(self):
        vendor = self.vendor_var.get()
        env_key = self.vendor_env_keys.get(vendor)
        if not env_key:
            messagebox.showerror("错误", f"未找到厂商 {vendor} 对应的环境变量配置")
            return

        new_val = self.api_key_var.get().strip()
        if not new_val:
            messagebox.showwarning("警告", "请输入有效的 API Key")
            return

        # If it consists only of asterisks, the user did not change it
        if re.match(r'^\*+$', new_val):
            messagebox.showinfo("信息", "API Key 未改变，无需保存")
            return

        env_path = self.get_project_env_path()
        try:
            content = ""
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    content = f.read()

            def set_env_val(key, val, current):
                regex = re.compile(rf'^{key}=.*', re.M)
                if regex.search(current):
                    return regex.sub(f'{key}={val}', current)
                prefix = "\n" if current and not current.endswith("\n") else ""
                return current + f'{prefix}{key}={val}'

            new_content = set_env_val(env_key, new_val, content)
            
            # Create parent dirs if needed
            os.makedirs(os.path.dirname(env_path), exist_ok=True)
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(new_content.strip() + '\n')
            
            # Sync to os.environ so the running process can pick it up immediately
            os.environ[env_key] = new_val

            messagebox.showinfo("成功", f"{vendor} 的 API Key 已成功保存并更新")
            # Update UI to show asterisks
            self.api_key_var.set("*" * 16)
        except Exception as e:
            messagebox.showerror("错误", f"保存 API Key 失败: {e}")

    def test_connectivity(self):
        vendor = self.vendor_var.get()
        model = self.model_var.get()
        if not model or model in ["正在获取...", "正在获取模型列表...", "未发现可用模型", "无模型", "错误", "获取失败"]:
            messagebox.showerror("错误", "请先选择一个有效的模型进行测试")
            return

        self.log(f"🔄 正在测试与 {vendor} ({model}) 的连通性...")
        self.status_label.config(text="🔄 正在测试连通性...")

        # Run connection test in a thread to keep GUI responsive
        threading.Thread(target=self.run_connectivity_test_async, args=(vendor, model), daemon=True).start()

    def run_connectivity_test_async(self, vendor, model):
        try:
            from llm_utils import LLMProvider, LLMClient
            v_id_str = self.vendor_map.get(vendor, "gemini")
            provider = LLMProvider(v_id_str)

            client = LLMClient()
            # If the user typed/updated the key but didn't save, we should temporarily set it at runtime to let them test it!
            temp_key = self.api_key_var.get().strip()
            if temp_key and not re.match(r'^\*+$', temp_key):
                client.set_provider_key(provider, temp_key)

            # Test prompt
            prompt = "Hi, this is a connectivity test. Please reply with exactly 'OK'."
            success, response = client.generate_content_with_provider(prompt, provider, model_name=model, fallback=False)

            if success:
                self.root.after(0, lambda: messagebox.showinfo("测试成功", f"连通性测试成功！\n响应内容: {response.strip()}"))
                self.root.after(0, lambda: self.status_label.config(text="✅ 连通性测试成功"))
                self.log(f"✅ [Test] 与 {vendor} ({model}) 连通性测试成功！响应内容: {response.strip()}")
            else:
                self.root.after(0, lambda: messagebox.showerror("测试失败", f"连通性测试失败！\n错误原因: {response}"))
                self.root.after(0, lambda: self.status_label.config(text="❌ 连通性测试失败"))
                self.log(f"❌ [Test] 与 {vendor} ({model}) 连通性测试失败: {response}")
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"连通性测试执行异常: {e}"))
            self.root.after(0, lambda: self.status_label.config(text="❌ 测试异常"))
            self.log(f"❌ [Test] 连通性测试执行异常: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = PostOSGUI(root)
    root.mainloop()

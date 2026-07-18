
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import sys
import os
import json
import re
import psutil

class ProcessTree:
    """Manages cross-platform process suspension and termination."""
    @staticmethod
    def kill(pid):
        if not pid: return
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True): child.kill()
            parent.kill()
        except: pass

    @staticmethod
    def suspend(pid):
        if not pid: return
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True): child.suspend()
            parent.suspend()
        except: pass

    @staticmethod
    def resume(pid):
        if not pid: return
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True): child.resume()
            parent.resume()
        except: pass

# --- Paths ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
COMMON_DIR = os.path.join(os.path.dirname(CURRENT_DIR), "common")
if COMMON_DIR not in sys.path:
    sys.path.append(COMMON_DIR)

AUTOSUB_SCRIPT = os.path.join(CURRENT_DIR, "autosub.py")
SETTINGS_FILE = os.path.join(CURRENT_DIR, "settings.json")
DEFAULTS_FILE = os.path.join(CURRENT_DIR, "defaults.json")

# --- Base Output Directory (mirrors autosub.py logic) ---
_tools_dir = os.path.dirname(CURRENT_DIR)
_tmp_root = os.path.dirname(_tools_dir)
if os.path.basename(_tmp_root).lower() == "library":
    PROJECT_ROOT = os.path.dirname(_tmp_root)
else:
    PROJECT_ROOT = _tmp_root
BASE_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Projects")
# Video extensions that hardsub files can have (matches download_video in autosub.py)
VIDEO_EXTS = ('.mp4', '.mkv', '.webm', '.mov', '.ts')

class AutoSubGUI:
    input_var: tk.StringVar
    output_dir_var: tk.StringVar
    layout_var: tk.StringVar
    main_lang_var: tk.StringVar
    cn_font_var: tk.StringVar
    en_font_var: tk.StringVar
    cn_size_var: tk.StringVar
    en_size_var: tk.StringVar
    cn_color_var: tk.StringVar
    en_color_var: tk.StringVar
    bili_enabled_var: tk.BooleanVar
    bili_tid_var: tk.StringVar
    bili_tags_var: tk.StringVar
    bili_season_var: tk.StringVar

    def __init__(self, root):
        self.root = root
        self.root.title("AutoSub Pro - 自动视频字幕生成工具")
        self.root.geometry("1020x500")

        # Set Window Icon
        icon_name = "autosub_vibrant_v2.png" if sys.platform == "darwin" else "autosub.ico"
        icon_path = os.path.join(CURRENT_DIR, icon_name)
        if os.path.exists(icon_path):
            try:
                if sys.platform == "darwin":
                    self.icon_img = tk.PhotoImage(file=icon_path)
                    self.root.tk.call('wm', 'iconphoto', self.root._w, self.icon_img)
                else:
                    self.root.iconbitmap(icon_path)
            except: pass

        self.ui_font = ("PingFang SC", 12) if sys.platform == "darwin" else ("Microsoft YaHei", 10)
        self.log_font = ("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10)

        # Vendor Map to LLMProvider Enum values
        self.vendor_map = {
            "Google Vertex AI": "vertex",
            "Google Gemini": "gemini",
            "OpenAI": "openai",
            "DeepSeek": "deepseek",
            "Silicon Flow": "siliconflow",
            "Zhipu (GLM)": "zhipu",
            "Moonshot (Kimi)": "moonshot",
            "Alibaba (Bailian)": "dashscope",
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
            "Alibaba (Bailian)": "DASHSCOPE_API_KEY",
            "MiniMax": "MINIMAX_API_KEY"
        }

        self.settings = self.load_settings()
        self.vendor_default_models = self.settings.get("vendor_default_models", {})
        self.key_editor_vendor = self.settings.get("llm_vendor", "Google Vertex AI")
        self.key_editor_env_key = self.vendor_env_keys.get(self.key_editor_vendor, "VERTEX_SA_KEY_PATH")
        self.current_process = None
        self.last_was_progress = False

        self.setup_ui()

        if sys.platform == "darwin":
            self.root.update_idletasks()
            self.root.lift()
            self.root.focus_force()

        # Initial async load
        self.root.after(1000, lambda: self.on_vendor_change(None))

    def load_settings(self):
        # Default fallback values
        defaults = {
            "input": "", "cookies": "chrome", "output_dir": "",
            "llm_vendor": "Google Vertex AI", "llm_model": "gemini-3-flash-preview",
            "api_key": "", "model": "large-v2", "style": "auto",
            "trans_mode": "balanced", "quick": False, "quality": "high",
            "layout": "bilingual", "main_lang": "cn",
            "cn_font": "STKaiti", "en_font": "Calibri",
            "cn_size": "60", "en_size": "36",
            "cn_color": "Gold", "en_color": "White",
            "bg_box": True,
            "sync_gdrive": "18iAFFSuHQmZlxVN0dri1Gbje9SmpS96f", "gdrive_enabled": True
        }

        # Try loading from existing settings
        for fpath in [DEFAULTS_FILE, SETTINGS_FILE]:
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as fs:
                        data = json.load(fs)
                        # [COMPATIBILITY] Handle key mapping differences
                        if "remote_id" in data: data["sync_gdrive"] = data["remote_id"]
                        if "gdrive_sync" in data: data["gdrive_enabled"] = data["gdrive_sync"]
                        # Skip empty cookies settings to preserve the 'chrome' default
                        if "cookies" in data and not data["cookies"]:
                            del data["cookies"]
                        defaults.update(data)
                except: pass
        return defaults

    def setup_ui(self):
        self.main_container = ttk.Frame(self.root, padding=10)
        self.main_container.pack(fill="both", expand=True)

        # Create Notebook (Tabbed Interface) for compact and adaptive layout
        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(fill="both", expand=True, pady=5)

        # Create Tab Frames
        self.tab1 = ttk.Frame(self.notebook, padding=10)
        self.tab2 = ttk.Frame(self.notebook, padding=10)
        self.tab3 = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.tab1, text=" 任务配置 ")
        self.notebook.add(self.tab2, text=" 字幕样式 ")
        self.notebook.add(self.tab3, text=" 执行日志 ")

        # 1. Input Section (Parent: tab1)
        f1 = ttk.LabelFrame(self.tab1, text=" 输入源 ", padding=10)
        f1.pack(fill="x", pady=5)
        self.create_entry_row(f1, "视频/URL:", "input_var", 0, self.browse_video)
        
        # Cookies Row (Dropdown + Entry)
        ttk.Label(f1, text="Cookies:").grid(row=1, column=0, sticky="w", pady=2)
        self.cookies_var = tk.StringVar(value=str(self.settings.get("cookies", "")))
        self.cookies_combo = ttk.Combobox(f1, textvariable=self.cookies_var, width=63)
        self.cookies_combo['values'] = ("None", "chrome", "safari", "firefox", "edge")
        self.cookies_combo.grid(row=1, column=1, padx=5)
        ttk.Button(f1, text="选择...", command=self.browse_cookies).grid(row=1, column=2)

        self.create_entry_row(f1, "项目根目录:", "output_dir_var", 2, self.browse_folder)

        # 2. Basic Settings (Parent: tab1)
        f2 = ttk.LabelFrame(self.tab1, text=" 基础设置 ", padding=10)
        f2.pack(fill="x", pady=5)

        ttk.Label(f2, text="模型厂商:").grid(row=0, column=0, sticky="w")
        current_vendor = str(self.settings.get("llm_vendor", ""))
        vendors = list(self.vendor_map.keys())
        if current_vendor not in vendors:
            current_vendor = "Alibaba (Bailian)"
            
        self.vendor_var = tk.StringVar(value=current_vendor)
        self.vendor_combo = ttk.Combobox(f2, textvariable=self.vendor_var, values=vendors, state="readonly", width=18)
        self.vendor_combo.grid(row=0, column=1, sticky="w", padx=5)
        self.vendor_combo.bind("<<ComboboxSelected>>", self.on_vendor_change)

        ttk.Label(f2, text="选择模型:").grid(row=0, column=2, sticky="w", padx=10)
        self.llm_model_var = tk.StringVar(value=str(self.settings.get("llm_model", "")))
        self.llm_combo = ttk.Combobox(f2, textvariable=self.llm_model_var, width=22)
        self.llm_combo.grid(row=0, column=3, sticky="w")
        ttk.Button(f2, text="设为默认", width=8, command=self.set_llm_model_default).grid(row=0, column=4, padx=5)

        self.api_key_label = ttk.Label(f2, text="API Key:")
        self.api_key_label.grid(row=1, column=0, sticky="w", pady=5)
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(f2, textvariable=self.api_key_var, show="*", width=35)
        self.api_key_entry.grid(row=1, column=1, columnspan=2, sticky="w", padx=5)
        self.api_key_entry.bind("<FocusOut>", lambda e: self.on_vendor_change(None))
        ttk.Button(f2, text="保存该密钥", width=10, command=self.save_api_key).grid(row=1, column=3, sticky="w")
        ttk.Button(f2, text="测试连接", width=10, command=self.test_connection).grid(row=1, column=4, padx=5)

        ttk.Label(f2, text="转录模型:").grid(row=2, column=0, sticky="w")
        self.whisper_var = tk.StringVar(value=str(self.settings.get("model", "")))
        ttk.Combobox(f2, textvariable=self.whisper_var, values=["large-v3", "large-v2", "medium", "small"], width=18).grid(row=2, column=1, sticky="w", padx=5)

        ttk.Label(f2, text="内容语气:").grid(row=2, column=2, sticky="w", padx=10)
        self.style_var = tk.StringVar(value=str(self.settings.get("style", "auto")))
        ttk.Combobox(f2, textvariable=self.style_var, values=["auto", "casual", "formal", "edgy"], width=22).grid(row=2, column=3, sticky="w")

        ttk.Label(f2, text="翻译策略:").grid(row=3, column=0, sticky="w", pady=5)
        self.trans_mode_var = tk.StringVar(value=str(self.settings.get("trans_mode", "balanced")))
        ttk.Combobox(f2, textvariable=self.trans_mode_var, values=["balanced", "paraphrase"], width=18).grid(row=3, column=1, sticky="w", padx=5)

        ttk.Label(f2, text="压制画质:").grid(row=3, column=2, sticky="w", padx=10)
        self.quality_var = tk.StringVar(value=str(self.settings.get("quality", "high")))
        ttk.Combobox(f2, textvariable=self.quality_var, values=["standard", "high", "lossless"], width=22).grid(row=3, column=3, sticky="w")

        self.quick_var = tk.BooleanVar(value=bool(self.settings.get("quick", False)))
        ttk.Checkbutton(f2, text="快捷转录（大模型/网页视频实验性）", variable=self.quick_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

        # 3. Subtitle Style (Parent: tab2)
        f3 = ttk.LabelFrame(self.tab2, text=" 字幕样式 ", padding=10)
        f3.pack(fill="x", pady=5)
        self.create_style_row(f3, "布局模式:", "layout_var", ["bilingual", "cn", "en"], "首选语言:", "main_lang_var", ["cn", "en"], 0)
        self.create_style_row(f3, "中文样式:", "cn_font_var", ["STKaiti", "PingFang SC"], "字号:", "cn_size_var", None, 1)
        self.create_style_row(f3, "英文样式:", "en_font_var", ["Arial", "Calibri"], "字号:", "en_size_var", None, 2)
        self.create_style_row(f3, "中文颜色:", "cn_color_var", ["Gold", "White", "Yellow"], "英文颜色:", "en_color_var", ["White", "Gold", "Gray"], 3)

        self.bg_box_var = tk.BooleanVar(value=bool(self.settings.get("bg_box", True)))
        ttk.Checkbutton(f3, text="启用背景框", variable=self.bg_box_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

        # 4. Cloud Sync (Parent: tab2)
        f4 = ttk.LabelFrame(self.tab2, text=" 云端同步 ", padding=10)
        f4.pack(fill="x", pady=5)
        self.gdrive_enabled_var = tk.BooleanVar(value=bool(self.settings.get("gdrive_enabled", True)))
        ttk.Checkbutton(f4, text="自动同步到 Google Drive", variable=self.gdrive_enabled_var).grid(row=0, column=0, sticky="w")
        ttk.Label(f4, text="文件夹 ID:").grid(row=0, column=1, padx=10)
        self.sync_gdrive_var = tk.StringVar(value=str(self.settings.get("sync_gdrive", "")))
        ttk.Entry(f4, textvariable=self.sync_gdrive_var, width=35).grid(row=0, column=2, padx=5)

        # 4.5 Bilibili Sync (Parent: tab2)
        f4_5 = ttk.LabelFrame(self.tab2, text=" Bilibili 同步 ", padding=10)
        f4_5.pack(fill="x", pady=5)
        self.bili_enabled_var = tk.BooleanVar(value=bool(self.settings.get("bili_enabled", True)))
        ttk.Checkbutton(f4_5, text="默认上传到 Bilibili", variable=self.bili_enabled_var).grid(row=0, column=0, sticky="w", pady=2)
        
        ttk.Label(f4_5, text="分区:").grid(row=0, column=1, padx=10, pady=2, sticky="e")
        self.bili_tid_var = tk.StringVar(value=str(self.settings.get("bili_tid", "智能识别 (Auto)")))
        bili_partitions = [
            "智能识别 (Auto)",
            "人工智能-主分区 (1011)",
            "人工智能-AI学习 (2096)",
            "人工智能-AI资讯 (2097)",
            "人工智能-AI杂谈 (2098)",
            "科技-计算机技术 (231)",
            "知识-科学科普 (201)",
            "知识-职业职场 (209)",
            "知识-财经商业 (207)",
            "影视-AI影像 (259)",
            "音乐-AI音乐 (265)",
            "资讯-热点 (212)",
            "生活-日常 (21)"
        ]
        ttk.Combobox(f4_5, textvariable=self.bili_tid_var, values=bili_partitions, width=18).grid(row=0, column=2, padx=5, pady=2, sticky="w")
        
        ttk.Label(f4_5, text="标签 (逗号/顿号分隔):").grid(row=1, column=0, padx=10, pady=2, sticky="e")
        self.bili_tags_var = tk.StringVar(value="")  # Tags: dynamically generated per upload, not persisted
        ttk.Entry(f4_5, textvariable=self.bili_tags_var, width=30).grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky="w")
        
        ttk.Label(f4_5, text="合集名称 (新建/选择):").grid(row=2, column=0, padx=10, pady=2, sticky="e")
        self.bili_season_var = tk.StringVar(value=str(self.settings.get("bili_season", "")))
        ttk.Entry(f4_5, textvariable=self.bili_season_var, width=30).grid(row=2, column=1, columnspan=2, padx=5, pady=2, sticky="w")

        # 5. Log Area (Parent: tab3)
        f5 = ttk.LabelFrame(self.tab3, text=" 日志与进度 ", padding=10)
        f5.pack(fill="both", expand=True, pady=5)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(f5, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=5)
        self.status_label = ttk.Label(f5, text="等待任务...")
        self.status_label.pack(pady=2)
        self.log_text = tk.Text(f5, height=10, state="disabled", font=self.log_font, bg="#ffffff", padx=5, pady=5)
        self.log_text.pack(fill="both", expand=True)

        # 6. Controls (Parent: root)
        f6 = ttk.Frame(self.root, padding=10)
        f6.pack(fill="x", side="bottom")
        ttk.Button(f6, text="退出", command=self.root.destroy).pack(side="left", padx=5)
        ttk.Button(f6, text="保存设置", command=self.save_settings).pack(side="left", padx=5)
        self.stop_btn = ttk.Button(f6, text="中止", state="disabled", command=self.stop_process)
        self.stop_btn.pack(side="right", padx=5)
        self.pause_btn = ttk.Button(f6, text="暂停", state="disabled", command=self.toggle_pause)
        self.pause_btn.pack(side="right", padx=5)
        self.start_btn = ttk.Button(f6, text="开始处理", command=self.start_process)
        self.start_btn.pack(side="right", padx=5)

        # Adjust window height dynamically based on the tallest tab content
        self.root.update_idletasks()
        req_height = self.root.winfo_reqheight()
        self.root.geometry(f"1020x{req_height + 10}")

    def create_entry_row(self, p, l, v, r, c):
        ttk.Label(p, text=l).grid(row=r, column=0, sticky="w", pady=2)
        var = tk.StringVar(value=str(self.settings.get(v.replace("_var", ""), "")))
        setattr(self, v, var)
        ttk.Entry(p, textvariable=var, width=65).grid(row=r, column=1, padx=5)
        ttk.Button(p, text="选择...", command=c).grid(row=r, column=2)

    def create_style_row(self, p, l1, v1, val1, l2, v2, val2, r):
        ttk.Label(p, text=l1).grid(row=r, column=0, sticky="w")
        var1 = tk.StringVar(value=str(self.settings.get(v1.replace("_var", ""), "")))
        setattr(self, v1, var1)
        if val1: ttk.Combobox(p, textvariable=var1, values=val1, width=22).grid(row=r, column=1, sticky="w", padx=5)
        else: ttk.Entry(p, textvariable=var1, width=24).grid(row=r, column=1, sticky="w", padx=5)
        ttk.Label(p, text=l2).grid(row=r, column=2, sticky="w", padx=10)
        var2 = tk.StringVar(value=str(self.settings.get(v2.replace("_var", ""), "")))
        setattr(self, v2, var2)
        if val2: ttk.Combobox(p, textvariable=var2, values=val2, width=22).grid(row=r, column=3, sticky="w", padx=5)
        else: ttk.Entry(p, textvariable=var2, width=24).grid(row=r, column=3, sticky="w", padx=5)

    def browse_video(self): f = filedialog.askopenfilename(); self.input_var.set(f) if f else None
    def browse_cookies(self): f = filedialog.askopenfilename(); self.cookies_var.set(f) if f else None
    def browse_folder(self): f = filedialog.askdirectory(); self.output_dir_var.set(f) if f else None

    def get_project_env_path(self):
        return os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", ".env"))

    def load_api_key(self, vendor, env_key=None):
        if not env_key:
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
                    val = match.group(1).strip().strip("'").strip('"')
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
                    val = match.group(1).strip().strip("'").strip('"')
                    if val: return val
            except:
                pass

        return os.environ.get(env_key, "")

    def update_api_key_ui(self):
        key_val = self.load_api_key(self.key_editor_vendor, self.key_editor_env_key)
        if key_val:
            self.api_key_var.set("*" * 16)
        else:
            self.api_key_var.set("")

    def update_key_editor(self, vendor_name, env_key):
        self.key_editor_vendor = vendor_name
        self.key_editor_env_key = env_key
        self.api_key_label.config(text=f"API Key ({vendor_name}):")
        self.update_api_key_ui()

    def save_api_key(self):
        vendor = self.key_editor_vendor
        env_key = self.key_editor_env_key
        if not env_key:
            messagebox.showerror("错误", f"未找到厂商 {vendor} 对应的环境变量配置")
            return

        new_val = self.api_key_var.get().strip()
        if not new_val:
            messagebox.showwarning("警告", "请输入有效的 API Key")
            return

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
            
            os.makedirs(os.path.dirname(env_path), exist_ok=True)
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(new_content.strip() + '\n')
            
            os.environ[env_key] = new_val

            messagebox.showinfo("成功", f"{vendor} 的 API Key 已保存并同步至统一 .env 文件")
            self.api_key_var.set("*" * 16)
        except Exception as e:
            messagebox.showerror("错误", f"保存 API Key 失败: {e}")

    def set_llm_model_default(self):
        vendor = self.vendor_var.get()
        model = self.llm_model_var.get()
        if not model or model in ["正在获取...", "正在获取模型列表...", "未发现可用模型", "无模型", "错误", "获取失败"]:
            messagebox.showerror("错误", "请先选择一个有效的模型")
            return
        self.vendor_default_models[vendor] = model
        self.save_settings()
        messagebox.showinfo("成功", f"已将 {model} 设为 {vendor} 的默认模型")

    def on_vendor_change(self, event=None):
        v_name = self.vendor_var.get()
        threading.Thread(target=self.fetch_models_async, args=(v_name,), daemon=True).start()
        env_key = self.vendor_env_keys.get(v_name, "GEMINI_API_KEY")
        self.update_key_editor(v_name, env_key)

    def fetch_models_async(self, v_name):
        try:
            from llm_utils import LLMProvider, LLMClient
            v_id_str = self.vendor_map.get(v_name, "gemini")
            provider = LLMProvider(v_id_str)

            # Show loading state
            self.root.after(0, lambda: self.llm_combo.config(values=["正在获取模型列表..."]))
            self.root.after(0, lambda: self.llm_model_var.set("正在获取..."))

            client = LLMClient()
            # Pass the API key from the GUI if it exists, but ONLY if not masked asterisks!
            gui_key = self.api_key_var.get().strip()
            if gui_key and not re.match(r'^\*+$', gui_key):
                client.set_provider_key(provider, gui_key)

            models = client.list_models_by_provider(provider)
            if models:
                self.root.after(0, lambda: self.llm_combo.config(values=models))
                
                # Check default model linkage
                default_model = self.vendor_default_models.get(v_name)
                if default_model and default_model in models:
                    self.root.after(0, lambda: self.llm_model_var.set(default_model))
                elif self.llm_model_var.get() not in models:
                    self.root.after(0, lambda: self.llm_model_var.set(models[0]))
            else:
                self.root.after(0, lambda: self.llm_combo.config(values=["未发现可用模型"]))
                self.root.after(0, lambda: self.llm_model_var.set("无模型"))
                self.root.after(0, lambda: self.log(f"⚠️ 厂商 {v_name} 未返回任何模型，请检查 API Key 或网络"))
        except Exception as e:
            import traceback
            err_msg = f"获取模型失败 ({v_name}): {str(e)}"
            self.root.after(0, lambda: self.log(f"❌ {err_msg}"))
            self.root.after(0, lambda: self.llm_combo.config(values=["获取失败"]))
            self.root.after(0, lambda: self.llm_model_var.set("错误"))
            print(traceback.format_exc())

    def test_connection(self):
        v_name = self.vendor_var.get()
        m_name = self.llm_model_var.get()
        api_key = self.api_key_var.get().strip()

        self.log(f"🧪 正在测试 {v_name} ({m_name}) 的连接...")
        threading.Thread(target=self.run_connection_test, args=(v_name, m_name, api_key), daemon=True).start()

    def run_connection_test(self, v_name, m_name, api_key):
        try:
            from llm_utils import LLMProvider, LLMClient
            v_id_str = self.vendor_map.get(v_name, "gemini")
            provider = LLMProvider(v_id_str)

            client = LLMClient()
            if api_key and not re.match(r'^\*+$', api_key):
                client.set_provider_key(provider, api_key)

            # Match the updated LLMClient.generate_content_with_provider API
            success, response = client.generate_content_with_provider(
                "Ping",
                provider=provider,
                model_name=m_name,
                fallback=False
            )

            if success:
                # Capture current values for the lambda
                final_resp = response
                self.root.after(0, lambda r=final_resp: self.log(f"✅ 连接成功! 响应: {r[:50]}..."))
                self.root.after(0, lambda r=final_resp: messagebox.showinfo("测试成功", f"与 {v_name} 的连接正常！\n\n响应内容:\n{r[:100]}..."))
            else:
                final_err = response
                self.root.after(0, lambda r=final_err: self.log(f"❌ 连接失败: {r}"))
                self.root.after(0, lambda r=final_err: messagebox.showerror("连接失败", f"无法连接到 {v_name}。\n\n详情:\n{r}"))
        except Exception as e:
            err_str = str(e)
            self.root.after(0, lambda es=err_str: self.log(f"❌ 测试过程出错: {es}"))

    def log(self, msg):
        self.log_text.config(state="normal")
        is_p = "Progress:" in msg or "%" in msg
        if is_p and self.last_was_progress: self.log_text.delete("end-2l", "end-1c")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.last_was_progress = is_p
        m = re.search(r"(\d+(\.\d+)?)%", msg)
        if m: self.progress_var.set(float(m.group(1)))
        if any(e in msg for e in ["🎬", "🎙️", "🌍", "🔥"]): self.status_label.config(text=msg.strip())

    def start_process(self):
        v = self.input_var.get().strip()
        if not v: return messagebox.showwarning("警告", "请输入视频 URL 或文件")
        
        # Switch to the Execution Logs tab automatically
        try:
            self.notebook.select(self.tab3)
        except Exception:
            pass

        # Reset UI state
        self.start_btn.config(state="disabled"); self.stop_btn.config(state="normal")
        self.progress_var.set(0)
        self.status_label.config(text="🚀 正在启动任务...")
        self.log_text.config(state="normal"); self.log_text.delete(1.0, tk.END); self.log_text.config(state="disabled")
        
        # Ensure any previous process is truly gone
        if self.current_process and self.current_process.poll() is None:
            try: ProcessTree.kill(self.current_process.pid)
            except: pass
            self.current_process = None

        # Robust Mapping for Localized Values
        trans_mode_map = {"平衡模式 (Balanced)": "balanced", "意译模式 (Paraphrase)": "paraphrase", "balanced": "balanced", "paraphrase": "paraphrase"}
        style_map = {"智能检测 (Auto)": "auto", "普通 (Casual)": "casual", "正式 (Formal)": "formal", "犀利 (Edgy)": "edgy", "auto": "auto", "casual": "casual", "formal": "formal", "edgy": "edgy"}
        
        t_mode = trans_mode_map.get(self.trans_mode_var.get(), "balanced")
        s_style = style_map.get(self.style_var.get(), "auto")

        py_exe = sys.executable
        venv_py = os.path.join(CURRENT_DIR, ".venv", "bin", "python" if sys.platform != "win32" else "python.exe")
        if os.path.exists(venv_py):
            py_exe = venv_py
        cmd = [py_exe, AUTOSUB_SCRIPT, v, "--headless"]
        cmd.extend(["--model", self.whisper_var.get(), "--llm-model", self.llm_model_var.get()])
        v_id_str = self.vendor_map.get(self.vendor_var.get(), "")
        if v_id_str:
            cmd.extend(["--llm-provider", v_id_str])
        
        cmd.extend(["--style", s_style, "--trans-mode", t_mode, "--quality", self.quality_var.get()])
        cmd.extend(["--layout", self.layout_var.get(), "--main-lang", self.main_lang_var.get()])
        cmd.extend(["--cn-font", self.cn_font_var.get(), "--en-font", self.en_font_var.get()])
        cmd.extend(["--cn-size", self.cn_size_var.get(), "--en-size", self.en_size_var.get()])
        if not self.bg_box_var.get(): cmd.append("--no-bg-box")
        if self.quick_var.get(): cmd.append("--quick")
        c_val = self.cookies_var.get().strip()
        if c_val:
            cmd.extend(["--cookies", c_val])
        if self.output_dir_var.get(): cmd.extend(["--output-dir", self.output_dir_var.get()])
        # GDrive sync runs in parallel with Bilibili upload after the pipeline
        # finishes (see run_worker), so we no longer pass --sync-gdrive here.
        gdrive_folder = self.sync_gdrive_var.get().strip() if self.gdrive_enabled_var.get() else ""

        print(f"🚀 [GUI] Launching: {' '.join(cmd)}")
        threading.Thread(target=self.run_worker, args=(cmd, v, self.output_dir_var.get(), gdrive_folder, py_exe), daemon=True).start()

    def run_worker(self, cmd, input_video, output_dir, gdrive_folder="", py_exe=None):
        import glob
        try:
            self.current_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
            self.root.after(0, lambda: self.pause_btn.config(state="normal"))
            if self.current_process.stdout:
                for line in self.current_process.stdout: self.root.after(0, self.log, line.strip())
            ret_code = self.current_process.wait()
            # Main pipeline (incl. hardsub burn) finished. Release current_process so
            # stop/pause no longer target the completed subprocess during uploads.
            self.current_process = None
            if ret_code != 0:
                self.root.after(0, lambda r=ret_code: self.status_label.config(text="❌ 失败"))
            else:
                # --- Parallel post-processing uploads ---
                # GDrive sync and Bilibili upload only READ the finished hardsub
                # video, so running them concurrently is safe; launch both at once.
                if output_dir:
                    search_dir = output_dir
                elif input_video.startswith("http"):
                    search_dir = BASE_OUTPUT_DIR
                else:
                    search_dir = os.path.dirname(input_video) or BASE_OUTPUT_DIR
                self.root.after(0, self.log, f"🔍 在目录中搜索 hardsub 视频: {search_dir}")
                hardsub_files = []
                for root_dir, _, files in os.walk(search_dir):
                    for f in files:
                        if "hardsub" in f and f.endswith(VIDEO_EXTS):
                            hardsub_files.append(os.path.join(root_dir, f))
                if not hardsub_files:
                    self.root.after(0, self.log, f"⚠️ 目录中未找到任何 hardsub 视频文件 (搜索了 {search_dir})")
                newest_video = max(hardsub_files, key=os.path.getmtime) if hardsub_files else None
                # Drive sync targets the job workdir (the folder holding the outputs).
                sync_dir = os.path.dirname(newest_video) if newest_video else search_dir

                upload_jobs = []  # (label, cmd) pairs launched concurrently below
                # 1) Google Drive sync (mirrors autosub.py trigger_sync headless branch)
                if gdrive_folder:
                    sync_script = os.path.join(PROJECT_ROOT, ".agents", "skills", "google-drive-sync", "scripts", "sync.py")
                    creds_path = os.path.join(PROJECT_ROOT, ".agents", "skills", "google-drive-sync", "credentials.json")
                    token_path = os.path.join(PROJECT_ROOT, ".agents", "skills", "google-drive-sync", "token.json")
                    sync_py = py_exe or sys.executable
                    if os.path.exists(sync_script) and os.path.exists(creds_path):
                        gdrive_cmd = [sync_py, sync_script, "--local-dir", sync_dir, "--remote-id", gdrive_folder, "--credentials", creds_path, "--token", token_path, "--wrap-folder", "--headless"]
                        upload_jobs.append(("☁️ [GDrive]", gdrive_cmd))
                    else:
                        self.root.after(0, self.log, f"⚠️ 找不到 GDrive 同步脚本或凭证，跳过 Drive 同步: {sync_script}")
                # 2) Bilibili upload (cmd built by the canonical autosub.build_bili_cmd,
                #    shared with the CLI and batch engine)
                if self.bili_enabled_var.get():
                    bili_tid_str = self.bili_tid_var.get().strip()
                    bili_tid = bili_category = None
                    if bili_tid_str and bili_tid_str != "智能识别 (Auto)":
                        m = re.search(r'\((\d+)\)', bili_tid_str)
                        if m:
                            bili_tid = m.group(1)
                        else:
                            bili_category = bili_tid_str
                    from autosub import build_bili_cmd
                    bili_cmd = build_bili_cmd(
                        sync_dir,
                        tid=bili_tid,
                        category_name=bili_category,
                        tags=self.bili_tags_var.get().strip() or None,
                        season=self.bili_season_var.get().strip() or None,
                    )
                    if bili_cmd:
                        self.root.after(0, self.log, f"📺 找到生成的视频: {os.path.basename(bili_cmd[2])}")
                        upload_jobs.append(("📺 [Bilibili]", bili_cmd))
                    elif newest_video:
                        self.root.after(0, self.log, "⚠️ Bilibili 上传跳过（未找到上传脚本或虚拟环境）。")
                    else:
                        self.root.after(0, self.log, "⚠️ 未找到生成的 hardsub 视频文件，跳过 Bilibili 上传。")
                # Launch all upload jobs concurrently, wait for all to finish
                if upload_jobs:
                    self.root.after(0, lambda: self.status_label.config(text="📤 正在上传..."))
                    def run_upload(label, ucmd):
                        self.root.after(0, self.log, f"{label} 开始上传...")
                        try:
                            proc = subprocess.Popen(ucmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
                            if proc.stdout:
                                for line in proc.stdout:
                                    self.root.after(0, self.log, f"{label} {line.strip()}")
                            proc.wait()
                            mark = "✅" if proc.returncode == 0 else "⚠️"
                            self.root.after(0, self.log, f"{label} {mark} 上传结束 (code={proc.returncode})")
                        except Exception as ue:
                            self.root.after(0, self.log, f"{label} ❌ 异常: {ue}")
                    upload_threads = []
                    for label, ucmd in upload_jobs:
                        t = threading.Thread(target=run_upload, args=(label, ucmd), daemon=True)
                        upload_threads.append(t)
                        t.start()
                    for t in upload_threads:
                        t.join()
                self.root.after(0, lambda: self.status_label.config(text="✅ 完成！"))
        except Exception as e: self.root.after(0, self.log, f"错误: {str(e)}")
        finally:
            self.current_process = None
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))
            self.root.after(0, lambda: self.pause_btn.config(state="disabled", text="暂停 (Pause)"))
            self.is_paused = False

    def toggle_pause(self):
        p = self.current_process
        if not p: return
        if not hasattr(self, "is_paused"): self.is_paused = False

        if self.is_paused:
            ProcessTree.resume(p.pid)
            self.is_paused = False
            self.pause_btn.config(text="暂停 (Pause)")
            self.log("▶️ 任务已继续...")
        else:
            ProcessTree.suspend(p.pid)
            self.is_paused = True
            self.pause_btn.config(text="继续 (Resume)")
            self.log("⏸️ 任务已暂停...")

    def stop_process(self):
        p = self.current_process
        if p and messagebox.askyesno("中止", "确定停止当前任务及其所有关联进程？"):
            ProcessTree.kill(p.pid)
            self.log("🛑 任务已手动中止。")

    def save_settings(self):
        data = {
            "llm_vendor": self.vendor_var.get(),
            "llm_model": self.llm_model_var.get(),
            "model": self.whisper_var.get(),
            "style": self.style_var.get(),
            "trans_mode": self.trans_mode_var.get(),
            "quality": self.quality_var.get(),
            "layout": self.layout_var.get(),
            "main_lang": self.main_lang_var.get(),
            "cn_font": self.cn_font_var.get(),
            "en_font": self.en_font_var.get(),
            "cn_size": self.cn_size_var.get(),
            "en_size": self.en_size_var.get(),
            "cn_color": self.cn_color_var.get(),
            "en_color": self.en_color_var.get(),
            "bg_box": self.bg_box_var.get(),
            "api_key": self.api_key_var.get(),
            "quick": self.quick_var.get(),
            "sync_gdrive": self.sync_gdrive_var.get(),
            "gdrive_enabled": self.gdrive_enabled_var.get(),
            "bili_enabled": self.bili_enabled_var.get(),
            "bili_tid": self.bili_tid_var.get(),
            # bili_tags intentionally not persisted - dynamically generated per upload
            "bili_season": self.bili_season_var.get(),
            "vendor_default_models": self.vendor_default_models
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            messagebox.showinfo("成功", "当前配置已保存为默认设置。")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    root = tk.Tk()
    app = AutoSubGUI(root)
    root.mainloop()

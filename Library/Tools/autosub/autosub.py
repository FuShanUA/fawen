import os
import sys
import subprocess
import json
import time
import re
import glob
import shutil
import argparse
import io

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# --- Global Window Suppression Patch for Windows ---
if sys.platform == "win32":
    _original_popen = subprocess.Popen
    def _patched_popen(*args, **kwargs):
        cflags = kwargs.get('creationflags', 0)
        kwargs['creationflags'] = cflags | CREATE_NO_WINDOW
        return _original_popen(*args, **kwargs)
    subprocess.Popen = _patched_popen

if sys.platform == "win32":
    import msvcrt
else:
    import select
    import termios
    import tty

    def _getch():
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return None
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch.encode('utf-8')

    def _kbhit():
        if not os.isatty(sys.stdin.fileno()):
            return False
        return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [])

    class _msvcrt_mock:
        @staticmethod
        def kbhit(): return _kbhit()
        @staticmethod
        def getch(): return _getch()
    
    msvcrt = _msvcrt_mock()

from datetime import datetime

# System and Third-party imports

# Force UTF-8 for stdout/stderr to handle emojis in logs on Windows
if sys.platform == "win32":
    try:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass

# --- Logging Helper ---
class Logger:
    def __init__(self, log_path):
        self.terminal = sys.stdout
        self.log_file = open(log_path, "a", encoding="utf-8", errors="replace")
        
    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
        self.terminal.flush()
        self.log_file.flush()
        
    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        if self.log_file:
            self.log_file.close()
            self.log_file = None  # type: ignore

# --- Configuration ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULTS_FILE = os.path.join(CURRENT_DIR, "defaults.json")
SETTINGS_FILE = os.path.join(CURRENT_DIR, "settings.json")
DEFAULTS = {}
if os.path.exists(DEFAULTS_FILE):
    try:
        with open(DEFAULTS_FILE, "r", encoding="utf-8") as f:
            DEFAULTS.update(json.load(f))
    except: pass
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            DEFAULTS = json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load settings.json: {e}")

VENDOR_MAP = {
    "Google (Vertex AI)": "vertex",
    "Google (Gemini API)": "gemini",
    "OpenAI": "openai",
    "Anthropic": "anthropic",
    "DeepSeek": "deepseek",
    "Alibaba (Bailian)": "dashscope",
    "DashScope (Alibaba Cloud)": "dashscope",
    "Zhipu AI": "zhipu",
    "Moonshot (Kimi)": "moonshot",
    "SiliconFlow": "siliconflow",
    "MiniMax": "minimax"
}

import multiprocessing
multiprocessing.freeze_support()

# --- Environment Setup (Isolation Logic) ---
if getattr(sys, 'frozen', False):
    # Packaged / Installer Mode
    BUNDLE_DIR = getattr(sys, '_MEIPASS', '')
    TOOLS_DIR = os.path.join(BUNDLE_DIR, "Library", "Tools")
    USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "AutoSub")
    PROJECT_ROOT = USER_DATA_DIR
    BASE_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Projects")
    env_path = os.path.join(PROJECT_ROOT, ".env")
    
    # In bundled mode, common is in BUNDLE_DIR/Library/Tools/common
    sys.path.append(os.path.join(TOOLS_DIR, "common"))
else:
    # Developer Mode (d:\cc)
    CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    TOOLS_DIR = os.path.dirname(CURRENT_SCRIPT_DIR)
    
    # Anchor to true repository root d:\cc
    tmp_root = os.path.dirname(TOOLS_DIR)
    if os.path.basename(tmp_root).lower() == "library":
        PROJECT_ROOT = os.path.dirname(tmp_root)
    else:
        PROJECT_ROOT = tmp_root
        
    BASE_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Projects")
    env_path = os.path.join(PROJECT_ROOT, ".env")
    
    # In dev mode, common is in d:\cc\Library\Tools\common
    sys.path.append(os.path.join(TOOLS_DIR, "common"))
    print(f"🏠 [DEV MODE] Root: {PROJECT_ROOT}")

# Load srt_utils after path setup
try:
    import srt_utils
except ImportError:
    srt_utils = None

def get_python_exe():
    """Returns python.exe even if running under pythonw.exe to ensure console output stability."""
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("pythonw.exe"):
        py_exe = exe.lower().replace("pythonw.exe", "python.exe")
        if os.path.exists(py_exe): return py_exe
        
    # Prefer virtual environment python if it exists
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    venv_py = os.path.join(curr_dir, ".venv", "bin", "python" if sys.platform != "win32" else "python.exe")
    if os.path.exists(venv_py):
        return venv_py
        
    return exe

def trigger_sync(local_dir, remote_id, headless=False):
    """Launches a single-run Google Drive sync."""
    sync_script = os.path.join(PROJECT_ROOT, ".agents", "skills", "google-drive-sync", "scripts", "sync.py")
    creds_path = os.path.join(PROJECT_ROOT, ".agents", "skills", "google-drive-sync", "credentials.json")
    token_path = os.path.join(PROJECT_ROOT, ".agents", "skills", "google-drive-sync", "token.json")
    
    # Use console-stable python executable
    py_exe = get_python_exe()
    
    if headless:
        print(f"☁️  [Cloud Sync] Starting integrated GDrive sync (HEADLESS) for: {os.path.basename(local_dir)}")
        sync_cmd = [py_exe, sync_script, "--local-dir", local_dir, "--remote-id", remote_id, "--credentials", creds_path, "--token", token_path, "--wrap-folder", "--headless"]
        try:
            process = subprocess.Popen(sync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=CREATE_NO_WINDOW)
            for line in process.stdout or []:
                msg = line.strip()
                if "Progress:" in msg:
                    sys.stdout.write(f"\r   {msg}    ")
                    sys.stdout.flush()
                else:
                    print(f"   [Sync] {msg}", flush=True)
            process.wait()
            print(f"\n✅ [Cloud Sync] Completed for {os.path.basename(local_dir)}")
        except Exception as e:
            print(f"⚠️  [Cloud Sync] Integrated sync failed: {e}")
    else:
        if sys.platform == "win32":
            final_cmd = (
                f"& '{py_exe}' '{sync_script}' --local-dir '{local_dir}' --remote-id '{remote_id}' "
                f"--credentials '{creds_path}' --token '{token_path}' --wrap-folder; "
                f"Write-Host '--- ✅ Sync task completed. Window will close in 5s ---' -ForegroundColor Green; "
                f"Start-Sleep 5"
            )
            ps_cmd = f"Start-Process powershell -ArgumentList '-NoExit', '-Command', \"{final_cmd}\""
            print(f"☁️  [Cloud Sync] Launching GDrive sync in a new window for: {os.path.basename(local_dir)}")
            try:
                subprocess.Popen(["powershell", "-Command", ps_cmd], creationflags=CREATE_NO_WINDOW)
            except Exception as e:
                print(f"⚠️  [Cloud Sync] Failed to launch sync window: {e}")
        elif sys.platform == "darwin":
            print(f"☁️  [Cloud Sync] Launching GDrive sync in a new Terminal window for: {os.path.basename(local_dir)}")
            mac_cmd = (
                f"'{py_exe}' '{sync_script}' --local-dir '{local_dir}' --remote-id '{remote_id}' "
                f"--credentials '{creds_path}' --token '{token_path}' --wrap-folder; "
                f"echo '--- ✅ Sync task completed. Window will close in 5s ---'; "
                f"sleep 5; exit"
            )
            osascript_cmd = f'tell application "Terminal" to do script "{mac_cmd}"'
            try:
                subprocess.Popen(["osascript", "-e", osascript_cmd])
            except Exception as e:
                print(f"⚠️  [Cloud Sync] Failed to launch sync terminal: {e}")
        else:
            print(f"☁️  [Cloud Sync] Running sync in background (not supported in new window on this platform)")
            trigger_sync(local_dir, remote_id, headless=True)

# --- Bilibili Upload (canonical implementation; batch engine + GUI reuse this) ---
BILI_SCRIPT = "/Users/shanfu/.gemini/config/skills/bilibili-uploader/scripts/bili_upload.py"
BILI_PYTHON = "/Users/shanfu/.gemini/config/skills/bilibili-uploader/.venv/bin/python"
BILI_VIDEO_EXTS = ('.mp4', '.mkv', '.webm', '.mov', '.ts')

def find_hardsub_video(workdir):
    """Return the most recently modified *_hardsub* video in workdir, or None."""
    try:
        files = os.listdir(workdir)
    except Exception:
        return None
    candidates = [f for f in files if "_hardsub" in f and f.endswith(BILI_VIDEO_EXTS)]
    if not candidates:
        return None
    return os.path.join(workdir, max(candidates, key=lambda fn: os.path.getmtime(os.path.join(workdir, fn))))

def build_bili_title(hardsub_path):
    """Derive a Bilibili title from a hardsub filename, capped at 80 chars."""
    title = os.path.basename(hardsub_path).replace("_hardsub", "")
    title = os.path.splitext(title)[0]
    title = re.sub(r' \[[a-zA-Z0-9_-]+\](\s*\[1080p\])?$', '', title).strip()
    if len(title) > 80:
        cut = title.rfind(' ', 0, 77)
        if cut == -1:
            cut = 77
        title = title[:cut].rstrip().rstrip('.') + "..."
    return title

def build_bili_cmd(workdir, title=None, tid=None, category_name=None, tags=None, season=None, desc=None, public=False):
    """Build the Bilibili upload command for the hardsub video in workdir.
    Metadata (tid/tags/desc/season) is auto-generated per-video by bili_upload.py's
    built-in LLM logic unless explicitly overridden. Returns the cmd list or None."""
    if not os.path.exists(BILI_SCRIPT) or not os.path.exists(BILI_PYTHON):
        return None
    hardsub_path = find_hardsub_video(workdir)
    if not hardsub_path:
        return None
    if title is None:
        title = build_bili_title(hardsub_path)
    cmd = [BILI_PYTHON, BILI_SCRIPT, hardsub_path, title]
    if tid:
        cmd.extend(["--tid", str(tid)])
    if category_name:
        cmd.extend(["--category_name", str(category_name)])
    if tags:
        cmd.extend(["--tags", str(tags)])
    if season:
        cmd.extend(["--season_name", str(season)])
    if desc:
        cmd.extend(["--desc", str(desc)])
    if public:
        cmd.append("--public")
    return cmd

def run_bili_cmd(cmd, on_progress=None, on_log=None, abort_flag=None):
    """Run a pre-built Bilibili upload command. Returns True on success.
    on_progress(pct)/on_log(line)/abort_flag() are optional callbacks; final
    success/failure status is NOT logged here (callers decide how to report)."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        if on_log:
            on_log(f"❌ Failed to start Bilibili upload: {e}")
        return False
    if p.stdout:
        for line in p.stdout:
            if abort_flag and abort_flag():
                p.kill()
                break
            stripped = line.strip()
            if stripped and on_log:
                on_log(stripped)
            m = re.search(r'Progress:\s*([\d.]+)%', line)
            if m and on_progress:
                on_progress(float(m.group(1)))
    p.wait()
    return p.returncode == 0

def trigger_bili_upload(workdir, title=None, tid=None, category_name=None, tags=None, season=None, desc=None, public=False, on_progress=None, on_log=None, abort_flag=None):
    """Build and run a Bilibili upload for the hardsub video in workdir.
    Convenience wrapper: build_bili_cmd + run_bili_cmd. Returns True on success."""
    cmd = build_bili_cmd(workdir, title=title, tid=tid, category_name=category_name, tags=tags, season=season, desc=desc, public=public)
    if not cmd:
        print("⚠️  [Bilibili] upload skipped (script/venv/hardsub not found)", flush=True)
        return False
    _log = on_log or (lambda msg: print(msg, flush=True))
    _log(f"📺 Starting Bilibili upload: {os.path.basename(cmd[2])}")
    ok = run_bili_cmd(cmd, on_progress=on_progress, on_log=_log, abort_flag=abort_flag)
    _log(f"📺 {'✅ Success' if ok else '❌ Failed'}")
    return ok

# --- Robust FFmpeg/ffprobe Detection ---
def find_tool(tool_name):
    """Finds a tool in PATH or common installation directories."""
    import shutil
    # 0. Check bundled internal path (if frozen)
    if getattr(sys, 'frozen', False):
        bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        exe_ext = ".exe" if sys.platform == "win32" else ""
        internal_tool = os.path.join(bundle_dir, tool_name + exe_ext)
        if os.path.exists(internal_tool): return internal_tool
        # Also check root of exe
        root_tool = os.path.join(os.path.dirname(sys.executable), tool_name + exe_ext)
        if os.path.exists(root_tool): return root_tool

    # 1. Check PATH
    path = shutil.which(tool_name)
    if path: return path
    
    # 2. Check WinGet Gyan FFmpeg (User Specific)
    user_home = os.path.expanduser("~")
    winget_base = os.path.join(user_home, "AppData", "Local", "Microsoft", "Winget", "Packages")
    if os.path.exists(winget_base):
        # Search for Gyan FFmpeg
        for d in os.listdir(winget_base):
            if "Gyan.FFmpeg" in d:
                # Glob search for the bin folder
                for bin_dir in glob.glob(os.path.join(winget_base, d, "**/bin"), recursive=True):
                    exe_ext = ".exe" if sys.platform == "win32" else ""
                    tool_path = os.path.join(bin_dir, tool_name + exe_ext)
                    if os.path.exists(tool_path): return tool_path

    # 3. Check common hardcoded paths
    fallbacks = [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
    ]
    
    # Proactively check for CapCut installation to steal its FFmpeg
    # Better: check for "CapCut.exe" path and then look for ffmpeg nearby
    for drive in ["C:", "D:"]:
        capcut_root = os.path.join(drive, "Program Files", "CapCut")
        if os.path.exists(capcut_root):
            # Find latest version folder
            try:
                versions = [d for d in os.listdir(capcut_root) if os.path.isdir(os.path.join(capcut_root, d)) and "." in d]
                if versions:
                    latest = sorted(versions, key=lambda x: [int(v) for v in x.split('.') if v.isdigit()], reverse=True)[0]
                    fallbacks.append(os.path.join(capcut_root, latest))
            except: pass

    for fb in fallbacks:
        exe_ext = ".exe" if sys.platform == "win32" else ""
        tool_path = os.path.join(fb, tool_name + exe_ext)
        if os.path.exists(tool_path): return tool_path
        
    return tool_name # Fallback to original name and hope for the best

FFMPEG_EXE = find_tool("ffmpeg")
FFPROBE_EXE = find_tool("ffprobe")

if FFMPEG_EXE != "ffmpeg":
    print(f"📦 Found FFmpeg at: {FFMPEG_EXE}")
    # Add to path for sub-scripts
    os.environ["PATH"] += os.pathsep + os.path.dirname(FFMPEG_EXE)

VDOWN_CMD = [sys.executable, os.path.join(TOOLS_DIR, "vdown", "download.py")]
TRANSCRIBER_CMD = [sys.executable, os.path.join(TOOLS_DIR, "transcriber", "transcribe_engine.py")]
SMART_TRANSLATE_CMD = [sys.executable, os.path.join(TOOLS_DIR, "autosub", "smart_translate.py")]
SUBTRANSLATOR_CMD = [sys.executable, os.path.join(TOOLS_DIR, "subtranslator", "subtranslator.py")]
SRT2ASS_CMD = [sys.executable, os.path.join(TOOLS_DIR, "hardsubber", "srt_to_ass.py")]
BURNSUB_CMD = [sys.executable, os.path.join(TOOLS_DIR, "hardsubber", "burn_engine.py")]

if os.path.exists(env_path):
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f :
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.strip().split('=', 1)
                    if k and v: os.environ[k] = v.strip('"\'')
    except: pass

def get_workdir(input_val, base_output_dir):
    if input_val.startswith("http"):
        return os.path.join(base_output_dir, "temp_" + str(int(time.time())))
    else:
        abs_path = os.path.abspath(input_val)
        try:
            base = os.path.normpath(base_output_dir).lower()
            current = os.path.normpath(abs_path).lower()
            if current.startswith(base): return os.path.dirname(abs_path)
        except: pass
        return os.path.join(base_output_dir, os.path.splitext(os.path.basename(input_val))[0])

def get_video_title(url, cookies=None):
    """Fetches video title using download.py --get-title."""
    try:
        # Use --print title for less noisy output
        cmd = list(VDOWN_CMD) + [url, cookies or "", "", "--get-title"]
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='replace',
            creationflags=CREATE_NO_WINDOW,
            timeout=10
        )
        if result.returncode == 0:
            title = result.stdout.strip()
            # If multiple lines, take the last non-empty one
            lines = [l.strip() for l in title.splitlines() if l.strip()]
            if lines:
                title = lines[-1]
                if "Error" not in title: return title
    except: pass
    return None

def get_video_folder_name(url, cookies=None):
    """Fetches stable folder name using download.py --get-folder-name."""
    try:
        cmd = list(VDOWN_CMD) + [url, cookies or "", "", "--get-folder-name"]
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='replace',
            creationflags=CREATE_NO_WINDOW,
            timeout=10
        )
        if result.returncode == 0:
            folder_name = result.stdout.strip()
            # If multiple lines, take the last non-empty one
            lines = [l.strip() for l in folder_name.splitlines() if l.strip()]
            if lines:
                folder_name = lines[-1]
                if "Error" not in folder_name: return folder_name
    except: pass
    return None

def sanitize_filename(filename):
    """Cleans a string to be a safe filename."""
    clean = re.sub(r'[\\/*?:"<>|]', '_', filename)
    clean = clean.strip().strip('.') # Strip trailing spaces and dots
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:100] # Limit length

def rename_workdir_safely(old_workdir, new_workdir, current_video_path, logger_instance):
    """Safely closes the logger, renames the directory, updates paths, and reopens the logger."""
    import sys
    
    # 1. Close current logger to release file handles
    if logger_instance:
        try:
            # Restore stdout/stderr first
            sys.stdout = logger_instance.terminal
            sys.stderr = logger_instance.terminal
            logger_instance.close()
        except Exception as e:
            print(f"⚠️ Error closing logger for rename: {e}")
            
    # 2. Rename directory
    renamed = False
    try:
        if os.path.exists(old_workdir) and not os.path.exists(new_workdir):
            os.rename(old_workdir, new_workdir)
            renamed = True
            print(f"✅ Project folder renamed to: {os.path.basename(new_workdir)}")
    except Exception as e:
        print(f"⚠️ Failed to rename project folder: {e}")
        
    if renamed:
        resolved_workdir = new_workdir
        # Update video path
        video_filename = os.path.basename(current_video_path)
        resolved_video_path = os.path.join(new_workdir, video_filename)
    else:
        resolved_workdir = old_workdir
        resolved_video_path = current_video_path
        
    # 3. Re-initialize logger in the new/old path
    new_log_path = os.path.join(resolved_workdir, "workflow.log")
    try:
        new_logger = Logger(new_log_path)
        sys.stdout = new_logger
        sys.stderr = new_logger
    except Exception as e:
        print(f"⚠️ Failed to restart logger: {e}")
        new_logger = logger_instance # Fallback
        
    return resolved_workdir, resolved_video_path, new_logger

def download_video(url, workdir, cookies=None, quick=False, start_time=None, end_time=None, title=None):
    print(f"🎬 Downloading {url}...", flush=True)
    if not os.path.exists(workdir): os.makedirs(workdir)
    cmd = list(VDOWN_CMD) + [url, cookies or "", workdir]
    if title:
        cmd.extend(["--title", title])
    if quick:
        cmd.append("--write-subs")
    if start_time:
        cmd.extend(["--start", start_time])
    if end_time:
        cmd.extend(["--end", end_time])
    try: 
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=CREATE_NO_WINDOW)
        for line in process.stdout or []:
            msg = line.strip()
            if "Progress:" in msg or ("[download]" in msg and "%" in msg):
                sys.stdout.write(f"\r   {msg}    ")
                sys.stdout.flush()
            else:
                print(msg, flush=True)
        process.wait()
        
        # --- Robustness Check with Transparency ---
        video_files = [f for f in os.listdir(workdir) if f.endswith(('.mp4', '.mkv', '.webm', '.mov', '.ts')) and not f.endswith('.part')]
        if video_files:
            # Pick the largest one and check if it's substantial (>1MB)
            video_files.sort(key=lambda x: os.path.getsize(os.path.join(workdir, x)), reverse=True)
            candidate = os.path.join(workdir, video_files[0])
            if os.path.getsize(candidate) > 1024 * 1024:
                if process.returncode != 0:
                    print(f"⚠️  Download reported error ({process.returncode}), but a valid video file was found.")
                    print(f"   Proceeding with: {os.path.basename(candidate)}")
                return candidate

        if process.returncode != 0:
            print(f"❌ Download command failed with code {process.returncode}")
            return None
    except Exception as e:
        print(f"❌ Error during download: {e}")
        return None
    return None

def transcribe_video(video_path, workdir, model="large-v2", quick=False):
    print(f"🎙️ Transcribing {os.path.basename(video_path)}...", flush=True)
    cmd = list(TRANSCRIBER_CMD) + [video_path, "--model", model, "--output", workdir, "--no-gui"]
    if quick:
        cmd.append("--quick")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=CREATE_NO_WINDOW)
        for line in process.stdout or []:
            msg = line.strip()
            if "Progress:" in msg or ("[download]" in msg and "%" in msg):
                sys.stdout.write(f"\r   {msg}    ")
                sys.stdout.flush()
            else:
                print(msg, flush=True)
        process.wait()
        res = os.path.join(workdir, os.path.splitext(os.path.basename(video_path))[0] + ".srt")
        if os.path.exists(res):
            en_res = res.replace(".srt", ".en.srt")
            if not os.path.exists(en_res):
                shutil.copy2(res, en_res)
                print(f"✅ Created copy: {os.path.basename(en_res)}")
            return res
        return None
    except: return None

def merge_bilingual(src_srt, zh_srt, main_lang="cn", llm_model="gemini-3.1-pro-preview"):
    print(f"🔀 Smart-Merging into bilingual SRT...")
    bi_path = src_srt[:-7] + ".bi.srt" if src_srt.lower().endswith(".en.srt") else src_srt.replace(".srt", ".bi.srt")
    
    # Check if a healthy bi_path already exists
    if os.path.exists(bi_path) and os.path.getsize(bi_path) > 100:
        with open(bi_path, 'r', encoding='utf-8', errors='ignore') as f:
            if "[UNTRANSLATED]" not in f.read(): 
                print(f"✅ Reusing existing bilingual file: {os.path.basename(bi_path)}")
                return bi_path
            
    cmd = list(SUBTRANSLATOR_CMD) + ["merge", src_srt, "--translated-file", zh_srt]
    env = os.environ.copy(); env["GEMINI_MODEL"] = llm_model
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=env, creationflags=CREATE_NO_WINDOW)
        for line in process.stdout or []:
            msg = line.strip()
            if "Progress:" in msg:
                sys.stdout.write(f"\r   {msg}    ")
                sys.stdout.flush()
            else:
                print(f"   [Merge] {msg}", flush=True)
        sys.stdout.write("\n")
        process.wait()
        
        if process.returncode == 0 and os.path.exists(bi_path):
            return bi_path
        else:
            print(f"❌ Merge process failed with code {process.returncode}")
            return None
    except Exception as e:
        print(f"❌ Merge launch error: {e}")
        return None

def burn_subtitle(video_path, srt_path, layout, main_lang, cn_font, en_font, cn_size, en_size, cn_color, en_color, bg_box=True, quality="high"):
    print("🔥 Burning subtitles...", flush=True)
    base_srt, _ = os.path.splitext(srt_path)
    ass_path = base_srt + ".ass"
    
    # --- Get Video Dimensions for Styling ---
    width, height = get_video_dimensions(video_path)
    print(f"📐 Video Resolution: {width}x{height}")

    if not os.path.exists(ass_path):
        cmd = list(SRT2ASS_CMD) + [srt_path, ass_path, "--layout", layout, "--main-lang", main_lang, "--cn-font", cn_font, "--en-font", en_font, "--cn-size", cn_size, "--en-size", en_size, "--cn-color", cn_color, "--en-color", en_color]
        cmd += ["--width", str(width), "--height", str(height)]
        if not bg_box: cmd.append("--no-bg-box")
        subprocess.run(cmd, check=True, creationflags=CREATE_NO_WINDOW)
        
    video_base = os.path.splitext(os.path.basename(video_path))[0]
    video_ext = os.path.splitext(video_path)[1]
    out_video = os.path.join(os.path.dirname(srt_path), video_base + "_hardsub" + video_ext)
    
    # --- Critical: Prevent File Locking issues ---
    if os.path.exists(out_video):
        try:
            os.remove(out_video)
        except PermissionError:
            print(f"❌ Error: Output file is LOCKED: {os.path.basename(out_video)}")
            print(f"   Please close any video players or run: Stop-Process -Name ffmpeg -Force")
            return None
        except Exception as e:
            print(f"⚠️ Warning: Could not remove existing output: {e}")

    cmd = list(BURNSUB_CMD) + [video_path, ass_path, out_video, "--headless", "--quality", quality]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=CREATE_NO_WINDOW)
        last_logs = []
        for line in process.stdout or []:
            msg = line.strip()
            if msg:
                if "Progress:" in msg:
                    sys.stdout.write(f"\r   {msg}    ")
                    sys.stdout.flush()
                else:
                    print(f"   [Burn] {msg}", flush=True)
                last_logs.append(msg)
                if len(last_logs) > 50: last_logs.pop(0)
        sys.stdout.write("\n")
        
        process.wait()
        if process.returncode != 0:
            print(f"❌ Burn failed with exit code {process.returncode}")
            # If logs didn't print or were short, show them again
            if not last_logs: print("   No log output captured.")
            raise subprocess.CalledProcessError(process.returncode, cmd)
        else:
            try:
                marker_path = os.path.join(os.path.dirname(out_video), ".burn_complete")
                with open(marker_path, "w", encoding="utf-8") as f:
                    f.write("1")
            except:
                pass
            
    except Exception as e:
        if isinstance(e, subprocess.CalledProcessError): raise e
        print(f"❌ Launch Error: {e}")
        return None
    return out_video if os.path.exists(out_video) else None

def get_video_duration(path):
    try:
        cmd = [FFPROBE_EXE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
        return float(subprocess.check_output(cmd, creationflags=CREATE_NO_WINDOW).decode().strip())
    except: return 0

def get_video_dimensions(path):
    """Returns (width, height) using ffprobe."""
    try:
        cmd = [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path]
        out = subprocess.check_output(cmd, creationflags=CREATE_NO_WINDOW).decode().strip()
        if "x" in out:
            w, h = out.split("x")
            return int(w), int(h)
    except: pass
    return 1920, 1080

def validate_cookies_file(path):
    """Checks if a cookie file exists and has a valid Netscape format header."""
    if not path or not os.path.exists(path): return False, "文件不存在"
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
            if "# Netscape HTTP Cookie File" in first_line or "# HTTP Cookie File" in first_line:
                return True, "有效的 Netscape 格式"
            content = f.read(1024)
            if "\t" in content and content.count("\t") > 5:
                return True, "疑似有效的格式 (缺少文件头)"
            return False, "非标准 Cookie 格式"
    except Exception as e:
        return False, f"读取失败: {e}"

def confirm_cookies(args):
    """Auto-detects and confirms cookies with the user (CLI)."""
    if getattr(args, 'cookies', None) and args.cookies.lower() == "none":
        args.cookies = "none"
        return "none"
    search_paths = []
    if getattr(args, 'cookies', None): search_paths.append(args.cookies)
    
    # Priority defaults
    paths_to_check = [
        r"D:\download\cookies.txt",
        r"D:\Downloads\cookies.txt",
        r"D:\cc\cookies.txt",
        os.path.join(os.getcwd(), "cookies.txt"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
    ]
    
    for p in paths_to_check:
        if p not in search_paths:
            search_paths.append(p)

    found_path = None
    for p in search_paths:
        if os.path.exists(p):
            found_path = p
            break
    
    if not found_path:
        # Don't prompt for local files
        is_url = args.input.startswith("http") if hasattr(args, 'input') else False
        if is_url:
            print("\n[bold yellow]⚠️  警告: 未找到 Cookie 文件。[/bold yellow]")
            print("   如果处理 YouTube 视频，可能会遇到机器人检测错误。")
            time.sleep(1)
        return None

    is_valid, reason = validate_cookies_file(found_path)
    mtime = datetime.fromtimestamp(os.path.getmtime(found_path)).strftime('%Y-%m-%d %H:%M:%S')
    size_kb = os.path.getsize(found_path) / 1024

    print(f"\n🍪 [Cookies Check] 检测到相关文件:")
    print(f"   路径: {found_path}")
    print(f"   时间: {mtime} ({size_kb:.1f} KB)")
    print(f"   状态: {reason}")

    # No prompt if it's not a URL (local file processing doesn't need cookies)
    is_url = args.input.startswith("http") if hasattr(args, 'input') else False
    if not is_url:
        args.cookies = found_path
        return found_path

    print("\n   [Confirm] 按回车键直接确认 (5s)，按 'N' 取消任务，或输入新路径:")
    
    start_wait = time.time()
    user_input = ""
    while time.time() - start_wait < 5:
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'\r', b'\n'): break
            if ch.lower() == b'n':
                print("\n❌ 任务取消。")
                sys.exit(0)
            try:
                char = ch.decode('utf-8')
                if char == '\x08': user_input = user_input[:-1]
                else: user_input += char
                sys.stdout.write(f"\r   新路径: {user_input} ")
                sys.stdout.flush()
            except: pass
        time.sleep(0.01)
    
    if user_input.strip():
        new_path = user_input.strip().strip('"')
        if os.path.exists(new_path):
            args.cookies = new_path
            print(f"\n   -> 已切换: {new_path}")
        else:
            print(f"\n   -> 路径无效，默认使用: {found_path}")
            args.cookies = found_path
    else:
        args.cookies = found_path
        print("\n   -> 已确认继续。")
    
    return args.cookies

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", default="", help="Input video URL or local file")
    
    # Batch mode arguments
    parser.add_argument("--batch-urls", nargs="+", help="Multiple URLs or path to a .txt/.md file containing URLs")
    parser.add_argument("--batch-dir", help="Directory containing multiple video project folders to process automatically")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers max 10")
    parser.add_argument("--max-api-calls", type=int, default=20, help="Global concurrency limit for Translation APIs")

    parser.add_argument("--model", default=DEFAULTS.get("whisper_model", DEFAULTS.get("model", "large-v2")))
    parser.add_argument("--llm-model", default=DEFAULTS.get("llm_model", "gemini-3-flash-preview"), help="LLM Model")
    default_provider = VENDOR_MAP.get(DEFAULTS.get("llm_vendor", ""), None)
    parser.add_argument("--llm-provider", default=default_provider, help="Explicit LLM Provider (e.g., dashscope, vertex)")
    parser.add_argument("--style", default=DEFAULTS.get("style", "auto"))
    parser.add_argument("--trans-mode", default=DEFAULTS.get("trans_mode", "balanced"), choices=["paraphrase", "balanced"])
    parser.add_argument("--cookies")
    parser.add_argument("--layout", default=DEFAULTS.get("layout", "bilingual"))
    parser.add_argument("--main-lang", default=DEFAULTS.get("main_lang", "cn"))
    parser.add_argument("--cn-font", default=DEFAULTS.get("cn_font", "KaiTi"))
    parser.add_argument("--en-font", default=DEFAULTS.get("en_font", "Arial"))
    parser.add_argument("--cn-size", default=DEFAULTS.get("cn_size", "60"))
    parser.add_argument("--en-size", default=DEFAULTS.get("en_size", "36"))
    parser.add_argument("--cn-color", default=DEFAULTS.get("cn_color", "Gold"))
    parser.add_argument("--en-color", default=DEFAULTS.get("en_color", "White"))
    parser.add_argument("--no-bg-box", action="store_true")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--output-dir", help="Project root directory for output files")
    parser.add_argument("--project-name", help="Dummy argument to prevent crashes")
    parser.add_argument("--sync-gdrive", help="Google Drive Folder ID to sync output files to")
    parser.add_argument("--bili-upload", action="store_true", help="Upload the hardsub video to Bilibili (auto-generates tid/tags/desc/season per video)")
    parser.add_argument("--quick", action="store_true", help="Experimental: Quick Transcribe (YouTube Subs + LLM)")
    parser.add_argument("--start", help="Start time (e.g. 00:01:30 or 90)")
    parser.add_argument("--end", help="End time (e.g. 00:03:00 or 180)")
    parser.add_argument("--quality", default="high", choices=["standard", "high", "lossless"], help="Burn quality (standard, high, lossless)")
    args = parser.parse_args()
    
    # --- Intelligent Time Parsing ---
    if args.start and "-" in args.start and not args.end:
        parts = args.start.split("-")
        args.start = parts[0].strip()
        args.end = parts[1].strip()
        print(f"✂️  Parsed time range: {args.start} to {args.end}")

    # Cookie verification step for CLI
    confirm_cookies(args)

    # Determine if we should run batch mode
    if args.batch_urls or args.batch_dir:
        import autosub_batch  # type: ignore
        return autosub_batch.run_batch(args)
        
    if not args.input:
        return parser.print_help()

    # --- Directory Logic ---
    final_output_dir = args.output_dir or DEFAULTS.get("output_dir") or BASE_OUTPUT_DIR
    if not os.path.isabs(final_output_dir):
        final_output_dir = os.path.abspath(os.path.join(PROJECT_ROOT, final_output_dir))
    
    # Update global-like state for this run
    effective_base_output_dir = final_output_dir

    # 0. Intelligent Project Naming
    if args.input.startswith("http"):
        # Local, instantaneous extraction of YouTube Video ID
        video_id = None
        if "youtube.com" in args.input or "youtu.be" in args.input:
            match = re.search(r'(?:v=|\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})', args.input)
            if match:
                video_id = match.group(1)
        
        # Check if a folder ending with [{video_id}] already exists locally
        existing_dir = None
        if video_id and os.path.exists(effective_base_output_dir):
            for item in os.listdir(effective_base_output_dir):
                item_path = os.path.join(effective_base_output_dir, item)
                if os.path.isdir(item_path) and item.endswith(f"[{video_id}]"):
                    existing_dir = item_path
                    break
        
        if existing_dir:
            workdir = existing_dir
            print(f"📁 Found existing Project Folder locally: {os.path.basename(workdir)}")
            title = get_video_title(args.input, args.cookies)
        else:
            print(f"🔍 Fetching video details (timeout in 10s)...", flush=True)
            folder_name = get_video_folder_name(args.input, args.cookies)
            title = get_video_title(args.input, args.cookies)
            if folder_name:
                workdir = os.path.join(effective_base_output_dir, folder_name)
                print(f"📁 Project Folder: {folder_name}")
            elif title:
                # Replicate stable restricted naming in Python fallback
                t_clean = title.replace(":", " - ").replace("|", " - ")
                t_clean = re.sub(r'\s+', '_', t_clean)
                t_clean = re.sub(r'[^a-zA-Z0-9_.-]', '', t_clean)
                t_clean = re.sub(r'_+', '_', t_clean).strip('_')
                
                if video_id:
                    folder_name_fallback = f"{t_clean} [{video_id}]"
                else:
                    folder_name_fallback = t_clean
                    
                workdir = os.path.join(effective_base_output_dir, folder_name_fallback)
                print(f"📁 Project Folder (fallback match): {folder_name_fallback}")
            else:
                workdir = get_workdir(args.input, effective_base_output_dir)
    else:
        workdir = get_workdir(args.input, effective_base_output_dir)

    if not os.path.exists(workdir): os.makedirs(workdir, exist_ok=True)
    
    # --- Initialize Workflow Logging ---
    log_path = os.path.join(workdir, "workflow.log")
    logger = Logger(log_path)
    sys.stdout = logger
    sys.stderr = logger

    print(f"--- 任务启动: {args.input} ---")
    print(f"🏠 [DEV MODE] Root: {PROJECT_ROOT}")
    print(f"📦 Found FFmpeg at: {FFMPEG_EXE}")

    if args.input.startswith("http"):
        # Always download full video first (more robust/fast than --download-sections for live streams)
        video_path = download_video(args.input, workdir, args.cookies, quick=args.quick, title=title)
        
        # Dynamic project folder renaming if title was not pre-fetched (temp fallback case)
        if video_path and os.path.exists(video_path) and not title:
            # Extract real video title from downloaded file
            actual_filename = os.path.basename(video_path)
            # Remove extension first
            name_without_ext = os.path.splitext(actual_filename)[0]
            # Keep the ID but strip only the last bracketed section (e.g. resolution "[1080p]")
            nice_title = re.sub(r'\s*\[[^\]]+\]\s*$', '', name_without_ext)
            nice_title = sanitize_filename(nice_title)
            
            if nice_title and not nice_title.startswith("temp_"):
                new_workdir = os.path.join(effective_base_output_dir, nice_title)
                # If target directory already exists, append a timestamp
                if os.path.exists(new_workdir) and new_workdir.lower() != workdir.lower():
                    new_workdir = new_workdir + "_" + str(int(time.time()))
                
                print(f"📁 Video downloaded. Dynamically upgrading project folder to: {os.path.basename(new_workdir)}", flush=True)
                workdir, video_path, logger = rename_workdir_safely(workdir, new_workdir, video_path, logger)
    else:
        # For local files, copy to project folder first
        src_path = os.path.abspath(args.input)
        dest_path = os.path.join(workdir, os.path.basename(src_path))
        if os.path.exists(src_path):
            if os.path.abspath(src_path).lower() != os.path.abspath(dest_path).lower():
                print(f"📂 Copying video to project folder...")
                shutil.copy2(src_path, dest_path)
            video_path = dest_path
        elif os.path.exists(dest_path):
            print(f"ℹ️ Original source missing, using video in project folder.")
            video_path = dest_path
        else:
            video_path = src_path

    # Post-acquisition / Clipping
    if (args.start or args.end) and video_path and os.path.exists(video_path):
        src_path = video_path
        ext = os.path.splitext(src_path)[1]
        s_clean = sanitize_filename(args.start or "0")
        e_clean = sanitize_filename(args.end or "end")
        clip_path = os.path.join(workdir, f"clip_{s_clean}_{e_clean}{ext}")
        
        # Skip if clip already exists
        if os.path.exists(clip_path) and os.path.getsize(clip_path) > 1024*1024:
            print(f"ℹ️  Clipped segment already exists, reusing: {os.path.basename(clip_path)}")
            video_path = clip_path
        else:
            print(f"✂️  Clipping segment: {args.start or '0'} -> {args.end or 'end'}")
            time.sleep(1) # Small delay to avoid file lock issues on Windows
            ss = ["-ss", args.start] if args.start else []
            to = ["-to", args.end] if args.end else []
            cmd = [FFMPEG_EXE, "-y"] + ss + ["-i", src_path] + to + ["-c", "copy", clip_path]
            try:
                subprocess.run(cmd, check=True, capture_output=True, creationflags=CREATE_NO_WINDOW)
                video_path = clip_path
                print(f"✅ Segment clipped: {os.path.basename(clip_path)}")
            except Exception as e:
                print(f"⚠️  Clipping failed: {e}. Using full file instead.")
            
    if not video_path or not os.path.exists(video_path): return print("❌ Invalid input")

    vid_dur = get_video_duration(video_path)
    base = os.path.splitext(os.path.basename(video_path))[0]
    expected_srt = os.path.join(workdir, base + ".srt")
    expected_en = os.path.join(workdir, base + ".en.srt")
    expected_cn = os.path.join(workdir, base + ".cn.srt")

    # 1. Transcription (Sequential)
    src_srt = None
    
    # Priority: 1. .srt (Transcribed) 2. .en.srt (Downloaded)
    possible_sources = [expected_srt, expected_en]
    
    for candidate in possible_sources:
        if os.path.exists(candidate) and os.path.getsize(candidate) > 500:
            if srt_utils:
                if vid_dur > 0:
                    try:
                        srt_dur = srt_utils.get_srt_duration(candidate)
                        if srt_dur > vid_dur * 0.9:
                            print(f"✅ Found existing SRT: {os.path.basename(candidate)} (Duration matches)")
                            src_srt = candidate
                            break
                        else:
                            print(f"⚠️ {os.path.basename(candidate)} duration mismatch ({srt_dur:.1f}s vs {vid_dur:.1f}s).")
                    except Exception as e:
                        print(f"⚠️ Error checking {os.path.basename(candidate)}: {e}")
                else:
                    print(f"✅ Found existing SRT: {os.path.basename(candidate)} (Video duration unknown, skipping transcription)")
                    src_srt = candidate
                    break
            else:
                # If srt_utils is missing, we still trust the file if it's > 500 bytes
                print(f"✅ Found existing SRT: {os.path.basename(candidate)} (srt_utils missing, assuming OK)")
                src_srt = candidate
                break
    
    if not src_srt:
        src_srt = transcribe_video(video_path, workdir, args.model, quick=args.quick)
    
    if not src_srt: return print("❌ Transcription failed")

    # --- Integrated Acoustic Spellcheck Middleware ---
    has_translation = False
    for candidate_cn in [expected_cn, os.path.join(workdir, base + ".zh.srt")]:
        if os.path.exists(candidate_cn) and os.path.getsize(candidate_cn) > 500:
            if srt_utils:
                try:
                    src_count = len(srt_utils.parse_srt(src_srt))
                    zh_count = len(srt_utils.parse_srt(candidate_cn))
                    if zh_count >= src_count * 0.95:
                        has_translation = True
                        break
                except:
                    pass
            else:
                has_translation = True
                break

    if has_translation:
        print("✅ Translation file already exists, skipping Acoustic Spellcheck Preprocessing.")
    else:
        try:
            py_exe = get_python_exe()
            spellcheck_script = os.path.join(CURRENT_DIR, "spellcheck_srt.py")
            print("🎙️ Running Acoustic Spellcheck Preprocessing...")
            # Spellcheck is a deterministic correction task, not deep reasoning.
            # Use a fast non-reasoning model (spellcheck_model) instead of the
            # heavy llm_model (e.g. glm-5.2 reasoning -> 143s/chunk -> 90s timeout).
            spellcheck_model = DEFAULTS.get("spellcheck_model") or args.llm_model
            cmd = [py_exe, spellcheck_script, src_srt, "--model", spellcheck_model]
            if getattr(args, "llm_provider", None):
                cmd.extend(["--provider", args.llm_provider])
            # Stream output line-by-line into Logger (and workflow.log).
            # subprocess.run(capture_output=False) inherits the underlying fd,
            # bypassing Logger.write() — spellcheck logs vanished from workflow.log.
            sp = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=CREATE_NO_WINDOW)
            for line in sp.stdout or []:
                print(line.rstrip(), flush=True)
            sp.wait()
            if sp.returncode != 0:
                print(f"⚠️ Acoustic Spellcheck exited with code {sp.returncode}")
        except Exception as e:
            print(f"⚠️ Acoustic Spellcheck failed/skipped: {e}")

    # 2. Translation (Sequential)
    zh_srt = None
    expected_zh = os.path.join(workdir, base + ".zh.srt")
    
    for candidate_cn in [expected_cn, expected_zh]:
        if os.path.exists(candidate_cn) and os.path.getsize(candidate_cn) > 500:
            if srt_utils:
                try:
                    src_count = len(srt_utils.parse_srt(src_srt))
                    zh_count = len(srt_utils.parse_srt(candidate_cn))
                    if zh_count >= src_count * 0.95:
                        print(f"✅ Found existing translation: {os.path.basename(candidate_cn)}")
                        zh_srt = candidate_cn
                        break
                except Exception as e:
                    print(f"⚠️ Error parsing {os.path.basename(candidate_cn)}: {e}")
            else:
                zh_srt = candidate_cn
                break

    if not zh_srt:
        print("🌍 Smart-translating...")
        try:
            py_exe = get_python_exe()
            cmd = [py_exe, SMART_TRANSLATE_CMD[1], src_srt, "--style", args.style, "--model", args.llm_model, "--trans-mode", getattr(args, "trans_mode", "balanced")]
            if getattr(args, "llm_provider", None):
                cmd.extend(["--provider", args.llm_provider])
            res = subprocess.run(cmd, check=True, creationflags=CREATE_NO_WINDOW, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.stdout:
                print(res.stdout.strip())
            if res.stderr:
                print(res.stderr.strip(), file=sys.stderr)
            if os.path.exists(expected_cn): zh_srt = expected_cn
            elif os.path.exists(expected_zh): zh_srt = expected_zh
        except Exception as e:
            print(f"⚠️ Translation step error: {e}")
    
    if not zh_srt: return print("❌ Translation failed")

    # 3. Merge & Burn
    final_srt = zh_srt
    if args.layout == "bilingual":
        print(f"🔀 Merging {os.path.basename(src_srt)} and {os.path.basename(zh_srt)}...")
        merged = merge_bilingual(src_srt, zh_srt, args.main_lang, args.llm_model)
        if merged and os.path.exists(merged):
            final_srt = merged
        else:
            # Check if there's an existing .bi.srt anyway (maybe created but returned None due to error code)
            bi_path = src_srt[:-7] + ".bi.srt" if src_srt.lower().endswith(".en.srt") else src_srt.replace(".srt", ".bi.srt")
            if os.path.exists(bi_path) and os.path.getsize(bi_path) > 500:
                print(f"✅ Using legacy/existing bilingual file: {os.path.basename(bi_path)}")
                final_srt = bi_path
            else:
                print(f"⚠️ Bilingual merge failed. Falling back to primary translation: {os.path.basename(zh_srt)}")
                final_srt = zh_srt
    
    print(f"📍 Final subtitle for burning: {os.path.basename(final_srt)}", flush=True)
    
    # Check if hardsub already exists
    video_base = os.path.splitext(os.path.basename(video_path))[0]
    video_ext = os.path.splitext(video_path)[1]
    out_video = os.path.join(workdir, video_base + "_hardsub" + video_ext)
    
    marker_file = os.path.join(workdir, ".burn_complete")
    if os.path.exists(out_video) and os.path.getsize(out_video) > 1024 * 1024 and os.path.exists(marker_file):
        print(f"✅ Found existing hardsub: {os.path.basename(out_video)} (Skipping burn stage)")
    else:
        burn_subtitle(video_path, final_srt, args.layout, args.main_lang, args.cn_font, args.en_font, args.cn_size, args.en_size, args.cn_color, args.en_color, not args.no_bg_box, args.quality)
    
    print("✅ All done!", flush=True)

    # --- Single Job Sync ---
    if getattr(args, 'sync_gdrive', None):
        trigger_sync(workdir, args.sync_gdrive, headless=args.headless)

    # --- Single Job Bilibili Upload ---
    if getattr(args, 'bili_upload', False):
        if trigger_bili_upload(workdir):
            try:
                with open(os.path.join(workdir, ".bili_uploaded"), "w") as f:
                    f.write("1")
            except Exception:
                pass

if __name__ == "__main__":
    main()

import os
import sys
import json
import subprocess
import re
import traceback
import time
import ctypes
import shutil
import tempfile
import contextlib
from typing import Any, Dict, Optional, Set, List, Union

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from rich import box

# Configuration
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(CURRENT_DIR)
# --- Robust Tool Discovery ---
def get_ytdlp_path():
    # 1. Check local tools folder
    local_ytdlp = os.path.join(TOOLS_DIR, "vdown", "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    if os.path.exists(local_ytdlp): return local_ytdlp
    # 2. Check current VENV bin
    venv_bin = os.path.join(CURRENT_DIR, ".venv", "bin")
    if sys.platform == "win32":
        venv_bin = os.path.join(CURRENT_DIR, ".venv", "Scripts")
    
    venv_ytdlp = os.path.join(venv_bin, "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    if os.path.exists(venv_ytdlp): return venv_ytdlp

    # 3. Check PATH
    path = shutil.which("yt-dlp")
    if path: return path
    return "yt-dlp"

YTDLP_EXE = get_ytdlp_path()

def discover_node():
    """Finds node for yt-dlp JS challenges."""
    path = shutil.which("node")
    if path: return path

    possible_paths = []
    if sys.platform == "win32":
        possible_paths = [
            os.path.join(TOOLS_DIR, "vdown", "node.exe"),
            r"C:\Program Files\nodejs\node.exe",
            r"D:\Program Files\nodejs\node.exe",
        ]
    elif sys.platform == "darwin":
        possible_paths = [
            "/opt/homebrew/bin/node",
            "/usr/local/bin/node",
            "/usr/bin/node",
        ]

    for p in possible_paths:
        if os.path.exists(p): return p
    return "node"

NODE_EXE = discover_node()

BATCH_SCRIPT = os.path.join(CURRENT_DIR, "autosub_batch_pro.py")
SINGLE_SCRIPT = os.path.join(CURRENT_DIR, "autosub.py")
DEFAULT_OUTPUT_ROOT = r"/Users/shanfu/cc/Projects"

def discover_initial_cookies():
    """Finds cookies.txt in prioritized locations for the launcher."""
    paths = [
        os.path.join(CURRENT_DIR, "cookies.txt"),
        r"/Users/shanfu/cc/cookies.txt",
        r"D:\download\cookies.txt",
        r"D:\Downloads\cookies.txt"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

INITIAL_COOKIES_PATH = discover_initial_cookies()

# CRITICAL: Use the exact same python executable that is running this launcher
PYTHON_EXE = sys.executable

console = Console()

# Set AppUserModelID for taskbar icon grouping
if sys.platform == "win32":
    windll = getattr(ctypes, 'windll', None)
    if windll:
        windll.shell32.SetCurrentProcessExplicitAppUserModelID("cc.autosub.batch.pro")

import re

def clean_title_text(title, playlist_title=None):
    if not title: return ""
    title = title.strip()
    for suffix in [" - YouTube", " | YouTube"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()

    if playlist_title and playlist_title.lower() != title.lower():
        escaped_pt = re.escape(playlist_title)
        marker = "<_MARK_>"
        temp_title = re.sub(f'(?i){escaped_pt}', marker, title)
        if temp_title != title:
            temp_title = re.sub(rf'\s*[-|:/]\s*{marker}\s*[-|:/]\s*', ' - ', temp_title)
            temp_title = re.sub(rf'^{marker}\s*[-|:/]\s*', '', temp_title)
            temp_title = re.sub(rf'\s*[-|:/]\s*{marker}$', '', temp_title)
            temp_title = temp_title.replace(marker, '').strip()
            if temp_title:
                title = temp_title

    return title

def check_all_completed(state_data: Any) -> bool:
    """Helper to check if all tasks in the existing state file are completed."""
    if not isinstance(state_data, dict) or not state_data:
        return False
    # Handle both launcher direct mapping and Pro tasks wrapper
    tasks_map = state_data.get("tasks", state_data) if "tasks" in state_data else state_data
    if isinstance(tasks_map, dict) and tasks_map:
        for task_id, task_d in tasks_map.items():
            if not isinstance(task_d, dict):
                return False
            status = task_d.get("status", "")
            pcts = task_d.get("pcts", {})
            is_done = (status == "完成") or (isinstance(pcts, dict) and pcts.get("BR", 0.0) >= 100.0)
            if not is_done:
                return False
        return True
    return False

import contextlib
import tempfile
import shutil

@contextlib.contextmanager
def use_temp_cookies(cookies_path):
    """Creates a temporary copy of cookies to prevent concurrent write corruption."""
    if not cookies_path or not os.path.exists(cookies_path):
        yield None
        return
    fd, temp_path = tempfile.mkstemp(suffix=".txt", prefix="yt_cookies_")
    os.close(fd)
    try:
        shutil.copy2(cookies_path, temp_path)
        yield temp_path
    finally:
        try:
            if os.path.exists(temp_path): os.remove(temp_path)
        except: pass

def fetch_metadata(url: str, cookies_path: Optional[str] = None, browser: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches playlist/video metadata using yt-dlp."""
    label = "匿名"
    if cookies_path: label = f"Cookies: {os.path.basename(cookies_path)}"
    if browser: label = f"浏览器: {browser}"

    with console.status(f"[bold blue]正在解析内容信息 ({label})..."):
        cmd = [
            YTDLP_EXE,
            "--flat-playlist",
            "--dump-single-json",
            "--quiet",
            "--no-warnings"
        ]

        # Enhanced challenge solving for YouTube
        if "youtube.com" in url or "youtu.be" in url:
            cmd.extend(["--extractor-args", "youtube:player-client=tv"])
            cmd.extend(["--remote-components", "ejs:github"])
            if NODE_EXE != "node":
                cmd.extend(["--js-runtime", f"node:{NODE_EXE}"])
            else:
                cmd.extend(["--js-runtime", "node"])

        def run_cmd(full_cmd):
            try:
                if sys.platform == "win32":
                    process = subprocess.Popen(
                        full_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                    )
                else:
                    process = subprocess.Popen(
                        full_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                stdout, stderr = process.communicate()

                if process.returncode != 0:
                    err_msg = stderr.decode('utf-8', errors='ignore')
                    return {"error": err_msg}

                out = stdout.decode('utf-8', errors='ignore')
                if not out.strip():
                    return None
                return json.loads(out)
            except Exception as e:
                return {"error": str(e)}

        if browser:
            cmd.extend(["--cookies-from-browser", browser])
            cmd.append(url)
            return run_cmd(cmd)
        elif cookies_path:
            with use_temp_cookies(cookies_path) as temp_cookies:
                if temp_cookies:
                    cmd.extend(["--cookies", temp_cookies])
                cmd.append(url)
                return run_cmd(cmd)
        else:
            cmd.append(url)
            return run_cmd(cmd)

def format_duration(seconds):
    try:
        if seconds is None: return "未知"
        s = int(float(seconds))
        if s <= 0: return "未知"
        hrs, rem = divmod(s, 3600)
        mins, secs = divmod(rem, 60)
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"
    except:
        return "未知"

def parse_indices(input_str, total_count):
    """
    Parses user input for indices.
    Supports:
    - Exclusion: "1,3,5" (default)
    - Inclusion: "+2,4,6" or "i2,4,6"
    - Ranges: "1-5", "+1-5"
    Returns a set of indices to KEEP.
    """
    input_str = input_str.strip()
    if not input_str:
        return set(range(1, total_count + 1))

    is_inclusion = input_str.startswith('+') or input_str.lower().startswith('i')

    # Robust cleanup: remove leading +, i, I and any spaces
    clean_str = re.sub(r'^[+iI\s]+', '', input_str)

    parts = [p.strip() for p in clean_str.split(',') if p.strip()]
    selected = set()

    for p in parts:
        if '-' in p:
            try:
                s_e = [x.strip() for x in p.split('-') if x.strip()]
                if len(s_e) == 2:
                    start, end = int(s_e[0]), int(s_e[1])
                    selected.update(range(start, end + 1))
            except: pass
        else:
            m = re.search(r'(\d+)', p)
            if m:
                selected.add(int(m.group(1)))

    if is_inclusion:
        return {i for i in selected if 1 <= i <= total_count}
    else:
        return {i for i in range(1, total_count + 1) if i not in selected}

def is_cookie_error(err_msg):
    keywords = [
        "sign in", "cookies", "reloaded", "not a bot", "authentication",
        "logged in", "n challenge solving failed", "format is not available"
    ]
    err_lower = err_msg.lower()
    return any(k in err_lower for k in keywords)

def launch_engine(cmd):
    # Command Construction for Windows
    cmd_parts = []
    for i, arg in enumerate(cmd):
        s_arg = arg
        if any(c in s_arg for c in " &()+,-|:"):
            quoted_arg = f"'{s_arg}'"
            if i == 0:
                cmd_parts.append(f"& {quoted_arg}")
            else:
                cmd_parts.append(quoted_arg)
        else:
            cmd_parts.append(s_arg)

    ps_inner_cmd = " ".join(cmd_parts)
    escaped_inner = ps_inner_cmd.replace('"', '\"')
    ps_command = f'chcp 65001; & {{ {escaped_inner} }}'

    try:
        # Final safety check: Clear PYTHONPATH to avoid version conflicts
        if "PYTHONPATH" in os.environ:
            del os.environ["PYTHONPATH"]
        os.environ["PYTHONUTF8"] = "1"

        if sys.platform == "win32":
            final_cmd = f'start "AutoSub Engine" powershell -NoExit -Command "{ps_command}"'
            subprocess.Popen(final_cmd, shell=True)
            console.print("\n[bold blue]✅ 任务已移交。[/]")
        elif sys.platform == "darwin":
            console.print("\n[bold blue]🚀 正在启动 AutoSub 压制引擎，请稍候...[/]\n")
            os.execv(cmd[0], cmd)
        else:
            subprocess.Popen(cmd)
            console.print("\n[bold blue]✅ 任务已在后台启动。[/]")
    except Exception as e:
        console.print(f"[bold red]启动失败: {e}[/]")
        input("\n按回车键退出...")

def is_project_running(project_path):
    lock_file = os.path.join(project_path, "batch_engine.lock")
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                pid = int(f.read().strip())
            import psutil
            if psutil.pid_exists(pid):
                try:
                    p = psutil.Process(pid)
                    cmdline = p.cmdline()
                    # Robust check: verify the process command line contains the script name
                    if any("autosub_batch_pro.py" in arg for arg in cmdline):
                        return True, pid
                except:
                    pass
        except:
            pass
    return False, None

def main():
    console.print("[bold cyan]========================================================[/]")
    console.print("[bold cyan]              AutoSub 交互式任务启动器[/]")
    console.print("[dim]        引导式配置 · 精准环境锁定 · 语法安全模式[/]")
    console.print("[bold cyan]========================================================[/]")

    # Check for existing projects with uncompleted tasks
    uncompleted_projects = []
    if os.path.exists(DEFAULT_OUTPUT_ROOT):
        for entry in os.listdir(DEFAULT_OUTPUT_ROOT):
            project_path = os.path.join(DEFAULT_OUTPUT_ROOT, entry)
            if os.path.isdir(project_path):
                state_path = os.path.join(project_path, "batch_state.json")
                if os.path.exists(state_path):
                    try:
                        with open(state_path, "r", encoding="utf-8") as f:
                            state_data = json.load(f)
                        if not check_all_completed(state_data):
                            uncompleted_projects.append((entry, project_path, state_data))
                    except Exception:
                        pass

    if uncompleted_projects:
        # Check active status of uncompleted projects
        running_projects_status = {}
        for name, proj_path, _ in uncompleted_projects:
            is_running, pid = is_project_running(proj_path)
            running_projects_status[name] = (is_running, pid)

        console.print("[bold yellow]⚠️ 检测到未完成的项目：[/]")
        for i, (name, proj_path, _) in enumerate(uncompleted_projects, 1):
            is_run, pid = running_projects_status[name]
            status_suffix = f" [bold green](运行中 🟢 PID {pid})[/]" if is_run else ""
            console.print(f"  [{i}] {name}{status_suffix}")
        
        # Default option: continue the most recently modified or the single one
        if len(uncompleted_projects) == 1:
            proj_name, proj_path, state_data = uncompleted_projects[0]
            is_run, pid = running_projects_status[proj_name]
            
            if is_run:
                console.print(f"\n✨ [bold green]检测到项目 [cyan]{proj_name}[/] 正在后台高速运行 (PID {pid})。[/]")
                console.print("📈 [bold cyan]将自动为您唤醒【只读 Live 看板监控模式】，查看实时进度...[/]")
                time.sleep(2.0)
                cmd = [
                    PYTHON_EXE,
                    BATCH_SCRIPT,
                    "--output", DEFAULT_OUTPUT_ROOT,
                    "--sub-dir-name", proj_name
                ]
                launch_engine(cmd)
                return
            
            if Confirm.ask(f"\n是否要继续未完成的项目 [bold cyan]{proj_name}[/]?", default=True):
                quality = "high"
                cookies_path = None
                browser = None
                do_sync = True
                
                if isinstance(state_data, dict):
                    # Robust state check: support both nested "tasks" structure and flat task list
                    tasks = state_data.get("tasks", state_data) if "tasks" in state_data else state_data
                    if tasks:
                        first_task = list(tasks.values())[0]
                        quality = first_task.get("quality", "high") if isinstance(first_task, dict) else "high"
                        cookies_path = state_data.get("cookies", first_task.get("cookies") if isinstance(first_task, dict) else None)
                        browser = state_data.get("browser", first_task.get("browser") if isinstance(first_task, dict) else None)
                        do_sync = state_data.get("gdsync", first_task.get("gdsync", True) if isinstance(first_task, dict) else True)
                
                cmd = [
                    PYTHON_EXE,
                    BATCH_SCRIPT,
                    "--output", DEFAULT_OUTPUT_ROOT,
                    "--sub-dir-name", proj_name,
                    "--quality", quality
                ]
                if cookies_path and os.path.exists(cookies_path):
                    cmd.extend(["--cookies", cookies_path])
                elif browser:
                    cmd.extend(["--cookies-from-browser", browser])
                if do_sync:
                    cmd.append("--gdsync")
                
                launch_engine(cmd)
                return
        else:
            choices = [str(i) for i in range(1, len(uncompleted_projects) + 1)] + ["n", "q"]
            console.print("  [n] 开始全新项目")
            console.print("  [q] 退出")
            choice = Prompt.ask("\n请选择您要继续的项目或输入操作", choices=choices, default="1")
            if choice == "q":
                return
            elif choice != "n":
                idx = int(choice) - 1
                proj_name, proj_path, state_data = uncompleted_projects[idx]
                is_run, pid = running_projects_status[proj_name]
                
                if is_run:
                    console.print(f"\n✨ [bold green]检测到项目 [cyan]{proj_name}[/] 正在后台运行 (PID {pid})。[/]")
                    console.print("📈 [bold cyan]将自动为您唤醒【只读 Live 看板监控模式】，查看实时进度...[/]")
                    time.sleep(2.0)
                    cmd = [
                        PYTHON_EXE,
                        BATCH_SCRIPT,
                        "--output", DEFAULT_OUTPUT_ROOT,
                        "--sub-dir-name", proj_name
                    ]
                    launch_engine(cmd)
                    return
                
                quality = "high"
                cookies_path = None
                browser = None
                do_sync = True
                
                if isinstance(state_data, dict):
                    # Robust state check: support both nested "tasks" structure and flat task list
                    tasks = state_data.get("tasks", state_data) if "tasks" in state_data else state_data
                    if tasks:
                        first_task = list(tasks.values())[0]
                        quality = first_task.get("quality", "high") if isinstance(first_task, dict) else "high"
                        cookies_path = state_data.get("cookies", first_task.get("cookies") if isinstance(first_task, dict) else None)
                        browser = state_data.get("browser", first_task.get("browser") if isinstance(first_task, dict) else None)
                        do_sync = state_data.get("gdsync", first_task.get("gdsync", True) if isinstance(first_task, dict) else True)
                
                cmd = [
                    PYTHON_EXE,
                    BATCH_SCRIPT,
                    "--output", DEFAULT_OUTPUT_ROOT,
                    "--sub-dir-name", proj_name,
                    "--quality", quality
                ]
                if cookies_path and os.path.exists(cookies_path):
                    cmd.extend(["--cookies", cookies_path])
                elif browser:
                    cmd.extend(["--cookies-from-browser", browser])
                if do_sync:
                    cmd.append("--gdsync")
                
                launch_engine(cmd)
                return

    # 1. URL Input
    url_input = ""
    while not url_input:
        url_input = Prompt.ask("\n[bold yellow]请输入播放列表/视频 URL 或 .txt 文件路径[/]").strip().strip('"')

    urls = []
    is_from_file = False
    if url_input.lower().endswith(".txt") and os.path.exists(url_input):
        is_from_file = True
        try:
            with open(url_input, "r", encoding="utf-8") as f:
                urls = []
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    # Extract the first URL found in the line
                    url_match = re.search(r'(https?://[^\s,]+)', line)
                    if url_match:
                        urls.append(url_match.group(1))
                    else:
                        # Fallback to whole line if no protocol found but looks like a URL
                        urls.append(line)
        except Exception as e:
            console.print(f"[bold red]❌ 无法读取文件: {e}[/]")
            return
        if not urls:
            console.print("[bold red]❌ 错误：[/]文件内容为空。")
            return
        console.print(f"📖 [cyan]已从文件加载 {len(urls)} 个 URL[/]")
    else:
        urls = [url_input]

    # Metadata Fetch Loop
    current_cookies = INITIAL_COOKIES_PATH if (INITIAL_COOKIES_PATH and os.path.exists(INITIAL_COOKIES_PATH)) else None
    current_browser = None
    all_entries: List[Dict[str, Any]] = []
    final_title = None
    data: Optional[Dict[str, Any]] = None

    for i, url in enumerate(urls):
        data = None
        while True:
            data = fetch_metadata(url, cookies_path=current_cookies, browser=current_browser)
            if data and "error" not in data: break

            err_detail = data.get("error", "未知错误") if data else "空返回"
            if is_cookie_error(err_detail):
                console.print(Panel(f"[bold red]❌ 权限验证失败 (URL #{i+1})[/]\n\n{err_detail.strip()}", title="身份验证", border_style="yellow"))
                console.print("  [bold]1.[/] 指定新的 [cyan]cookies.txt[/] 路径\n  [bold]2.[/] 尝试从 [cyan]Chrome[/] 读取 Cookies\n  [bold]3.[/] 忽略 Cookies，尝试匿名访问\n  [bold]q.[/] 退出程序")
                sub_choice = Prompt.ask("\n您的选择", choices=["1", "2", "3", "q"], default="1")
                if sub_choice == "1":
                    new_path = Prompt.ask("\n请输入 cookies.txt 的完整路径").strip().strip('"')
                    if os.path.exists(new_path): current_cookies, current_browser = new_path, None
                elif sub_choice == "2": current_browser, current_cookies = "chrome", None
                elif sub_choice == "3": current_cookies, current_browser = None, None
                else: return
            else:
                console.print(Panel(f"[bold red]❌ 抓取失败 (URL #{i+1})[/]\n\n{err_detail}", title="错误"))
                if is_from_file:
                    if Confirm.ask("跳过此 URL 继续?", default=True):
                        data = None
                        break
                    else: return
                else:
                    if not Confirm.ask("\n是否要更换 URL 重试?"): return
                    url = Prompt.ask("\n[bold yellow]请输入新的 URL[/]").strip()

        if not data: continue

        # Determine if this specific URL is a playlist
        is_p = 'entries' in data and data['entries'] is not None and len(data.get('entries', [])) > 0
        if is_p:
            all_entries.extend([e for e in data['entries'] if e])
            if not final_title: final_title = data.get('title')
        else:
            all_entries.append(data)
            if not final_title: final_title = data.get('title')

    if not all_entries:
        console.print("[bold red]❌ 错误：[/]未找到任何有效的视频信息。")
        input("\n按回车键退出..."); return

    # Construct virtual data object
    if is_from_file:
        data = {
            'title': final_title or os.path.splitext(os.path.basename(url_input))[0],
            'entries': all_entries
        }
    else:
        # For single URL input, ensure entries is populated for consistent downstream logic
        if not isinstance(data, dict):
            data = {}
        data['entries'] = all_entries

    # Normalize entries
    # Improved playlist detection: check for 'entries' key AND ensure it's not a single entry that is also a playlist
    is_playlist = 'entries' in data and data['entries'] is not None and len(data.get('entries', [])) > 0

    # Extra safety: if it's a playlist but it only has 1 entry and its ID matches the playlist ID, treat as single video
    if is_playlist and len(data['entries']) == 1:
        if data['entries'][0].get('id') == data.get('id'):
            is_playlist = False

    entries = [e for e in data.get('entries', []) if e] if is_playlist else [data]

    if not entries:
        console.print("[bold red]❌ 错误：[/]未找到有效的视频条目。")
        input("\n按回车键退出..."); return

    is_single_video = len(entries) == 1 and not is_from_file
    playlist_title = data.get('title') or data.get('playlist_title') or entries[0].get('title') or 'New_Project'
    clean_title = re.sub(r'[\\/*?:"<>|_]', ' ', playlist_title).strip()

    # 2. Show Summary Table
    table = Table(title=f"\n[bold cyan]内容预览:[/] {playlist_title}", box=box.SIMPLE_HEAD, expand=False)
    table.add_column("序号", style="bold cyan")
    table.add_column("时长", justify="right", style="green")
    table.add_column("视频名称")

    durations = []
    for i, entry in enumerate(entries, 1):
        d = entry.get('duration')
        durations.append((i, d if d is not None else 0))
        display_title = clean_title_text(entry.get('title', '未知视频'), playlist_title)
        table.add_row(str(i), format_duration(d), display_title)
    console.print(table)

    # 3. Suggestions & Folder
    exclude_input = ""
    if not is_single_video:
        exclude_suggestion = ""
        if len(durations) > 5:
            valid_durs = [d for d in durations if d[1] > 0]
            if valid_durs:
                shortest, longest = min(valid_durs, key=lambda x: x[1]), max(valid_durs, key=lambda x: x[1])
                exclude_suggestion = f"{shortest[0]},{longest[0]}"
                console.print(f"\n💡 [bold green]智能建议：[/]建议排除最短视频 [bold]#{shortest[0]}[/] 和最长视频 [bold]#{longest[0]}[/]")
        exclude_input = Prompt.ask("\n视频选择 (如 1,3,5 排除; [bold green]+2,4,6[/] 仅做; 1-5 范围)", default="")

    folder_name = Prompt.ask("\n项目保存文件夹名称", default=clean_title)
    do_sync = Confirm.ask("\n是否同步到 Google Drive?", default=True)
    quality = Prompt.ask("\n选择压制字幕画质 (standard: 标准质量, high: 高清原画, lossless: 无损超清)", choices=["standard", "high", "lossless"], default="high")

    # 4. Engine Assignment
    if is_single_video:
        target_script = SINGLE_SCRIPT
        cmd = [ PYTHON_EXE, target_script, url, "--output-dir", DEFAULT_OUTPUT_ROOT, "--project-name", folder_name, "--headless", "--quality", quality ]
        if current_cookies: cmd.extend(["--cookies", current_cookies])
        elif current_browser: cmd.extend(["--cookies-from-browser", current_browser])
    else:
        # Pre-seed the batch_state.json to avoid redundant yt-dlp fetch in batch_v4
        project_dir = os.path.join(DEFAULT_OUTPUT_ROOT, folder_name)
        os.makedirs(project_dir, exist_ok=True)
        state_path = os.path.join(project_dir, "batch_state.json")

        # CRITICAL FIX: Overwrite if the state file doesn't exist OR if a specific selection was provided
        # This ensures that "+2,4,6" actually updates the task list even if the project folder exists.
        should_write = True
        if os.path.exists(state_path):
            try:
                is_all_completed = False
                existing_data = None
                try:
                    with open(state_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                    is_all_completed = check_all_completed(existing_data)
                except Exception as e:
                    console.print(f"⚠️  解析现有任务进度时出错: {e}")

                if is_all_completed:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_path = f"{state_path}.bak_{timestamp}"
                    shutil.copy2(state_path, backup_path)
                    console.print(f"\n✨ [bold green]检测到该项目的先前任务已全部完成！[/bold green]")
                    console.print(f"📦 已自动将旧状态归档至: [cyan]{os.path.basename(backup_path)}[/cyan]")
                    console.print("🚀 开始创建全新进度的任务...")
                    should_write = True
                else:
                    console.print(f"\n[bold yellow]⚠️  检测到项目目录中已存在未完成的先前任务状态！[/bold yellow]")
                    resume = Confirm.ask("\n是否从上一次的断点恢复 (Resume) 任务进度？", default=True)
                    if resume:
                        if existing_data:
                            should_write = False
                            console.print("✨ [bold cyan]已选择从断点恢复上一次的任务进度。[/bold cyan]")
                        else:
                            console.print("⚠️  [bold yellow]现有任务状态文件为空或已损坏，无法从断点恢复！[/bold yellow]")
                            console.print("🚀 开始创建全新进度的任务...")
                    else:
                        import datetime
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        backup_path = f"{state_path}.bak_{timestamp}"
                        shutil.copy2(state_path, backup_path)
                        console.print(f"📦 [bold green]已将未完成的状态备份至: {os.path.basename(backup_path)}[/bold green]")
                        console.print("🚀 开始创建全新进度的任务...")
            except Exception as e:
                console.print(f"⚠️  处理状态文件时出错: {e}")

        if should_write:
            # Build the task map for batch_v4
            task_map = {}
            indices_to_keep = parse_indices(exclude_input, len(entries))

            for idx, entry in enumerate(entries, 1):
                original_title = entry.get('title', 'Unknown')
                title = clean_title_text(original_title, playlist_title)
                # Skip private or deleted videos
                if "[private video]" in title.lower() or "[deleted video]" in title.lower():
                    console.print(f"  [dim]跳过第 {idx} 项: {title} (视频不可用)[/]")
                    continue

                if idx not in indices_to_keep:
                    console.print(f"  [dim]忽略第 {idx} 项: {title} (未选中)[/]")
                    continue

                vid_id = entry.get('id') or 'Unknown'
                safe_title = re.sub(r'[\\/*?:"<>|]', '_', title).strip()[:80]
                workdir = os.path.join(project_dir, f"[{idx:02d}] - {safe_title} [{vid_id}]")

                task_map[str(idx)] = {
                    "url": entry.get('webpage_url') or entry.get('url'),
                    "title": title, "vid_id": vid_id, "uid": idx, "workdir": workdir,
                    "duration": format_duration(entry.get('duration')),
                    "status": "等待中", "error": None, "is_paused": False,
                    "pcts": {"DL": 0.0, "TR": 0.0, "TL": 0.0, "MR": 0.0, "BR": 0.0, "GD": 0.0},
                    "queued_stages": ["DL"]
                }

            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(task_map, f, ensure_ascii=False, indent=2)

        target_script = BATCH_SCRIPT
        # If we seeded the state, we don't need to pass --urls to avoid re-expansion conflicts
        cmd = [ PYTHON_EXE, target_script, "--output", DEFAULT_OUTPUT_ROOT, "--sub-dir-name", folder_name, "--quality", quality ]
        if current_cookies: cmd.extend(["--cookies", current_cookies])
        elif current_browser: cmd.extend(["--cookies-from-browser", current_browser])
        sel = exclude_input.strip()
        if sel:
            if sel.startswith('+'):
                cmd.extend(["--include", sel[1:].strip()])
            elif sel.lower().startswith('i'):
                cmd.extend(["--include", sel[1:].strip()])
            else:
                cmd.extend(["--exclude", sel])
        if do_sync: cmd.append("--gdsync")

    console.print(f"\n[bold green]🚀 启动 {'单视频处理' if is_single_video else '批处理'} 引擎...[/]")
    launch_engine(cmd)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt: console.print("\n[yellow]已取消。[/]")
    except Exception as e:
        console.print(Panel(f"[bold red]程序运行发生错误：[/]\n{e}\n\n[dim]{traceback.format_exc()}[/]", title="崩溃保护"))
        input("\n按回车键退出...")
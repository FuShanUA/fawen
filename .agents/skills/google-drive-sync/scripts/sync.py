import os
import sys
import argparse
import datetime
import traceback
import json
import socket

# Forcing IPv4 to prevent hanging in broken IPv6 environments on macOS
orig_getaddrinfo = socket.getaddrinfo
def patched_getaddrinfo(*args, **kwargs):
    try:
        res = orig_getaddrinfo(*args, **kwargs)
        filtered = [r for r in res if r[0] == socket.AF_INET]
        return filtered if filtered else res
    except Exception:
        return orig_getaddrinfo(*args, **kwargs)
socket.getaddrinfo = patched_getaddrinfo
# Set default socket timeout to 30 seconds so network calls don't hang indefinitely
socket.setdefaulttimeout(30)
try:
    import msvcrt
except ImportError:
    class _msvcrt_mock:
        def kbhit(self): return False
        def getch(self): return b''
        def putch(self, char): pass
    msvcrt = _msvcrt_mock()
import time
import threading
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request, AuthorizedSession
from googleapiclient.discovery import build
import select
try:
    import termios
    import tty
except ImportError:
    termios = None
    tty = None
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn, TaskID, TaskProgressColumn
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout

class CustomTransferSpeedColumn(TransferSpeedColumn):
    def render(self, task):
        speed = task.finished_speed or task.speed
        if speed is None:
            return Text("", style="progress.data.speed")
        return super().render(task)

class CustomTimeRemainingColumn(TimeRemainingColumn):
    def render(self, task):
        if task.finished or task.speed is None:
            return Text("", style="progress.remaining")
        return super().render(task)

class CustomTaskProgressColumn(TaskProgressColumn):
    def render(self, task):
        if task.total is None or task.total == 0:
            return Text("", style="progress.percentage")
        return super().render(task)

SCOPES = ['https://www.googleapis.com/auth/drive.file']
console = Console()

# Global States
GLOBAL_PAUSE = False
EXIT_FLAG = False
STATE_FILE = ""
groups = {}
overall_stats = {"total": 0, "completed": 0}
state_lock = threading.RLock()
active_workers = {}
SCROLL_OFFSET = 0
MAX_TUI_LINES = 12

# ----------------- AUTH & API -----------------
def get_service_and_session(credentials_path, token_path):
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                console.print(f"[yellow]Refresh token failed ({e}), re-authenticating...[/yellow]")
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    service = build('drive', 'v3', credentials=creds)
    session = AuthorizedSession(creds)
    return service, session

def get_remote_contents(service, parent_id, console):
    query = f"'{parent_id}' in parents and trashed=false"
    items = []
    page_token = None
    retries = 0
    while True:
        try:
            results = service.files().list(
                q=query, spaces='drive',
                fields='nextPageToken,files(id,name,mimeType,size,modifiedTime)',
                pageToken=page_token, pageSize=1000
            ).execute()
            items.extend(results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token: break
        except Exception as e:
            if "500" in str(e) and retries < 3:
                retries += 1
                time.sleep(2 * retries)
                continue
            console.print(f"[red]Error fetching remote dir: {e}[/red]")
            break
    remote_files = {}
    remote_folders = {}
    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            remote_folders[item['name']] = item['id']
        else:
            remote_files[item['name']] = item
    return remote_files, remote_folders

def create_folder(service, folder_name, parent_id, console):
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    try:
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    except Exception as e:
        console.print(f"[red]Error creating folder '{folder_name}': {e}[/red]")
        return None

# ----------------- SCAN & PLAN -----------------
def build_plan(service, local_dir, parent_id, state, plan_items, console):
    global EXIT_FLAG
    if EXIT_FLAG: return
    remote_files, remote_folders = get_remote_contents(service, parent_id, console)

    for item in os.listdir(local_dir):
        if EXIT_FLAG: return
        item_path = os.path.join(local_dir, item)
        if os.path.isfile(item_path):
            local_size = os.path.getsize(item_path)
            local_mtime = os.path.getmtime(item_path)

            rem_file = remote_files.get(item)
            rem_size = int(rem_file.get('size', 0)) if rem_file else -1

            # Identical exact payload match highest priority
            if rem_size == local_size:
                if item_path in state:
                    del state[item_path]
                plan_items.append({
                    "action": "skip", "path": item_path, "name": item, "size": local_size
                })
                continue

            # Partial broken resume
            if item_path in state:
                plan_items.append({
                    "action": "resume", "path": item_path, "name": state[item_path]['name'],
                    "size": local_size, "mtime": local_mtime, "parent_id": parent_id, "uri": state[item_path]['uri']
                })
                continue

            if rem_file:
                # File differs -> append unique ID
                name, ext = os.path.splitext(item)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name_to_upload = f"{name}_v{timestamp}{ext}"
            else:
                file_name_to_upload = item

            if local_size == 0: continue
            plan_items.append({
                "action": "upload", "path": item_path, "name": file_name_to_upload,
                "size": local_size, "mtime": local_mtime, "parent_id": parent_id
            })

        elif os.path.isdir(item_path):
            folder_id = remote_folders.get(item)
            if not folder_id:
                folder_id = create_folder(service, item, parent_id, console)
            if folder_id:
                build_plan(service, item_path, folder_id, state, plan_items, console)

# ----------------- TRANSFER LOGIC -----------------
def save_state_locked(file_path, uri, file_name):
    global groups
    with state_lock:
        state = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception: pass
        if uri:
            state[file_path] = {'uri': uri, 'name': file_name}
        else:
            if file_path in state: del state[file_path]
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)

def remove_state_locked(file_path):
    save_state_locked(file_path, None, None)

def check_abort(group_key):
    if EXIT_FLAG: return True
    with state_lock:
        g_state = groups[group_key]['state']
        if GLOBAL_PAUSE or g_state == 'PAUSED':
            return True
    return False

def upload_worker(session, group_key, file_item, worker_progress):
    global GLOBAL_PAUSE, EXIT_FLAG, groups, active_workers, overall_stats
    tid = threading.get_ident()

    file_name = file_item['name']
    local_path = file_item['path']
    
    # Refresh file size to current state to handle active log files growing
    local_size = file_item['size']
    try:
        current_size = os.path.getsize(local_path)
        if current_size != local_size:
            local_size = current_size
            file_item['size'] = current_size
    except Exception:
        pass

    g_task_id = groups[group_key]['task']

    f_task = file_item['task']
    f_size_mb = local_size / (1024 * 1024)
    size_str = f"{f_size_mb:.1f} MB" if f_size_mb >= 0.1 else f"{local_size/1024:.1f} KB"
    worker_progress.update(f_task, visible=True, description=f"[bold blue]  ↳ {file_name} ({size_str})[/bold blue]", completed=0)

    with state_lock:
        active_workers[tid] = {"group_key": group_key, "file_name": file_name}

    success = False
    start_byte = 0
    resumable_uri = file_item.get('uri')

    # STEP 1: Initialization
    if not resumable_uri:
        metadata = {
            'name': file_item['name'],
            'parents': [file_item['parent_id']]
            # REMOVED modifiedTime metadata setting that was triggering Google Drive API HTTP 400 Bad Requests locally causing silent hangs!
        }
        init_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"

        init_retries = 0
        while not resumable_uri and not check_abort(group_key) and not EXIT_FLAG:
            worker_progress.update(f_task, description=f"[bold yellow]  ↳ {file_name} (Initializing API...)[/bold yellow]")
            try:
                res = session.post(init_url, json=metadata, headers={'X-Upload-Content-Length': str(local_size)}, timeout=20)
                if res.status_code == 200:
                    resumable_uri = res.headers.get('Location')
                    if resumable_uri:
                        file_item['uri'] = resumable_uri
                        save_state_locked(local_path, resumable_uri, file_item['name'])
                        break
                else:
                    file_item['error'] = f"Init {res.status_code}"
            except Exception as e:
                file_item['error'] = "Timed out"
                pass

            init_retries += 1
            if init_retries > 6:
                break
            worker_progress.update(f_task, description=f"[bold red]  ↳ {file_name} (Sync Retry {init_retries}...)[/bold red]")
            time.sleep(3)

    # STEP 2: Pre-check Google Servers Context Bytes
    if resumable_uri:
        retry_count = 0
        while not EXIT_FLAG and retry_count < 3:
            if check_abort(group_key): break
            headers = {"Content-Range": f"bytes */{local_size}"}
            try:
                res = session.put(resumable_uri, headers=headers, timeout=15)
                if res.status_code == 308:
                    range_header = res.headers.get("Range")
                    start_byte = int(range_header.split("-")[1]) + 1 if range_header else 0
                    if start_byte > 0:
                        added_already = file_item.get('session_added_bytes', 0)
                        to_add = start_byte - added_already
                        if to_add > 0:
                            with state_lock:
                                groups[group_key]['completed_bytes'] += to_add
                                overall_stats['completed'] += to_add
                                worker_progress.update(g_task_id, completed=groups[group_key]['completed_bytes'])
                            file_item['session_added_bytes'] = start_byte
                    worker_progress.update(f_task, completed=start_byte)
                    break
                elif res.status_code in (200, 201):
                    start_byte = local_size
                    added_already = file_item.get('session_added_bytes', 0)
                    to_add = start_byte - added_already
                    if to_add > 0:
                        with state_lock:
                            groups[group_key]['completed_bytes'] += to_add
                            overall_stats['completed'] += to_add
                            worker_progress.update(g_task_id, completed=groups[group_key]['completed_bytes'])
                        file_item['session_added_bytes'] = start_byte
                    worker_progress.update(f_task, completed=start_byte)
                    success = True
                    break
                else:
                    resumable_uri = None
                    if 'uri' in file_item:
                        del file_item['uri']
                    remove_state_locked(local_path)
                    break
            except Exception:
                retry_count += 1
                time.sleep(2)

    # STEP 3: Main Payload Transfer Loop
    if resumable_uri and not success and not check_abort(group_key):
        worker_progress.update(f_task, completed=start_byte, description=f"[bold cyan]  ↳ {file_name}[/bold cyan]")
        chunk_size = 1024 * 1024 * 3

        try:
            with open(local_path, 'rb') as f:
                f.seek(start_byte)
                while start_byte < local_size:
                    if check_abort(group_key): break

                    # Safely limit reading to target local_size to prevent issues with growing files
                    bytes_to_read = min(chunk_size, local_size - start_byte)
                    chunk = f.read(bytes_to_read)
                    if not chunk: break
                    end_byte = start_byte + len(chunk) - 1
                    headers = {"Content-Range": f"bytes {start_byte}-{end_byte}/{local_size}"}

                    success_recovery = False
                    while not success_recovery:
                        if check_abort(group_key): break
                        try:
                            res = session.put(resumable_uri, data=chunk, headers=headers, timeout=30)
                            if res.status_code in (200, 201, 308):
                                start_byte += len(chunk)
                                added_already = file_item.get('session_added_bytes', 0)
                                to_add = start_byte - added_already
                                if to_add > 0:
                                    with state_lock:
                                        groups[group_key]['completed_bytes'] += to_add
                                        overall_stats['completed'] += to_add
                                        worker_progress.update(g_task_id, completed=groups[group_key]['completed_bytes'])
                                    file_item['session_added_bytes'] = start_byte
                                worker_progress.update(f_task, completed=start_byte, description=f"[bold cyan]  ↳ {file_name} ({size_str})[/bold cyan]")
                                if res.status_code in (200, 201):
                                    success = True
                                success_recovery = True
                                break
                            else:
                                file_item['error'] = f"Chunk {res.status_code}"
                                success_recovery = True
                                break
                        except Exception:
                            worker_progress.update(f_task, description=f"[bold red]  ↳ {file_name} (Hanging... Re-syncing)[/bold red]")
                            time.sleep(3)

                            while not check_abort(group_key):
                                try:
                                    qr = session.put(resumable_uri, headers={"Content-Range": f"bytes */{local_size}"}, timeout=15)
                                    if qr.status_code == 308:
                                        r_head = qr.headers.get("Range")
                                        n_st = int(r_head.split("-")[1]) + 1 if r_head else 0
                                        diff = n_st - start_byte
                                        if diff > 0:
                                            added_already = file_item.get('session_added_bytes', 0)
                                            to_add = n_st - added_already
                                            if to_add > 0:
                                                with state_lock:
                                                    groups[group_key]['completed_bytes'] += to_add
                                                    overall_stats['completed'] += to_add
                                                    worker_progress.update(g_task_id, completed=groups[group_key]['completed_bytes'])
                                                file_item['session_added_bytes'] = n_st
                                        start_byte = n_st
                                        f.seek(start_byte)
                                        worker_progress.update(f_task, completed=start_byte, description=f"[bold cyan]  ↳ {file_name} ({size_str})[/bold cyan]")
                                        success_recovery = True
                                        break
                                    elif qr.status_code in (200, 201):
                                        diff = local_size - start_byte
                                        if diff > 0:
                                            added_already = file_item.get('session_added_bytes', 0)
                                            to_add = local_size - added_already
                                            if to_add > 0:
                                                with state_lock:
                                                    groups[group_key]['completed_bytes'] += to_add
                                                    overall_stats['completed'] += to_add
                                                    worker_progress.update(g_task_id, completed=groups[group_key]['completed_bytes'])
                                                file_item['session_added_bytes'] = local_size
                                        worker_progress.update(f_task, completed=local_size)
                                        success = True
                                        success_recovery = True
                                        break
                                    else:
                                        success_recovery = True
                                        break
                                except Exception:
                                    time.sleep(3)
                                    continue
                            if check_abort(group_key) or success:
                                break
                    if file_item.get('error'):
                        break

        except Exception as e:
            file_item['error'] = "Read Fail"

    # STEP 4: FLUSH WORKER STATUS
    with state_lock:
        if success:
            file_item['status'] = 'COMPLETED'
            remove_state_locked(local_path)
            if start_byte == local_size and groups[group_key]['completed_bytes'] < groups[group_key]['total_bytes']: pass
        else:
            if file_item.get('error'): file_item['status'] = 'FAILED'
            else: file_item['status'] = 'PENDING'

        if tid in active_workers:
            del active_workers[tid]

    if success:
        worker_progress.update(f_task, visible=True, completed=local_size, description=f"[bold green]  ✓ {file_name} (COMPLETED)[/bold green]")
    else:
        worker_progress.update(f_task, visible=False)
        if file_item.get('error'):
            worker_progress.console.print(f"[red]⚠️ [Folder {group_key}] {file_name} failed: {file_item['error']}[/red]")
        else:
            worker_progress.console.print(f"[yellow]⏸️ [Folder {group_key}] {file_name} suspended via toggle[/yellow]")


# ----------------- TUI LOGIC -----------------
def kb_monitor(worker_progress):
    global GLOBAL_PAUSE, EXIT_FLAG, groups, SCROLL_OFFSET
    
    # Setup for Unix-like systems
    old_settings = None
    if sys.platform != 'win32' and termios and tty:
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except Exception:
            pass

    def check_kbhit():
        if sys.platform == 'win32':
            if msvcrt and not hasattr(msvcrt, '_is_mock'):
                return msvcrt.kbhit()
            return False
        else:
            try:
                dr, _, _ = select.select([sys.stdin], [], [], 0)
                return dr != []
            except Exception:
                return False

    def read_char():
        if sys.platform == 'win32':
            if msvcrt and not hasattr(msvcrt, '_is_mock'):
                return msvcrt.getch()
            return b''
        else:
            try:
                return sys.stdin.read(1).encode('utf-8')
            except Exception:
                return b''

    try:
        while not EXIT_FLAG:
            if check_kbhit():
                ch = read_char()
                # Handle special keys (arrows on Windows usually start with \x00 or \xe0)
                if sys.platform == "win32" and ch in (b'\x00', b'\xe0'):
                    sc = msvcrt.getch() if msvcrt else b''
                    with state_lock:
                        if sc == b'H': SCROLL_OFFSET = max(0, SCROLL_OFFSET - 1)
                        elif sc == b'P': SCROLL_OFFSET += 1
                    continue
                
                # Handle Unix arrows (usually \x1b[A, \x1b[B)
                if sys.platform != "win32" and ch == b'\x1b':
                    # Basic escape sequence parsing for arrows
                    extra = sys.stdin.read(2)
                    if extra == '[A': # Up
                        with state_lock: SCROLL_OFFSET = max(0, SCROLL_OFFSET - 1)
                    elif extra == '[B': # Down
                        with state_lock: SCROLL_OFFSET += 1
                    continue

                # Handle normal characters
                try:
                    k_char = ch.decode("utf-8", errors="ignore").lower()
                except:
                    continue

                with state_lock:
                    if k_char == 'p':
                        GLOBAL_PAUSE = not GLOBAL_PAUSE
                    elif k_char == 'q' or ch == b'\x03':
                        EXIT_FLAG = True
                    elif k_char == 'w':
                        SCROLL_OFFSET = max(0, SCROLL_OFFSET - 1)
                    elif k_char == 's':
                        SCROLL_OFFSET += 1
                    elif k_char in [g['key'] for g in groups.values() if g['key']]:
                        # Find group by hotkey
                        target_k = [k for k, g in groups.items() if g['key'] == k_char][0]
                        gs = groups[target_k]['state']
                        if gs != 'COMPLETED':
                            groups[target_k]['state'] = 'PENDING' if gs == 'PAUSED' else 'PAUSED'
                            status_label = "RESUMED" if groups[target_k]['state'] == 'PENDING' else "PAUSED"
                            worker_progress.console.print(f"[cyan] >>> Group '{groups[target_k]['name']}' {status_label} <<<[/cyan]")
            time.sleep(0.1)
    finally:
        # Restore terminal settings
        if old_settings and termios:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
            except Exception:
                pass

def dispatcher(session, worker_progress):
    global EXIT_FLAG, active_workers
    while not EXIT_FLAG:
        with state_lock:
            all_done = True
            for g in groups.values():
                pending_count = sum(1 for f in g['files'] if f['status'] in ('PENDING', 'UPLOADING'))
                if pending_count == 0 and g['state'] != 'COMPLETED' and len(g['files']) > 0:
                    g['state'] = 'COMPLETED'
                    worker_progress.update(g['task'], description=f"[bold green][{g['key']}] 📁 {g['name']} (COMPLETED)[/bold green]")

                if g['state'] != 'COMPLETED':
                    all_done = False

            if all_done and len(groups) > 0:
                EXIT_FLAG = True
                break

            if not GLOBAL_PAUSE and len(active_workers) < 10:
                launched = False
                for k, g in groups.items():
                    if g['state'] in ('ACTIVE', 'PENDING'):
                        for f in g['files']:
                            if f['status'] == 'PENDING':
                                f['status'] = 'UPLOADING'
                                if g['state'] == 'PENDING':
                                    g['state'] = 'ACTIVE'
                                    worker_progress.update(g['task'], description=f"[bold cyan][{g['key']}] 📁 {g['name']}[/bold cyan]")
                                t = threading.Thread(target=upload_worker, args=(session, k, f, worker_progress))
                                t.daemon = True
                                t.start()
                                launched = True
                                break
                    if launched: break
        time.sleep(0.5)

# ----------------- MAIN -----------------
def main():
    global STATE_FILE, groups, overall_stats, EXIT_FLAG
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_creds = os.path.join(os.path.dirname(script_dir), "credentials.json")
    default_token = os.path.join(os.path.dirname(script_dir), "token.json")

    parser = argparse.ArgumentParser()
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--remote-id", required=True)
    parser.add_argument("--credentials", default=default_creds)
    parser.add_argument("--token", default=default_token)
    parser.add_argument("--wrap-folder", action="store_true", help="Create a subfolder with the name of the local directory inside the remote directory")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode with plain text progress output")
    args = parser.parse_args()

    STATE_FILE = os.path.join(os.path.dirname(args.local_dir), ".gdrive_sync_state.json")

    try:
        service, session = get_service_and_session(args.credentials, args.token)

        # --- Handle Wrap Folder Logic ---
        if args.wrap_folder:
            folder_name = os.path.basename(os.path.normpath(args.local_dir))
            console.print(f"[yellow]Wrapping contents in remote folder: {folder_name}[/yellow]")
            remote_files, remote_folders = get_remote_contents(service, args.remote_id, console)

            target_id = remote_folders.get(folder_name)
            if not target_id:
                console.print(f"[cyan]Creating remote folder '{folder_name}'...[/cyan]")
                target_id = create_folder(service, folder_name, args.remote_id, console)

            if target_id:
                args.remote_id = target_id
            else:
                console.print(f"[red]Failed to create or find remote folder '{folder_name}'. Proceeding with root remote-id.[/red]")

    except Exception as e:
        console.print(f"[bold red]Authentication or initialization failed[/bold red]: {e}")
        sys.exit(1)

    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception: pass

    plan_items = []
    console.print("[yellow]Phase 1: 差异对比中... (Diffing local and remote payloads...)[/yellow]")
    build_plan(service, args.local_dir, args.remote_id, state, plan_items, console)

    hotkeys = "123456789abcdefghijklmnopqrstuvwxyz"
    h_idx = 0

    for item in plan_items:
        rel_path = os.path.relpath(item['path'], args.local_dir)
        parts = rel_path.split(os.sep)
        top_name = parts[0] if len(parts) > 1 else "[Root Files / 根级文件]"

        if top_name not in [g['name'] for g in groups.values()]:
            # Internal key for map (unique), UI label is a number
            g_idx = len(groups) + 1
            # Hotkey for toggle: 1-9 then a-z. After 35, no hotkey toggle.
            key = hotkeys[len(groups) % len(hotkeys)] if len(groups) < len(hotkeys) else None
            groups[str(g_idx)] = {"key": key, "label": str(g_idx), "name": top_name, "files": [], "state": "PENDING", "total_bytes": 0, "completed_bytes": 0, "task": None}

        gk = [k for k,v in groups.items() if v['name'] == top_name][0]
        item['status'] = 'COMPLETED' if item['action'] == 'skip' else 'PENDING'
        groups[gk]["files"].append(item)
        groups[gk]["total_bytes"] += item['size']
        overall_stats['total'] += item['size']
        if item['action'] == 'skip':
            groups[gk]["completed_bytes"] += item['size']
            overall_stats['completed'] += item['size']

    if overall_stats['total'] == 0:
        console.print("\n[bold green]✅ 同步校验通过！所有文件已在远端存在。引擎终止。(Sync verified! All files identical. Terminating.)[/bold green]")
        if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
        time.sleep(3)
        return

    console.print("\n[bold cyan]=== 同步计划概览 (Synchronization Plan Overview) ===[/bold cyan]")

    for key, g in groups.items():
        console.print(f"[{key}] 📁 {g['name']} - {len(g['files'])} files ({g['total_bytes']/(1024*1024):.1f} MB)")

    # Pure Native Scrollable Context to Prevent Flickering Heights permanently
    overall_progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(bar_width=None, style="grey37", complete_style="bright_green", finished_style="bright_green"),
        CustomTaskProgressColumn(),
        CustomTransferSpeedColumn(),
        CustomTimeRemainingColumn(),
        expand=False
    )

    # ----------------- UI HEIGHT MANAGEMENT -----------------
    MAX_VISIBLE_GROUPS = 15
    completed_groups_hidden = 0
    visible_groups_count = 0

    # ----------------- UI HEIGHT MANAGEMENT -----------------
    MAX_VISIBLE_GROUPS = 15

    safe_o_total = overall_stats['total'] if overall_stats['total'] > 0 else 1
    safe_o_comp = overall_stats['completed'] if overall_stats['total'] > 0 else 1
    for key, g in groups.items():
        safe_g_total = g['total_bytes'] if g['total_bytes'] > 0 else 1
        safe_g_comp = g['completed_bytes'] if g['total_bytes'] > 0 else 1
        g['task'] = overall_progress.add_task(f"[grey50][{key}] 📁 {g['name']}[/grey50]", total=safe_g_total, completed=safe_g_comp)
        if g['completed_bytes'] == g['total_bytes'] and g['total_bytes'] > 0:
            g['state'] = 'COMPLETED'
            overall_progress.update(g['task'], description=f"[bold green][{key}] 📁 {g['name']} (COMPLETED)[/bold green]")
        for f in g['files']:
            f_size_mb = f['size'] / (1024 * 1024)
            size_str = f"{f_size_mb:.1f} MB" if f_size_mb >= 0.1 else f"{f['size']/1024:.1f} KB"
            # Ensure 0-byte skipped files don't result in percentage '?' NaN
            f_tot = f['size'] if f['size'] > 0 else 1
            if f['status'] == 'COMPLETED':
                f['task'] = overall_progress.add_task(f"[bold green]  ✓ {f['name']} (COMPLETED)[/bold green]", total=f_tot, completed=f_tot, visible=False)
            else:
                f['task'] = overall_progress.add_task(f"[dim]  ↳ {f['name']} ({size_str})[/dim]", total=f_tot, visible=False)

    controls_text = Panel("\n[bold]快捷键/Controls: P (Pause), Q (Quit), 1-9/a-z (Toggle Folder) | Arrows to Page[/bold]\n", title="Commands", border_style="cyan")

    class ScrollSafeGroup:
        def __rich__(self):
            global SCROLL_OFFSET
            with state_lock:
                all_keys = list(groups.keys())
                total_groups = len(all_keys)

                # Adaptive Max Rows (Header: 4, Footer: 5, Table Padding: 4)
                _, h = Console().size
                max_rows = max(5, h - 13)

                # Boundary check for offset
                if SCROLL_OFFSET > total_groups - max_rows:
                    SCROLL_OFFSET = max(0, total_groups - max_rows)

                for idx, k in enumerate(all_keys):
                    g = groups[k]
                    clean_name = g['name'][:60] + ("..." if len(g['name']) > 60 else "")
                    desc_col = "yellow" if g['state'] == 'PAUSED' else "cyan"

                    # Show Hotkey if available, else just the label
                    hotkey_str = f" ({g['key']})" if g['key'] else ""
                    prefix = f"[{g['label']}{hotkey_str}]"

                    if g['state'] == 'COMPLETED':
                        desc = f"[bold green]{prefix} 📁 {clean_name} (DONE)[/bold green]"
                    else:
                        is_current_uploading = any(f['status'] == 'UPLOADING' for f in g['files'])
                        state_label = " (UPLOADING)" if is_current_uploading else ""
                        desc = f"[{desc_col}]{prefix} 📁 {clean_name}{state_label}[/{desc_col}]"

                    overall_progress.update(g['task'], description=desc)

                    is_visible = (idx >= SCROLL_OFFSET and idx < SCROLL_OFFSET + max_rows)
                    overall_progress.update(g['task'], visible=is_visible)

                    # Update visibility for file tasks within this group
                    for f in g['files']:
                        if is_visible and f['status'] == 'UPLOADING':
                            overall_progress.update(f['task'], visible=True)
                        else:
                            overall_progress.update(f['task'], visible=False)

                # Build a simple sidebar as a scrollbar
                scrollbar = []
                for i in range(max_rows):
                    if i < total_groups:
                        # Map current scroll range to a highlighted block in the sidebar
                        if total_groups <= max_rows:
                             scrollbar.append("[bright_green]█[/bright_green]")
                        else:
                            # Simple block mapping
                            block_idx = int((SCROLL_OFFSET / (total_groups - max_rows)) * (max_rows - 1)) if total_groups > max_rows else 0
                            if i == block_idx:
                                scrollbar.append("[bright_green]█[/bright_green]")
                            else:
                                scrollbar.append("[grey62]│[/grey62]")

                sidebar = Text("\n".join(scrollbar))

                table = Table.grid(padding=(0, 1))
                table.add_column("progress", ratio=1)
                table.add_column("scrollbar", width=1)
                table.add_row(overall_progress, sidebar)

                if total_groups > max_rows:
                    indicator = Text(f" ↕ Scroll: {SCROLL_OFFSET+1}-{min(total_groups, SCROLL_OFFSET+max_rows)}/{total_groups} (Arrows or W/S to scroll)", style="bold bright_cyan underline if_hover")
                    return Group(table, indicator)

            return overall_progress

    # ----------------- LAYOUT ASSEMBLY -----------------
    layout = Layout()
    layout.split(
        Layout(name="header", size=4),
        Layout(name="body"),
        Layout(name="footer", size=5)
    )

    # Decouple Overall Progress for Header
    header_progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(bar_width=None, style="grey37", complete_style="bright_green", finished_style="bright_green"),
        CustomTaskProgressColumn(),
        CustomTransferSpeedColumn(),
        CustomTimeRemainingColumn(),
        expand=True
    )
    h_task = header_progress.add_task("[bold green]🏁 整体进度 (OVERALL PROGRESS)[/bold green]", total=overall_stats['total'], completed=overall_stats['completed'])

    # Move current overall progress logic to update h_task
    def sync_header():
        with state_lock:
            pause_label = " [bold yellow]>>> GLOBAL PAUSED <<<[/bold yellow]" if GLOBAL_PAUSE else ""
            header_progress.update(h_task, description=f"[bold green]🏁 整体进度 (OVERALL PROGRESS){pause_label}[/bold green]", completed=overall_stats['completed'], total=overall_stats['total'])

    layout["header"].update(Panel(header_progress, title="Status", border_style="green"))
    layout["body"].update(Panel(ScrollSafeGroup(), title="Sync Details (Folders)", border_style="blue"))
    layout["footer"].update(controls_text)

    if not args.headless:
        Console().print("[bold magenta] === Starting Engine Thread Multiplexing (Fixed Layout) === [/bold magenta]\n")
    else:
        print(f"🚀 Integrated Sync Started (HEADLESS). Files to process: {len(plan_items)}")

    t_kb = None
    if not args.headless:
        t_kb = threading.Thread(target=kb_monitor, args=(overall_progress,))
        t_kb.start()

    t_disp = threading.Thread(target=dispatcher, args=(session, overall_progress))
    t_disp.start()

    if not args.headless:
        with Live(layout, console=Console(), refresh_per_second=4, screen=True) as live:
            while not EXIT_FLAG:
                sync_header()
                time.sleep(0.25)
    else:
        last_reported_percent = -1
        while not EXIT_FLAG:
            sync_header()
            if overall_stats['total'] > 0:
                percent = (overall_stats['completed'] / overall_stats['total']) * 100
                # Report every 1% or significant change
                if int(percent) > last_reported_percent:
                    print(f"Progress: {percent:.1f}%", flush=True)
                    last_reported_percent = int(percent)
            time.sleep(1.0)

    # Wait for threads to clean up
    if t_kb: t_kb.join(timeout=2.0)
    t_disp.join(timeout=2.0)

    all_completed = all(g['state'] == 'COMPLETED' for g in groups.values())
    if all_completed:
        Console().print("\n[bold green]✅ 同步圆满完成！(Sync completed gracefully!)[/bold green]")
        if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
    else:
        Console().print("\n[bold yellow]⚠️ 同步被挂起/中止。可随时使用相同命令安全续传！(Sync Halted. Resume via identical command any time!)[/bold yellow]")

    time.sleep(1.5)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
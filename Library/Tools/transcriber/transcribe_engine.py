import sys
import os

# Add common Mac Homebrew paths to PATH to ensure ffmpeg is found by MLX Whisper and standard engines
for path in ["/opt/homebrew/bin", "/usr/local/bin"]:
    if os.path.exists(path) and path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")

import json
import time
import ctypes
import re
import subprocess
import argparse
import io
import traceback

try:
    from faster_whisper import WhisperModel # type: ignore
except ImportError:
    import site
    from importlib import reload
    reload(site)
    from faster_whisper import WhisperModel # type: ignore

# Try to import MLX support
try:
    from mlx_engine import transcribe_mlx, is_apple_silicon, HAS_MLX
except ImportError:
    HAS_MLX = False

# Force UTF-8 for stdout/stderr
if sys.platform == "win32":
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    try:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass

import multiprocessing
multiprocessing.freeze_support()

# Configuration
STD_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "faster-whisper")
DEFAULT_MODEL_SIZE = "large-v2"
# Anchor RESULT_ROOT to the repository structure
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Library/Tools/transcriber -> Library/Tools -> Library -> Root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_SCRIPT_DIR)))
RESULT_ROOT = os.path.join(PROJECT_ROOT, "Projects")
LOCAL_MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
DOCS_MODELS = os.path.join(os.path.expanduser("~"), "Documents", "AutoSub", "Models")

class SegmentChunk:
    def __init__(self, start, end, text, id):
        self.start = start
        self.end = end
        self.text = text
        self.id = id

from typing import Any

def get_v(obj: Any, key: str, default: Any = 0) -> Any:
    if hasattr(obj, key):
        res = getattr(obj, key, default)
        return res if (res is not None) else default
    if isinstance(obj, dict):
        res = obj.get(key, default)
        return res if (res is not None) else default
    return default

CHUNK_PROFILES = {
    'formal': {'max_chars': 80, 'max_duration': 8.0, 'gap_threshold': 2.5, 'min_context': 45, 'min_words': 5, 'min_yield_chars': 20},
    'spoken': {'max_chars': 80, 'max_duration': 8.0, 'gap_threshold': 1.5, 'min_context': 45, 'min_words': 5, 'min_yield_chars': 20},
}

def detect_content_type(segments_list):
    if not segments_list: return 'spoken'
    durations = [get_v(s, 'end') - get_v(s, 'start') for s in segments_list if get_v(s, 'end') > get_v(s, 'start')]
    gaps = []
    for i in range(1, len(segments_list)):
        g = get_v(segments_list[i], 'start') - get_v(segments_list[i-1], 'end')
        if g >= 0: gaps.append(g)
    avg_dur = sum(durations) / len(durations) if durations else 0
    avg_gap = sum(gaps) / len(gaps) if gaps else 0
    style = 'formal' if (avg_dur > 4.5 or avg_gap > 0.6) else 'spoken'
    # print(f"📊 Pacing: avg_seg={avg_dur:.1f}s, avg_gap={avg_gap:.2f}s → style='{style}'")
    return style

def chunk_segments(segments_list, content_type=None):
    if content_type is None: content_type = detect_content_type(segments_list)
    p = CHUNK_PROFILES[content_type]
    max_chars, max_duration, gap_threshold = p['max_chars'], p['max_duration'], p['gap_threshold']
    min_context, min_words, min_yield_chars = p['min_context'], p['min_words'], p['min_yield_chars']

    chunk_id = 1
    def word_streamer(segs):
        for seg in segs:
            words = get_v(seg, 'words', None)
            if words:
                for w in words: yield w
            else:
                # Segment has no word-level timestamps (e.g. from checkpoint resume).
                # Yield a synthetic word from the full segment text so it isn't silently dropped.
                text = get_v(seg, 'text', '')
                if text and text.strip():
                    yield {'word': text, 'start': get_v(seg, 'start'), 'end': get_v(seg, 'end')}

    all_words = list(word_streamer(segments_list))
    if not all_words:
        # Fallback to segments if no word-level timestamps are available
        for i, s in enumerate(segments_list):
            yield SegmentChunk(get_v(s, 'start'), get_v(s, 'end'), get_v(s, 'text', ""), i+1)
        return

    def smart_join(t1, t2):
        if not t1: return t2
        return t1 + ('' if t1.endswith(' ') or t2.startswith(' ') else ' ') + t2

    i = 0
    while i < len(all_words):
        current_chunk_words = [all_words[i]]
        current_start = get_v(all_words[i], 'start')
        current_text = get_v(all_words[i], 'word', "") or get_v(all_words[i], 'text', "")
        i += 1
        while i < len(all_words):
            word = all_words[i]
            word_text = get_v(word, 'word', "") or get_v(word, 'text', "")
            gap = get_v(word, 'start') - get_v(all_words[i-1], 'end')
            would_exceed_chars = len(current_text) + len(word_text.strip()) > max_chars
            would_exceed_duration = (get_v(word, 'end') - current_start) > max_duration
            is_large_gap = gap > gap_threshold
            is_sentence_end = word_text.strip()[-1] in '.?!。？！' if word_text.strip() else False

            if would_exceed_chars and not would_exceed_duration:
                found_near_end = False
                if is_sentence_end and len(current_text) + len(word_text.strip()) < max_chars * 1.4:
                    found_near_end = True
                if not found_near_end:
                    for j in range(1, 6):
                        if i + j < len(all_words):
                            w_peek_text = get_v(all_words[i+j], 'word', "") or get_v(all_words[i+j], 'text', "")
                            if w_peek_text.strip() and w_peek_text.strip()[-1] in '.?!。？！' and len(current_text) < max_chars * 1.4:
                                found_near_end = True; break
                if found_near_end: would_exceed_chars = False

            should_break = (would_exceed_chars or would_exceed_duration or (is_large_gap and len(current_chunk_words) >= min_words) or (is_sentence_end and len(current_text) > min_context))
            if should_break and len(current_text.strip()) >= min_yield_chars:
                if is_sentence_end and not (would_exceed_chars or would_exceed_duration):
                    current_chunk_words.append(word); current_text = smart_join(current_text, word_text); i += 1
                break
            current_chunk_words.append(word); current_text = smart_join(current_text, word_text); i += 1
        yield SegmentChunk(current_start, get_v(current_chunk_words[-1], 'end'), current_text.strip(), chunk_id)
        chunk_id += 1

def get_ffmpeg_path():
    import shutil
    path = shutil.which("ffmpeg")
    if path: return path
    for fb in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe", r"D:\Program Files\CapCut\7.7.0.3143\ffmpeg.exe"]:
        if os.path.exists(fb): return fb
    return "ffmpeg"

FFMPEG_EXE = get_ffmpeg_path()

def get_duration(file_path):
    cmd = [FFMPEG_EXE, "-i", file_path, "-hide_banner"]
    try:
        startupinfo = None
        if hasattr(subprocess, 'STARTUPINFO'):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, 'STARTF_USESHOWWINDOW', 0)
        
        kwargs = {}
        if startupinfo:
            kwargs['startupinfo'] = startupinfo
            
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', **kwargs)
        for line in result.stderr.split('\n'):
            if "Duration" in line:
                time_str = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = time_str.split(':')
                return float(h) * 3600 + float(m) * 60 + float(s)
    except: pass
    return 0

def show_notification(title, message):
    try: 
        if hasattr(ctypes, 'windll'):
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x1)
    except: pass

def get_project_folder(file_path):
    base = os.path.splitext(os.path.basename(file_path))[0]
    clean = re.sub(r'[^a-zA-Z0-9]', '_', base)
    folder_name = "_".join([p for p in clean.split('_') if p][:5]) or "Untitled_Project"
    return os.path.join(RESULT_ROOT, folder_name)

def serialize_segment(s):
    """Converts a faster-whisper segment into a serializable dict."""
    res = {
        'start': getattr(s, 'start', 0),
        'end': getattr(s, 'end', 0),
        'text': getattr(s, 'text', ""),
        'words': []
    }
    words = getattr(s, 'words', None)
    if words:
        for w in words:
            res['words'].append({'start': getattr(w, 'start', 0), 'end': getattr(w, 'end', 0), 'word': getattr(w, 'word', ""), 'probability': getattr(w, 'probability', 0)})
    return res

def save_checkpoint(path, segments):
    """Saves transcription state atomically using a temporary file."""
    temp_path = path + ".tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump({'segments': segments}, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception as e:
        print(f"⚠️ Failed to save checkpoint: {e}")

def main():
    print(f"🚀 Transcriber engine started (PID: {os.getpid()})")
    print(f"Progress: 0.1% (Initializing engine...)", flush=True)
    print(f"DEBUG: sys.argv = {sys.argv}")
    parser = argparse.ArgumentParser(description="Standalone Faster-Whisper Transcriber")
    parser.add_argument("file", help="Path to video/audio file")
    parser.add_argument("--device", default=None, help="Device (cuda/cpu)")
    parser.add_argument("--model", default=DEFAULT_MODEL_SIZE, help="Whisper model name/path")
    parser.add_argument("--output", default=None, help="Output directory for SRT")
    parser.add_argument("--no-gui", action="store_true", help="Run without UI progress")
    parser.add_argument("--quick", action="store_true", help="Experimental: Quick Transcribe (YouTube Subs + LLM)")
    args = parser.parse_args()

    file_path = os.path.abspath(args.file)
    output_dir = os.path.abspath(args.output) if args.output else get_project_folder(file_path)
    raw_model_name = args.model
    if raw_model_name.startswith("faster-whisper-"): raw_model_name = raw_model_name.replace("faster-whisper-", "", 1)

    os.makedirs(output_dir, exist_ok=True)
    lock_file = os.path.join(output_dir, ".transcribe.lock")
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                old_pid = int(f.read().strip())
            
            running = False
            if sys.platform == "win32":
                import psutil
                running = psutil.pid_exists(old_pid)
            else:
                try:
                    os.kill(old_pid, 0)
                    running = True
                except OSError:
                    running = False
                    
            if running:
                print(f"⚠️ Project folder locked by PID {old_pid}. Exiting.")
                sys.exit(0)
        except Exception as e:
            pass

    with open(lock_file, "w") as f: f.write(str(os.getpid()))

    try:
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}"); sys.exit(1)

        print(f"🎙️ File: {os.path.basename(file_path)}\n📂 Output: {output_dir}\n🧠 Model: {raw_model_name}")

        # --- Quick Mode (YouTube + LLM) ---
        if args.quick:
            print("⚡ Mode: Quick Transcribe (Experimental)")
            quick_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quick_transcribe.py")
            cmd = [sys.executable, quick_script, file_path, "--output", output_dir]
            # Try to pass cookies if we can find them
            cookies = r"D:\Downloads\cookies.txt"
            if os.path.exists(cookies):
                cmd.extend(["--cookies", cookies])

            try:
                creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if sys.platform == "win32" else 0
                subprocess.run(cmd, check=True, creationflags=creationflags)
                print("✅ Quick Transcribe finished.")
                if os.path.exists(lock_file): os.remove(lock_file)
                sys.exit(0)
            except Exception as e:
                print(f"❌ Quick Transcribe failed: {e}. Falling back to normal transcription.")

        total_duration = get_duration(file_path)

        # UI
        root, progress_var, lbl_time = None, None, None
        if not args.no_gui:
            try:
                import tkinter as tk
                from tkinter import ttk
                root = tk.Tk(); root.title("Transcribing...")
                root.geometry('400x150')
                tk.Label(root, text=f"Processing: {os.path.basename(file_path)}", wraplength=380).pack(pady=10)
                progress_var = tk.DoubleVar()
                ttk.Progressbar(root, variable=progress_var, maximum=100, length=350).pack(pady=10)
                lbl_time = tk.Label(root, text="Initializing..."); lbl_time.pack()
                root.update()
            except: root = None

        # Model Load
        if args.device:
            device = args.device
        else:
            if sys.platform == "win32":
                try:
                    device = "cuda" if ctypes.windll.kernel32.GetModuleHandleW("nvcuda.dll") else "cpu"
                except:
                    device = "cpu"
            else:
                # For Mac/Linux, stick to CPU for maximum compatibility unless specifically requested
                device = "cpu"
        search_paths = [LOCAL_MODELS, DOCS_MODELS, STD_CACHE]
        best_root = next((d for d in search_paths if d and os.path.exists(d)), None)
        print(f"Progress: 0.8% (Analyzing audio...)", flush=True)

        # Checkpoint
        checkpoint_path = os.path.join(output_dir, "transcribe_state.json")
        segments_list, clip_start = [], 0
        if os.path.exists(checkpoint_path):
            try:
                with open(checkpoint_path, 'r', encoding='utf-8') as f:
                    segments_list = json.load(f).get('segments', [])
                    if segments_list:
                        clip_start = segments_list[-1].get('end', 0)
                        if clip_start is None: clip_start = 0
                        print(f"⏩ Resuming from {clip_start:.2f}s")
                        # 立即向 TUI 汇报当前真实进展，避免用户误以为从头开始
                        if total_duration > 0:
                            p = round(min(99.9, (clip_start / total_duration) * 100), 1)
                            print(f"Progress: {p}% (Resuming from {clip_start:.0f}s...)", flush=True)
            except Exception as e:
                print(f"⚠️ State file corrupted or unreadable ({e}). Starting fresh.")
                segments_list, clip_start = [], 0

        kwargs: dict[str, Any] = {"beam_size": 5, "vad_filter": True, "word_timestamps": True}
        if clip_start > 0: kwargs["clip_timestamps"] = [float(clip_start), float(total_duration)]

        # --- High-level Skip: If already finished, don't even start the engine ---
        if total_duration > 0 and clip_start >= total_duration - 1.0:
            print(f"✅ Transcription already completed ({clip_start:.1f}s / {total_duration:.1f}s). Skipping to output.", flush=True)
            segments = []
        else:
            # --- Transcription Engine Selection ---
            skip_loop_progress = False
            if HAS_MLX and is_apple_silicon() and (device == "cpu" or device is None):
                # Apple Silicon + MLX installed
                try:
                    print(f"🚀 [MLX Mode] Igniting Apple Silicon GPU...", flush=True)
                    
                    import threading
                    
                    segments_collected = []
                    thread_error = []
                    def worker_func():
                        try:
                           # Detect if Chinese characters are in the file path to decide initial prompt language
                            has_chinese = any('\u4e00' <= char <= '\u9fff' for char in file_path)
                            prompt = "以下是视频的字幕转录：" if has_chinese else None
                            
                            # Iterate the generator fully to populate segments_collected
                            for s in transcribe_mlx(file_path, model_name=raw_model_name, 
                                                    initial_prompt=prompt,
                                                    clip_timestamps=kwargs.get("clip_timestamps"),
                                                    total_duration=total_duration,
                                                    checkpoint_path=checkpoint_path,
                                                    language=None):
                                segments_collected.append(s)
                        except Exception as e_thread:
                            thread_error.append(e_thread)
                    
                    t_mlx = threading.Thread(target=worker_func)
                    t_mlx.daemon = True
                    t_mlx.start()
                    
                    resumed_pct = 0.0
                    if total_duration > 0:
                        resumed_pct = (clip_start / total_duration) * 100.0
                        
                    last_pct = round(resumed_pct, 1)
                    if last_pct <= 0.0:
                        last_pct = 0.1
                    
                    print(f"Progress: {last_pct}% (GPU Processing - Initializing MLX...)", flush=True)
                    
                    while t_mlx.is_alive():
                        time.sleep(1.0)
                            
                    if thread_error:
                        raise thread_error[0]
                        
                    segments = segments_collected
                    info = None
                    skip_loop_progress = True
                except Exception as e:
                    print(f"⚠️  MLX load failed: {e}. Falling back to Standard engine.")
                    model = WhisperModel(raw_model_name, device=device, compute_type="auto", download_root=best_root)
                    segments, info = model.transcribe(file_path, **kwargs)
            else:
                # Standard Path
                print(f"Progress: 0.2% (Loading model {raw_model_name} on {device}...)", flush=True)
                model = WhisperModel(raw_model_name, device=device, compute_type="auto", download_root=best_root)
                print(f"Progress: 0.5% (Model loaded)", flush=True)
                segments, info = model.transcribe(file_path, **kwargs)
        detected_style = None

        for s in segments:
            segments_list.append(serialize_segment(s))
            # 提高存档频率，每 2 个片段存一次，增加抗风险能力
            if len(segments_list) % 2 == 0:
                save_checkpoint(checkpoint_path, segments_list)

            s_end = getattr(s, 'end', 0)
            if s_end is None: s_end = 0

            if not detected_style and (s_end > 60 or len(segments_list) > 20):
                detected_style = detect_content_type(segments_list)

            if total_duration and total_duration > 0:
                p = round((s_end / total_duration) * 100, 1)
                if root and progress_var:
                    try:
                        progress_var.set(p); root.update()
                    except: pass
                elif not skip_loop_progress:
                    print(f"Progress: {p}% ({s_end:.0f}/{total_duration:.0f}s)", flush=True)

        save_checkpoint(checkpoint_path, segments_list)
        if skip_loop_progress:
            print(f"Progress: 100.0% (GPU Transcription finished successfully)", flush=True)
        if not detected_style: detected_style = detect_content_type(segments_list)

        srt_path = os.path.join(output_dir, os.path.splitext(os.path.basename(file_path))[0] + ".srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(chunk_segments(segments_list, detected_style)):
                def fmt(t):
                    if t is None: t = 0
                    h, m, s, ms = int(t//3600), int((t%3600)//60), int(t%60), int((t%1)*1000)
                    return f"{h:02}:{m:02}:{s:02},{ms:03}"
                f.write(f"{i+1}\n{fmt(get_v(segment,'start'))} --> {fmt(get_v(segment,'end'))}\n{get_v(segment,'text','')}\n\n")

        print(f"✅ Saved: {srt_path}")
        if root: root.destroy()
        if os.path.exists(lock_file): os.remove(lock_file)

    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        if os.path.exists(lock_file):
            try: os.remove(lock_file)
            except: pass
        sys.exit(1)

if __name__ == "__main__":
    main()

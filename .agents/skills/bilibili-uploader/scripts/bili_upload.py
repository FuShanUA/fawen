import asyncio
import hashlib
import json
import os
import re
import sys
import time
import shutil
import subprocess
from bilibili_api import video_uploader, Credential, sync
from bilibili_api.video_uploader import VideoUploaderEvents, Lines
from bilibili_api.utils.network import Api, get_api, request_settings

request_settings.set_timeout(60)

# Patch _probe to guarantee a fallback line when all CDN probes fail.
# Without this, _probe() returns None if every CDN probe times out,
# and VideoUploader._preupload crashes with 'NoneType' is not subscriptable.
_orig_probe = video_uploader._probe


async def _safe_probe():
    result = await _orig_probe()
    if result is None:
        first_line = next(iter(video_uploader.LINES_INFO.values()))
        print("⚠️ B站线路探测全部失败，使用默认线路 fallback。", flush=True)
        return first_line
    return result


video_uploader._probe = _safe_probe

# Route GLM models through Bailian (Dashscope) instead of Zhipu
os.environ.setdefault("ACTIVE_LLM_VENDOR", "Alibaba (Bailian)")

_COMMON_DIR = "/Users/shanfu/cc/Library/Tools/common"
if os.path.isdir(_COMMON_DIR) and _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
try:
    from llm_utils import get_client as _get_llm_client, LLMProvider as _LLMProvider
    _LLM_AVAILABLE = True
except Exception:
    _LLM_AVAILABLE = False
try:
    from cover_utils import generate_platform_covers
    _COVER_UTILS_AVAILABLE = True
except Exception:
    _COVER_UTILS_AVAILABLE = False
try:
    from subtitle_title import SubtitleTitleError, build_subtitle_grounded_title
    _SUBTITLE_TITLE_AVAILABLE = True
except Exception:
    SubtitleTitleError = ValueError
    _SUBTITLE_TITLE_AVAILABLE = False

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COOKIES = os.path.join(SKILL_DIR, "assets", "cookies.json")
PRE_INFO_CACHE_PATH = os.path.join(SKILL_DIR, "assets", "pre_info_cache.json")
PRE_INFO_CACHE_TTL_SECONDS = 600


def _credential_fingerprint(cookies):
    """Identify a cache entry without persisting credential values."""
    material = "|".join(
        str(cookies.get(key, ""))
        for key in ("SESSDATA", "bili_jct", "buvid3", "buvid4")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _load_cached_pre_info(cookies, now=None):
    try:
        with open(PRE_INFO_CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("credential_fingerprint") != _credential_fingerprint(cookies):
        return None
    try:
        saved_at = float(payload.get("saved_at", 0))
    except (TypeError, ValueError):
        return None
    current_time = time.time() if now is None else now
    if current_time - saved_at > PRE_INFO_CACHE_TTL_SECONDS:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) and data else None


def _save_cached_pre_info(cookies, pre_info):
    if not isinstance(pre_info, dict):
        return
    payload = {
        "credential_fingerprint": _credential_fingerprint(cookies),
        "saved_at": time.time(),
        "data": pre_info,
    }
    os.makedirs(os.path.dirname(PRE_INFO_CACHE_PATH), exist_ok=True)
    temporary_path = PRE_INFO_CACHE_PATH + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary_path, PRE_INFO_CACHE_PATH)
    except OSError:
        try:
            os.remove(temporary_path)
        except OSError:
            pass


def _autosub_llm_default():
    try:
        p = "/Users/shanfu/cc/Library/Tools/autosub/settings.json"
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
            return s.get("llm_model", "glm-5.2"), s.get("llm_vendor", "dashscope").lower().replace(" (bailian)", "dashscope")
    except: pass
    return "glm-5.2", "dashscope"

def _srt_ts_to_sec(ts):
    """Convert '00:01:02,500' -> 62.5 seconds."""
    ts = ts.replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _parse_srt_blocks(path):
    """Parse SRT into [{'index': str, 'start': float, 'end': float, 'text': str}]."""
    blocks = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return blocks
    for chunk in re.split(r'\n\s*\n', content.strip()):
        lines = [l.strip() for l in chunk.split('\n') if l.strip()]
        if len(lines) < 2:
            continue
        idx = lines[0] if lines[0].isdigit() else str(len(blocks) + 1)
        time_line = None
        text_lines = []
        for l in lines[1:]:
            if '-->' in l:
                time_line = l
            else:
                text_lines.append(l)
        start = end = 0.0
        if time_line:
            m = re.match(r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})', time_line)
            if m:
                start = _srt_ts_to_sec(m.group(1))
                end = _srt_ts_to_sec(m.group(2))
        blocks.append({'index': idx, 'start': start, 'end': end, 'text': ' '.join(text_lines)})
    return blocks


def _load_ad_block_ids(base):
    """Read <base>.ad_segments.json (from smart_translate.detect_ad_segments)
    and return the set of ad block indices to exclude."""
    ids = set()
    ad_path = base + ".ad_segments.json"
    if not os.path.exists(ad_path):
        return ids
    try:
        with open(ad_path, "r", encoding="utf-8") as f:
            segs = json.load(f)
        for seg in segs:
            try:
                si, ei = int(seg.get("start_block")), int(seg.get("end_block"))
                for i in range(si, ei + 1):
                    ids.add(str(i))
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return ids


def _read_subtitle_text(video_path, max_chars=30000):
    """Read subtitle text for tag/description generation.

    Fixes vs. the old version:
    1. Excludes ad/sponsor blocks via <base>.ad_segments.json when present,
       so intro/midroll ads no longer leak into tags/description.
    2. Samples evenly across the WHOLE transcript instead of just the head,
       so the LLM sees representative content from start to end.
    3. For long videos (1hr+), sends up to 30K chars and 300 sampled blocks
       (up from 6K/40) so the LLM gets comprehensive coverage, not just a
       few hundred chars that bias tags toward the opening minutes.
    """
    base = os.path.splitext(video_path)[0]
    if base.endswith("_hardsub"):
        base = base[:-8]
    sub_path = None
    blocks = []
    for suffix in [".bi.srt", ".srt", ".cn.srt"]:
        p = base + suffix
        if os.path.exists(p):
            sub_path = p
            blocks = _parse_srt_blocks(p)
            break
    if not blocks:
        return None, None

    ad_ids = _load_ad_block_ids(base)
    content = [b for b in blocks if str(b['index']) not in ad_ids and b['text']]
    if not content:
        content = [b for b in blocks if b['text']] or blocks

    texts = [b['text'] for b in content]
    full = " ".join(texts)
    if len(full) <= max_chars:
        return full, sub_path
    # Even sampling across the whole transcript: take more blocks for longer
    # videos so the LLM sees representative content from start to end.
    sample_count = min(300, len(texts))
    step = max(1, len(texts) // sample_count)
    sampled = texts[::step]
    return (" ".join(sampled))[:max_chars], sub_path

def _generate_tags_via_llm(subtitle_text, title, source_label, llm_provider="dashscope", llm_model="glm-5.2"):
    if not _LLM_AVAILABLE: return None
    try:
        client = _get_llm_client()
        out = client.generate_content(
            f"""根据以下视频字幕内容，生成5-8个适合B站的标签。
每个标签2-6个字，用逗号分隔，包含核心主题、人物、技术概念。
不要使用泛标签，要具体。

视频标题：{title}
字幕内容（{source_label}）：
{subtitle_text}

只输出标签，逗号分隔。""",
            model_name=llm_model
        )
        if out:
            tags = [t.strip() for t in re.split(r'[,，、\n]', out.strip()) if t.strip()]
            if tags: return tags[:10]
    except Exception as e:
        print(f">>> LLM标签生成失败: {e}")
    return None

def build_description(video_path, title, description, llm_provider="dashscope", llm_model="glm-5.2"):
    if description: return description.strip()
    sub_text, sub_src = _read_subtitle_text(video_path)
    if sub_text and _LLM_AVAILABLE:
        try:
            client = _get_llm_client()
            out = client.generate_content(
                f"""根据以下视频字幕，写一段100-200字的视频简介。简洁有力，概括核心内容，不要AI味。

视频标题：{title}
字幕内容：
{sub_text}

只输出简介内容。""",
                model_name=llm_model
            )
            if out:
                print(f">>> 简介来源：根据字幕内容总结（{os.path.basename(sub_src)}）")
                return out.strip()
        except Exception as e:
            print(f">>> LLM简介生成失败: {e}")
    print(">>> 简介来源：使用标题作为简介")
    return title

def build_title(
    video_path,
    original_title,
    llm_provider="dashscope",
    llm_model="glm-5.2",
):
    """Generate a restrained Bilibili form title from subtitle content.

    The filename title is intentionally not used as LLM context or as a
    fallback. Every automatic title must either be validated against exact
    subtitle evidence or be an exact extractive subtitle clause.
    """
    if not _SUBTITLE_TITLE_AVAILABLE:
        raise SubtitleTitleError("subtitle_title module is unavailable")
    client = _get_llm_client() if _LLM_AVAILABLE else None
    grounded = build_subtitle_grounded_title(
        video_path,
        llm_client=client,
        model_name=llm_model,
        max_title_chars=48,
        min_title_chars=12,
        platform_hint="B站表单标题应平实、准确、克制，不要照搬封面标题。",
        title_style="plain",
    )
    print(f">>> 标题来源：{grounded.source}（{os.path.basename(grounded.subtitle_path)}）")
    print(f"    原标题: {original_title}")
    print(f"    新标题: {grounded.title}")
    for fragment in grounded.evidence:
        print(f"    字幕证据: {fragment}")
    return grounded.title


def build_cover_title(
    video_path,
    llm_provider="dashscope",
    llm_model="glm-5.2",
    attribution=None,
):
    """Generate the separate editorial headline rendered on Bilibili covers."""
    if not _SUBTITLE_TITLE_AVAILABLE:
        raise SubtitleTitleError("subtitle_title module is unavailable")
    client = _get_llm_client() if _LLM_AVAILABLE else None
    grounded = build_subtitle_grounded_title(
        video_path,
        llm_client=client,
        model_name=llm_model,
        max_title_chars=48,
        min_title_chars=12,
        platform_hint="B站封面标题可以更有信息量，但仍要专业、克制。",
        title_style="cover_headline",
        attribution=attribution,
    )
    print(f">>> 封面标题来源：{grounded.source}（{os.path.basename(grounded.subtitle_path)}）")
    print(f"    封面标题: {grounded.title}")
    for fragment in grounded.evidence:
        print(f"    字幕证据: {fragment}")
    return grounded.title


def _generate_bili_covers(video_path, title):
    """Generate Bilibili's 16:9 upload cover and 4:3 companion asset."""
    if not _COVER_UTILS_AVAILABLE:
        print(">>> ❌ 封面生成模块不可用，已停止上传")
        return None, None
    try:
        wide_path, four_by_three_path = generate_platform_covers(
            video_path,
            "bilibili",
            title,
        )
        return wide_path, four_by_three_path
    except Exception as e:
        print(f">>> ❌ 生成B站封面失败: {e}")
        return None, None

def find_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "ffmpeg"
    except:
        for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(p): return f'"{p}"'
    return None

def extract_best_cover(ffmpeg_exe, video_path, cover_path):
    import tempfile
    candidates = []
    try:
        dur_out = subprocess.check_output(f'{ffmpeg_exe} -i "{video_path}" 2>&1', shell=True, text=True, errors="ignore")
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+)', dur_out)
        if m:
            total = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
            timestamps = [max(1, total//4), max(1, total//3), max(1, total//2)]
        else: timestamps = [1, 5, 10]
    except: timestamps = [1, 5, 10]
    for ts in timestamps:
        tmp = tempfile.mktemp(suffix=".jpg")
        try:
            subprocess.run(f'{ffmpeg_exe} -ss {ts} -i "{video_path}" -vframes 1 -q:v 2 "{tmp}" -y',
                          shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 5000:
                try:
                    from PIL import Image
                    img = Image.open(tmp)
                    pixels = list(img.getdata())  # TODO: Pillow 14 migration to get_flattened_data
                    if pixels:
                        avg = sum(sum(p[:3]) for p in pixels) / (len(pixels) * 3)
                        candidates.append((avg, tmp))
                        continue
                except: pass
            os.remove(tmp)
        except: pass
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        brightness, best = candidates[0]
        for _, tmp in candidates[1:]:
            try: os.remove(tmp)
            except: pass
        shutil.copy2(best, cover_path)
        try: os.remove(best)
        except: pass
        print(f">>> 封面已选择 (亮度评分: {int(brightness)}/255)")
    else:
        subprocess.run(f'{ffmpeg_exe} -ss 1 -i "{video_path}" -vframes 1 -q:v 2 "{cover_path}" -y',
                      shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

TID_COMPUTER = 231
TID_FINANCE = 207
TID_SCIENCE = 122
TID_CAREER = 21

def get_smart_partition(pre_info, match_context, full_text, category_name=None):
    if category_name:
        typelist = pre_info.get("typelist", [])
        for cat in typelist:
            for child in cat.get("children", []):
                if category_name in child.get("name", ""):
                    return child["id"], f"{cat.get('name','')}-{child.get('name','')}"
        print(f">>> ⚠️ 无法在官方最新一级分区中找到 '{category_name}'，将根据您的输入由 AI 算法为您智能定位最接近的板块...")
    text = full_text.upper()
    if any(kw in text for kw in ["编程", "代码", "CODE", "PYTHON", "SOFTWARE", "工程", "AI", "LLM", "GPT", "STARTUP", "ELON", "MUSK", "PALANTIR", "AGENT"]):
        return TID_COMPUTER, "科技-计算机技术"
    if any(kw in text for kw in ["投资", "股票", "基金", "FINANCE", "金融"]):
        return TID_FINANCE, "知识-财经商业"
    if any(kw in text for kw in ["职业", "求职", "面试"]):
        return TID_CAREER, "知识-职业职场"
    return TID_COMPUTER, "科技-计算机技术"

async def get_target_season(pre_info, title, full_text, target_season_name=None, credential=None):
    """Find the best matching season (合集) for the video being uploaded.

    B站 migrated the season API: pre_info no longer returns a seasons list
    (the 'season' key is just a boolean flag now). The real list must be
    fetched from /x2/creative/web/seasons. Each item nests under 'season'
    with 'id' and 'title' (not 'name').
    """
    # 1. Try pre_info first (legacy path, in case B站 restores it)
    season_data = pre_info.get("seasons") or []
    if not season_data and isinstance(pre_info.get("season"), dict):
        season_data = pre_info["season"].get("seasons", [])
    seasons = season_data if season_data else []

    # 2. If pre_info has no seasons, fetch from the new API endpoint.
    #    B站 migrated to /x2/creative/web/seasons; the old bilibili_api
    #    Api class can't parse the response, so we use httpx directly.
    if not seasons and credential:
        try:
            import httpx
            _ck = json.load(open(DEFAULT_COOKIES))
            _cs = f"SESSDATA={_ck['SESSDATA']}; bili_jct={_ck['bili_jct']}; buvid3={_ck['buvid3']}"
            if _ck.get("buvid4"): _cs += f"; buvid4={_ck['buvid4']}"
            _ch = {"User-Agent": "Mozilla/5.0", "Referer": "https://member.bilibili.com/platform/upload/video/frame", "Cookie": _cs}
            async with httpx.AsyncClient(timeout=15) as _cx:
                _r = await _cx.get("https://member.bilibili.com/x2/creative/web/seasons",
                                    params={"pn": 1, "ps": 50}, headers=_ch)
                _j = _r.json()
            raw_seasons = _j.get("data", {}).get("seasons", [])
            seasons = []
            for item in raw_seasons:
                s = item.get("season", item) if isinstance(item, dict) else {}
                seasons.append({"id": s.get("id"), "name": s.get("title") or s.get("name", "")})
            if seasons:
                print(f">>> 获取到 {len(seasons)} 个合集: {', '.join(s['name'] for s in seasons if s.get('name'))}")
        except Exception as e:
            err_brief = str(e).split("<")[0].strip()[:150]
            print(f">>> 获取合集列表失败: {err_brief}")

    if not seasons:
        return None, None

    # 3. Always pick the best-scoring season among existing ones.
    content_text = (title + " " + full_text).upper()
    target_upper = (target_season_name or "").upper().strip()
    best_id, best_name, best_score = None, None, 0
    for s in seasons:
        sname = (s.get("name") or s.get("title") or "").upper().strip()
        if not sname:
            continue
        score = 0
        if target_upper:
            if sname == target_upper:
                score = 1000
            elif target_upper in sname or sname in target_upper:
                score = max(score, 100)
            target_tokens = set(re.split(r'[\s\-_/]+', target_upper))
            season_tokens = set(re.split(r'[\s\-_/]+', sname))
            overlap = len(target_tokens & season_tokens)
            score = max(score, overlap * 20)
        if sname in content_text:
            score = max(score, 30)
        # Keyword pairs: (season_kw, content_kw) — matches Chinese season
        # names against English content and vice versa.
        kw_pairs = [
            ("AI", "AI"), ("人工智能", "AI"), ("人工智能", "人工智能"),
            ("LLM", "LLM"), ("科技", "科技"), ("科技", "TECH"),
            ("自动化", "自动化"), ("自动化", "AUTOMATION"),
            ("STARTUP", "STARTUP"), ("ELON", "ELON"),
            ("PALANTIR", "PALANTIR"), ("KARP", "KARP"),
            ("数据治理", "数据治理"), ("数据治理", "DCMM"),
            ("本体", "本体"), ("活人感", "活人感"),
        ]
        for skw, ckw in kw_pairs:
            if skw.upper() in sname and ckw.upper() in content_text:
                score += 10
        if score > best_score:
            best_score, best_id, best_name = score, s.get("id"), s.get("name") or s.get("title")

    if best_score > 0:
        print(f">>> 合集匹配: '{best_name}' (score={best_score})")
        return best_id, best_name
    # Fallback: pick the first season
    s0 = seasons[0]
    name0 = s0.get("name") or s0.get("title")
    print(f">>> 无精确匹配，使用第一个合集作为兜底: {name0}")
    return s0.get("id"), name0


def _register_bili_uploader_events(uploader, last_progress):
    """Expose upload/submit transitions so the batch watchdog can see them."""

    @uploader.on(VideoUploaderEvents.AFTER_CHUNK.value)
    async def on_after_chunk(data):
        chunk_idx = data.get("chunk_number", 0)
        total = data.get("total_chunk_count", 0)
        if total > 0:
            progress = (chunk_idx / total) * 100
            if progress - last_progress[0] >= 1.0 or progress >= 100:
                print(f">>> 上传进度: {progress:.1f}%", flush=True)
                last_progress[0] = progress
                print(f"Progress: {progress:.1f}%", flush=True)

    @uploader.on(VideoUploaderEvents.PRE_PAGE_SUBMIT.value)
    async def on_pre_page_submit(data):
        print(">>> 分块传输完成，提交分P元数据...", flush=True)

    @uploader.on(VideoUploaderEvents.AFTER_PAGE_SUBMIT.value)
    async def on_after_page_submit(data):
        print(">>> 分P元数据已提交...", flush=True)

    @uploader.on(VideoUploaderEvents.AFTER_PAGE.value)
    async def on_after_page(data):
        print(">>> 分块上传完成，进入封面/发布提交...", flush=True)
        if last_progress[0] < 99.0:
            last_progress[0] = 99.0
            print("Progress: 99.0%", flush=True)

    @uploader.on(VideoUploaderEvents.PRE_COVER.value)
    async def on_pre_cover(data):
        print(">>> 正在上传B站封面...", flush=True)

    @uploader.on(VideoUploaderEvents.AFTER_COVER.value)
    async def on_after_cover(data):
        print(">>> B站封面上传完成...", flush=True)

    @uploader.on(VideoUploaderEvents.PRE_SUBMIT.value)
    async def on_pre_submit(data):
        print(">>> 正在提交B站发布请求...", flush=True)

    @uploader.on(VideoUploaderEvents.AFTER_SUBMIT.value)
    async def on_after_submit(data):
        print(">>> B站发布请求已返回，等待解析响应...", flush=True)


def _upload_total_timeout():
    """Total wall-clock limit for one Bilibili upload attempt."""
    try:
        return float(os.environ.get("BILI_UPLOAD_TIMEOUT_SECONDS", "7200"))
    except ValueError:
        return 7200.0


async def _start_uploader_with_heartbeat(uploader, timeout=None):
    """Run uploader.start() with heartbeats and a hard attempt timeout."""
    if timeout is None:
        timeout = _upload_total_timeout()
    task = asyncio.create_task(uploader.start())
    deadline = time.monotonic() + timeout
    waited = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        wait_timeout = min(60.0, remaining)
        done, _ = await asyncio.wait({task}, timeout=wait_timeout)
        if done:
            return task.result()
        waited += wait_timeout
        if waited >= 60:
            print(f">>> B站接口仍在等待响应（{waited // 60}分钟）...", flush=True)

    if task.done():
        return task.result()

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        raise TimeoutError(
            f"B站上传超过 {timeout:.0f} 秒未返回，已取消本次上传；底层任务退出时还报错: {e}"
        ) from e
    raise TimeoutError(
        f"B站上传超过 {timeout:.0f} 秒未返回，已取消本次上传。"
        "若持续出现，请检查 VPN/代理对 B站上传端点的路由。"
    )


async def upload_video(video_path, title, tid=None, season_id=None, tags=None,
                      description=None, is_private=True, season_name=None,
                      category_name=None, llm_provider="dashscope", llm_model="glm-5.2",
                      auto_title=True, attribution=None, cover_title=None):
    if not os.path.exists(DEFAULT_COOKIES):
        print("Error: 找不到 cookies.json"); return False
    with open(DEFAULT_COOKIES, "r", encoding="utf-8") as f:
        c = json.load(f)
        # buvid4 is required by bilibili_api's get_buvid_cookies(): if it's
        # missing the library calls the B站 SPI endpoint to fetch one, which
        # currently returns 412 / times out (anti-bot), stalling every upload
        # at the buvid handshake. Passing buvid4 from the stored cookies skips
        # that network fetch entirely.
        cred_kwargs = dict(sessdata=c["SESSDATA"], bili_jct=c["bili_jct"], buvid3=c["buvid3"])
        if c.get("buvid4"):
            cred_kwargs["buvid4"] = c["buvid4"]
        credential = Credential(**cred_kwargs)
    _API = get_api("video_uploader")

    async def _fetch_pre_info(attempts=5):
        last_error = None
        retry_waits = {1: 5, 2: 10, 3: 20, 4: 40}
        for attempt in range(1, attempts + 1):
            try:
                result = await Api(**_API["pre"], credential=credential).result
                _save_cached_pre_info(c, result)
                return result
            except Exception as e:
                last_error = e
                if attempt == attempts:
                    break
                wait = retry_waits.get(attempt, 40)
                brief = str(e).split("<")[0].strip()[:160]
                print(
                    f">>> ⚠️ B站预上传信息获取失败（attempt {attempt}/{attempts}）: "
                    f"{type(e).__name__}: {brief}",
                    flush=True,
                )
                print(f">>> {wait}s 后重试...", flush=True)
                await asyncio.sleep(wait)
        raise last_error

    pre_info = _load_cached_pre_info(c)
    if pre_info is None:
        pre_info = await _fetch_pre_info()
    else:
        print(">>> 使用 10 分钟内的 B站预上传信息缓存。", flush=True)
    if auto_title:
        try:
            title = build_title(
                video_path,
                title,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
        except SubtitleTitleError as e:
            print(f">>> ❌ 自动标题失败：{e}")
            print(">>> 已停止上传。请先生成/翻译字幕，或显式使用 --no_auto_title。")
            return False
    if cover_title is None:
        try:
            cover_title = build_cover_title(
                video_path,
                llm_provider=llm_provider,
                llm_model=llm_model,
                attribution=attribution,
            )
        except SubtitleTitleError as e:
            print(f">>> ❌ 封面标题无法从字幕提炼：{e}")
            print(">>> 已停止上传。封面标题不能来自表单标题或文件名。")
            return False
    match_context = title
    if category_name and not tid:
        tid, pname = get_smart_partition(pre_info, match_context, f"{video_path} {description or ''}", category_name)
    elif not tid:
        tid, pname = get_smart_partition(pre_info, match_context, f"{video_path} {description or ''}")
    else:
        pname = f"TID:{tid}"
    print(f">>> 自动选择分区: {pname} (TID: {tid})")
    description = build_description(video_path, title, description, llm_provider=llm_provider, llm_model=llm_model)
    if not tags:
        sub_text, sub_src = _read_subtitle_text(video_path)
        if sub_text:
            gen_tags = _generate_tags_via_llm(sub_text, title, os.path.basename(sub_src), llm_provider=llm_provider, llm_model=llm_model)
            if gen_tags:
                tags = gen_tags
                print(f">>> 标签来源：根据字幕内容动态生成（{os.path.basename(sub_src)}）")
        if not tags:
            tags = ["人工智能", "AI", "自动化"]
            print(">>> 标签来源：默认标签（LLM 生成失败，回退）")
    print(f">>> 分配的标签: {', '.join(tags)}")
    cover_path, cover_4x3_path = _generate_bili_covers(video_path, cover_title)
    if not cover_path or not cover_4x3_path or not os.path.isfile(cover_path):
        print(">>> 已停止上传，避免提交随机截图封面。")
        return False
    print(f">>> B站主封面（16:9）: {cover_path}")
    print(f">>> B站备用封面（4:3）: {cover_4x3_path}")
    meta = video_uploader.VideoMeta(
        tid=tid, title=title, desc=description, tags=tags,
        cover=cover_path if os.path.exists(cover_path) else None,
        no_reprint=True, dynamic="" if is_private else f"发布新视频：{title}"
    )
    meta_dict = meta.__dict__()
    meta_dict["copyright"] = 1
    # Drop cover key entirely when no cover file exists: VideoUploader passes
    # cover through to bilibili_api Picture.from_file(), which raises TypeError
    # on None. Omitting the key lets the uploader skip the cover step.
    if not (cover_path and os.path.exists(cover_path)):
        meta_dict.pop("cover", None)
    if is_private:
        meta_dict["is_only_self"] = 1
        meta_dict["up_close_reply"] = True
        meta_dict["up_close_danmu"] = True
    if not season_id:
        season_id, sname = await get_target_season(pre_info, title, f"{video_path} {description or ''}", target_season_name=season_name, credential=credential)
        if season_id:
            print(f">>> 自动绑定至合集: {sname} (ID: {season_id})")
            meta_dict["season_id"] = season_id
        else:
            print(f">>> 未匹配到合适的合集，跳过绑定")
    else:
        meta_dict["season_id"] = season_id
    uploader_kwargs = dict(
        pages=[video_uploader.VideoUploaderPage(path=video_path, title=title)],
        meta=meta_dict, credential=credential,
    )
    # Only pass cover when the file actually exists — VideoUploader forwards it
    # to bilibili_api Picture.from_file(), which raises TypeError on None.
    if cover_path and os.path.exists(cover_path):
        uploader_kwargs["cover"] = cover_path
    uploader = video_uploader.VideoUploader(**uploader_kwargs)
    last_progress = [-10.0]
    _register_bili_uploader_events(uploader, last_progress)
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            print(f">>> 开始上传: {title}... (attempt {attempt}/{max_attempts})")
            result = await _start_uploader_with_heartbeat(uploader)
            print(f"\n>>> B站API返回: {result}")
            if not result or "bvid" not in result:
                print("\n❌ 上传失败：B站未返回有效的 bvid")
                if attempt < max_attempts:
                    wait = 10 * attempt
                    print(f">>> {wait}s 后重试...")
                    await asyncio.sleep(wait)
                    # Re-create uploader for retry: B站不支持续传，
                    # 每次上传是独立 session，必须从头开始传。
                    uploader = video_uploader.VideoUploader(**uploader_kwargs)
                    last_progress[0] = -10.0
                    _register_bili_uploader_events(uploader, last_progress)
                    continue
                return False
            print("\n✅ 上传完成！")
            return True
        except Exception as e:
            err_brief = str(e).split("<")[0].strip()[:200]
            print(f"\n❌ 失败 (attempt {attempt}/{max_attempts}): {err_brief}")
            import traceback
            traceback.print_exc()
            if attempt < max_attempts:
                wait = 10 * attempt
                print(f">>> {wait}s 后重试...")
                await asyncio.sleep(wait)
                uploader = video_uploader.VideoUploader(**uploader_kwargs)
                last_progress[0] = -10.0
                _register_bili_uploader_events(uploader, last_progress)
                continue
            return False

import argparse
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bilibili Video Uploader")
    parser.add_argument("path", help="Video file path")
    parser.add_argument("title", help="Video title")
    parser.add_argument("--tid", type=int, default=None)
    parser.add_argument("--category_name", type=str, default=None)
    parser.add_argument("--season_id", type=int, default=None)
    parser.add_argument("--season_name", type=str, default=None)
    parser.add_argument("--tags", type=str, default=None)
    parser.add_argument("--desc", type=str, default=None)
    _def_model, _def_prov = _autosub_llm_default()
    parser.add_argument("--llm-model", type=str, default=_def_model)
    parser.add_argument("--llm-provider", type=str, default=_def_prov)
    parser.add_argument("--public", action="store_true")
    parser.add_argument(
        "--no_auto_title",
        action="store_true",
        help="Keep the provided form title; cover title is still derived from subtitles",
    )
    parser.add_argument(
        "--attribution",
        default=None,
        help="Optional speaker/company prefix, e.g. Palantir CEO卡普",
    )
    parser.add_argument(
        "--cover-title",
        default=None,
        help="Text rendered on the cover image (default: subtitle-grounded title)",
    )
    args = parser.parse_args()
    tags = [t.strip() for t in re.split(r'[,，、]', args.tags) if t.strip()] if args.tags else None
    def _run_upload():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Silence noisy asyncio uncaught-exception tracebacks (e.g. aiohttp
        # DNS resolution failures print a multi-line stack trace even when
        # the upload ultimately succeeds after retry). Degrade these to a
        # one-line warning instead of flooding the log.
        def _exc_handler(loop, context):
            exc = context.get("exception")
            msg = context.get("message", "")
            exc_name = type(exc).__name__ if exc else "Exception"
            brief = str(exc).split("<")[0].strip()[:120] if exc else msg[:120]
            print(f">>> ⚠️ 网络抖动（已自动重试）: {exc_name}: {brief}", flush=True)
        loop.set_exception_handler(_exc_handler)
        try:
            return loop.run_until_complete(upload_video(
                args.path, args.title, tid=args.tid, season_id=args.season_id,
                tags=tags, description=args.desc, llm_provider=args.llm_provider,
                llm_model=args.llm_model, is_private=not args.public,
                season_name=args.season_name, category_name=args.category_name,
                auto_title=not args.no_auto_title,
                attribution=args.attribution,
                cover_title=args.cover_title,
            ))
        finally:
            # Cancel pending tasks before closing the loop to prevent
            # bilibili_api's atexit __clean from raising
            # "RuntimeError: Event loop is closed" on Python 3.14.
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()
    result = _run_upload()
    # The upload result is already determined above. Use os._exit to bypass
    # bilibili_api's atexit __clean callback which crashes with
    # "RuntimeError: Event loop is closed" on Python 3.14.
    import os
    os._exit(0 if result else 1)

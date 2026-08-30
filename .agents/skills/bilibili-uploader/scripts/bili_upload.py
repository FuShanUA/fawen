import asyncio
import json
import os
import re
import sys
import time
import shutil
import subprocess
from bilibili_api import video_uploader, Credential, sync
from bilibili_api.video_uploader import VideoUploaderEvents
from bilibili_api.utils.network import Api, get_api, request_settings

request_settings.set_timeout(60)

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

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COOKIES = os.path.join(SKILL_DIR, "assets", "cookies.json")

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

def build_title(video_path, original_title, llm_provider="dashscope", llm_model="glm-5.2"):
    """Generate an attractive B站 title from subtitle content via LLM.
    Falls back to the original filename-based title if LLM is unavailable."""
    sub_text, sub_src = _read_subtitle_text(video_path)
    if sub_text and _LLM_AVAILABLE:
        try:
            client = _get_llm_client()
            out = client.generate_content(
                f"""根据以下视频字幕，拟定一个吸引人的B站视频标题。
要求：
- 10-30个字，简洁有力
- 体现视频的核心主题或最亮眼的观点
- 可以包含关键人名/公司名/技术名
- 不要用"震惊""必看"等标题党词汇
- 不要用书名号、括号、引号等符号
- 直接输出标题文字，不要任何解释

原始文件名（参考）：{original_title}
字幕内容：
{sub_text}

只输出标题。""",
                model_name=llm_model
            )
            if out:
                new_title = out.strip().strip('"\'「」『』""''').strip()
                if len(new_title) <= 80 and len(new_title) >= 5:
                    print(f">>> 标题来源：根据字幕内容生成（{os.path.basename(sub_src)}）")
                    print(f"    原标题: {original_title}")
                    print(f"    新标题: {new_title}")
                    return new_title
        except Exception as e:
            print(f">>> LLM标题生成失败: {e}")
    print(f">>> 标题来源：使用文件名标题")
    return original_title

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

async def upload_video(video_path, title, tid=None, season_id=None, tags=None,
                      description=None, is_private=True, season_name=None,
                      category_name=None, llm_provider="dashscope", llm_model="glm-5.2",
                      auto_title=True):
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
    pre_info = await Api(**_API["pre"], credential=credential).result
    if auto_title:
        title = build_title(video_path, title, llm_provider=llm_provider, llm_model=llm_model)
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
    base_name = os.path.splitext(video_path)[0]
    cover_path = base_name + ".jpg"
    def _is_portrait(path):
        try:
            from PIL import Image
            with Image.open(path) as im: return im.size[0] < im.size[1]
        except: return False
    if os.path.exists(cover_path) and _is_portrait(cover_path):
        shutil.copy2(cover_path, base_name + ".portrait.jpg")
        os.remove(cover_path)
    if not os.path.exists(cover_path):
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            print(">>> 未找到横版封面，正在从视频截取横版帧...")
            extract_best_cover(ffmpeg.strip('"'), video_path, cover_path)
    if not os.path.exists(cover_path):
        # 抽帧失败（视频损坏/无法读取）时生成纯色兜底封面，避免
        # VideoMeta/VideoUploader 收到空路径而崩溃。
        try:
            from PIL import Image
            Image.new("RGB", (1146, 717), (24, 24, 32)).save(cover_path, "JPEG")
            print(">>> 生成兜底封面（视频无法抽帧，使用纯色封面）")
        except Exception as e:
            print(f">>> ⚠️ 无法生成封面: {e}")
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
    @uploader.on(VideoUploaderEvents.AFTER_PAGE.value)
    async def on_after_page(data):
        print("\n>>> 分块上传完成，正在提交发布...")
    try:
        print(f">>> 开始上传: {title}...")
        result = await uploader.start()
        print(f"\n>>> B站API返回: {result}")
        if not result or "bvid" not in result:
            print("\n❌ 上传失败：B站未返回有效的 bvid")
            return False
        print("\n✅ 上传完成！")
        return True
   except Exception as e:
       err_brief = str(e).split("<")[0].strip()[:200]
       print(f"\n❌ 失败: {err_brief}")
        import traceback
        traceback.print_exc()
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
    parser.add_argument("--no_auto_title", action="store_true", help="Disable LLM-based title generation, use filename title as-is")
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
                auto_title=not args.no_auto_title
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

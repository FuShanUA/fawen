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

def _read_subtitle_text(video_path, max_chars=6000):
    base = os.path.splitext(video_path)[0]
    # Strip _hardsub suffix to find subtitle files named after the original video
    if base.endswith("_hardsub"):
        base = base[:-8]
    for suffix in [".bi.srt", ".srt", ".cn.srt"]:
        p = base + suffix
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            lines = []
            for line in text.split("\n"):
                line = line.strip()
                if not line or line.isdigit() or "-->" in line: continue
                lines.append(line)
            return " ".join(lines)[:max_chars], p
    return None, None

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
{subtitle_text[:3000]}

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
{sub_text[:3000]}

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
                    pixels = list(img.getdata())
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
    season_data = pre_info.get("seasons") or (pre_info.get("season") if isinstance(pre_info.get("season"), dict) else {}).get("seasons", []) if isinstance(pre_info.get("season"), dict) else []
    seasons = season_data if season_data else []
    if not seasons and not target_season_name: return None, None
    if target_season_name:
        for s in seasons:
            if s.get("name") == target_season_name:
                return s.get("id"), s.get("name")
        if credential:
            try:
                api = {"method": "POST", "url": "https://member.bilibili.com/x/vupre/web/season/add", "data": {"name": target_season_name, "desc": "自动创建的合集"}, "comment": "创建合集"}
                resp = await Api(**api, credential=credential).result
                new_id = resp.get("data", {}).get("season_id")
                if new_id: return new_id, target_season_name
            except Exception as e:
                print(f"Warning: 创建合集请求异常: {e}")
    content_text = (title + " " + full_text).upper()
    best_id, best_name, max_score = None, None, 0
    for s in seasons:
        sname = s.get("name", "").upper()
        score = 10 if sname in content_text else 0
        for kw in ["AI", "人工智能", "LLM", "科技", "自动化", "STARTUP", "ELON"]:
            if kw in sname and kw in content_text: score += 5
        if score > max_score: max_score = score; best_id = s.get("id"); best_name = s.get("name")
    return (best_id, best_name) if max_score > 0 else (None, None)

async def upload_video(video_path, title, tid=None, season_id=None, tags=None,
                      description=None, is_private=True, season_name=None,
                      category_name=None, llm_provider="dashscope", llm_model="glm-5.2"):
    if not os.path.exists(DEFAULT_COOKIES):
        print("Error: 找不到 cookies.json"); return False
    with open(DEFAULT_COOKIES, "r", encoding="utf-8") as f:
        c = json.load(f)
        credential = Credential(sessdata=c["SESSDATA"], bili_jct=c["bili_jct"], buvid3=c["buvid3"])
    _API = get_api("video_uploader")
    pre_info = await Api(**_API["pre"], credential=credential).result
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
    meta = video_uploader.VideoMeta(
        tid=tid, title=title, desc=description, tags=tags,
        cover=cover_path if os.path.exists(cover_path) else "",
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
        print(f"\n❌ 失败: {e}")
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
    args = parser.parse_args()
    tags = [t.strip() for t in re.split(r'[,，、]', args.tags) if t.strip()] if args.tags else None
    result = asyncio.run(upload_video(
        args.path, args.title, tid=args.tid, season_id=args.season_id,
        tags=tags, description=args.desc, llm_provider=args.llm_provider,
        llm_model=args.llm_model, is_private=not args.public,
        season_name=args.season_name, category_name=args.category_name
    ))
    sys.exit(0 if result else 1)

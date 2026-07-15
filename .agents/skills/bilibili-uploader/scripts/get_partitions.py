import asyncio
import json
import os
from bilibili_api import Credential
from bilibili_api.utils.network import Api, get_api

# 获取脚本所在配置目录
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COOKIES = os.path.join(SKILL_DIR, "assets", "cookies.json")

async def get_partitions():
    if not os.path.exists(DEFAULT_COOKIES):
        print("Error: 找不到 cookies.json")
        return
        
    with open(DEFAULT_COOKIES, 'r', encoding='utf-8') as f:
        c = json.load(f)
        credential = Credential(sessdata=c['SESSDATA'], bili_jct=c['bili_jct'], buvid3=c['buvid3'])

    _API = get_api("video_uploader")
    try:
        pre_info = await Api(**_API["pre"], credential=credential).result
        typelist = pre_info.get("typelist", [])
        
        print(f"{'分区名称':<20} | {'ID':<10} | {'类型'}")
        print("-" * 50)
        
        for cat in typelist:
            name = cat.get("name", "Unknown")
            tid = cat.get("id", "N/A")
            print(f"{name:<20} | {tid:<10} | 一级分区")
            
            for child in cat.get("children", []):
                c_name = child.get("name", "Unknown")
                c_tid = child.get("id", "N/A")
                print(f"  {c_name:<18} | {c_tid:<10} | 二级分区")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(get_partitions())

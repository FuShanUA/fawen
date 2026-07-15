import asyncio
from bilibili_api import login_v2, sync
import json
import os
import qrcode
import time

# 获取脚本所在目录的父目录下的 assets 文件夹
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")
COOKIES_FILE = os.path.join(ASSETS_DIR, "cookies.json")

async def main():
    print("正在获取登录二维码...")
    login_obj = login_v2.QrCodeLogin()
    await login_obj.generate_qrcode()
    
    # 提取内部链接
    try:
        qr_url = login_obj._QrCodeLogin__qr_link
    except AttributeError:
        qr_url = "https://passport.bilibili.com/h5/account-h5/auth/scan-web"

    # 生成一张清晰的图片
    qr = qrcode.QRCode(border=2)
    qr.add_data(qr_url)
    img = qr.make_image(fill_color="black", back_color="white")
    img_path = "qrcode.png"
    img.save(img_path)

    print("\n" + "="*60)
    print(f"✅ 二维码图片已生成: {os.path.abspath(img_path)}")
    print("👉 请直接双击打开该图片并使用 Bilibili App 扫码。")
    print("\n或者，如果你电脑浏览器已登录 B站，点击此链接确认：")
    print(f"🔗 {qr_url}")
    print("="*60)
    
    print("\n正在等待确认，请在手机上点击“确认登录”...")
    
    last_state = None
    while True:
        try:
            state = await login_obj.check_state()
            if state != last_state:
                if state == login_v2.QrCodeLoginEvents.SCAN:
                    print(">>> [状态] 等待扫码...")
                elif state == login_v2.QrCodeLoginEvents.CONF:
                    print(">>> [状态] 已扫码！请在手机/网页上点击“确认”。")
                elif state == login_v2.QrCodeLoginEvents.DONE:
                    print("\n>>> ✅ 登录成功！")
                    credential = login_obj.get_credential()
                    
                    cookies = {
                        "SESSDATA": credential.sessdata,
                        "bili_jct": credential.bili_jct,
                        "buvid3": credential.buvid3
                    }
                    
            # 确保目录存在
            if not os.path.exists(ASSETS_DIR):
                os.makedirs(ASSETS_DIR)
                
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            
            print(f"Cookie 已保存至: {os.path.abspath(COOKIES_FILE)}")
                    # 删除临时二维码
                    if os.path.exists(img_path):
                        os.remove(img_path)
                    return
                elif state == login_v2.QrCodeLoginEvents.TIMEOUT:
                    print("\n>>> ❌ 超时，请重新运行脚本。")
                    return
                last_state = state
        except Exception:
            pass
            
        await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已取消。")

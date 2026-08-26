import asyncio
from bilibili_api import login_v2
import json
import os
import qrcode

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")
COOKIES_FILE = os.path.join(ASSETS_DIR, "cookies.json")

async def main():
    print("正在获取登录二维码...")
    login_obj = login_v2.QrCodeLogin()
    await login_obj.generate_qrcode()

    try:
        qr_url = login_obj._QrCodeLogin__qr_link
    except AttributeError:
        qr_url = "https://passport.bilibili.com/h5/account-h5/auth/scan-web"

    qr = qrcode.QRCode(border=2)
    qr.add_data(qr_url)
    img = qr.make_image(fill_color="black", back_color="white")
    img_path = os.path.join(ASSETS_DIR, "qrcode.png")
    os.makedirs(ASSETS_DIR, exist_ok=True)
    img.save(img_path)

    print("\n" + "=" * 60)
    print(f"二维码图片已生成: {img_path}")
    print("请用 Bilibili App 扫码登录。")
    print(f"或点击此链接确认: {qr_url}")
    print("=" * 60)
    print("\n正在等待确认...")

    last_state = None
    while True:
        try:
            state = await login_obj.check_state()
            if state != last_state:
                if state == login_v2.QrCodeLoginEvents.SCAN:
                    print(">>> [状态] 等待扫码...")
                elif state == login_v2.QrCodeLoginEvents.CONF:
                    print(">>> [状态] 已扫码，请在手机上确认。")
                elif state == login_v2.QrCodeLoginEvents.DONE:
                    print("\n>>> 登录成功！")
                    credential = login_obj.get_credential()

                    from bilibili_api.utils.network import get_buvid
                    try:
                        buvid3, buvid4 = await get_buvid()
                    except Exception:
                        buvid3, buvid4 = None, None

                    cookies = {
                        "SESSDATA": credential.sessdata,
                        "bili_jct": credential.bili_jct,
                        "buvid3": buvid3 or credential.buvid3,
                    }
                    if buvid4:
                        cookies["buvid4"] = buvid4

                    os.makedirs(ASSETS_DIR, exist_ok=True)
                    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                        json.dump(cookies, f, indent=2)

                    print(f"Cookie 已保存至: {COOKIES_FILE}")
                    if os.path.exists(img_path):
                        os.remove(img_path)
                    return
                elif state == login_v2.QrCodeLoginEvents.TIMEOUT:
                    print("\n>>> 超时，请重新运行脚本。")
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

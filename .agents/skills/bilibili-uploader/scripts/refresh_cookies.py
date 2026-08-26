#!/usr/bin/env python3
"""Refresh B站 cookies by extracting them from Chrome's cookie store.

Usage: python refresh_cookies.py
"""
import sqlite3, os, shutil, tempfile, subprocess, json, hashlib, datetime, sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIES_FILE = os.path.join(SKILL_DIR, "assets", "cookies.json")

def get_chrome_key():
    """Get the Chrome Safe Storage password from macOS Keychain and derive AES key."""
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"❌ Keychain error: {result.stderr.strip()}")
        return None
    password = result.stdout.strip()
    return hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), b"saltysalt", 1003, 16)

def decrypt_cookie(enc_val, key):
    """Decrypt a Chrome v10 cookie value using AES-128-CBC."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    if enc_val[:3] not in (b"v10", b"v11"):
        return None
    ciphertext = enc_val[3:]
    iv = b" " * 16
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = decrypted[-1]
    if 1 <= pad_len <= 16:
        decrypted = decrypted[:-pad_len]
    # First 32 bytes are a domain hash; actual value starts after
    return decrypted[32:].decode("utf-8", errors="replace")

def extract_from_chrome():
    """Extract B站 cookies from Chrome's cookie database."""
    key = get_chrome_key()
    if not key:
        return None

    # Try Default profile, then Profile 1, etc.
    chrome_base = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    cookie_paths = []
    for p in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
        cp = os.path.join(chrome_base, p, "Cookies")
        if os.path.exists(cp):
            cookie_paths.append(cp)

    wanted = ["SESSDATA", "bili_jct", "buvid3", "buvid4"]
    cookies = {}

    for cp in cookie_paths:
        if not cookies.get("SESSDATA"):
            tmp = tempfile.mktemp(suffix=".db")
            shutil.copy2(cp, tmp)
            try:
                conn = sqlite3.connect(tmp)
                c = conn.cursor()
                for name in wanted:
                    if name in cookies and cookies[name]:
                        continue
                    c.execute(
                        'SELECT name, encrypted_value, expires_utc FROM cookies '
                        'WHERE host_key = ".bilibili.com" AND name = ?',
                        (name,)
                    )
                    row = c.fetchone()
                    if not row:
                        continue
                    val = decrypt_cookie(row[1], key)
                    if val:
                        cookies[name] = val
                        expires_utc = row[2]
                        if expires_utc > 0:
                            unix_expires = (expires_utc - 11644473600000000) // 1000000
                            expire_dt = datetime.datetime.fromtimestamp(unix_expires)
                            is_expired = datetime.datetime.now().timestamp() > unix_expires
                            print(f"  {name}: expires={expire_dt} expired={is_expired}")
                conn.close()
            except Exception as e:
                print(f"⚠️ Error reading {cp}: {e}")
            finally:
                os.remove(tmp)

    return cookies if cookies.get("SESSDATA") else None

def main():
    print("🔄 从 Chrome 提取 B站 cookies...")
    cookies = extract_from_chrome()
    if not cookies:
        print("❌ 未能从 Chrome 提取有效的 B站 cookies")
        print("   请确保 Chrome 已登录 B站，然后重试。")
        return 1

    os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f"✅ Cookies 已保存至: {COOKIES_FILE}")
    print(f"   Keys: {list(cookies.keys())}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

import re
import os
import sys
import hashlib
import urllib.request
from urllib.parse import urlparse

def download_image(url, assets_dir):
    try:
        # Avoid downloading non-http(s) urls
        if not url.startswith('http'):
            return None

        # generate a secure filename based on url
        ext = os.path.splitext(urlparse(url).path)[1]
        if not ext or len(ext) > 5:
            # guess from url, or default to .png if it looks like an image service without extension
            if 'jpeg' in url.lower() or 'jpg' in url.lower():
                ext = '.jpg'
            elif 'gif' in url.lower():
                ext = '.gif'
            else:
                ext = '.png'

        # use md5 hash for filename to avoid special char issues and collisions
        filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ext
        filepath = os.path.join(assets_dir, filename)

        if not os.path.exists(filepath):
            print(f"Downloading {url} -> {filepath}")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                with open(filepath, 'wb') as f:
                    f.write(response.read())
        else:
            print(f"Already exists: {filepath}")

        return f"./assets/{filename}"
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return None

def process_markdown(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    base_dir = os.path.dirname(os.path.abspath(filepath))
    assets_dir = os.path.join(base_dir, "assets")

    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Match ![alt](url)
    md_img_pattern = re.compile(r'!\[([^\]]*)\]\((https?://[^\s)]+)\)')

    # Match <img src="url">
    html_img_pattern = re.compile(r'<img[^>]+src=["\'](https?://[^"\']+)["\'][^>]*>')

    replacements = {}

    # Find all MD images
    for match in md_img_pattern.finditer(content):
        url = match.group(2)
        local_path = download_image(url, assets_dir)
        if local_path:
            replacements[url] = local_path

    # Find all HTML images
    for match in html_img_pattern.finditer(content):
        url = match.group(1)
        local_path = download_image(url, assets_dir)
        if local_path:
            replacements[url] = local_path

    # Replace URLs
    new_content = content
    for original_url, local_path in replacements.items():
        new_content = new_content.replace(original_url, local_path)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath} with local asset links.")
    else:
        print(f"No remote images found or downloaded in {filepath}.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python download_assets.py <markdown_file>")
        sys.exit(1)

    process_markdown(sys.argv[1])
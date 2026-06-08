"""
wechat_publisher.py (Simplified)
"""
import sys
import os
import subprocess
import re

from common_utils import resolve_tool_path

def generate_wechat_assets(md_path):
    abs_md_path = os.path.abspath(md_path)
    cwd = os.path.dirname(abs_md_path)

    # Dynamically resolve baoyu-markdown-to-html tool path
    baoyu_dir = resolve_tool_path("baoyu-markdown-to-html")
    if baoyu_dir and os.path.exists(os.path.join(baoyu_dir, "scripts", "main.ts")):
        baoyu_main_ts = os.path.join(baoyu_dir, "scripts", "main.ts")
    else:
        # Fallback to local sibling or hardcoded default
        fallback_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "baoyu-skills", "skills", "baoyu-markdown-to-html"))
        if os.path.exists(os.path.join(fallback_dir, "scripts", "main.ts")):
            baoyu_main_ts = os.path.join(fallback_dir, "scripts", "main.ts")
        else:
            baoyu_main_ts = r"/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-markdown-to-html/scripts/main.ts"

    base_name = os.path.basename(abs_md_path).replace(".md", "")
    tmp_out = os.path.join(cwd, f"{base_name}_pub_log.txt")
    cmd = f'npx -y bun "{baoyu_main_ts}" "{abs_md_path}" --theme default --keep-title > "{tmp_out}" 2>&1'
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True, cwd=cwd)

    # Expected HTML path
    html_path = abs_md_path.replace(".md", ".html")
    if not os.path.exists(html_path):
        print(f"Error: {html_path} not found.")
        return

    print(f"HTML generated at {html_path}. Fixing image paths...")

    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    replacements = {}

    # Try to find replacements in the log file (dynamic mapping)
    if os.path.exists(tmp_out):
        try:
            with open(tmp_out, 'r', encoding='utf-8', errors='ignore') as f:
                logs = f.read()
            # Find JSON block reliably
            import json
            start_idx = logs.find('{')
            end_idx = logs.rfind('}')
            if start_idx != -1 and end_idx != -1:
                try:
                    data = json.loads(logs[start_idx:end_idx+1])
                    if "contentImages" in data:
                        for img in data["contentImages"]:
                            placeholder = img.get("placeholder")
                            original_path = img.get("originalPath")
                            if placeholder and original_path:
                                # Use relative path for production/publish readiness
                                # We assume HTML is in project root or publish/,
                                # and assets/ is in project root.
                                # If publish/ exists, the user likely moves HTML there.
                                if placeholder in html_content:
                                    # Fallback to absolute file:/// for local preview if not in a server
                                    # But for WeChat/Web, relative assets/ is safer.
                                    # We use the original path as requested by most platforms.
                                    replacements[placeholder] = original_path
                                    print(f"  Mapped {placeholder} -> {original_path}")
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON from logs: {e}")
        except Exception as e:
            print(f"Error reading {tmp_out}: {e}")

    # Apply all found replacements
    for placeholder, web_path in replacements.items():
        if placeholder in html_content:
            html_content = html_content.replace(placeholder, web_path)
            print(f"  Injected {placeholder}")

    # Final cleanup of any missed placeholders or absolute local paths
    html_content = html_content.replace("MDTOHTMLIMGPH_", "MISSING_IMG_")

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print("Done.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    generate_wechat_assets(sys.argv[1])
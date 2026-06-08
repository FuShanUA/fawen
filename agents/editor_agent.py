"""
editor_agent.py

Agent 9: Interactive GUI Editor for Postfdry HTML.
Launches a local web server with a 'contenteditable' UI to refine text in place.
Reuses distillation logic from translation-distiller tool.
"""

import sys
import os
import http.server
import socketserver
import webbrowser
import threading
import json
import base64
import re
import subprocess
import shutil
# Add paths for common tools
COMMON_TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "common"))
if os.path.exists(COMMON_TOOLS_DIR) and COMMON_TOOLS_DIR not in sys.path:
    sys.path.append(COMMON_TOOLS_DIR)

# Import AI utils from common
try:
    from llm_utils import get_client
except ImportError:
    def get_client(): return None

# Import prompt logic from patcher_agent
from patcher_agent import build_patch_prompt

PORT = 8080
ORIGINAL_FILE = ""
HTML_FILE = ""
BASELINE_FILE = ""
DIFF_DRAFT = "diff_draft.md"

def get_new_version_path(original_path):
    """Calculates the next available version number for a file."""
    base, ext = os.path.splitext(original_path)
    # Remove existing version suffix for calculation if present
    base = re.sub(r'_v\d+$', '', base)
    v = 1
    while True:
        new_path = f"{base}_v{v}{ext}"
        if not os.path.exists(new_path):
            return new_path
        v += 1

class EditorHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            with open(HTML_FILE, 'r', encoding='utf-8') as f:
                content = f.read()

            # For the editor UI, we need to convert absolute file:/// paths back to relative
            base_dir = os.path.dirname(os.path.abspath(HTML_FILE))

            def make_rel(match):
                full_path = match.group(1).replace("file:///", "")
                if os.name == 'nt' and full_path.startswith('/'):
                    full_path = full_path[1:]
                try:
                    rel = os.path.relpath(full_path, base_dir)
                    return f'src="{rel.replace("\\", "/")}"'
                except: return match.group(0)

            content = re.sub(r'src="file:///(.*?)"', make_rel, content)

            editor_ui = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Postfdry GUI Editor</title>
    <style>
        :root {
            --primary: #0F4C81; --bg: #f5f7fa; --accent: #ff7e5f; --card-padding: 60px;
        }
        body { margin: 0; background: var(--bg); font-family: -apple-system-font,BlinkMacSystemFont,Helvetica Neue,PingFang SC,sans-serif; }
        #admin-bar {
            position: fixed; top: 0; left: 0; right: 0; height: 60px;
            background: #0F4C81; color: white; display: flex; align-items: center; justify-content: space-between;
            padding: 0 40px; z-index: 10000; box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }
        .logo { font-weight: 800; font-size: 1.2rem; }
        .logo span { background: var(--accent); color: white; padding: 2px 8px; border-radius: 4px; margin-left: 8px; font-size: 0.8rem; }
        button {
            background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.3); padding: 8px 20px; border-radius: 30px;
            font-weight: 600; cursor: pointer; transition: 0.3s; color: white; margin-left:10px;
        }
        button:hover { background: rgba(255,255,255,0.2); transform: translateY(-1px); }
        button.save { background: var(--accent); border: none; }
        button.save:hover { background: #ff9d85; }

        #ai-patch-box {
            background: rgba(255,126,95,0.15); border: 2px solid rgba(255,126,95,0.4);
            border-radius: 8px; padding: 5px 15px; display: flex; align-items: center; margin: 0 20px; flex-grow: 1; max-width: 600px;
            box-shadow: 0 0 15px rgba(255,126,95,0.2);
        }
        #ai-patch-box input {
            background: transparent; border: none; color: white; width: 100%; outline: none; font-size: 1rem;
            height: 30px;
        }
        #ai-patch-box input::placeholder { color: rgba(255,255,255,0.6); }
        .patch-go {
            background: #ff7e5f; border: none; color: white; cursor: pointer; font-weight: bold; font-size: 1.2rem;
            padding: 4px 12px; transition: 0.2s; border-radius: 6px; margin-left:10px;
        }
        .patch-go:hover { transform: scale(1.05); background: #ff9d85; }

        #preview-container { padding: 80px 20px; display: flex; justify-content: center; }
        #editable-frame {
            background: white; padding: var(--card-padding); width: 860px;
            box-shadow: 0 10px 50px rgba(0,0,0,0.05); border-radius: 12px; outline: none;
        }
        [contenteditable="true"]:hover { background: rgba(255, 126, 95, 0.03); outline: 2px dashed #ff7e5f; outline-offset: 4px; }
        [contenteditable="true"]:focus { background: transparent; outline: 2px solid #ff7e5f; outline-offset: 4px; }
        .toast {
            position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
            background: #2c3e50; color: white; padding: 12px 30px; border-radius: 30px;
            opacity: 0; transition: 0.4s; z-index: 11000; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }
        img { max-width: 100%; display: block; margin: 20px auto; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
    </style>
</head>
<body>
    <div id="admin-bar">
        <div class="logo">Postfdry <span>EDITOR V2</span></div>
        <div id="ai-patch-box">
            <input type="text" id="patch-instruction" placeholder="✨ 魔法补丁功能开发中..." disabled>
            <button class="patch-go" onclick="alert('✨ 魔法补丁功能正在内测开发中，敬请期待！')" title="开发中">🪄</button>
        </div>
        <div class="controls">
            <button onclick="window.close()">退出</button>
            <button class="save" onclick="saveContent()">💾 保存并提取专家知识</button>
        </div>
    </div>
    <div id="preview-container"><div id="editable-frame">""" + content + """</div></div>
    <div id="toast" class="toast">✨ 修改已保存到新版本，正在生成专家知识库草案...</div>

    <script>
        const frame = document.getElementById('editable-frame');
        function setup(root) {
            const elms = root.querySelectorAll('p, h1, h2, h3, li, span, blockquote, em, strong, td, th');
            elms.forEach(el => { if(el.innerText && el.innerText.trim().length > 0) el.contentEditable = "true"; });
        }
        setup(frame);

        async function runAiPatch() {
            const insInput = document.getElementById('patch-instruction');
            const ins = insInput.value;
            if(!ins) return;
            const btn = document.querySelector('.patch-go');
            const t = document.getElementById('toast');

            btn.disabled = true;
            btn.innerText = "⏳";
            t.innerText = "🚀 Antigravity 正在调遣 AI 进行修复，请稍候...";
            t.style.opacity = '1';

            try {
                const res = await fetch('/patch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ instruction: ins })
                });
                const data = await res.json();
                if(res.ok) {
                    t.innerText = "✅ AI 修复已完成！正在更新视图...";
                    // Update content dynamically
                    frame.innerHTML = data.html;
                    setup(frame);
                    setTimeout(() => t.style.opacity = '0', 2000);
                } else {
                    const errorMsg = data.error || 'AI 修复发生未知错误';
                    alert('AI 修复失败: ' + errorMsg);
                    t.style.opacity = '0';
                }
            } catch(e) {
                alert('网络通讯故障: ' + e);
                t.style.opacity = '0';
            } finally {
                btn.disabled = false;
                btn.innerText = "🪄";
            }
        }

        async function saveContent() {
            const clones = frame.cloneNode(true);
            clones.querySelectorAll('[contenteditable]').forEach(el => el.removeAttribute('contenteditable'));
            try {
                const res = await fetch('/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ html: clones.innerHTML })
                });
                if (res.ok) {
                    const t = document.getElementById('toast');
                    t.style.opacity = '1';
                    setTimeout(() => t.style.opacity = '0', 3000);
                }
            } catch (err) { alert('保存故障: ' + err); }
        }
    </script>
</body>
</html>
"""
            self.wfile.write(editor_ui.encode('utf-8'))
        else:
            self.directory = os.path.dirname(os.path.abspath(HTML_FILE))
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        if self.path == "/save":
            length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            inner = data['html']

            base = os.path.dirname(os.path.abspath(HTML_FILE))

            # Ensure images load correctly by restoring file:/// paths
            def mk_abs(match):
                rel = match.group(1)
                if rel.startswith(('http', 'file:///')): return match.group(0)
                path = os.path.normpath(os.path.join(base, rel)).replace("\\", "/")
                return f'src="file:///{path}"'

            inner = re.sub(r'src="(.*?)"', mk_abs, inner)

            # Reconstruction
            final = f'<!doctype html><html><body style="padding: 24px; max-width: 860px; margin: 0 auto; font-family: sans-serif; line-height: 1.75;"><div id="output"><section class="container">{inner}</section></div></body></html>'

            with open(HTML_FILE, 'w', encoding='utf-8') as f:
                f.write(final)

            print(f"Editor Agent: Changes saved to {HTML_FILE}")

            # DISTILLATION TRIGGER
            try:
                distill_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "translation-distiller"))
                if not os.path.exists(distill_dir):
                    distill_dir = r"/Users/shanfu/cc/Library/Tools/translation-distiller"
                diff_script = os.path.join(distill_dir, "generate_diff_draft.py")

                if os.path.exists(diff_script):
                    output_md = os.path.join(os.path.dirname(HTML_FILE), DIFF_DRAFT)
                    cmd = [sys.executable, diff_script, BASELINE_FILE, HTML_FILE, output_md]
                    print(f"Editor Agent: Generating knowledge draft -> {output_md}")
                    subprocess.run(cmd, check=True, cwd=os.path.dirname(HTML_FILE))
                    print(f"Editor Agent: Expert knowledge draft generated successfully.")
                else:
                    print(f"Editor Agent: Warning: generate_diff_draft.py not found at {diff_script}")
            except Exception as de:
                print(f"Editor Agent: Distillation error: {de}")

            self.send_response(200); self.end_headers()

        elif self.path == "/patch":
            length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            instruction = data.get('instruction', '')

            print(f"\n[AI_PATCH_REQUEST] {instruction}\n")

            try:
                # 1. Read current HTML from file (or state)
                with open(HTML_FILE, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                # 2. Build Prompt using Agent 8 logic
                prompt = build_patch_prompt(html_content, instruction)

                # 3. Call LLM
                client = get_client()
                if not client:
                    raise Exception("LLM Client not initialized. Check .env and common/llm_utils.py")

                model = os.environ.get("PATCH_MODEL", "gemini-3.1-pro-preview")
                print(f"Editor Agent: Requesting patch from {model}...")

                response = client.generate_content(prompt, model_name=model)
                if not response:
                    raise Exception("LLM returned empty response")

                # Clean HTML tags if LLM wrapped it in markdown
                patched_html = response.replace("```html", "").replace("```", "").strip()

                # 4. Save and return ONLY the inner body content if we are updating the frame
                # Actually, patcher_agent returns full HTML. We need to extract the inner part
                # or just save it all and tell the client what the new innerHTML is.

                # Let's save the whole thing
                # Backup first
                shutil.copy2(HTML_FILE, HTML_FILE + ".patch_bak")

                with open(HTML_FILE, 'w', encoding='utf-8') as f:
                    f.write(patched_html)

                # Extract inner content for the frontend to update #editable-frame
                # We expect the HTML to have <section class="container">... or similar
                inner_match = re.search(r'<section class="container">(.*?)</section>', patched_html, re.DOTALL)
                if not inner_match:
                    # Fallback to output div or anything within body
                    inner_match = re.search(r'<body>(.*?)</body>', patched_html, re.DOTALL)

                display_html = inner_match.group(1) if inner_match else patched_html

                # Ensure images stay relative for discovery
                base_dir = os.path.dirname(os.path.abspath(HTML_FILE))
                def make_rel(match):
                    full_path = match.group(1).replace("file:///", "")
                    if os.name == 'nt' and full_path.startswith('/'): full_path = full_path[1:]
                    try:
                        rel = os.path.relpath(full_path, base_dir)
                        return f'src="{rel.replace("\\", "/")}"'
                    except: return match.group(0)
                display_html = re.sub(r'src="file:///(.*?)"', make_rel, display_html)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "html": display_html}).encode('utf-8'))
                print("Editor Agent: Patch applied and synchronized to GUI.")

            except Exception as e:
                print(f"Editor Agent: AI Patch Error: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def run_server():
    server_address = ("", PORT)
    httpd = ThreadingHTTPServer(server_address, EditorHandler)
    print(f"Editor Agent: Started (Threaded) http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    httpd.serve_forever()

if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(1)
    target = os.path.abspath(sys.argv[1])

    # 1. Setup Versioning
    # If the file passed in doesn't exist, we can't edit it.
    if not os.path.exists(target):
        print(f"Error: Target file not found: {target}")
        sys.exit(1)

    ORIGINAL_FILE = target

    # Determine if we should work on a new version or the current one.
    # To match 'edit-translation' behavior, we immediately create a NEW version.
    HTML_FILE = get_new_version_path(ORIGINAL_FILE)
    shutil.copy2(ORIGINAL_FILE, HTML_FILE)

    # 2. Setup Baseline (Original state for diffing)
    BASELINE_FILE = HTML_FILE + ".baseline"
    shutil.copy2(ORIGINAL_FILE, BASELINE_FILE)

    print(f"Editor Agent: Working on NEW VERSION -> {os.path.basename(HTML_FILE)}")
    print(f"Editor Agent: Baseline set to -> {os.path.basename(BASELINE_FILE)}")

    run_server()
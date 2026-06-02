import sys
import os
import argparse
import subprocess
import shutil
import json

# Add common tools to path
# Standalone fallback support: use local common directory if present, otherwise fallback to project-wide common
local_common = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'common'))
common_dir = local_common if os.path.exists(local_common) else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common'))
if common_dir not in sys.path:
    sys.path.append(common_dir)

from llm_utils import get_client

def run_agent_prompt(agent_script, input_file, additional_args=None):
    cmd = [sys.executable, agent_script, input_file, "--prompt-only"]
    if additional_args:
        cmd.extend(additional_args)
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if res.returncode != 0:
        raise Exception(f"Agent prompt generation failed: {res.stderr}")
    return res.stdout

def run_agent_scrub(agent_script, target_file):
    subprocess.run([sys.executable, agent_script, target_file])

def main():
    parser = argparse.ArgumentParser(description="Postfdry CLI Runner with Cascading API Fallbacks")
    parser.add_argument("input", help="Source markdown file")
    parser.add_argument("--mode", choices=["translate", "rewrite"], required=True, help="Mode of operation")
    parser.add_argument("--output", help="Output file path (optional)")
    parser.add_argument("--model", default=None, help="Force a specific model (e.g. gpt-4o), will cascade if failed")

    args = parser.parse_args()

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    agent_name = f"{args.mode}r_agent.py" if args.mode == "rewrite" else f"{args.mode[:-1]}or_agent.py"
    agent_script = os.path.join(base_dir, "agents", agent_name)

    if not os.path.exists(agent_script):
        # Fallback to simple check
        possible_names = [f"{args.mode}r_agent.py", f"{args.mode[:-1]}or_agent.py", f"{args.mode}r_agent.py"]
        for name in possible_names:
            p = os.path.join(base_dir, "agents", name)
            if os.path.exists(p):
                agent_script = p
                break

    if not os.path.exists(agent_script):
        print(f"❌ Could not find agent script: {agent_script}")
        sys.exit(1)

    print(f"📖 Generating prompt using {args.mode}r_agent...")
    prompt = run_agent_prompt(agent_script, args.input)

    # NEW: Create prompts directory and save last prompt
    project_dir = os.path.dirname(os.path.abspath(args.input))
    prompt_dir = os.path.join(project_dir, "prompts")
    if not os.path.exists(prompt_dir):
        os.makedirs(prompt_dir)

    prompt_log = os.path.join(prompt_dir, f"{args.mode}_prompt.md")
    with open(prompt_log, 'w', encoding='utf-8') as f:
        f.write(prompt)
    print(f"📝 Prompt saved to {prompt_log}")

    print(f"🚀 Calling LLM via cascading configuration in .env...")
    client = get_client()
    try:
        content = client.generate_content(prompt, model_name=args.model, fallback=True)
        if not content:
            raise Exception("LLM returned empty content.")
    except Exception as e:
        print(f"❌ LLM Error: {e}")
        sys.exit(1)

    output_file = args.output or args.input.replace(".md", f"_{args.mode}d.md")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"🧹 Scrubbing output constraints...")
    run_agent_scrub(agent_script, output_file)

    # NEW: Generate HTML using baoyu-markdown-to-html
    print(f"🎨 Generating styled HTML using baoyu-markdown-to-html...")
    baoyu_dir = os.path.abspath(os.path.join(base_dir, "..", "baoyu-skills", "skills", "baoyu-markdown-to-html"))
    if os.path.exists(baoyu_dir):
        # On Windows, we need shell=True or finding the absolute path of npx
        html_cmd = f'npx -y bun "{os.path.join(baoyu_dir, "scripts", "main.ts")}" "{output_file}"'
        print(f"🛠️ Running: {html_cmd}")
        res = subprocess.run(html_cmd, capture_output=True, text=True, encoding='utf-8', shell=True)
        if res.returncode == 0:
            print(f"✨ HTML version generated successfully.")
        else:
            print(f"⚠️ HTML generation failed: {res.stderr}\n{res.stdout}")
    else:
        print(f"⚠️ Could not find baoyu-markdown-to-html at {baoyu_dir}")

    print(f"✅ Finished! final output written to {output_file}")

if __name__ == "__main__":
    main()
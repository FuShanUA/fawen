"""
patcher_agent.py

Agent 8: Text-only refinement of final HTML.
Modifies only the text content within tags to avoid re-rendering layout.
"""

import sys
import os
import re

def build_patch_prompt(html_content, instruction):
    prompt = f"""
### ROLE
你是一个极其精准的 HTML 文本修复专家。你的任务是只修改 HTML 中的【文本内容】，绝对不能破坏任何 HTML 标签、内联样式（Style）、类名（Class）或占位符。

### TASK
请根据给出的【修改指令】，对 HTML 中的文字进行微调。

### CONSTRAINTS
- **保持结构不变**：严禁增删任何 HTML 标签或属性。比例：`<p style="...">原本的文字</p>` 只能改为 `<p style="...">修改后的文字</p>`。
- **保留占位符**：保留所有类似于 `MDTOHTMLIMGPH_N` 的占位符和图片链接。
- **只返回代码**：直接输出修改后的完整 HTML，不要有任何解释。

### MODIFICATION INSTRUCTION (修改指令)
{instruction}

### HTML CONTENT
{html_content}

### OUTPUT
直接返回修复后的完整 HTML 内容。
"""
    return prompt

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python patcher_agent.py <html_file> <instruction> [--prompt-only]")
        sys.exit(1)

    html_file = sys.argv[1]
    instruction = sys.argv[2]
    prompt_only = "--prompt-only" in sys.argv

    if not os.path.exists(html_file):
        print(f"Error: File not found {html_file}")
        sys.exit(1)

    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()

    if prompt_only:
        print(build_patch_prompt(content, instruction))
    else:
        # Currently, the orchestrator handles the LLM flow via the user or a subagent.
        # This agent primarily serves to generate the context-aware prompt.
        print("Patcher Agent: Ready to refine HTML.")
        print(f"Target: {html_file}")
        print(f"Instruction: {instruction}")
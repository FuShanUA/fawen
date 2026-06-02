"""
aggregator_agent.py

Agent 8: Handles aggregation of multiple sources (PDFs, URLs, texts) and user thoughts.
Generates the prompt for the Aggregator LLM to create a single cohesive article.
"""

import sys
from common_utils import load_skill_content, load_readme_content, load_writing_style, deterministic_scrub, load_unslop_rules, build_de_ai_protocol

def build_aggregation_prompt(source_text, thoughts="", style="intellectual", intent="面向国内 B 端读者提供数据管理领域的深度见解，强调落地实践。", unslop_domain=""):
    writing_style, _ = load_writing_style()
    verbalizer_rules = load_readme_content("verbalizer")
    de_ai_protocol = build_de_ai_protocol(unslop_domain)

    prompt = f"""
### ROLE
你是一名数据治理与前沿科技领域的资深研究员和专栏作家。你不仅对全球技术趋势有深刻见解，更擅长将极其庞杂、碎片化的多源信息进行提炼、重构和批判性思考。

### TASK
请根据下方提供的【多篇参考原文/素材】以及我的【核心思考与切入点】，撰写一篇逻辑严密、洞察深刻的全新文章。这不是简单的拼凑，而是“融会贯通”。

### INTENT (写作意图)
{intent}

### AGGREGATION PHILOSOPHY (聚合心法)
1. **主轴驱动**：以我的【核心思考与切入点】为主线，将参考材料作为证据、案例或背景来支撑主线逻辑。如果参考材料之间存在冲突，请客观分析或提取其中最有价值的部分。
2. **重构语境**：抛弃原文各自的散兵游勇结构，建立一个自洽的全新文章骨架。向读者清晰阐述：这是关于什么领域的核心洞察？结合国内环境有何启发？
3. **平等的对话姿态 (No AI Slop)**：避免使用预设的权威立场，不要使用华而不实的常见 AI 套话。以平等的姿态讲述事实、陈述观点，并可恰当加入建设性和批判性的独立思考。

### ARTICLE STRUCTURE & FORMATTING
1. **结构化页头**：文章开头必须包含以下格式的标题和作者信息：
    # [以核心思考为落脚点的中文新标题]
    作者：数据治理研究院
2. **简明导读 (The Lead-in)**：在标题下方，用 **2到3句话** 概括本文讲述了什么核心内容，最后再加上一句具有吸引力的“不容错过”或“值得一读”的促读提示。
   - **格式强制要求**：该导读必须使用 Markdown 引用语法，以 `> **导读：**` 开头。
3. **深度提炼正文 (Synthesized Body)**：
    - 按逻辑主题（如核心挑战、演进路径、关键案例等）组织小标题和内容，自然融入各篇参考素材中的精华数据和观点。
    - **按需保留图像**：如果你觉得参考素材中的图像（Markdown 图片标签）能强有力地支撑新的正文语境，请将其插入合适的位置。保留的图片必须保持原始链接不变。请舍弃不必要或重复的插图。
    - 绝对禁止使用“不再是……而是……”或“不是……而是……”大跨度强行制造转折。
4. **专家风范 (Expert Style)**：
    - **应用积累模式 (Persona Core)**：遵循以下专栏作家风格要点（禁止浮夸词汇及冒号标题体）。【注意：由于本次任务是多源素材聚合而非英翻中，如果以下风格规则中包含关于“英翻中”的具体约束，请直接忽略，仅保留核心行文风格和“去AI味”要求】：
{writing_style[:1500]}
5. **结尾总结 (The Three-Part Finale)**：
    文章最后必须包含以下三个板块：
    - **【核心观点聚合】**：用 Bullet Points 总结全文最核心的 takeaways。
    - **【素材高光时刻】**：提取参考材料中最有价值的 3-5 句话，作为金句展示。
    - **【落地启示】**：针对国内读者提出具体、可操作的落地建议。
6. **结构化页脚**：
    在全文最后，使用独立的一行添加：
    *作者简介：数据治理研究院。文章基于多份最新前沿资料聚合梳理而成。*

{de_ai_protocol}
### MY CORE THOUGHTS (核心思考与切入点)
{thoughts if thoughts else "（无额外思考，请直接根据多篇参考材料提炼出有价值的行业干货）"}

### REFERENCE MATERIALS (参考原文/素材)
【请注意：以下可能是来自多个 PDF、网页或文本的聚合内容】
{source_text}

### OUTPUT
直接返回重构、聚合后的高质量 Markdown 内容。
"""
    return prompt

def run_scrub(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    scrubbed = deterministic_scrub(text)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(scrubbed)
    print(f"Aggregator Agent: Deterministic scrub applied to {filepath}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python aggregator_agent.py <file> [--prompt-only] [--thoughts '...'] [--style intellectual] [--intent '...']")
        sys.exit(1)

    input_file = sys.argv[1]
    prompt_only = False
    thoughts = ""
    style = "intellectual"
    unslop_domain = ""
    intent = "面向国内 B 端读者提供数据管理领域的深度见解，强调落地实践。"

    for i in range(2, len(sys.argv)):
        if sys.argv[i] == "--prompt-only":
            prompt_only = True
        elif sys.argv[i] == "--thoughts" and i + 1 < len(sys.argv):
            thoughts = sys.argv[i+1]
        elif sys.argv[i] == "--style" and i + 1 < len(sys.argv):
            style = sys.argv[i+1]
        elif sys.argv[i] == "--unslop" and i + 1 < len(sys.argv):
            unslop_domain = sys.argv[i+1]
        elif sys.argv[i] == "--intent" and i + 1 < len(sys.argv):
            intent = sys.argv[i+1]

    if prompt_only:
        with open(input_file, 'r', encoding='utf-8') as f:
            text = f.read()
        print(build_aggregation_prompt(text, thoughts, style, intent, unslop_domain))
    else:
        run_scrub(input_file)
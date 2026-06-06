"""
lead_in_agent.py [Postfdry 2.0 Agent]

Generates a non-AI-flavored Lead-in (导读) based on the FULL text of an article.
Strictly avoids clichés and robotic patterns.
"""

import sys
import os

# Add common to path to load llm_utils
common_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common'))
if common_dir not in sys.path:
    sys.path.append(common_dir)

from llm_utils import get_client

def build_lead_in_prompt(full_text, thoughts="", type_selection="trend", narrative_theme="", author=""):
    """
    Builds a prompt for the Lead-in Agent.
    Requires full text to ensure accuracy.
    """
    has_theme = bool(narrative_theme and narrative_theme != "无特定主题")
    data_governance_keywords = ["数据要素", "数据资产", "数据治理", "DCMM", "数据空间", "数据管理", "数据开发", "数据要素市场"]
    is_data_gov = any(kw in narrative_theme for kw in data_governance_keywords) if has_theme else False
    
    if author:
        institute_name = author
        institute_eng = "Research Institute"
    else:
        institute_name = "数据治理研究院" if is_data_gov else "前沿科技智库"
        institute_eng = "Data Governance Research Institute" if is_data_gov else "Tech and Frontier Think Tank"

    if has_theme:
        theme_section = f"""### NARRATIVE THEME (叙事对齐主题)
本次解读文章的叙事主题/业务主题设定为：【{narrative_theme}】。
在撰写导读时，请遵循以下原则：
1. **叙事对齐**：在提炼文章核心痛点与价值时，应以该业务主题为视角和背景框架进行审视和引导。
2. **拒绝硬关联与词汇堆砌**：
   - 本次设定包含一组主题候选词：【{narrative_theme}】。你必须根据文章具体内容，**仅选择其中与原文最契合的 1-2 个核心概念词/主题进行自然融入**。严禁将这组候选词全部堆砌、罗列到导读中。
   - 如果本篇文章的内容与选中的候选词有较强或中等的相关性，请在导读中自然地引导到该主题或其相关延伸探讨上，以便为全文的解读定下基调。
   - 如果本篇文章的内容与该业务主题候选词完全无关或关联极弱，**切勿生拉硬拽、生硬联系**。此时你应当专注于文章本身的核心洞察，不提及该业务主题，或者仅用极度自然、微弱的一句话过渡，切忌强行关联。"""
    else:
        theme_section = """### NARRATIVE THEME (叙事对齐主题)
本次解读没有特定的叙事主题限制。你应当完全专注于文章本身的核心洞察、痛点与价值，平实客观地提炼出文章本身的最核心内容。"""

    prompt = f"""
### ROLE
你是一名在大厂深耕多年的首席研究员 (Chief Researcher)。
作为这篇文章的深度解读作者，你需要在文章开头撰写一段具有洞察力的“导读”。
你的语气专业、客观、犀利，不带任何推销感。你是在以专家的身份，指出文章所揭示的核心行业痛点与价值。

### TASK
请阅读全文，并写一段 2-3 句话 of 导读（Lead-in）。
导读的目标是：根据文章的实际情况，结合编辑输入的思想进行言简意赅的动态提炼。直接、生动地抽象出文章的核心基本要义。既要避免面面俱到，又要发掘出一两个核心阅读兴趣点（注意：绝对不要使用刻意煽情或说教的 AI Slop Hooks，也不要给管理者上课或下指导棋，不要以“管理者需...”、“高管应当...”、“企业必须...”等高高在上的教导、说教语气给人上课）。

{theme_section}

### CONSTRAINTS (必读规则)
1. **禁用 AI 常用废话与特定结构**：
   - 绝对禁止出现“值得一读”、“深度解读”、“本文探讨了”、“不仅仅是...更是”、“戳破”、“击碎”、“交底”、“一文读懂”等。
   - **绝对禁止使用结构**：“不是……而是……”、“不再是……而是……”（严禁使用此类句式强行制造反差或升华）。
   - **绝对禁止使用夸张与情绪化词汇**：“残酷的”、“冷酷的”（严禁使用此类带有强烈主观夸张色彩的词，保持客观中立）。
   - **绝对禁止使用黑话俗语**：“拆一层”（如“把这个逻辑拆一层”）、“问得很直接”、“深挖”等。
2. **拒绝元叙事视角**：禁止以“推荐大家读这篇文章”或“作者认为”开头。直接进入事实描述。
3. **角色一致性**：必须保持首席研究员的专家视角。语气要平实、硬核、去 PPT 化，杜绝说教与居高临下的“爹味”。
4. **executive-friendly**：确保 CXO 们一读就懂，不讲虚头巴脑的战略大词。
5. **拒绝冒号模板与说教套路**：导读正文中严禁使用 `短语：解释` 的结构。同时，严禁使用任何生硬说教的句式（例如“管理者需停止重度定制”这种说教不是洞察，而是不受欢迎的说教）。如果需要提出行动方向，必须以冷静、客观的第三人称叙述（如“这表明企业在...时应聚焦于...”、“这提示行业需要重新评估...”）进行推演，语气要平等、客观、言之有物，不能高高在上。
6. **破折号限制**：严禁出现英文连续减号 `--` 或中文双破折号 `——` 组成的双横线。如需解释或强调，请统一使用利落的单破折号 `—`（或单横线），或使用逗号代替，以保持排版干练。
7. **业务关联**：{"结合以下 thoughts 进行关联：" + thoughts if thoughts else ""}

### FULL TEXT
{full_text}

### OUTPUT REQUIREMENTS
- 仅输出 2-3 句话的导读。
- 必须使用 Markdown 引用语法，以 `> **导读：**` 开头。
- 直接输出结果，不要有任何额外对话。
"""
    return prompt

def generate_lead_in(text, thoughts="", project_root=None, model_name="gemini-3-flash-preview", type_selection="trend", narrative_theme="", author=""):
    """Generates the lead-in via LLM."""
    # If text is too long for the model, we can truncate a bit,
    # but Gemini 1.5 Pro/3.1 Pro has large window.
    # We'll take up to 30,000 characters for safety.
    context = text[:30000]

    prompt = build_lead_in_prompt(context, thoughts, type_selection=type_selection, narrative_theme=narrative_theme, author=author)

    # Save prompt for audit
    try:
        from common_utils import log_prompt
        log_prompt(None, "03_leadin", prompt, project_root=project_root)
    except: pass

    print(f"  [Agent] Generating Lead-in from full text [Model: {model_name}]...")
    client = get_client()

    lead_in = client.generate_content(prompt, model_name=model_name)
    return lead_in.strip()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lead_in_agent.py <file> [--thoughts '...']")
        sys.exit(1)

    input_file = sys.argv[1]
    thoughts = ""
    if "--thoughts" in sys.argv:
        idx = sys.argv.index("--thoughts")
        if idx + 1 < len(sys.argv):
            thoughts = sys.argv[idx+1]

    with open(input_file, 'r', encoding='utf-8') as f:
        print(generate_lead_in(f.read(), thoughts))
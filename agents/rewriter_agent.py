import sys
import os
import argparse
import re

# Add common to path to load llm_utils
common_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common'))
if common_dir not in sys.path:
    sys.path.append(common_dir)

from llm_utils import get_client

# Add agents to path (Hardened absolute path)
POSTFDRY_ROOT = r"/Users/shanfu/cc/Library/Tools/postfdry"
agents_dir = os.path.join(POSTFDRY_ROOT, "agents")
if agents_dir not in sys.path:
    sys.path.insert(0, agents_dir)

try:
    import common_utils
    from common_utils import deterministic_scrub, build_de_ai_protocol, log_prompt, extract_clean_body
except ImportError:
    import importlib.util
    spec = importlib.util.spec_from_file_location("common_utils", os.path.join(agents_dir, "common_utils.py"))
    common_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common_utils)
    deterministic_scrub = common_utils.deterministic_scrub
    build_de_ai_protocol = common_utils.build_de_ai_protocol
    log_prompt = common_utils.log_prompt
    extract_clean_body = common_utils.extract_clean_body

def build_rewriting_prompt(source_text, thoughts="", type_selection="trend", style="formal", unslop_domain="数据治理", target_title=""):
    """
    Constructs the prompt for the rewriting stage.
    """
    is_custom = (style == "custom")
    de_ai_protocol = build_de_ai_protocol(unslop_domain, custom_style=is_custom)

    # Define Tones and Structures based on selection
    type_map = {
        "paper": {"tone": "干练、务实、直击痛点", "focus": "核心事实、实施难点、落地建议"},
        "trend": {"tone": "前瞻、大白话、不讲虚头巴脑的宏大叙事", "focus": "趋势带来的实际影响、钱/风险在哪里、该做什么"},
        "policy": {"tone": "稳重、批判性、实战视角", "focus": "合规成本、执行边界、实操建议"},
        "product": {"tone": "硬核、场景化、去PPT味", "focus": "解决了什么具体麻烦、架构如何支撑业务、不吹牛"},
        "standard": {"tone": "实用、一读就懂、执行手册感", "focus": "落地步骤、避坑指南、资源投入"}
    }

    config = type_map.get(type_selection, type_map["trend"])

    # Title logic: Use confirmed target_title if available, else invent one
    title_instruction = f"文章开头直接以 `# {target_title}` 开头（**你必须严格使用此标题，严禁修改或拟定新标题**）。" if target_title else "文章开头直接以 `# 标题` 开头（标题要新拟，具有行业深度）。"

    prompt = f"""
### ROLE
你是一名在大厂深耕多年、现任【AI数据治理研究院】的【首席研究员】(Chief Researcher)。
你极其反感为了显得专业而堆砌黑话的“咨询顾问感”，更讨厌脱离业务事实、强行上价值、硬蹭趋势的浮夸文字。

### TASK
请基于原文的核心事实（Facts），生成一篇具有独立深度的“解读版”文章。
你的目标是：将海外的前沿研究，转化为国内数据从业者（特别是关注 DCMM 和数据要素市场的群体）能够一读就懂、甚至能直接拿去用的实战参考。

### CONSTRAINTS (必读 Hard Constraints)
1. **拒绝 AI 翻译腔 (CRITICAL)**：
   - **绝对禁止使用破折号（—— 或 -）来进行名词解释或强行转折**。
   - **绝对禁止使用**：“戳破”、“一语道破”、“惊现”、“交底”、“彻底打通”、“击碎”、“重磅”、“颠覆”、“业务底盘”等。
2. **读者视角、人称规范与防说教 (CRITICAL)**：
   - 不要像 AI 一样在做“总结”，要像专家在面对面交流。少讲大道理，多讲具体的业务场景。
   - **严禁说教**：绝对禁止采用居高临下、居高临下的态度对读者进行生硬说教（例如“管理者需停止重度定制”、“高管应当重新审视技术逻辑”这类说教是 AI 典型废话，而不是真知灼见）。
   - **视角中立**：如果探讨技术决策或投资，必须以冷静、客观的第三人称叙述（如“企业采购重型平台的核心考量是...”、“平台建设需要建立在...之上”）进行推演。严格防范“你应该在底座上...”这种将读者作为第二人称的指代错乱、人称错乱问题。确保整篇文章是在分享客观研究洞察，而不是单向的训导与灌输。
3. **视觉布局锚点与图片处理 (Visual Assets - CRITICAL)**：
   - **保留原文图片**：你必须保留原文（翻译稿）中出现的所有图片（如 `![alt](path)`）。
   - **封面图 (COVER)**：你必须在文章 H1 标题正下方的第一个换行处，插入：`[AI_GEN_IMG: COVER_METAPHOR | 封面图逻辑描述]`。独占一行。
   - **逻辑信息图 (INFOGRAPHIC) 约束（高优先级）**：
     - **检测已有图片**：请仔细扫描原文中是否已有插图（以 `![alt](path)` 形式存在）。
     - **非强制生成**：最终文章的底线要求是【必须至少有一张插图】（不论是已有的还是新生成的）。**如果原文已经包含有意义的插图，除非必要，否则【绝对不要】强行插入新的 `[AI_GEN_IMG]`。** 只有在原文没有任何插图时，才【必须】在最需要直观理解的局部复杂逻辑段落后插入至少一张。
     - **严禁主题冲突与重复**：新插入的插图**所表达的逻辑概念和画面，绝对不能与文章中已有的原文图片发生任何功能或含义上的冲突、重复或堆砌**。
     - **聚焦微观局部，严禁覆盖全文**：逻辑信息图应只是局部的补充。**它必须聚焦在某一个局部的微观拓扑结构、演进过程或关键概念对比上，切实起到辅助读者理解该复杂段落的作用。严禁让它去宏观覆盖整篇文章的大意**（因为整篇文章的宏观视觉表达已由上面的封面图 COVER 承担了），从而避免与封面图（头图）功能无法区分。
     - **插入格式**：若符合上述条件，请在被插图的复杂逻辑段落后独占一行插入：`[AI_GEN_IMG: 类型 | 核心逻辑提炼 | 关键事实数据 | 标注标签]`。类型可选：对比、因果、过程、并列、层级。
4. **Layout 规范**：
   - {title_instruction}
   - 标题下方紧跟一行 `- 作者：AI数据治理研究院`。
   - 严禁输出任何 YAML Frontmatter。

### ARTICLE TYPE: {type_selection.upper()}
- **口吻要求**：{config['tone']}
- **重构侧重**：{config['focus']}

### ENDING: 总结 (Flexible Conclusion)
不要进行机械的“板块化”总结。如果需要为最后一部分设置标题，【绝对不要】以“终局思考”、“实战思考”、“写在最后”或“实战视角的思考”这类虚空套话命名，而是应该使用：“总结：[具体的核心提炼]”的句式（例如，若是关于混合云，则可以使用“总结：混合云下的技术收敛”；若是关于平台采购，则使用“总结：回归系统合规与稳定性”）。请直接陈述实战层面的观点，结尾严禁出现强行升华。

{de_ai_protocol}

### USER THOUGHTS (译者的思想输入)
{thoughts if thoughts else "（暂无额外指令）"}

### INPUT TEXT (翻译稿正文)
{source_text}

### OUTPUT REQUIREMENTS
- 仅返回重构后的 Markdown 内容。
- 不要包含任何解释或开场白。
"""
    return prompt

def run_atomic_rewrite(input_file, thoughts="", type_selection="trend", unslop_domain="数据治理", style="formal", wip_dir=None, model_name="gemini-3-flash-preview", target_title=""):
    """Reads input and generates rewritten output."""
    with open(input_file, 'r', encoding='utf-8') as f:
        source_text = f.read()

    # Clean the translated body to strip any newsletter ad blocks/promotions before rewriting
    source_text = extract_clean_body(source_text)

    prompt = build_rewriting_prompt(source_text, thoughts, type_selection, style, unslop_domain, target_title=target_title)

    # Save prompt for audit
    log_prompt(input_file, "02_rewrite", prompt, project_root=os.path.dirname(wip_dir) if wip_dir else None)

    print(f"  [Skill] Rewriting as '{type_selection}' type via LLM [Model: {model_name}]...")
    client = get_client()

    rewritten_text = client.generate_content(prompt, model_name=model_name)

    # Final mechanical scrubbing
    rewritten_text = deterministic_scrub(rewritten_text)

    output_file = input_file.replace(".md", "_rewritten.md")
    if input_file == output_file: output_file += ".out.md"

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(rewritten_text)

    print(f"  [Skill] Atomic rewriting complete: {os.path.basename(output_file)}")
    return output_file

def run(input_file, project_root=None, style="trend", unslop_domain="数据治理", thoughts="", target_title="", model_name="gemini-3-flash-preview"):
    """Alias for interpret_workflow integration."""
    wip_dir = os.path.join(project_root, "wip") if project_root else None
    return run_atomic_rewrite(input_file, thoughts=thoughts, type_selection=style, unslop_domain=unslop_domain, wip_dir=wip_dir, model_name=model_name, target_title=target_title)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Postfdry 2.0 Atomic Rewriting Skill")
    parser.add_argument("input", help="Source Chinese Markdown file")
    parser.add_argument("--thoughts", default="", help="User's thoughts/direction for rewrite")
    parser.add_argument("--type", default="trend", choices=["paper", "trend", "policy", "product", "standard"], help="Article type selection")
    parser.add_argument("--unslop", default="数据治理", help="Unslop domain domain")
    parser.add_argument("--target-title", default="", help="Fixed title to use")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Model name")

    args = parser.parse_args()
    run_atomic_rewrite(args.input, args.thoughts, args.type, args.unslop, target_title=args.target_title, model_name=args.model)
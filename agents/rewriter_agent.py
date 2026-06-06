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
POSTFDRY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
agents_dir = os.path.join(POSTFDRY_ROOT, "agents")
if agents_dir not in sys.path:
    sys.path.insert(0, agents_dir)

try:
    import common_utils
    from common_utils import deterministic_scrub, build_de_ai_protocol, log_prompt, extract_clean_body, load_narrative_logics
except ImportError:
    import importlib.util
    spec = importlib.util.spec_from_file_location("common_utils", os.path.join(agents_dir, "common_utils.py"))
    common_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common_utils)
    deterministic_scrub = common_utils.deterministic_scrub
    build_de_ai_protocol = common_utils.build_de_ai_protocol
    log_prompt = common_utils.log_prompt
    extract_clean_body = common_utils.extract_clean_body
    load_narrative_logics = getattr(common_utils, 'load_narrative_logics', None)

def build_rewriting_prompt(source_text, thoughts="", type_selection="trend", style="formal", unslop_domain="数据治理", target_title="", summary_mode="preset", summary_prompt="", generate_summary=None, narrative_theme="", author=""):
    """
    Constructs the prompt for the rewriting stage.
    """
    if generate_summary is not None:
        summary_mode = "explicit" if generate_summary else "none"

    # Backward compatibility mappings
    if summary_mode == "preset":
        summary_mode = "explicit"
    elif summary_mode == "auto":
        summary_mode = "implicit"

    has_theme = bool(narrative_theme and narrative_theme != "无特定主题")

    # Check if this theme/text/thoughts is about data governance/elements
    data_governance_keywords = ["数据要素", "数据资产", "数据治理", "DCMM", "数据空间", "数据管理", "数据开发", "数据要素市场"]
    is_data_gov = any(kw in narrative_theme for kw in data_governance_keywords) if has_theme else False

    if not is_data_gov and unslop_domain == "中国政企特色数据治理":
        unslop_domain = "前沿趋势与商业实战"

    is_custom = True if (summary_mode in ["explicit", "implicit"] and summary_prompt) else False
    de_ai_protocol = build_de_ai_protocol(unslop_domain, custom_style=is_custom)

    # Dynamic loading of narrative logics
    logics = load_narrative_logics() if load_narrative_logics else {}
    config = logics.get(type_selection)
    if not config:
        config = logics.get("trend", {
            "tone": "前瞻、大白话、不讲虚头巴脑的宏大叙事",
            "focus": "趋势带来的实际影响、钱/风险在哪里、该做什么",
            "summary_guide": "提炼趋势演进的关键路径，并针对未来布局给出具体的行动建议。"
        })

    # Title logic: Use confirmed target_title if available, else invent one
    title_instruction = f"文章开头直接以 `# {target_title}` 开头（**你必须严格使用此标题，严禁修改或拟定新标题**）。" if target_title else "文章开头直接以 `# 标题` 开头（标题要新拟，具有行业深度）。"

    # Ending section prompt
    if summary_mode == "explicit":
        title_to_use = target_title if target_title else "文章主标题"
        guide = config.get("summary_guide", "结合所选叙事逻辑的侧重点进行实战层面的内容提炼，并针对未来布局给出具体的行动建议。")
        if summary_prompt:
            instruction_text = summary_prompt.strip()
        else:
            theme_rel = f"\n- 如有与【{narrative_theme}】相关，可以稍加提及，但不要硬关联。若叙事主题与本文内容高度相关则可以展开多写，若无直接关联则用一两句话略带提及即可，切忌强行关联、生硬升华。" if has_theme else ""
            instruction_text = f"请在文章最后生成一个显式总结板块，标题为“### 总结：{title_to_use}”，用两三个自然段包含以下内容，不要用僵化的小标题-内容方式，而是夹叙夹议地进行总结：\n- 全文核心观点或洞察，直白表达，严禁虚空套话或强行升华。\n- 结合此叙事逻辑的侧重点（{config['focus']}）与指南（{guide}）进行提炼。{theme_rel}\n- 包含两三条清晰的、可指导行动的具体建议。"
        ending_instruction = f"""### ENDING: 显式总结 (Explicit Conclusion)
{instruction_text}"""
    elif summary_mode == "implicit":
        guide = config.get("summary_guide", "结合所选叙事逻辑的侧重点进行实战层面的内容提炼，并简单表达编者的感悟与实战思考。")
        if summary_prompt:
            instruction_text = summary_prompt.strip()
        else:
            theme_rel = f"若涉及【{narrative_theme}】可适当提及，但不要生硬升华；如果与本文主题无直接关联，则用一两句话略带提及即可，切忌强行关联、生硬升华。" if has_theme else ""
            instruction_text = f"请在文章末尾自然生成两三个段落进行收尾，不要设置任何标题。内容要求自然对全文进行总结提炼，表达编者的感悟与实战思考。行文要求夹叙夹议，自然过渡，严禁说教。结合此叙事逻辑的侧重点（{config['focus']}）与指南（{guide}）进行隐式收尾。{theme_rel}"
        ending_instruction = f"""### ENDING: 隐式总结 (Implicit Conclusion)
{instruction_text}"""
    else:  # none
        ending_instruction = """### ENDING (Flexible Ending)
【绝对不要】在文章末尾添加任何总结、结尾陈述、升华段落或总结标题。文章重构到正文核心内容结束即可，不要进行任何机械的“板块化”总结或收尾，直接自然结束。"""

    institute_name = author if author else "数据治理研究院"

    if has_theme:
        narrative_section = f"""### NARRATIVE THEME (叙事对齐主题)
本次解读文章的叙事主题/业务主题设定为：【{narrative_theme}】。
在重构正文内容时，请遵循以下原则：
1. **编辑思路绝对优先 (CRITICAL PRIORITY)**：译者的【编辑思路/思想输入 (USER THOUGHTS)】是整篇文章重构的最高优先原则。任何业务主题词的对齐都必须在【不偏离、不违背、不淡化】编辑思路的前提下进行。如果编辑思路的导向与业务主题词有任何侧重不同，必须无条件绝对优先服从编辑思路，严禁为了强行堆砌或迎合业务主题词而偏离编辑思路。
2. **选择性对齐**：请以该业务主题为视角和背景框架，审视原文的案例、技术或观点，并自然地引导到该主题的相关探讨上。
3. **拒绝生搬硬套（防生硬硬蹭与词汇堆砌）**：
   - 本次设定包含一组主题候选词：【{narrative_theme}】。你必须根据原文的具体技术与业务内容，**仅选择其中与原文关联度最高、最契合的 1-2 个核心概念词/主题进行自然融合**。严禁将上面列出的所有主题词一股脑地堆砌、罗列到文章中。
   - 如果原文内容与选中的候选词有较强或中等的相关性，请在重构正文时融入该主题的视角，使论述更加贴合国内的实际需求与商业背景。
   - 如果原文内容与该业务主题候选词完全无关或关联极弱，**切忌生拉硬拽**。你应当优先尊重原文的核心事实与逻辑，保持独立客观，不生硬凑数或强行关联，只需用极其自然的方式顺承，或者完全忽略该主题，以确保解读逻辑通顺、去“AI味”且真实可信。"""
    else:
        narrative_section = ""

    prompt = f"""
### ROLE
你是一名在大厂深耕多年的首席研究员 (Chief Researcher)。
你极其反感为了显得专业而堆砌黑话的“咨询顾问感”，更讨厌脱离业务事实、强行上价值、硬蹭趋势的浮夸文字。

### TASK
请基于原文的核心事实（Facts），生成一篇具有独立深度的“解读版”文章。
你的目标是：将海外的前沿研究，转化为国内科技与商业领域从业者能够一读就懂、甚至能直接拿去用的实战参考。

### CONSTRAINTS (必读 Hard Constraints)
1. **拒绝 AI 翻译腔 (CRITICAL)**：
   - **绝对禁止使用破折号（—— 或 -）来进行名词解释或强行转折**。
   - **绝对禁止使用结构与词汇**：
     * 禁用结构：“不是……而是……”、“不再是……而是……”（严禁使用此类句式强行制造反差或升华，必须平实地陈述事实与观点）。
     * 禁用夸张与情绪化词汇：“残酷的”、“冷酷的”（严禁使用此类带有强烈主观夸张色彩的词，保持客观中立）。
     * 禁用互联网/AI黑话词：“拆一层”（如“把这个逻辑拆一层”）、“问得很直接”、“深挖”等。
     * 绝对禁止使用：“戳破”、“一语道破”、“惊现”、“交底”、“彻底打通”、“击碎”、“重磅”、“颠覆”、“业务底盘”等。
2. **读者视角、人称规范与防说教 (CRITICAL)**：
   - 不要像 AI 一样在做“总结”，要像专家在面对面交流。少讲大道理，多讲具体的业务场景。
   - **严禁说教（防居高临下的爹味）**：绝对禁止采用居高临下的态度对读者进行生硬说教（例如“管理者需停止重度定制”、“高管应当重新审视技术逻辑”这类说教是 AI 典型废话，而不是真知灼见）。
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
   - 标题下方紧跟一行 `- 作者：{institute_name}`.
   - 严禁输出 any YAML Frontmatter.
5. **绝对禁止照抄或包含翻译稿原文**：你只需输出你重构、解读后的中文文章，**绝对不要在你的输出中包含、保留、照抄翻译稿原文的全文或任何大段的翻译正文**。直接输出解读正文，不要有任何过渡性引用原文的动作。

{narrative_section}

### ARTICLE TYPE: {type_selection.upper()}
- **口吻要求**：{config['tone']}
- **重构侧重**：{config['focus']}

{ending_instruction}

{de_ai_protocol}

### USER THOUGHTS (编辑思路 / 译者思想输入 - 最高优先级 ✨)
【特别说明】：这是本篇重构文章的核心灵魂与最高优先原则。你必须围绕这段思路所指定的方向进行深度解读，并将业务主题词融合在它的框架之下：
{thoughts if thoughts else "（暂无额外指令）"}

### INPUT TEXT (翻译稿正文)
{source_text}

### OUTPUT REQUIREMENTS
- 仅返回重构后的 Markdown 内容。
- 不要包含任何解释或开场白。
"""
    return prompt

def run_atomic_rewrite(input_file, thoughts="", type_selection="trend", unslop_domain="数据治理", style="formal", wip_dir=None, model_name="gemini-3-flash-preview", target_title="", summary_mode="preset", summary_prompt="", generate_summary=None, narrative_theme="", author=""):
    """Reads input and generates rewritten output."""
    with open(input_file, 'r', encoding='utf-8') as f:
        source_text = f.read()

    # Clean the translated body to strip any newsletter ad blocks/promotions before rewriting
    source_text = extract_clean_body(source_text)

    prompt = build_rewriting_prompt(source_text, thoughts, type_selection, style, unslop_domain, target_title=target_title, summary_mode=summary_mode, summary_prompt=summary_prompt, generate_summary=generate_summary, narrative_theme=narrative_theme, author=author)

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

def run(input_file, project_root=None, style="trend", unslop_domain="数据治理", thoughts="", target_title="", model_name="gemini-3-flash-preview", summary_mode="preset", summary_prompt="", generate_summary=None, narrative_theme="", author=""):
    """Alias for interpret_workflow integration."""
    wip_dir = os.path.join(project_root, "wip") if project_root else None
    return run_atomic_rewrite(input_file, thoughts=thoughts, type_selection=style, unslop_domain=unslop_domain, wip_dir=wip_dir, model_name=model_name, target_title=target_title, summary_mode=summary_mode, summary_prompt=summary_prompt, generate_summary=generate_summary, narrative_theme=narrative_theme, author=author)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Postfdry 2.0 Atomic Rewriting Skill")
    parser.add_argument("input", help="Source Chinese Markdown file")
    parser.add_argument("--thoughts", default="", help="User's thoughts/direction for rewrite")
    parser.add_argument("--type", default="trend", choices=["paper", "trend", "policy", "product", "standard"], help="Article type selection")
    parser.add_argument("--unslop", default="数据治理", help="Unslop domain domain")
    parser.add_argument("--target-title", default="", help="Fixed title to use")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Model name")
    parser.add_argument("--skip-summary", action="store_true", help="Skip generating summary ending")
    parser.add_argument("--summary-mode", default="explicit", choices=["explicit", "implicit", "none", "preset", "auto"], help="Summary mode")
    parser.add_argument("--summary-prompt", default="", help="Preset summary prompt")
    parser.add_argument("--narrative-theme", default="", help="Narrative/business theme keywords")
    parser.add_argument("--author", default="", help="Author signature override")

    args = parser.parse_args()
    sum_mode = args.summary_mode
    if args.skip_summary:
        sum_mode = "none"
    run_atomic_rewrite(args.input, args.thoughts, args.type, args.unslop, target_title=args.target_title, model_name=args.model, summary_mode=sum_mode, summary_prompt=args.summary_prompt, narrative_theme=args.narrative_theme, author=args.author)
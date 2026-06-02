"""
translator_agent.py [Postfdry 2.0 Skill]

Atomic Translation Skill: Translates English MD/Text to Chinese.
Focus: Accuracy (信), Native Flow (达), Terminology Consistency (terms.yml).
De-AI: Built-in Humanizer-ZH (去翻译腔).
"""

import sys
import os
import subprocess
import argparse
import glob
import re
import shutil

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
    from common_utils import deterministic_scrub, build_de_ai_protocol
except ImportError:
    import importlib.util
    spec = importlib.util.spec_from_file_location("common_utils", os.path.join(agents_dir, "common_utils.py"))
    common_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common_utils)
    deterministic_scrub = common_utils.deterministic_scrub
    build_de_ai_protocol = common_utils.build_de_ai_protocol

def build_translation_prompt(source_text, style="formal", unslop_domain=""):
    """
    Builds an atomic translation prompt.
    Focus is strictly on faithfulness and native phrasing.
    """
    is_custom = (style == "custom")
    de_ai_protocol = build_de_ai_protocol(unslop_domain, custom_style=is_custom)

    # NEW: Direct load to avoid parameter passing drift
    from common_utils import load_terms
    terms_xml = load_terms()

    prompt = f"""
### ROLE
你是一名深耕数据治理（Data Governance）多年的资深技术专家和顶级翻译，在大厂负责 DCMM 落地和数据资产管理。你追求“信、达、雅”，不仅保证技术事实 100% 准确，更能将枯燥的英文专业术语转换为地道、专业的中文行业表达。
你的翻译风格：严谨、专业、去 AI 味。

### CONSTRAINTS (必读规则 - MANDATORY)
1. **内容完整性 (Content Integrity - CRITICAL)**:
   - **严禁漏翻**：原文中可能包含由 `---` 分隔的多个章节。你**必须**翻译每一个章节，严禁跳过、严禁摘要化、严禁选择性翻译。
   - **1:1 对应**：每一段落、每一标题都必须在译文中找到对应，确保信息 100% 传递。

2. **术语一致性 (Terminology Consistency - MANDATORY)**：
   你必须严格遵守以下提供的术语规范。如果原文中出现了术语表中的词汇，**必须**使用指定的中文翻译，严禁自由发挥或使用同义词。

<TERMINOLOGY>
{terms_xml}
</TERMINOLOGY>

3. **去翻译腔 (Humanizer)**：打破英文句式，采用灵活的语序，避免“被、当...时、不可或缺”等典型的中式英语结构。
4. **实体与标题翻译保护 (Entity & Title Translation - CRITICAL)**：
   - **翻译引号内容**：原文中出现在引号 `""` 或 `''` 内的报告名称、工具名、项目名必须**翻译为地道的中文**，并完整保留其文字意义。
   - **书名号化处理**：如果是报告、书籍、白皮书或博文标题，必须将其转换为中文书名号格式 `《中文翻译后的标题》`。如果是普通名词或工具名，则保留为纯文本。
   - **链接降级**：原文中的 Markdown 链接 `[标题内容](URL)` 必须转换为纯文字。**绝对禁止保留英文原名（除非是无法翻译的品牌名或缩写）**，必须将其翻译为中文并根据上述规则加书名号。
5. **元数据块保护 (Metadata Preservation - CRITICAL)**：
   - **严禁修改 YAML 结构**：Markdown 顶部的 `---` 包围的 YAML Frontmatter 中的 **Key (键名)** 必须保持原文（如 `source:`, `publish_date:`, `author:`），不得翻译成中文或改变缩进。
   - **Value (键值) 处理**：仅翻译 `title:` 后的内容。`source:`、`author:` 等字段如果原文是英文，请保持英文，除非明确知道其官方中文名称。
6. **严禁序号重复**：在翻译列表项时，确保内容中不包含多余的数字序号、字母序号或符号标志，直接利用 Markdown 的列表语法。**绝对禁止**出现类似 `1. 1. 内容`、`2. 2. 内容` 或 `- - 内容` 的双重序号。
7. **图片保留 (Image Preservation - CRITICAL)**：
   - **1:1 复制**：**绝对禁止**修改、移动或遗漏任何图片标签 `![]()` 或 `![alt](url)`。必须在译文对应的位置原样呈现，不得对图片路径做任何改动。
 8. **绝对忠实翻译 (100% Faithful Translation - CRITICAL)**：
    - **绝对禁止自我加戏**：严禁在翻译正文的开头或结尾添加任何原文中不存在的导读、引言、前言、提炼、总结、译者注、译者寄语、感悟或任何多余段落。原来是什么就是什么，直奔正文，保持 1:1 纯净翻译。
 9. **人名处理 (Personal Names)**：
    - **优先级**：严格遵循上述 <TERMINOLOGY> 术语表中的特定译法。
    - **核心人物**：对于文章主要讨论的人物，采用“中文音译 (英文原名)”的格式（仅在正文中首次出现时标注英文），后续仅使用中文音译。
    - **技术/次要人物**：对于文中提及的次要研究员、技术引用或参考文献中的人名，建议**直接保留英文原名**，以确保专业检索的准确性。

{de_ai_protocol}

### STYLE PRESET: {style.upper()}

### INPUT TEXT
{source_text}

### OUTPUT REQUIREMENTS
- 仅输出翻译后的中文正文内容（如果是 chunk 则输出翻译后的正文，如果有 YAML 元数据则输出包含 YAML 的译文）。
- **绝对禁止自我加戏**：严禁在翻译正文的开头或结尾添加任何原文中不存在的导读、引言、前言、提炼、总结、译者注、译者寄语、感悟、评价或任何多余段落。原来是什么就是什么，直奔正文，保持 1:1 纯净翻译。
- **严禁**任何对话，禁止包含任何 Markdown 格式以外的说明文字，直接返回翻译好的内容。
"""
    return prompt

def validate_content(chunk, model_name="gemini-3-flash-preview"):
    """
    Secondary Judgment: Determines if this chunk is core article content or boilerplate.
    Returns: True if core content (KEEP), False if boilerplate (SKIP).
    """
    if len(chunk.strip()) < 50: return True # Don't filter short snippets that might be headers

    client = get_client()
    prompt = f"""
    Analyze this text chunk from an article.
    Is it core article content (arguments, technical data, narrative, or analysis) or is it BOILERPLATE (Author bio, 'Follow me on social media' links, site advertisements, cookie notices, or generic site footers)?

    Reply ONLY with:
    [KEEP] - If it is part of the core article.
    [SKIP] - If it is boilerplate metadata or promotional noise.

    TEXT:
    {chunk}
    """
    res = client.generate_content(prompt, model_name=model_name).strip()
    return "[SKIP]" not in res

def translate_string(s, force_chinese=False, model_name="gemini-3-flash-preview"):
    """单独翻译一个短字符串（如标题）。"""
    from llm_utils import get_client
    s = s.strip()
    if not s: return s

    # Check if string already contains Chinese (using regex for CJK)
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', s))

    # 仅当没有中文、明确为英文、或强制要求中文时翻译
    if not has_chinese or "Extracted from" in s or force_chinese:
        client = get_client()

        # Load terminology to prevent common name/brand translation errors
        terms_xml = ""
        try:
            from common_utils import load_terms
            terms_xml = load_terms()
        except: pass

        prompt = f"""Translate the following article title, author, or source into professional, natural B2B Chinese.
**MANDATORY**: The result must be in Chinese characters.
**GLOSSARY**: If any terms from the list below appear in the source, you MUST use the specified translation (or keep as-is if specified).

<TERMINOLOGY>
{terms_xml}
</TERMINOLOGY>

Return ONLY the translation, no explanation.

Text to translate: {s}"""
        res = client.generate_content(prompt, model_name=model_name).strip().strip('"').strip("'")

        # Validation: If translating from English but result still has no Chinese, it failed
        if not re.search(r'[\u4e00-\u9fff]', res) and not force_chinese:
             print(f"  [Warning] Translation failed to produce Chinese for: {s}")
             return s # Keep original if translation stayed English
        return res
    return s

def run_atomic_translation(input_file, style="formal", unslop_domain="B2B", project_root=None, model_name="gemini-3-flash-preview"):
    """Coordinates chunking and parallel translation of the input file."""
    with open(input_file, 'r', encoding='utf-8') as f:
        source_text = f.read()

    # Determine output directory (matching Baoyu style)
    basename = os.path.splitext(os.path.basename(input_file))[0]
    out_dir = os.path.join(os.path.dirname(os.path.abspath(input_file)), f"{basename}-translated-tmp")

    # Load terminology once for the whole run
    terms_xml = ""
    try:
        from common_utils import load_terms
        terms_xml = load_terms()
        print(f"  [Skill] Loaded {len(terms_xml)} chars of terminology glossary.")
    except Exception as e:
        print(f"  [Warning] Failed to load terms: {e}")

    # Audit logging (Save first chunk's prompt as sample if multiple)
    sample_prompt = build_translation_prompt(source_text[:2000], style, unslop_domain)
    from common_utils import log_prompt
    log_prompt(input_file, "01_translate", sample_prompt, project_root=project_root)

    # Separate metadata header from body to protect it from translation
    # NEW: Use MetadataEngine for robustness
    from common_utils import MetadataEngine
    meta_eng = MetadataEngine(source_text)

    header = ""
    body = source_text

    # Identify if we have a valid metadata block
    has_meta = bool(meta_eng.raw_meta)

    if has_meta:
        # 1. 翻译标题 (Title)
        orig_title = meta_eng.get('title')
        if orig_title:
            print(f"  [Skill] Detecting metadata title: {orig_title}. Translating...")
            translated_title = translate_string(orig_title, model_name=model_name)
            meta_eng.raw_meta['title'] = translated_title
            if 'eng_title' not in meta_eng.raw_meta:
                meta_eng.raw_meta['eng_title'] = orig_title
            print(f"  [Skill] Translated title: {translated_title}")

        # 2. 保持发布机构原样 (Keep Source/Publisher Original)
        # 遵循用户设定：作者和机构一般不翻译，保持专业原汁原味
        pass

        # 3. 规范化日期 (Date)
        orig_date = meta_eng.get('date')
        if orig_date and any(c.isalpha() for c in orig_date): # 如果包含字母（如 April）则翻译
            print(f"  [Skill] Detecting metadata date: {orig_date}. Translating...")
            translated_date = translate_string(orig_date, model_name=model_name)
            meta_eng.raw_meta['date'] = translated_date
            print(f"  [Skill] Translated date: {translated_date}")

        header = meta_eng.to_yaml()
        body = meta_eng.clean_body(source_text)
        print(f"  [Skill] Metadata found and isolated ({len(meta_eng.raw_meta)} keys).")
    else:
        header = ""
        body = source_text

    # Threshold for chunking: 2000 words (User prefers larger context for coherence)
    if len(body) > 2000:
        print(f"  [Skill] 📏 Content length ({len(body)}) exceeds threshold. Splitting into smaller chunks for high fidelity...")

        # Write body to a temporary file for chunking
        temp_body_file = os.path.join(os.path.dirname(input_file), "temp_body.md")
        with open(temp_body_file, 'w', encoding='utf-8') as f:
            f.write(body)

        # Ensure out_dir is clean before chunking
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir, ignore_errors=True)

        script_path = r"/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-translate/scripts/main.ts"
        cmd_str = f'npx -y bun "{script_path}" chunk "{temp_body_file}" --max-words 800 --output-dir "{out_dir}"'
        subprocess.run(cmd_str, shell=True, check=True)

        chunks_dir = os.path.join(out_dir, "chunks")
        # Natural Sort to handle chunk-1.md, chunk-10.md, chunk-2.md correctly
        raw_files = glob.glob(os.path.join(chunks_dir, "chunk-*.md"))
        chunk_files = sorted(raw_files, key=lambda f: int(re.findall(r'\d+', os.path.basename(f))[0]) if re.findall(r'\d+', os.path.basename(f)) else 0)

        print(f"  [Skill] Processing {len(chunk_files)} chunks in order:")
        for idx, f in enumerate(chunk_files):
            print(f"    {idx+1:02d}. {os.path.basename(f)}")

        tasks = []
        for cf in chunk_files:
            with open(cf, 'r', encoding='utf-8') as f:
                content = f.read()
                # Bypass validation to ensure no sections are missing
                tasks.append({"prompt": build_translation_prompt(content, style, unslop_domain), "file": cf})

        if not tasks:
            print("  [Skill] ⚠️ No content chunks passed validation. Continuing with raw translation...")
            for cf in chunk_files:
                 with open(cf, 'r', encoding='utf-8') as f:
                     tasks.append({"prompt": build_translation_prompt(f.read(), style, unslop_domain), "file": cf})

        client = get_client()
        results = client.generate_batch(tasks, model_name=model_name)

        merged_translated_body = ""
        for r in results:
            content = r.get("result", "").strip()
            if content:
                merged_translated_body += content + "\n\n"

        # Avoid empty yaml markers
        if header.strip() == "---\n---":
            header = ""

        final_text = (header + "\n\n" + merged_translated_body).strip()

        # Cleanup temp body file
        if os.path.exists(temp_body_file):
            os.remove(temp_body_file)
    else:
        # ONE-SHOT MODE for small to mid-sized articles
        print(f"  [Skill] Article length {len(body)} words. Translating in one-shot mode...")
        # Remove triple backticks around YAML to avoid confusing the LLM
        clean_source = source_text.replace("```yaml\n", "").replace("```\n", "").replace("```", "")
        prompt = build_translation_prompt(clean_source, style, unslop_domain)
        client = get_client()
        translated_body = client.generate_content(prompt, model_name=model_name)
        final_text = translated_body.strip()

    # Final mechanical scrubbing
    final_text = deterministic_scrub(final_text)

    # Output file name
    output_file = input_file.replace(".md", f"_translated.md")
    if input_file == output_file: output_file += ".zh.md"

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(final_text)

    # NEW: Cleanup temporary chunk directory
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)

    print(f"  [Skill] Atomic translation complete: {os.path.basename(output_file)}")
    return output_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Postfdry 2.0 Atomic Translation Skill")
    parser.add_argument("input", help="Source Markdown file")
    parser.add_argument("--style", default="formal", help="Translation style preset")
    parser.add_argument("--unslop", default="B2B", help="Unslop domain")
    parser.add_argument("--prompt-only", action="store_true", help="Only output the generated prompt")

    args = parser.parse_args()

    if args.prompt_only:
        with open(args.input, 'r', encoding='utf-8') as f:
            print(build_translation_prompt(f.read(), args.style, args.unslop))
    else:
        run_atomic_translation(args.input, args.style, args.unslop)
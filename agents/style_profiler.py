"""
style_profiler.py [Postfdry 2.0 Skill]

Style Extraction Skill: Analyzes user-provided samples (Markdown, DOCX, PDF) to extract
a cohesive "Style Profile" that can be reused by other agents.
"""

import os
import sys
import argparse
import glob

# Add common to path
common_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common'))
if common_dir not in sys.path:
    sys.path.append(common_dir)

from llm_utils import get_client

def extract_text_from_file(file_path):
    """Parses text content from MD, DOCX, or PDF."""
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == '.md':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()

        elif ext == '.docx':
            import docx
            doc = docx.Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs])

        elif ext == '.pdf':
            import fitz # PyMuPDF
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text

        else:
            print(f"⚠️ Unsupported format: {ext} for file {file_path}")
            return ""
    except Exception as e:
        print(f"❌ Error reading {file_path}: {e}")
        return ""

def extract_style_from_samples(sample_dir):
    """
    Reads files in sample_dir (MD, DOCX, PDF) and uses LLM to synthesize a style profile.
    """
    patterns = ["*.md", "*.docx", "*.pdf"]
    files = []
    for p in patterns:
        files.extend(glob.glob(os.path.join(sample_dir, p)))

    if not files:
        print(f"❌ No suitable files (MD, DOCX, PDF) found in {sample_dir}")
        return None

    print(f"🔍 Analyzing {len(files)} sample articles from: {sample_dir}")

    combined_content = ""
    # Sample up to 5 files to stay within token limits while getting a good variety
    for f in files[:5]:
        content = extract_text_from_file(f)
        if content.strip():
            combined_content += f"\n--- SAMPLE: {os.path.basename(f)} ---\n"
            combined_content += content[:3000].strip() + "\n" # Slightly larger sample for PDF/DOCX

    if not combined_content.strip():
        print("❌ Could not extract any text from the provided samples.")
        return None

    prompt = f"""
### ROLE
你是一名专业的文本分析专家和写作教练。你的任务是分析以下几篇不同格式（Markdown, DOCX, PDF）的“黄金样本”文章的写作风格，并总结出一份【风格配置文件】。

### SAMPLES
{combined_content}

### ANALYSIS GOALS
请从以下维度进行深度拆解：

1. **核心人设 (Persona)**: 作者是以什么身份在说话？（例：平辈的技术布道者、严谨的分析师、幽默的极客）
2. **语气调性 (Tone & Voice)**: 是平实的、犀利的、温暖的、还是冷峻的？
3. **句式习惯 (Sentence Patterns)**:
   - 喜欢长句还是短句？
   - 是否经常使用反问句或设问句？
   - 动词的使用习惯（例如：喜欢用强动词还是名词化表达）？
   - 是否喜欢用特定的连接词（如“说白了”、“本质上”、“换句话说”）？
4. **结构癖好 (Structural Preferences)**:
   - 如何组织内容（加粗、列表、引用）？
   - 每个段落的平均长度？
   - 开篇和结尾的固定范式（如果有的话）？
5. **词汇偏好 (Vocabulary Banks)**:
   - 经常出现的领域词汇？
   - 明显在客观中立还是带有个人色彩？

### OUTPUT FORMAT (REQUIREMENT)
请仅返回一个结构化的 Markdown 块，标题为 "USER_STYLE_PROFILE"。
必须包含：
- **Summary**: 一句话总结这种风格。
- **Declarative Rules**: 10 条左右的指令，用于指导另一个 AI 模仿这种风格。
- **Negative Constraints**: 5 条绝对不要做的禁令。
"""

    client = get_client()
    print("🚀 Sending multi-format style analysis task to LLM...")
    profile_content = client.generate_content(prompt, model_name="gemini-3.1-pro-preview")

    # Save to config/styles/user_style.md
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'config', 'styles')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output_file = os.path.join(output_dir, "user_style.md")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(profile_content)

    print(f"✅ Style Profile successfully extracted to: {os.path.relpath(output_file)}")
    return output_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Postfdry Multi-Format Style Extractor")
    parser.add_argument("dir", help="Directory containing your sample articles (MD, DOCX, PDF)")
    args = parser.parse_args()

    extract_style_from_samples(args.dir)
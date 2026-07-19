import os
import sys
import argparse
import math
import time
import re
import json
from typing import List, Dict
import io

# Force UTF-8 for stdout/stderr to handle emojis in logs on Windows (essential for pythonw)
if sys.platform == "win32":
    # If we are running under pythonw.exe, stdout and stderr might be None
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass

# Configuration
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = getattr(sys, '_MEIPASS', '')
    TOOLS_DIR = os.path.join(BUNDLE_DIR, "Library", "Tools")
    USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "AutoSub")
    ENV_PATH = os.path.join(USER_DATA_DIR, ".env")
else:
    TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(TOOLS_DIR)), ".env")

sys.path.append(os.path.join(TOOLS_DIR, "subtranslator", "lib"))
sys.path.append(os.path.join(TOOLS_DIR, "common"))
from llm_utils import LLMClient, LLMProvider

try:
    import gemini_utils
except ImportError as e:
    print(f"Warning: gemini_utils not found ({e}). Using llm_utils only.")

try:
    import srt_utils
except ImportError as e:
    print(f"❌ Error: srt_utils is mandatory and was not found: {e}")
    print(f"Current sys.path: {sys.path}")
    sys.exit(1)

# --- SKILL INTEGRATION ---

def load_skill_rules(tool_name):
    """
    Reads the README/SKILL.md of a tool to extract prompting rules.
    """
    skill_dir = os.path.join(TOOLS_DIR, tool_name)
    readme_path = os.path.join(skill_dir, "README.md")
    content = ""
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
           content = f.read()
    return content

def _extract_rules(content: str) -> str:
    """
    Drop install/setup/usage/license preamble from a skill README so the real
    rules reach the LLM. Previously the prompt did RULES[:1500], which captured
    only the install instructions (npx / git clone / manual setup) and truncated
    the actual de-AI / tone rules sitting further down the file. This extractor
    splits on '## ' headers and drops sections whose titles match install/usage/
    contributing/license patterns, keeping the rule-bearing sections intact.
    """
    if not content:
        return ""
    drop_re = re.compile(
        r"项目简介|安装|方法|验证安装|使用|使用场景|文件说明|手动使用|贡献|参考资源|许可|"
        r"install|setup|usage|contributing|license|reference",
        re.IGNORECASE,
    )
    parts = re.split(r"\n(?=#{1,2}\s)", content)
    kept = []
    for part in parts:
        m = re.match(r"#{1,2}\s+(.+?)(\n|$)", part)
        title = m.group(1).strip() if m else ""
        if title and drop_re.search(title):
            continue
        kept.append(part)
    cleaned = "\n".join(kept).strip()
    return cleaned or content

# Load rules once at startup
HUMANIZER_RULES = _extract_rules(load_skill_rules("humanizer-zh"))
VERBALIZER_RULES = _extract_rules(load_skill_rules("verbalizer"))
SUBTRANSLATOR_RULES = load_skill_rules("subtranslator")



# Retrieve API Keys from environment
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    pass

import llm_utils
client = llm_utils.get_client()

def get_context_window(blocks: List[Dict], index: int, window_size: int = 2) -> Dict:
    """
    Returns context lines (before/after) for a given block index.
    """
    start = max(0, index - window_size)
    end = min(len(blocks), index + window_size + 1)

    prev_text = " ".join([" ".join(b['lines']) for b in blocks[start:index]])
    next_text = " ".join([" ".join(b['lines']) for b in blocks[index+1:end]])

    return {"prev": prev_text, "next": next_text}

def detect_translation_style(blocks: List[Dict], model_name: str, provider=None) -> str:
    """
    Analyzes the English subtitle blocks to determine the best translation style.
    Returns: 'casual', 'formal', or 'edgy'.
    """
    print("🔍 Auto-detecting subtitle language style...")
    if not blocks:
        print("⚠️ No subtitle blocks found. Defaulting to CASUAL.")
        return "casual"
    # Take a sample of the first 50 blocks
    sample_blocks = blocks[:50]
    sample_text = "\n".join([" ".join(b['lines']).strip() for b in sample_blocks])
    
    prompt = f"""Analyze the following English video subtitle transcript and classify its tone/genre into exactly one of these three categories:
1. `casual`: Conversational, informal speech. Often contains filler words ("you know", "like", "well"), colloquial phrasing, personal anecdotes, or relaxed banter. (Typical of podcasts, casual discussions, vlogs).
2. `formal`: Structured, written, or academic speech. Grammatically precise, lacks filler words, uses professional terminology, or presents structured arguments. (Typical of presentations, formal lectures, business reports, documentaries).
3. `edgy`: Short, punchy, high-impact language. Very short sentences or fragments designed to grab attention. (Typical of TikToks, reels, ads, or high-energy marketing).

Respond with ONLY the category name (`casual`, `formal`, or `edgy`) as a single word in lowercase. Do not include formatting, punctuation, or any other explanation.

### TRANSCRIPT SAMPLE:
{sample_text}
"""
    try:
        # Use fallback=True to ensure robust cascading if Vertex/primary provider fails
        detected = client.generate_content(prompt, model_name=model_name, fallback=True, provider=provider)
        detected = detected.strip().lower() if detected else "casual"
        if detected not in ["casual", "formal", "edgy"]:
            # Clean up if model added markdown or formatting
            for style in ["casual", "formal", "edgy"]:
                if style in detected:
                    detected = style
                    break
            else:
                detected = "casual"
        print(f"🎯 Auto-detected style: {detected.upper()}")
        return detected
    except Exception as e:
        print(f"⚠️ Style detection failed ({e}). Defaulting to CASUAL.")
        return "casual"

def smart_translate_chunk(chunk_blocks: List[Dict], style: str = "casual", model_name: str = "gemini-3.1-pro-preview") -> List[Dict]:
    """
    Translates a chunk of subtitle blocks using context-aware prompting.
    """
    # Construct the Prompt
    input_text = ""
    for i, block in enumerate(chunk_blocks):
        # We simplify the input to line format: [ID] Text
        text = " ".join(block['lines']).replace("\n", " ")

        # Apply terminology scrubbing to fix ASR errors (claw -> OpenClaw) before LLM sees it
        scrubbed_text = humanize_text(text, is_source=True)
        if not scrubbed_text.strip() and text.strip():
            # Fallback if scrubbing accidentally wiped everything
            scrubbed_text = text.strip()

        input_text += f"[{block['index']}] {scrubbed_text}\n"

    prompt = f"""
You are an expert subtitle translator and editor.
Translate the following English subtitles into Simplified Chinese.

### STEP 1: VERBALIZATION (Tone & Persona)
{VERBALIZER_RULES}
TARGET STYLE: {style}
- "Casual": Natural, spoken Chinese. Use "其实", "也就是说".
- "Tech": Accurate terminology. "Code" -> "代码", "Agent" -> "智能体".
- "Edgy": Short, punchy, impactful.

### STEP 2: HUMANIZATION (De-AI)
{HUMANIZER_RULES}
- NO "translationese".
- NO "此外", "意味着", "不可或缺".
- NO long dashes "——".
- Vary sentence length.

### CORE REQUIREMENTS:
1. **Timing & Rhythm (Highest Priority)**: Maintain strict alignment with the time-axis. The Chinese text should match the rhythm of the English speech.
2. **Context-Driven Meaning**: Use the 'Context Lines' to understand the full sentence, but only translate the specific 'Target Line'.
3. **Synchronization Constraint (CRITICAL)**: Do not significantly restructure sentences across time boundaries. Ensure the meaning of each segment is self-contained enough to be understood at that specific moment. NEVER merge the content of consecutive blocks or skip block IDs in your output. Every input ID in `[ID]` format MUST have its exact corresponding translated line in the output. If a sentence spans across block boundaries (e.g., block N ends with a conjunction and block N+1 starts a clause), translate the fragments strictly into their corresponding blocks to prevent timeline shifts.
4. **Glossary Consistency**: Strictly follow the terms provided in the 'ARTICLE ANALYSIS'.
   - NOTE: Pre-translated terms like "前线部署工程师" (person) and "前线部署模式" (concept) may already appear in the input. When "前线部署模式" is used in a verbal/active context (e.g. "doing 前线部署模式 for X"), naturally adjust to "前线部署" for fluent Chinese.

INPUT BLOCK:
{input_text}

OUTPUT FORMAT:
[ID] Translated Text
...
"""

    try:
        translated_text = client.generate_content(prompt, model_name=model_name)
        if not translated_text:
            return chunk_blocks

        # Parse the Output
        translated_map = {}
        for line in translated_text.split('\n'):
            match = re.match(r'\[(\d+)\]\s*(.*)', line.strip())
            if match:
                idx = match.group(1)
                content = match.group(2).strip()
                if content:  # guard: reject empty translations
                    translated_map[idx] = content

        # Apply translations back to blocks
        translated_blocks = []
        for block in chunk_blocks:
            new_block = block.copy()
            idx = str(block['index']) # Ensure string comparison
            if idx in translated_map:
                new_block['lines'] = [translated_map[idx]]
            else:
                # Fallback: keep original if translation missing (better than empty)
                print(f"Warning: Missing translation for block {idx}")
                new_block['lines'] = block['lines']
            translated_blocks.append(new_block)

        return translated_blocks

    except Exception as e:
        print(f"Error translating chunk: {e}")
        return chunk_blocks # Return original on failure


STYLE_GUIDE_PATH = os.path.join(TOOLS_DIR, "common", "HARD_CONSTRAINTS.md")

def load_regex_rules(filepath):
    """
    Loads regex rules from HARD_CONSTRAINTS.md and auto-classifies each rule:
    - "asr": Section 1 rules whose replacement contains NO CJK (English→English ASR correction).
             Safe for pre-LLM source text scrubbing.
    - "term": Section 1 rules whose replacement CONTAINS CJK (English→Chinese terminology).
              Post-LLM only — must never touch source text before LLM sees it.
    - "cleanup": Sections 2+ (text cleanup, compliance). Post-LLM only.
    """
    rules = []
    if os.path.exists(filepath):
        is_section1 = True  # Section 1 = Terminology/Glossary
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if "## 2. Text Cleanup" in line:
                    is_section1 = False
                if line.startswith("|") and not line.startswith("| Rule") and not line.startswith("| description") and not line.startswith("|---"):
                    # Split by pipe but IGNORE escaped pipes \|
                    parts = [p.strip() for p in re.split(r'(?<!\\)\|', line)]
                    # Remove empty parts from start/end
                    if parts[0] == "": parts.pop(0)
                    if parts and parts[-1] == "": parts.pop()

                    if len(parts) >= 2:
                        pattern = parts[1].strip('`').replace(r'\|', '|') # Unescape pipe for regex engine
                        replacement = parts[2].strip('`').replace(r'\|', '|') if len(parts) > 2 else ""
                        if is_section1:
                            has_cjk = bool(re.search(r'[\u4e00-\u9fff]', replacement))
                            rule_type = "term" if has_cjk else "asr"
                        else:
                            rule_type = "cleanup"
                        rules.append((pattern, replacement, rule_type))
    return rules

REGEX_RULES = load_regex_rules(STYLE_GUIDE_PATH)

def humanize_text(text: str, is_source: bool = False) -> str:
    """
    Applies configured Regex rules and basic Humanizer cleanup.

    is_source=True:  Pre-LLM ASR correction ONLY (English→English, no CJK injected).
                     This ensures the LLM always receives clean English source text.
    is_source=False: Post-LLM full pipeline (ASR + terminology translation + cleanup).
    """
    # 0. Apply Regex Rules from STYLE_GUIDE.md
    for pattern, replacement, rule_type in REGEX_RULES:
        if is_source and rule_type != "asr":
            continue  # Pre-LLM: only English→English ASR correction
        try:
            text = re.sub(pattern, replacement, text)
        except Exception:
            pass

    if is_source:
        # Safety guard: ASR correction must never introduce CJK into source text.
        # If this triggers, an ASR-classified rule has a CJK replacement — fix the rule.
        if re.search(r'[\u4e00-\u9fff]', text):
            print(f"⚠️  WARNING: humanize_text(is_source=True) introduced CJK: {text[:80]}", file=sys.stderr)
        return text.strip()

    # 1. Remove common AI connectors (Hardcoded fallbacks)
    text = text.replace("此外，", "另外，")
    text = text.replace("总而言之，", "简单说，")
    text = text.replace("不可或缺", "很重要")
    text = text.replace("意味着", "说明")

    # 2. Fix punctuation
    text = text.replace(",", "，").replace("?", "？").replace("!", "！")

    # 3. Trim extra spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def is_untranslated(block: Dict) -> bool:
    """
    Returns True if a block has not been successfully translated.
    Detects: empty lines, known marker tags, or predominantly English text.
    Blocks containing CJK characters are considered translated UNLESS the text
    is predominantly English with only a few Chinese chars (which can happen
    when terminology pre-replacement injects Chinese into otherwise untranslated
    English lines, e.g. "Head of 前线部署工程师ing at OpenAI").
    """
    text = " ".join(block.get('lines', [])).strip()
    if not text:
        return True
    markers = ['[UNTRANSLATED]', '[TRANSLATION_FAILED]']
    if any(m in text for m in markers):
        return True
    if re.search(r'[\u4e00-\u9fff]', text):
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        # Partially translated: mostly English with a few Chinese chars
        # (typically from terminology pre-replacement that injected Chinese)
        if english_words >= 5 and chinese_chars < english_words:
            return True
        return False
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return False
    ascii_ratio = sum(1 for c in alpha if ord(c) < 128) / len(alpha)
    return ascii_ratio > 0.7 and len(alpha) >= 8


def translate_blocks(blocks: List[Dict], client, model: str, style: str,
                     verbalizer_snippet: str, humanizer_snippet: str,
                     knowledge_snippet: str, trans_mode_snippet: str = "", provider=None) -> List[Dict]:
    """
    Translates a list of blocks (may be any size) using generate_batch.
    Returns the blocks with translations applied. Does NOT apply humanize_text.
    Original text is kept as fallback for any block whose translation is missing/empty.
    """
    BATCH = 20
    total = len(blocks)
    tasks = []

    for i in range(0, total, BATCH):
        chunk = blocks[i:i + BATCH]
        input_text = ""
        for block in chunk:
            text = " ".join(block['lines']).replace("\n", " ").strip()
            # Apply terminology scrubbing to fix ASR errors (claw -> OpenClaw) before LLM sees it
            scrubbed_text = humanize_text(text, is_source=True)
            if not scrubbed_text.strip() and text.strip():
                scrubbed_text = text
            input_text += f"[{block['index']}] {scrubbed_text}\n"

        prompt = f"""You are an expert subtitle translator and editor.
Translate the following English subtitles into Simplified Chinese.

### STEP 1: VERBALIZATION (Tone & Persona)
{verbalizer_snippet}...
TARGET STYLE: {style}

### STEP 2: DOMAIN KNOWLEDGE & ASR CORRECTION
{knowledge_snippet}

### STEP 3: HUMANIZATION (De-AI)
{humanizer_snippet}...
{trans_mode_snippet}

### STEP 3.8: SYNCHRONIZATION & ALIGNMENT CONSTRAINTS (CRITICAL)
- **Strict ID Alignment**: NEVER merge the content of consecutive blocks or skip block IDs in your output. Every input ID in `[ID]` format MUST have its exact corresponding translated line in the output.
- **No Restructuring Across Time Boundaries**: Do not significantly restructure sentences across time boundaries. Ensure the meaning of each segment is self-contained enough to be understood at that specific moment. If a sentence spans across block boundaries (e.g., block N ends with a conjunction and block N+1 starts a clause), translate the fragments strictly into their corresponding blocks to prevent timeline shifts.

### STEP 4: CONTEXT AWARENESS
INPUT BLOCK:
{input_text}

OUTPUT FORMAT (STRICT — one line per segment, no extra text):
[ID] Translated Text
...
"""
        tasks.append({'index': i // BATCH, 'chunk': chunk, 'prompt': prompt})

    results = client.generate_batch(tasks, model, fallback=False, provider=provider)
    results.sort(key=lambda x: x['index'])

    # Build a map of all translations
    translated_map = {}
    for res in results:
        result_text = res.get('result')
        if result_text:
            for line in result_text.split('\n'):
                match = re.match(r'\[(\d+)\]\s*(.*)', line.strip())
                if match:
                    idx = match.group(1)
                    content = match.group(2).strip()
                    if content:  # guard: reject empty translations
                        translated_map[idx] = content

    # Apply translations; fall back to original text if missing
    out = []
    for block in blocks:
        new_block = block.copy()
        idx = str(block['index'])
        if idx in translated_map:
            new_block['lines'] = [translated_map[idx]]
        # else: keep whatever was there (original EN or previous attempt)
        out.append(new_block)
    return out


def postprocess_retry_loop(final_blocks: List[Dict], client, model: str, style: str,
                            verbalizer_snippet: str, humanizer_snippet: str,
                            knowledge_snippet: str, trans_mode_snippet: str = "", max_iterations: int = 5, provider=None) -> List[Dict]:
    """
    Iteratively re-translates any untranslated/empty blocks until all are done
    (or max_iterations is reached). Returns final_blocks with all translations filled.
    Does NOT apply humanize_text — that is done in a single pass after this function.
    """
    for iteration in range(1, max_iterations + 1):
        missed_positions = [i for i, b in enumerate(final_blocks) if is_untranslated(b)]
        if not missed_positions:
            print(f"✅ Post-processing complete after {iteration - 1} extra pass(es). All segments translated.")
            break

        print(f"🔄 Post-processing pass {iteration}/{max_iterations}: "
              f"{len(missed_positions)} untranslated segment(s) detected. Re-translating...")

        missed_blocks = [final_blocks[i] for i in missed_positions]
        retranslated = translate_blocks(
            missed_blocks, client, model, style,
            verbalizer_snippet, humanizer_snippet, knowledge_snippet, trans_mode_snippet,
            provider=provider
        )

        # Re-insert results at original positions
        for pos, new_block in zip(missed_positions, retranslated):
            final_blocks[pos] = new_block

        # Report remaining
        still_missed = [i for i, b in enumerate(final_blocks) if is_untranslated(b)]
        resolved = len(missed_positions) - len(still_missed)
        print(f"   ✔ Resolved: {resolved} | Still untranslated: {len(still_missed)}")
    else:
        still_missed = [i for i, b in enumerate(final_blocks) if is_untranslated(b)]
        if still_missed:
            print(f"⚠️ Max iterations ({max_iterations}) reached. "
                  f"{len(still_missed)} segment(s) still untranslated.")
            # Final naked-prompt fallback: the batch prompt (with large
            # verbalizer/humanizer rule blocks) sometimes makes the LLM return
            # malformed [ID] lines for tricky fragments (e.g. a bare list of
            # proper nouns). Re-translate each remaining block with a minimal
            # single-line prompt that has no rule preamble — this reliably
            # produces a clean [ID] <translation> line. Prevents 1 stuck
            # block from failing the entire 978-block translation.
            print("🔄 Naked-prompt fallback for remaining stuck block(s)...")
            for pos in still_missed:
                blk = final_blocks[pos]
                idx = str(blk['index'])
                src = " ".join(blk.get('lines', [])).replace("\n", " ").strip()
                if not src:
                    continue
                naked = (f"Translate this ONE subtitle fragment into Simplified Chinese. "
                         f"Keep proper nouns/acronyms in English. "
                         f"Reply with ONLY one line in this exact format: [{idx}] <translation>\n\n"
                         f"[{idx}] {src}\n")
                try:
                    out = client.generate_content(naked, model_name=model, provider=provider)
                    if out:
                        import re as _re
                        m = _re.search(r'\[%s\]\s*(.+)' % _re.escape(idx), out)
                        if m:
                            cn = m.group(1).strip()
                            if cn and _re.search(r'[\u4e00-\u9fff]', cn):
                                final_blocks[pos]['lines'] = [cn]
                                print(f"   ✔ block {idx}: naked fallback succeeded")
                                continue
                    print(f"   ✗ block {idx}: naked fallback failed, keeping original")
                except Exception as e:
                    print(f"   ✗ block {idx}: naked fallback error {e}")

    return final_blocks

def _en_distinctive_tokens(text: str) -> set:
    """Extract proper-noun/acronym tokens (kept as-is in CN) for alignment checks."""
    # All-caps acronyms len>=2 (CTOL, eVTOL, AI, US) and Capitalized words len>=3.
    toks = set(re.findall(r"\b[A-Z]{2,}[0-9A-Za-z]*\b", text))
    toks |= set(re.findall(r"\b[A-Z][A-Za-z0-9]{2,}\b", text))
    return {t.lower() for t in toks}


def detect_misaligned_blocks(final_blocks: List[Dict], source_lines: Dict[str, str],
                            client, model: str, style: str, verbalizer_snippet: str,
                            humanizer_snippet: str, knowledge_snippet: str,
                            trans_mode_snippet: str = "") -> List[Dict]:
    """
    Desync backstop. The translation LLM sometimes merges content from EN
    block N+1 (or later) into the CN translation of block N, so the Chinese
    runs ahead of the English on the timeline. Detect this by finding
    distinctive proper-noun/acronym tokens that appear in a CN block but
    whose EN source lives in a LATER block, then re-translate those blocks
    one-at-a-time with a strict single-fragment prompt that cannot absorb
    adjacent content.
    """
    # Build per-block EN distinctive-token sets.
    en_tokens = {}
    for b in final_blocks:
        idx = str(b['index'])
        en_tokens[idx] = _en_distinctive_tokens(source_lines.get(idx, ""))

    # CN blocks may keep acronyms/proper nouns verbatim; find forward-absorbed ones.
    misaligned = []
    for i, b in enumerate(final_blocks):
        idx = str(b['index'])
        cn_text = " ".join(b.get('lines', []))
        cn_tokens = _en_distinctive_tokens(cn_text)
        if not cn_tokens:
            continue
        own_en = en_tokens.get(idx, set())
        # tokens in CN that are NOT in this block's own EN but ARE in a later EN block
        forward = cn_tokens - own_en
        absorbed = set()
        for j in range(i + 1, min(i + 4, len(final_blocks))):  # look ahead up to 3 blocks
            later_idx = str(final_blocks[j]['index'])
            absorbed |= (forward & en_tokens.get(later_idx, set()))
        if absorbed:
            misaligned.append((i, idx, sorted(absorbed)))

    if not misaligned:
        print("✅ Alignment check passed: no forward-absorbed blocks detected.")
        return final_blocks

    print(f"⚠️ Alignment check: {len(misaligned)} block(s) appear to absorb later content. "
          f"Re-translating individually: {[(idx, toks) for _, idx, toks in misaligned]}")

    # Re-translate each flagged block strictly by itself.
    for pos, idx, toks in misaligned:
        en_src = source_lines.get(idx, "")
        if not en_src:
            continue
        strict_prompt = f"""You are translating ONE subtitle fragment. Translate ONLY the
text below into Simplified Chinese. Do NOT include content from any other fragment, do NOT
look ahead or behind. The text is a partial sentence — translate exactly that fragment,
even if it is incomplete, so it aligns with this one subtitle block on the timeline.
These tokens must NOT appear unless they are in the source fragment: {', '.join(toks)}.

FRAGMENT: {en_src}

Reply with ONLY the Chinese translation, nothing else."""
        try:
            corrected = client.generate_content(strict_prompt, model_name=model)
            corrected = (corrected or "").strip()
            # sanity: must contain CJK and not be empty
            if corrected and re.search(r"[\u4e00-\u9fff]", corrected):
                final_blocks[pos]['lines'] = [corrected]
                print(f"   ✔ block {idx}: re-translated (was absorbing {toks})")
            else:
                print(f"   ✗ block {idx}: re-translation failed validation, kept original")
        except Exception as e:
            print(f"   ✗ block {idx}: re-translation error {e}, kept original")

    return final_blocks


def clean_untranslated_english(final_blocks: List[Dict], source_lines: Dict[str, str],
                              client, model: str, style: str, verbalizer_snippet: str,
                              humanizer_snippet: str, knowledge_snippet: str,
                              trans_mode_snippet: str = "") -> List[Dict]:
    """
    Strip residual untranslated English words from mostly-Chinese blocks (the
    'actually' / 'you know' issue). A block that has CJK but also >=2 lowercase
    English words (excluding proper nouns/acronyms/numbers) is partially
    untranslated and gets re-translated with a no-residual-English instruction.
    """
    # Common English filler words that leak through as untranslated.
    filler = set("""actually basically literally basically really just like you know
    so anyway though however well right okay okay yeah yes no oh um ah
    i mean kind of sort of""".split())

    def _residual_en(text: str) -> list:
        if not re.search(r"[\u4e00-\u9fff]", text):  # only flag mixed (CN+EN) blocks
            return []
        words = re.findall(r"\b[a-z]{2,}\b", text)
        # drop filler we explicitly allow-list as low-risk? no — filler is the target.
        return [w for w in words if w in filler or len(w) >= 3]

    flagged = [(i, str(b['index'])) for i, b in enumerate(final_blocks)
               if len(_residual_en(" ".join(b.get('lines', [])))) >= 2]
    if not flagged:
        print("✅ Residual-English check passed: no partially-translated blocks.")
        return final_blocks

    print(f"⚠️ Residual-English check: {len(flagged)} block(s) have untranslated English. "
          f"Re-translating: {[idx for _, idx in flagged]}")

    for pos, idx in flagged:
        en_src = source_lines.get(idx, "")
        if not en_src:
            continue
        clean_prompt = f"""Translate this ONE subtitle fragment into Simplified Chinese.
The output must be fully Chinese except for proper nouns / acronyms / brand names
(keep those in English). Do NOT leave common English words like "actually", "you know",
"so" untranslated. If the fragment is a partial sentence, translate just that part.

FRAGMENT: {en_src}

Reply with ONLY the Chinese translation."""
        try:
            corrected = client.generate_content(clean_prompt, model_name=model)
            corrected = (corrected or "").strip()
            if corrected and re.search(r"[\u4e00-\u9fff]", corrected):
                final_blocks[pos]['lines'] = [corrected]
                print(f"   ✔ block {idx}: re-translated (residual English removed)")
            else:
                print(f"   ✗ block {idx}: re-translation failed, kept original")
        except Exception as e:
            print(f"   ✗ block {idx}: re-translation error {e}, kept original")

    return final_blocks

def main():
    parser = argparse.ArgumentParser(description="Smart Translation with Context & Style")
    parser.add_argument("input", help="Input English SRT file")
    parser.add_argument("--style", default="auto", choices=["auto", "casual", "formal", "edgy"])
    default_model = os.environ.get("GOOGLE_GENAI_MODEL") or "gemini-3.1-pro-preview"
    parser.add_argument("--model", default=default_model, help="LLM Model to use for translation")
    parser.add_argument("--provider", default=None, help="Explicit LLM Provider")
    parser.add_argument("--chunk-size", type=int, default=50, help="Number of blocks per batch")
    parser.add_argument("--trans-mode", default="balanced", choices=["paraphrase", "balanced"], help="Translation Mode")

    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        print(f"File not found: {input_path}")
        return

    print(f"🚀 Starting Smart Translation for: {os.path.basename(input_path)}")
    print(f"Progress: 0.1% (Analyzing subtitle chunks...)", flush=True)

    # 1. Parse Input
    blocks = srt_utils.parse_srt(input_path)
    if not blocks:
        print("Error parsing SRT file.")
        return

    # Snapshot the English source text per block BEFORE translation/cache overwrite.
    # Needed later by detect_misaligned_blocks / clean_untranslated_english to
    # compare the CN output against its EN source fragment.
    source_lines = {str(b['index']): " ".join(b['lines']).replace("\n", " ").strip() for b in blocks}

    # 1.5 Auto style detection
    effective_style = args.style
    
    provider_enum = None
    if args.provider:
        try:
            provider_enum = LLMProvider(args.provider)
        except ValueError:
            pass

    if args.style == "auto":
        effective_style = detect_translation_style(blocks, args.model, provider=provider_enum)
    print(f"   Style: {effective_style} (Configured: {args.style}) | Chunk Size: {args.chunk_size}")

    total_chunks = math.ceil(len(blocks) / args.chunk_size)
    print(f"   Total Blocks: {len(blocks)} -> {total_chunks} Chunks")

    # --- Cache Logic ---
    cache_path = os.path.join(os.path.dirname(input_path), os.path.splitext(os.path.basename(input_path))[0] + ".translation_cache.json")
    translated_map = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                translated_map = json.load(f)
            print(f"🔄 Loaded {len(translated_map)} cached translations.")
        except: pass

    # Apply cache to initial blocks
    for block in blocks:
        idx = str(block['index'])
        if idx in translated_map:
            block['lines'] = [translated_map[idx]]

    final_blocks = []

    # Identify untranslated blocks
    untranslated_blocks = [b for b in blocks if is_untranslated(b)]
    if not untranslated_blocks:
        print("✅ All blocks already translated (from cache).")
        final_blocks = blocks
    else:
        print(f"🚀 Translating {len(untranslated_blocks)} remaining segments...")

        # 2. Process Chunks Concurrently
        tasks = []
        chunk_size = args.chunk_size
        num_untranslated_chunks = math.ceil(len(untranslated_blocks) / chunk_size)

    # Initialize default snippets for safety
    target_model = args.model
    verbalizer_snippet = VERBALIZER_RULES if VERBALIZER_RULES else "Translate naturally."
    humanizer_snippet = HUMANIZER_RULES if HUMANIZER_RULES else "Do not sound robotic."
    knowledge_snippet = ""
    trans_mode_snippet = ""

    if untranslated_blocks:
        # Pre-load rules for efficiency
        verbalizer_snippet = VERBALIZER_RULES if VERBALIZER_RULES else "Translate naturally."
        humanizer_snippet = HUMANIZER_RULES if HUMANIZER_RULES else "Do not sound robotic."
        knowledge_snippet = ""
        if SUBTRANSLATOR_RULES:
            # Extract Domain Knowledge if present, or just use relevant parts
            match = re.search(r'(## Domain Knowledge & ASR Correction.*)', SUBTRANSLATOR_RULES, re.DOTALL)
            if match:
                knowledge_snippet = match.group(1).strip()
            else:
                # Fallback to general constraints if section not found (or just empty)
                pass

        if args.trans_mode == "balanced":
            trans_mode_snippet = """
    ### STEP 3.5: TRANSLATION BALANCE (CRITICAL)
    ### STEP 3.5: TRANSLATION BALANCE (CRITICAL CONCISENESS)
    - **Aggressive Conciseness**: The output must be as short and punchy as possible. Compress verbose English phrases into dense, telegraphic Chinese. Drop unnecessary pronouns, filler words, and conjunctions.
    - **Example Constraint**: "As Anurag said, this is our fifth DevCon in about 15 months, and momentum is palpable, I think." -> "正如 Anurag 所说，15个月内第五届 DevCon，势头非常迅猛。"
    - **Metaphors & Terms**: Do not expand or explain (e.g., keep "DevCon", do not translate to "开发者大会" if it wastes space). Keep terms like "Gastown", "Ralph Wiggum" as direct translations or original English.
    - **Context Injection**: Strictly forbidden. Do not add any explanatory background.
    """
        else:
            trans_mode_snippet = """
    ### STEP 3.5: TRANSLATION PARAPHRASE
    - Focus on sense-for-sense paraphrasing. Explain metaphors and add cultural/contextual background if it helps the domestic audience understand the subtext.
    """

        print(f"📦 Preparing {total_chunks} chunks for parallel processing...")

        tasks = []
        for i in range(total_chunks):
            start = i * args.chunk_size
            end = min((i + 1) * args.chunk_size, len(blocks))
            chunk = blocks[start:end]

            # Construct Prompt string here in main loop to be thread-safe/independent
            input_text = ""
            for block in chunk:
                text = " ".join(block['lines']).replace("\n", " ").strip()
                input_text += f"[{block['index']}] {text}\n"

            prompt = f"""
    You are an expert subtitle translator and editor.
    Translate the following English subtitles into Simplified Chinese.

    ### STEP 1: VERBALIZATION (Tone & Persona)
    {verbalizer_snippet}...
    TARGET STYLE: {effective_style}

    ### STEP 2: DOMAIN KNOWLEDGE & ASR CORRECTION
    {knowledge_snippet}

    ### STEP 3: HUMANIZATION (De-AI)
    {humanizer_snippet}...
    {trans_mode_snippet}

    ### STEP 3.8: SYNCHRONIZATION & ALIGNMENT CONSTRAINTS (CRITICAL)
    - **Strict ID Alignment**: NEVER merge the content of consecutive blocks or skip block IDs in your output. Every input ID in `[ID]` format MUST have its exact corresponding translated line in the output.
    - **No Restructuring Across Time Boundaries**: Do not significantly restructure sentences across time boundaries. Ensure the meaning of each segment is self-contained enough to be understood at that specific moment. If a sentence spans across block boundaries (e.g., block N ends with a conjunction and block N+1 starts a clause), translate the fragments strictly into their corresponding blocks to prevent timeline shifts.

    ### STEP 4: CONTEXT AWARENESS
    INPUT BLOCK:
    {input_text}

    ### OUTPUT FORMAT:
    [ID] Translated Text
    ...
    """
            tasks.append({
                'index': i,
                'chunk': chunk,
                'prompt': prompt
            })

        # Execute Batch
        try:
            # Use user-specified model, or default to gemini-3-flash-preview.
            target_model = args.model
            print(f"🚀 Using LLM: {target_model}...")

            # Start a background simulation thread for translation progress
            import threading
            
            # Estimate total batch translation time:
            # Each chunk is processed in parallel, so a typical batch takes about 10 seconds.
            # Plus 0.4 seconds per chunk to account for provider queueing.
            estimated_translate_seconds = 8.0 + len(tasks) * 0.4
            if estimated_translate_seconds < 10.0:
                estimated_translate_seconds = 10.0
                
            sim_done = False
            def sim_worker():
                start_time = time.time()
                last_pct = 1.0
                while not sim_done:
                    time.sleep(1.0)
                    if sim_done: break
                    elapsed = time.time() - start_time
                    pct = (elapsed / estimated_translate_seconds) * 99.0
                    if pct > 99.0: pct = 99.0
                    if pct > last_pct + 0.5:
                        last_pct = round(pct, 1)
                        print(f"Progress: {last_pct}% (Translating chunks...)", flush=True)
                        
            t_sim = threading.Thread(target=sim_worker)
            t_sim.daemon = True
            t_sim.start()

            results = client.generate_batch(tasks, target_model, fallback=False, provider=provider_enum)
            sim_done = True

            # Sort results by index to ensure correct subtitle order
            results.sort(key=lambda x: x['index'])

            for res in results:
                result_text = res.get('result')
                chunk = res['chunk']

                translated_chunk_blocks = []

                if result_text:
                    # Parse output logic
                    translated_map_chunk = {}
                    for line in result_text.split('\n'):
                        match = re.match(r'\[(\d+)\]\s*(.*)', line.strip())
                        if match:
                            idx = match.group(1)
                            content = match.group(2).strip()
                            if content:  # guard: reject empty translations
                                translated_map_chunk[idx] = content

                    # Apply translations; keep original as fallback for missing/empty
                    for block in chunk:
                        new_block = block.copy()
                        idx = str(block['index'])
                        if idx in translated_map_chunk:
                            new_block['lines'] = [translated_map_chunk[idx]]
                        # else: keep original English as fallback (detected by is_untranslated)
                        translated_chunk_blocks.append(new_block)
                else:
                    print(f"❌ Chunk {res['index']} failed completely. Will retry in post-processing.")
                    translated_chunk_blocks = chunk  # keep original for retry

                # Update Cache (we use translated_map from line 375)
                for b in translated_chunk_blocks:
                    if not is_untranslated(b):
                        translated_map[str(b['index'])] = " ".join(b['lines'])

                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(translated_map, f, ensure_ascii=False, indent=2)

                # Suppress rapid-fire chunk progress prints to avoid launcher UI jumping
                print(f"DEBUG: Chunk {res['index'] + 1}/{total_chunks} processed successfully.", flush=True)

            # Rebuild final_blocks from translated chunk results (the loop above
            # applied translations to translated_chunk_blocks but never merged them
            # back into final_blocks — this was the bug that caused all 559 segments
            # to be flagged as "untranslated" and needlessly re-translated).
            final_blocks = []
            for res in results:
                chunk = res['chunk']
                result_text = res.get('result')
                if result_text:
                    t_map = {}
                    for line in result_text.split('\n'):
                        m = re.match(r'\[(\d+)\]\s*(.*)', line.strip())
                        if m and m.group(2).strip():
                            t_map[m.group(1)] = m.group(2).strip()
                    for block in chunk:
                        nb = block.copy()
                        idx = str(block['index'])
                        if idx in t_map:
                            nb['lines'] = [t_map[idx]]
                        final_blocks.append(nb)
                else:
                    final_blocks.extend(chunk)

        except Exception as e:
            print(f"❌ Parallel execution failed: {e}")
            import traceback
            traceback.print_exc()
            return

    # 3. Post-Processing: retry all still untranslated segments
    untranslated_count = sum(1 for b in final_blocks if is_untranslated(b))
    if untranslated_count > 0:
        print(f"\n🔍 Post-processing: {untranslated_count} untranslated segment(s) found. Starting retry loop...")
        final_blocks = postprocess_retry_loop(
            final_blocks, client, target_model, effective_style,
            verbalizer_snippet, humanizer_snippet, knowledge_snippet, trans_mode_snippet,
            provider=provider_enum
        )
        # Final Cache update
        for b in final_blocks:
            if not is_untranslated(b):
                translated_map[str(b['index'])] = " ".join(b['lines'])
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(translated_map, f, ensure_ascii=False, indent=2)
    else:
        print("\n✅ All segments translated. Skipping post-processing.", flush=True)

    # 3.5 Desync backstop: detect blocks whose CN absorbed later EN content,
    #     and strip residual untranslated English. Both use source_lines snapshot.
    final_blocks = detect_misaligned_blocks(
        final_blocks, source_lines, client, target_model, effective_style,
        verbalizer_snippet, humanizer_snippet, knowledge_snippet, trans_mode_snippet
    )
    final_blocks = clean_untranslated_english(
        final_blocks, source_lines, client, target_model, effective_style,
        verbalizer_snippet, humanizer_snippet, knowledge_snippet, trans_mode_snippet
    )
    # Persist any re-translated blocks from the backstop into the cache.
    for b in final_blocks:
        if not is_untranslated(b):
            translated_map[str(b['index'])] = " ".join(b['lines'])
    if os.path.exists(os.path.dirname(cache_path)):
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(translated_map, f, ensure_ascii=False, indent=2)

    # 4. Final Style-Guide Humanization (single pass over all blocks)
    print("\n✨ Applying style guide and humanization to all blocks...")
    for block in final_blocks:
        new_lines = []
        for l in block['lines']:
            h = humanize_text(l, is_source=False)
            if not h.strip() and l.strip():
                # Safety: if humanize_text wipes everything, fallback to original
                new_lines.append(l)
            else:
                new_lines.append(h)
        block['lines'] = new_lines

    # 5. Final validation: check if there are any untranslated blocks remaining
    untranslated_count = sum(1 for b in final_blocks if is_untranslated(b))
    if untranslated_count > 0:
        # Soft-degrade: a handful of stuck blocks (typically bare lists of
        # proper nouns like "CoreWeave and Crusoe and Nebius and ...") can
        # resist translation across all retries. Failing the entire run over
        # 1-2 such blocks is worse than keeping the original text for them —
        # the bilingual merge will still show EN for those fragments. Warn
        # and continue instead of aborting.
        stuck = [str(b['index']) for b in final_blocks if is_untranslated(b)]
        print(f"\n⚠️ {untranslated_count} segment(s) could not be translated after all retries "
              f"(likely bare proper-noun lists): {stuck}. Keeping original text for these; "
              f"output will have EN for those blocks. Continuing.")

    # 6. Save Output
    if input_path.lower().endswith(".en.srt"):
        output_path = input_path[:-7] + ".cn.srt"
    else:
        output_path = input_path.replace(".srt", ".cn.srt")


    def get_versioned_filename(filepath):
        if not os.path.exists(filepath): return filepath
        base, ext = os.path.splitext(filepath)
        match = re.search(r'_v(\d+)$', base)
        if match:
            version = int(match.group(1)); base = base[:match.start()]
        else: version = 0
        while True:
            version += 1
            new_path = f"{base}_v{version}{ext}"
            if not os.path.exists(new_path): return new_path

    output_path = get_versioned_filename(output_path)

    srt_utils.write_srt(final_blocks, output_path)
    print(f"Progress: 100.0% (Translation successfully completed)", flush=True)
    print(f"✅ Translation Saved to: {output_path}", flush=True)

    # Cleanup cache on success
    if os.path.exists(cache_path):
        try: os.remove(cache_path)
        except: pass

if __name__ == "__main__":
    main()

# CLAUDE.md

> [!CAUTION]
> **READ [GLOBAL_RULES.md](file:////Users/shanfu/cc/GLOBAL_RULES.md) FIRST**. 
> All shell commands MUST follow the macOS/Zsh conventions defined there.


### Scripts
- `cc_research_engine.py`: Core logic for CCResearch skill (File organization, PDF conversion).

## User Constraints
> [!IMPORTANT]
> **STRICT ADHERENCE**: Strictly follow the user's order. If the user says **do NOT** do something, you must NOT do it, even if it was executed as a natural step of a previous project or seems like a logical next step. Negative constraints override all "defaults" or "standard workflows".
>
> **macOS/Zsh Compatibility Rules (CRITICAL)**:
> - **Environment**: You are on a macOS system using Zsh.
> - **CLI Commands**: Use standard Unix/Zsh commands.
>   - ✅ **List Dirs**: `ls -F` or `ls -l`.
>   - ✅ **Delete**: `rm -rf <path>`.
>   - ✅ **Create File**: `touch <path>`.
>   - ✅ **Search Text**: Use internal `grep_search` tool first. Fallback: `grep -r`.
>   - ✅ **Find Files**: Use internal `find_by_name` tool. Fallback: `find . -name "pattern"`.
>   - ✅ **Environment Variables**: Use `export VAR="value"`.
> - **Paths**: Use `/` for paths. Always quote paths containing spaces.
>
> **Project Working Folders**: Any new workflow, skill, or automated task MUST set up its working folder within the `Projects` directory at the root (e.g., `/Users/shanfu/cc/Projects/Your_Project_Name`). **CRITICAL:** Do NOT create loose scripts (`.py`), logs (`.txt`), or folders directly in the root. All temporary tests must go to `/Users/shanfu/cc/tmp/`.

## Memory & Continuity Protocol
> [!IMPORTANT]
> At the start of EVERY new session, you MUST read the following files:
> 1. **[MEMORY/CORE.md](file:////Users/shanfu/cc/MEMORY/CORE.md)**: User profile, workspace layout, active projects, hard rules.
> 2. **[MEMORY/SESSIONS.md](file:////Users/shanfu/cc/MEMORY/SESSIONS.md)**: Rolling session log — recent progress and current objectives.
> 3. **[PROJECT_MAP.md](file:////Users/shanfu/cc/PROJECT_MAP.md)**: High-level status of all projects.
> 4. **[todos.md](file:////Users/shanfu/cc/todos.md)**: Movie Database Revival specific backlog (if working on that project).
> 5. **[TODO.md](file:////Users/shanfu/cc/TODO.md)**: General multi-project todo list.
>
> This prevents redundant research and ensures continuity. `CORE.md` is the single source of truth — read it first.
> 


## Available Skills

### /CCOLS [topic]
Performs a deep online research cycle (called by /CCResearch or used standalone):
1. **Keyword-Based Search Strategy**:
    - Conduct broad searches using meaningful combinations of topic keywords.
    - **Step 1 (General)**: Run a search without any firm names.
    - **Step 2 (Targeted)**: Run searches combining the topic with high-authority firms (Gartner, IDC, Forrester, McKinsey, BCG, Bain, Deloitte, PwC, Accenture, KPMG, EY, Capgemini, Databricks, Palantir).
2. **Precision and Relevance**: Focus on how AI enhances data governance/management or how strategies evolve for AI adoption. Avoid broad AI governance drifting.
3. **Depth**: Check at least 50 results per combination.
4. **Content Acquisition**: Automatically download PDF/DOCX/PPTX and crawl high-relevance pages, saving content to `research_log.md`.

### /humanizer-zh [text_or_file]
Removes AI traces from text using the rules in `humanizer-zh/SKILL.md`.
1. **Rule Loading**: Read and understand the 24 patterns in `humanizer-zh/SKILL.md`.
2. **Analysis**: Identify AI-isms (e.g., "delve into", "testament to", structure symmetry).
3. **Rewrite**: Rewrite the content to be direct, varied in rhythm, and "human" with a distinct voice.

### /hhfy [url]
Translates an English article to Simplified Chinese and humanizes it using the rules in `hhfy/SKILL.md`.
1. **Fetch**: Read the content from the provided [url].
2. **Translate**: Translate the full content from English to Simplified Chinese.
3. **Humanize**: Apply the `/humanizer-zh` skill patterns to the translated text to make it sound natural and remove AI traces.
4. **HTML Output**: Run `python md_to_html.py <markdown_file>` to generate a styled HTML version.

### /publish-wechat [markdown_file]
Publishes a Markdown article to WeChat Official Account with formatting and AI-generated images.
1. **Analyze**: Run `python wechat_prep.py <markdown_file>` to get the publishing plan (JSON).
2. **Generate Images**:
    - **Cover**: Use the `generate_image` tool with the cover prompt from the plan. Name it `cover_<filename>`.
    - **Inline**: Use `generate_image` for inline images. Name them `inline_<index>_<filename>`.
3. **Assemble**: Run `python wechat_finalize_html.py <markdown_file> <plan_json_path> <image_map_json>` to create `_wechat.html`.
4. **Publish**: Use `browser_subagent` to:
    - Login to `https://mp.weixin.qq.com/`.
    - Create a new article.
    - Copy content from `_wechat.html` and paste into the editor.
    - Upload the Cover image.
    - Set the Title, Author, and Digest from the plan.
    - **Pause** for user to review before sending (or save as draft).

### /CCResearch [topic]
Performs an automated research workflow:
1.  **Online Research**: Invokes **CCOLS** for targeted deep search.
2.  **Dynamic Organization**: Auto-categorize files and create folders on the fly.
3.  **PDF Sync**: Incremental conversion of .docx/.pptx to PDF via `cc_research_engine.py`.
4.  **Insight Synthesis**: Generate a holistic research report outline with painpoints, best practices, existing efforts, and suggestions (with cross-referencing).

## Custom Skill Logic: CCResearch
When the user requests research on a topic, follow this automated workflow:

### Part 1: Deep Online Research (CCOLS)
- Use the `CCOLS` logic to generate keyword combinations and perform deep searching/downloading as defined in the `/CCOLS` skill.

### Part 2: Dynamic File Organization
- Scan the directory and categorize files into buckets.
- Use prefixes (e.g., 01_, 02_) and create new folders on the fly based on file types or themes.

### Part 3: PDF Synchronization
- Convert all `.docx` and `.pptx` files to a separate `06_PDF_Backup` folder using the local Office COM interface.

### Part 4: Holistic Analysis & Outline Generation
- Analyze all internal and external documents.
- Generate/Update a research report outline with:
    1. **Industry/Company Painpoints**: Specific issues regarding the topic.
    2. **Latest Research & Best Practices**: Global trends and analyst views with URLs.
    3. **Existing Efforts**: What the company has already planned or implemented (extract from internal PPTs/Docs).
    4. **Strategic Suggestions**: Actionable tasks to bridge the gap.

## Implementation Details
- For file conversion, always refer to the logic in `cc_research_engine.py` to handle Windows path and encoding issues.
- Use `Explore` agent for multi-document cross-referencing.
- Ensure all suggestions are cross-referenced with page numbers or URLs.

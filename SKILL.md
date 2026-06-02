---
name: PostOS
description: Postfdry 2.0 Editorial OS - 智能化、去AI味的专家级出版工作流水线 (Translation & Interpretation OS). TRIGGER when: user asks to "translate article", "interpret article", "publish whitepaper", "公众号文章翻译", "译介", "深度解读", "PostOS", or provides a URL with publication intent. Automates deep translation, rewriting, lead-in generation, and brand-consistent visual asset creation (Industrial Amber).
---

# Postfdry 2.0 (Expert Publishing OS)

Postfdry 2.0 is a modular intelligence system for high-end B2B content publishing. It transitions from a monolithic script to an atomic **Skill & Workflow** architecture, specifically designed to eliminate "translationese" and "AI flavor."

## 🚀 When to Use (Triggers)
- **"Translate this article"** $\rightarrow$ Triggers **Translate Mode**.
- **"Interpret this news" / "Write a WeChat post"** $\rightarrow$ Triggers **Interpret Mode**.
- **"Publish this as a PDF/Whitepaper"** $\rightarrow$ Triggers formatting & asset generation.
- **Providing a URL** $\rightarrow$ Automatically fetches content and enters the pipeline.

## 🛠️ Usage & Calling

### 1. Direct URL/PDF Execution (Recommended)
If a user provides a URL (e.g., Substack, Arxiv, News) or a PDF:
Run the dispatcher directly on the target:
`python Library/Tools/postfdry/scripts/postfdry-os.py <url_or_pdf_path>`

*Note: This will automatically use the internal `crawler_agent.py` to fetch and clean content into a project workspace.*

### 2. Manual CLI Invocation
Initialize the interactive "Pre-flight Check" for any local Markdown file:
```powershell
python /Users/shanfu/cc/Library/Tools/postfdry/scripts/postfdry-os.py <input.md>
```
*Note: This will automatically prompt for Text Style, Visual Style, and Editor Thoughts.*

## 📂 Project Management (Workspace Control)
Postfdry 2.0 implements a **Centralized Asset Control** system. Every run creates a project folder in `/Users/shanfu/cc/Projects/Postfdry/`:
- **`source/`**: Localized original article.
- **`assets/original/`**: **Automated sync** of all images from the source MD (links are rewritten to local paths).
- **`assets/`**: Generated cover and brand-consistent infographics.
- **`output/`**: Final deliverables (MD, HTML, PDF).

## Key Entry Point: postfdry-os

The primary way to use Postfdry is via the interactive dispatcher:
- **Execution**: `python Library/Tools/postfdry/scripts/postfdry-os.py <input_file.md>`
- **Interactive Pre-flight Check**: Allows selecting Mode, Style, Article Type, and injecting "Editor Thoughts" before starting the pipeline.

## Core Capabilities (Atomic Skills)

### 1. Style Profiler (个人风格提取)
- **Agent**: `agents/style_profiler.py`
- **Role**: Analyzes sample articles (MD, DOCX, PDF) to extract a "Style Profile" (`user_style.md`).
- **Usage**: Select `[2] 提取个人写作风格` in the `postfdry-os` menu.

### 2. Translator (专业翻译)
- **Agent**: `agents/translator_agent.py`
- **Role**: Focuses on "信达雅" (Faithfulness, Fluency, Elegance). Uses Humanizer-ZH to ensure native Chinese flow.
- **Protocol**: Strictly follows `config/terms.yml` and `WritingStyle` guidelines.

### 3. Rewriter (专家改写)
- **Agent**: `agents/rewriter_agent.py`
- **Role**: Acts as a Senior Industry Researcher. Adapts tone based on article type (Trend, Research, Policy, Product, Standard).
- **Output**: Market-ready titles and long-form insights.

### 4. Lead-in Synthesizer (全文导读)
- **Agent**: `scripts/lead_in_agent.py`
- **Role**: Reads the **full processed text** to generate high-fidelity, punchy lead-ins.

## Operational Modes (Workflows)

### Mode 1: 译介模式 (Translate Mode)
- **Goal**: Faithful translation for internal or professional documents.
- **Workflow**: Atomic Translation -> Global Lead-in -> Visual Prompts -> PDF/HTML.

### Mode 2: 解读模式 (Interpret Mode)
- **Goal**: Deep, rewritten insights for public distribution (WeChat).
- **Workflow**: Atomic Translation -> Atomic Rewriting -> Global Lead-in -> Visuals (Infographics) -> HTML.

## Terminology Governance
Postfdry 2.0 uses a centralized **[terms.yml](file:////Users/shanfu/cc/Library/Tools/postfdry/config/terms.yml)** for domain terminology (e.g., FDE, Agentic Infrastructure, DCMM). Updating this file immediately updates all agents' behavior.

---
## Automation Protocol for Orchestrator
As the Antigravity Orchestrator, you should prefer calling the `postfdry-os.py` dispatcher or its underlying workflows (`translate_workflow.py` / `interpret_workflow.py`) to manage projects in `/Users/shanfu/cc/Projects/<project_name>/`.
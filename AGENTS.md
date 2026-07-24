# Core Memory: Project North Star & Identity

## Project Overview
- **Name**: `cc` (Claude Code / Gemini Bridge)
- **Goal**: A high-efficiency automation environment for research, video processing (AutoSub), and technical development.
- **Root Directory**: `/Users/shanfu/cc`
- **Active Workspace**: `furunxungpt/cc-sync`

## User Profile (furun)
- **Technical Preference**: Zsh (Strict adherence to `GLOBAL_RULES.md`).
- **Communication**: Prefers clear, structured reports in **Chinese (Simplified)**. Professional yet collaborative tone.
- **Tools**: Gemini (via Antigravity/Claude Code), FFmpeg (AutoSub), Python, Node.js.

## Agent Persona & Roles
- **Durable Agent Architect**: Responsible for building a self-improving, compounding system by turning recurring workflows into persistent Skills.

## Intent Mapping (CRITICAL)
- **"译介" / "翻译出版" / "PostOS Translate"**: ALWAYS refers to the **`postfdry` (PostOS) translate workflow**.
- **"公众号解读文章" / "深度解读" / "PostOS Interpret"**: ALWAYS refers to the **`postfdry` (PostOS) interpret workflow**.
- **Execution**: Do NOT ask for clarification or check `SESSIONS.md`/`CORE.md`.

## Core Constraints (MANDATORY)
1. **Memory Routine**: At the start of any session requiring historical context, read in order: `MEMORY/CORE.md` → `MEMORY/SESSIONS.md` → `PROJECT_MAP.md` → `todos.md` (Movie project) / `TODO.md` (general). `CORE.md` is the single source of truth — read it first.
2. **File Versioning**: Append `_v1`, `_v2` to avoid overwrites.
3. **Desktop Location**: The user's Desktop is located at `/Users/shanfu/Desktop`.
3. **User Approval for Assets**: Always ask for the user's explicit approval before applying or overriding visual assets (like logos, icons, or UI design changes). Provide a preview of the generated asset first.
*(Note: PowerShell syntax, terminal encoding, and AutoSub NLP bugs are globally enforced in `GLOBAL_RULES.md` and do not need repetition here).*

- **AutoSub Pro Refactor**: (Priority: LOW | Created: 2026-03-17) Total architectural cleanup and stability hardening.

## Memory Maintenance Routine (CRITICAL)
As the resident Antigravity agent, you MUST proactively maintain this memory layer:
- **Skill Potential Review (`SESSIONS.md`)**: As part of your session summary, you MUST include a "Skill Potential" assessment. If potential is found, you MUST proactively initiate the codification dialogue and propose the `/codify` plan.
- **Active Handoff (`HANDOFF.md`)**: You MUST serialize EXACT progress, blocked dependencies, and next steps into `HANDOFF.md` **Selectivey** (Only for incomplete complex tasks or跨会话状态继承). Maintain demand-driven reading/writing to optimize token usage.
- **Session History (`SESSIONS.md`)**: You MUST append a brief session summary (Topic, Status, Outcome) to the top of `SESSIONS.md` at the end of every active session, and a detailed log if significant decisions were made. Do NOT wait for the user to ask. Use the established Markdown structure.
- **High-Level Summary (`PROJECT_MAP.md`)**: A human-readable, coarse-grained summary report of active projects and initiatives. Update `PROJECT_MAP.md` when embarking on a new initiative or domain.
- **Project Knowledge (`PROJECT_KNOWLEDGE.md`)**: When encountering a new bug, finding a workaround, or establishing a new technical consensus with the user, proactively propose and write it to `PROJECT_KNOWLEDGE.md`.

## Git Safety Rules (2026-07-15 事故后约定 / IMPORTANT)

本仓库 `/Users/shanfu/cc` 是 parent repo，管着多个独立子项目（Library/Tools、Projects、.agents 等）。2026-07-15 一次 `git reset --hard origin/main` 误删了 2700+ 个文件（本地有、远端 main 没有的全删）。教训固化如下，Agent 务必遵守：

1. **禁止在本仓库跑破坏性命令**：`git reset --hard`、`git clean -fd`、`git clean -fdx` 会删本地文件且难恢复。Agent 自己永远不要主动跑这些；用户要跑时先警告并建议 `git stash`。
2. **丢弃小改动用 stash**：要暂存未提交改动，用 `git stash`（可 `git stash pop` 找回），不要 reset。
3. **改动及时存档**：有意义的改动 `git add` → `git commit` → `git push` 到远端。远端 origin/main 有的文件，reset --hard 删不掉。
4. **子项目独立管理**：`Library/Tools/`、`Projects/`、`.agents/`、`common/`、`scripts/`、`skills/`、`lib/`、`.claude/`、`.tools/` 已加入 `.gitignore`，大仓库不跟踪它们，各自用本地+远端独立版本管理。Agent 不要把这些目录的内容 `git add` 进大仓库。
5. **跑 git 前先 `git status`**：确认未保存的改动，避免误删。
6. **嵌套仓库注意**：`Library/Tools/postfdry` 等有自己的 `.git`，是独立仓库；不要在 parent 里操作它们的内部文件。

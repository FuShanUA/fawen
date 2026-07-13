# PostOS 2.0 - 智能化专家级出版工作流平台 (Standalone 2.0)

智能化、去 AI 味的专家级公众号出版与译介工作流平台。开箱即用，无需额外依赖仓库。

---

## 安装说明

### Windows 用户

1. 解压项目到任意目录
2. 双击运行 `setup.bat`（或命令行中执行）
3. 安装完成后启动 GUI：
   ```cmd
   .venv\Scripts\python scripts\postos_gui.py
   ```

### macOS 用户

1. 解压项目到任意目录
2. 打开终端进入项目目录，运行：
   ```bash
   ./setup.sh
   ```
3. 安装完成后启动 GUI：
   ```bash
   .venv/bin/python scripts/postos_gui.py
   ```

详细安装指引请参考 [INSTALL_GUIDE.md](INSTALL_GUIDE.md)。

---

## 前置条件

**必需：**
- Python 3.10+（Windows 安装时勾选 "Add Python to PATH"）
- 至少一个 LLM API Key（Gemini / OpenAI / DeepSeek / 阿里百炼等）

**可选（启用高级功能）：**
- Node.js 18+ + Bun（HTML 精美排版、图片生成、微信发布）
- 安装方式：`npm install -g bun`

---

## 配置 API Key

首次使用时，在 GUI 界面 **「模型配置」** 标签页中：
1. 选择对应厂商
2. 输入 API Key 并点击 **「保存 Key」**
3. 系统自动在项目根目录创建 `.env` 文件

---

## PDF 模板自定义

`assets/templates/federation/` 目录下的 `cover.pdf`（封面）、`inside.pdf`（正文背景）和 `back.pdf`（封底）为样例模板。

替换方法：将自定义 PDF 重命名后覆盖同名文件。若封面标题区域不同，编辑 `config/styler_federation.json` 中的 `pos` 坐标即可。

---

## 项目结构

```
postfdry/
├── setup.bat / setup.sh     # 一键安装脚本
├── requirements.txt         # Python 依赖
├── scripts/                 # 工作流与 GUI
│   ├── postos_gui.py        # GUI 入口
│   ├── postfdry-os.py       # CLI 调度器
│   ├── translate_workflow.py
│   └── interpret_workflow.py
├── agents/                  # 各功能 Agent
├── common/                  # 公共工具库
├── config/                  # 配置文件
├── assets/                  # 模板与素材
├── lib/baoyu-skills/        # 内置 TypeScript 技能工具
└── skills/                  # Claude Code 编排技能
```

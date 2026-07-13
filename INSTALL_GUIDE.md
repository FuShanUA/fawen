# PostOS 2.0 安装指南 (For Claude Code Assisted Installation)

本指南面向使用 Claude Code 辅助安装的同事。Claude Code 可以直接读取此文件并按步骤执行安装。

---

## 前置条件

### 必需
1. **Python 3.10+** — 从 https://python.org 下载。Windows 安装时务必勾选 "Add Python to PATH"。
2. **API Key** — 至少一个 LLM 厂商的 API Key（如 Google Gemini、OpenAI、DeepSeek、阿里百炼等）。

### 可选（启用部分高级功能需要）
3. **Node.js 18+** — 用于运行 TypeScript 技能工具（HTML 精美排版、图片生成、微信发布）。从 https://nodejs.org 下载。
4. **Bun 运行时** — TypeScript 技能工具的执行引擎。安装 Node.js 后运行 `npm install -g bun` 即可。

---

## Windows 安装步骤

```cmd
:: 1. 解压项目到任意目录（如 C:\Users\你的用户名\PostOS）
:: 2. 打开命令提示符 (CMD) 或 PowerShell，进入项目目录
cd C:\Users\你的用户名\PostOS

:: 3. 运行一键安装脚本（自动创建虚拟环境、安装依赖、下载 Chromium）
setup.bat

:: 4. 启动 GUI 界面
.venv\Scripts\python scripts\postos_gui.py
```

## macOS 安装步骤

```bash
# 1. 解压项目到任意目录（如 ~/PostOS）
# 2. 打开终端 (Terminal)，进入项目目录
cd ~/PostOS

# 3. 运行一键安装脚本
./setup.sh

# 4. 启动 GUI 界面
.venv/bin/python scripts/postos_gui.py
```

---

## 安装后的配置

### 1. 配置 API Key
启动 GUI 后，在顶部 **「模型配置」** 标签页中：
1. 选择你使用的 LLM 厂商（如 Google Gemini、OpenAI、DeepSeek 等）
2. 在 API Key 输入框中粘贴你的密钥
3. 点击 **「保存 Key」**，系统会自动在项目根目录创建 `.env` 文件
4. 点击 **「测试连通性」** 验证密钥是否有效

### 2. 选择模型
在厂商选择后，系统会自动获取可用模型列表。选择你要使用的模型并设为默认。

### 3. 开始使用
在 **「任务设置」** 标签页中输入文章 URL 或本地 Markdown 文件路径，选择任务模式（译介/解读），点击 **「分析并配置流水线」** 即可。

---

## 常见问题

### Q: Playwright Chromium 安装失败？
A: 手动运行 `.venv\Scripts\playwright install chromium`（Windows）或 `.venv/bin/playwright install chromium`（macOS）。如果仍然失败，尝试以管理员身份运行命令提示符。

### Q: HTML 排版功能不可用？
A: 这通常是因为没有安装 Node.js 和 Bun。安装 Node.js 18+ 后运行 `npm install -g bun`，然后重新运行即可。系统会在缺少这些工具时自动降级为基础 HTML 输出。

### Q: 微信公众号同步失败？
A: 确保已在 **「公众号配置」** 标签页中正确填写微信公众号的 AppID 和 AppSecret，并已安装 Node.js + Bun。

### Q: PDF 生成失败？
A: PDF 生成依赖 Playwright Chromium。请确保 Chromium 已正确安装。模板文件位于 `assets/templates/federation/` 目录下。

---

## Claude Code 辅助安装说明

如果你使用 Claude Code 来辅助安装，可以告诉它：

> "请阅读 INSTALL_GUIDE.md 文件，然后帮我在当前机器上安装 PostOS 2.0"

Claude Code 会读取本文件并按步骤执行安装。如果遇到环境问题，Claude Code 可以直接检查和修复。

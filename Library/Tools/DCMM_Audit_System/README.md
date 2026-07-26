# DCMM AI 审计系统 v2.0

双引擎可版本化审计系统，融合 Gemini（Vertex AI 单次 PDF）和 GLM-5.2 + Qwen-VL-Max（三阶段文本+视觉）两套引擎，共享基础设施但配置、规则、Prompt 完全隔离。

## 架构

```
dcmm/
├── cli.py              统一入口: --engine gemini|glm
├── config.py           per-engine 配置加载 (.env.gemini / .env.glm)
├── batch.py            批量运行器 (并行 + 429 重试 + Excel 汇总)
├── core/               共享基础设施
│   ├── pdf.py          PDF 文本提取 + 页面截图
│   ├── consistency.py  跨文件矛盾检测
│   ├── page_map.py     物理页码 → 印刷页码映射
│   ├── enterprise.py   企业名单加载 + 路径推导
│   ├── reporter.py     结论提取 + Excel 生成
│   └── retry.py        429 限流追踪
├── engines/
│   ├── base.py         AuditEngine 抽象基类
│   ├── gemini/         Gemini 引擎 (Vertex AI, 单次 PDF)
│   │   ├── engine.py
│   │   └── prompts.py  hard_rules 系统指令 + audit_prompt
│   └── glm/            GLM 引擎 (DashScope, 三阶段)
│       ├── engine.py   Phase1 文本 → Phase2 视觉 → Phase3 综合
│       ├── prompts.py  三阶段 Prompt 模板
│       └── api.py      call_glm / call_qwen_vl
rules/
├── gemini/             Gemini 专用规则 (可独立演化)
└── glm/                GLM 专用规则 (可独立演化)
```

## 使用

### GLM 引擎 (三阶段流水线)

```bash
python run.py --engine glm --batch-dir "2、三级（第一天）"
python run.py --engine glm --batch-dir "2、三级（第一天）" --batch-dir "2、三级（第二天）"
python run.py --engine glm --enterprise "1、XX公司" --pdf-dir /path/to/pdfs
```

### Gemini 引擎 (单次 PDF)

```bash
python run.py --engine gemini --batch-dir "2、三级（第一天）"
python run.py --engine gemini --batch-dir "2、三级（第一天）" --use-pro
```

### 直接调用模块

```bash
python -m dcmm --engine glm --batch-dir "2、三级（第一天）"
```

## 配置

每套引擎有独立的 .env 文件，互不干扰:

| 文件 | 引擎 | 关键配置 |
|------|------|----------|
| `.env.gemini` | Gemini | VERTEX_PROJECT_ID, GCS_BUCKET_NAME, GEMINI_MODEL |
| `.env.glm` | GLM | DASHSCOPE_API_KEY, GLM_MODEL, VL_MODEL |

示例文件: `.env.gemini.example` / `.env.glm.example`

## 两套引擎差异

| | Gemini | GLM |
|---|---|---|
| API | Vertex AI | DashScope (阿里云) |
| 模型 | gemini-3-flash/pro | glm-5.2 + qwen-vl-max |
| 方式 | 单次 PDF (Gemini 原生处理 PDF) | 三阶段: 文本审计 → 截图视觉 → 综合判定 |
| Prompt | system_instruction + audit_prompt | 三阶段 inline f-string |
| 规则 | rules/gemini/ | rules/glm/ |
| 输出 | audit_results/审计结果/gemini/ | audit_results/审计结果/glm/ |

## 向后兼容

旧脚本仍可使用 (但不推荐):
- `main.py` — Gemini TUI (桌面 App 启动器)
- `local_audit_v3.py` — GLM 批量流水线
- `run_batch.py` — GLM 并行批量

推荐迁移到 `run.py` 或 `python -m dcmm`。

## 版本

v2.0.0 — 双引擎融合, 可版本化包结构

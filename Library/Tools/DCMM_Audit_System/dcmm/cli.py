"""Unified CLI: select engine, discover enterprises, run audit.

Usage:
  python -m dcmm --engine glm --batch-dir "2、三级（第一天）"
  python -m dcmm --engine gemini --batch-dir "2、三级（第二天）"
  python -m dcmm --engine glm --enterprise "1、XX公司" --pdf-dir /path/to/pdfs
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import __version__
from .config import load_config, DEFAULT_DATA_ROOT


def get_engine(engine_id: str):
    """Create an engine instance by id."""
    cfg = load_config(engine_id)
    if engine_id == "gemini":
        from .engines.gemini import GeminiEngine
        return GeminiEngine(cfg)
    elif engine_id == "glm":
        from .engines.glm import GLMEngine
        return GLMEngine(cfg)
    else:
        print(f"Unknown engine: {engine_id}. Use 'gemini' or 'glm'.")
        sys.exit(1)


def main():
    # TUI mode: python -m dcmm tui  (or: python run.py tui)
    if len(sys.argv) > 1 and sys.argv[1] == "tui":
        from .tui import run_tui
        run_tui()
        return

    ap = argparse.ArgumentParser(
        prog="dcmm",
        description=f"DCMM AI 审计系统 v{__version__} — 双引擎 (Gemini / GLM)",
    )
    ap.add_argument("--engine", choices=["gemini", "glm"], required=True,
                    help="审计引擎: gemini (Vertex AI 单次PDF) 或 glm (GLM+Qwen-VL 三阶段)")
    ap.add_argument("--batch-dir", action="append", default=[],
                    help="报告批次目录名(相对 DATA_ROOT 或绝对路径),可重复")
    ap.add_argument("--institution", default="",
                    help="只跑指定评估机构目录")
    ap.add_argument("--enterprise", default="",
                    help="只跑指定企业(企业目录名)")
    ap.add_argument("--pdf-dir", default="",
                    help="单企业审计: 直接指定PDF目录路径")
    ap.add_argument("--use-pro", action="store_true",
                    help="Gemini: 使用 Pro 模型(深度模式)")
    ap.add_argument("--max-workers", type=int, default=None,
                    help="并行数(默认: gemini=10, glm=5)")
    ap.add_argument("--version", action="version", version=f"dcmm {__version__}")
    args = ap.parse_args()

    # Load config
    cfg = load_config(args.engine)

    # Load enterprise list (for notes/institution lookup)
    from .core.enterprise import load_enterprise_list
    load_enterprise_list(cfg.enterprise_list_path)

    # Create engine
    engine = get_engine(args.engine)
    print(f"引擎就绪: {engine}")

    # Determine mode: single enterprise or batch
    if args.pdf_dir:
        # Single enterprise audit
        ent_name = args.enterprise or "单企业审计"
        print(f"\n单企业审计: {ent_name}")
        print(f"PDF目录: {args.pdf_dir}")
        result = engine.audit_enterprise(
            ent_name, args.pdf_dir,
            use_pro=args.use_pro,
        )
        if result.get("error"):
            print(f"\n✗ 错误: {result['error'][:200]}")
        else:
            print(f"\n✓ 完成: {result['report_path']}")
            print(f"  耗时: {result['timing'].get('total', 0):.1f}s")
    else:
        # Batch audit
        from .batch import discover_enterprises, run_batch

        batch_dirs = list(args.batch_dir) if args.batch_dir else []
        if not batch_dirs:
            print("请指定 --batch-dir 或 --pdf-dir")
            ap.print_help()
            sys.exit(1)

        enterprises = []
        for bd in batch_dirs:
            bdir = bd if bd.startswith("/") else None
            if bdir and not bd.startswith("/"):
                bdir = None
            enterprises.extend(
                discover_enterprises(
                    [bd], cfg.data_root, institution=args.institution,
                )
            )

        if args.enterprise:
            enterprises = [(n, p) for n, p in enterprises if args.enterprise in n]

        if not enterprises:
            print("未发现待审计企业。请检查 --batch-dir 路径。")
            sys.exit(1)

        max_workers = args.max_workers or cfg.max_workers
        run_batch(engine, enterprises, batch_dirs, cfg.data_root, max_workers)


if __name__ == "__main__":
    main()

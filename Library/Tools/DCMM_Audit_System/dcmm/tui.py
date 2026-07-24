"""Unified interactive TUI: engine selection, batch audit, single enterprise, rules.

Run:
  python run.py tui
  python -m dcmm tui
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from . import __version__
from .config import load_config, DEFAULT_DATA_ROOT


def _clear():
    os.system("clear" if os.name != "nt" else "cls")


def _print_header(engine_id: str, cfg):
    _clear()
    w = 56
    print("=" * w)
    print(f"  DCMM AI 审计系统 v{__version__}  [{engine_id.upper()}]")
    print("=" * w)
    print(f"  模型:   {cfg.text_model}")
    if cfg.vision_model:
        print(f"  视觉:   {cfg.vision_model}")
    print(f"  输出:   {cfg.out_dir}")
    print(f"  规则:   {cfg.rules_dir}")
    print(f"  数据:   {cfg.data_root}")
    if engine_id == "gemini":
        print(f"  GCS:    {cfg.gcs_bucket}")
    elif engine_id == "glm":
        print(f"  并行:   {cfg.max_workers}")
    print("-" * w)


def _select_engine() -> str:
    _clear()
    w = 56
    print("=" * w)
    print(f"  DCMM AI 审计系统 v{__version__}")
    print("=" * w)
    print()
    print("  选择审计引擎:")
    print()
    print("  [1] GLM 5.2 + Qwen-VL-Max")
    print("      三阶段: 文本审计 → 截图视觉 → 综合判定")
    print("      本地处理 PDF, 无需 GCS")
    print()
    print("  [2] Gemini (Vertex AI)")
    print("      单次 PDF 审计 (Gemini 原生处理)")
    print("      需要 GCS 上传")
    print()
    print("  [Q] 退出")
    print()
    choice = input("  请选择 [1/2/Q]: ").strip().upper()
    if choice == "1":
        return "glm"
    elif choice == "2":
        return "gemini"
    return ""


def _scan_batch_dirs(data_root: str) -> list[str]:
    """Auto-discover batch directories under data_root."""
    dirs = []
    if os.path.isdir(data_root):
        for name in sorted(os.listdir(data_root)):
            full = os.path.join(data_root, name)
            if os.path.isdir(full) and name.startswith("2、"):
                dirs.append(name)
    return dirs


def _menu_batch(engine, cfg) -> bool:
    """Batch audit menu. Returns True to stay in loop, False to go back."""
    batch_dirs = _scan_batch_dirs(cfg.data_root)
    _print_header(engine.engine_id, cfg)
    print("  批量审计")
    print("-" * 56)
    if not batch_dirs:
        print(f"  未在 {cfg.data_root} 下发现批次目录 (2、三级...)")
        print("  请检查 DCMM_DATA_ROOT 配置或 --batch-dir 参数")
        input("\n  按回车返回...")
        return True

    for i, name in enumerate(batch_dirs, 1):
        bdir = os.path.join(cfg.data_root, name)
        ent_count = 0
        for inst in os.listdir(bdir):
            ip = os.path.join(bdir, inst)
            if not os.path.isdir(ip):
                continue
            for d in os.listdir(ip):
                dp = os.path.join(ip, d)
                if os.path.isdir(dp):
                    pdfs = [f for f in os.listdir(dp) if f.endswith(".pdf")]
                    if len(pdfs) >= 5:
                        ent_count += 1
        print(f"  [{i}] {name}  ({ent_count} 家企业)")

    all_choice = len(batch_dirs) + 1
    print(f"  [{all_choice}] 全部批次")
    print("  [B] 返回")
    print()
    choice = input(f"  请选择 [1-{all_choice}/B]: ").strip().upper()

    if choice == "B":
        return True

    try:
        idx = int(choice)
    except ValueError:
        return True

    if 1 <= idx <= len(batch_dirs):
        selected = [batch_dirs[idx - 1]]
    elif idx == all_choice:
        selected = batch_dirs
    else:
        return True

    use_pro = False
    if engine.engine_id == "gemini":
        print("\n  模式选择:")
        print("  [1] 极速 (Flash)")
        print("  [2] 深度 (Pro)")
        mc = input("  请选择 [1/2]: ").strip()
        use_pro = mc == "2"

    max_w = cfg.max_workers if engine.engine_id == "glm" else 10
    print(f"\n  即将审计: {', '.join(selected)}")
    print(f"  引擎: {engine.display_name}")
    print(f"  并行: {max_w}")
    confirm = input("\n  确认启动? (y/n): ").strip().lower()
    if confirm != "y":
        return True

    from .batch import discover_enterprises, run_batch
    enterprises = []
    for bd in selected:
        enterprises.extend(discover_enterprises([bd], cfg.data_root))

    if not enterprises:
        print("  未发现待审计企业 (需要至少5个PDF的目录)")
        input("\n  按回车返回...")
        return True

    kwargs = {"use_pro": use_pro} if engine.engine_id == "gemini" else {}
    run_batch(engine, enterprises, selected, cfg.data_root, max_w)
    input("\n  按回车返回...")
    return True


def _menu_single(engine, cfg) -> bool:
    """Single enterprise audit menu."""
    _print_header(engine.engine_id, cfg)
    print("  单企业审计")
    print("-" * 56)
    pdf_dir = input("  PDF 目录路径: ").strip()
    if not pdf_dir or not os.path.isdir(pdf_dir):
        print("  无效路径")
        input("\n  按回车返回...")
        return True
    ent_name = input("  企业名称 (可选, 回车跳过): ").strip() or "单企业审计"

    use_pro = False
    if engine.engine_id == "gemini":
        mc = input("  使用 Pro 模式? (y/n): ").strip().lower()
        use_pro = mc == "y"

    print(f"\n  开始审计: {ent_name}")
    result = engine.audit_enterprise(ent_name, pdf_dir, use_pro=use_pro)

    if result.get("error"):
        print(f"\n  ✗ 错误: {result['error'][:200]}")
    else:
        print(f"\n  ✓ 完成: {result['report_path']}")
        print(f"    耗时: {result['timing'].get('total', 0):.1f}s")

    input("\n  按回车返回...")
    return True


def _menu_rules(engine_id, cfg) -> bool:
    """Open rules for editing."""
    _print_header(engine_id, cfg)
    print("  审计规则")
    print("-" * 56)
    print(f"  [1] expert_rules.md  ({cfg.expert_rules_path})")
    print(f"  [2] negative_cases.md  ({cfg.negative_cases_path})")
    print("  [B] 返回")
    print()
    choice = input("  请选择 [1/2/B]: ").strip().upper()

    if choice == "1" and os.path.exists(cfg.expert_rules_path):
        os.system(f'open "{cfg.expert_rules_path}"')
    elif choice == "2" and os.path.exists(cfg.negative_cases_path):
        os.system(f'open "{cfg.negative_cases_path}"')
    return True


def _menu_gcs_upload(cfg) -> bool:
    """Gemini: upload local PDFs to GCS."""
    _print_header("gemini", cfg)
    print("  GCS 上传")
    print("-" * 56)
    local_root = input(f"  本地PDF根目录 (回车={cfg.data_root}): ").strip()
    if not local_root:
        local_root = cfg.data_root
    if not os.path.isdir(local_root):
        print("  无效路径")
        input("\n  按回车返回...")
        return True

    print(f"\n  即将上传 {local_root} → gs://{cfg.gcs_bucket}")
    confirm = input("  确认? (y/n): ").strip().lower()
    if confirm != "y":
        return True

    from google.cloud import storage
    bucket = storage.Client().bucket(cfg.gcs_bucket)
    count = 0
    for root, _dirs, files in os.walk(local_root):
        for f in files:
            if f.endswith(".pdf") and not f.startswith("._"):
                local_path = os.path.join(root, f)
                rel = os.path.relpath(local_path, local_root)
                blob_name = f"audit_batch/{rel}"
                bucket.blob(blob_name).upload_from_filename(local_path)
                count += 1
                print(f"  [{count}] {blob_name}")
    print(f"\n  上传完成: {count} 个文件")
    input("\n  按回车返回...")
    return True


def run_tui():
    """Main TUI loop."""
    engine_id = _select_engine()
    if not engine_id:
        print("\n  再见!")
        return

    cfg = load_config(engine_id)

    # Load enterprise list for notes lookup
    from .core.enterprise import load_enterprise_list
    load_enterprise_list(cfg.enterprise_list_path)

    # Create engine instance
    if engine_id == "gemini":
        from .engines.gemini import GeminiEngine
        engine = GeminiEngine(cfg)
    else:
        from .engines.glm import GLMEngine
        engine = GLMEngine(cfg)

    while True:
        _print_header(engine_id, cfg)
        print("  [1] 批量审计")
        print("  [2] 单企业审计")
        print("  [3] 审计规则")
        if engine_id == "gemini":
            print("  [4] GCS 上传")
        print("  [E] 切换引擎")
        print("  [Q] 退出")
        print()
        choice = input("  请选择: ").strip().upper()

        if choice == "1":
            _menu_batch(engine, cfg)
        elif choice == "2":
            _menu_single(engine, cfg)
        elif choice == "3":
            _menu_rules(engine_id, cfg)
        elif choice == "4" and engine_id == "gemini":
            _menu_gcs_upload(cfg)
        elif choice == "E":
            engine_id = _select_engine()
            if engine_id:
                cfg = load_config(engine_id)
                load_enterprise_list(cfg.enterprise_list_path)
                if engine_id == "gemini":
                    from .engines.gemini import GeminiEngine
                    engine = GeminiEngine(cfg)
                else:
                    from .engines.glm import GLMEngine
                    engine = GLMEngine(cfg)
        elif choice == "Q":
            print("\n  再见!")
            break


if __name__ == "__main__":
    run_tui()

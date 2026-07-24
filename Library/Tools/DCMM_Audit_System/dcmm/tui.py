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
            if os.path.isdir(full) and not name.startswith(".") and not name.startswith("._"):
                # 排除输出目录, 只列出含子目录的文件夹(批次目录通常有机构子目录)
                if name == "审计结果" or name == "重试":
                    continue
                subdirs = [d for d in os.listdir(full)
                           if os.path.isdir(os.path.join(full, d)) and not d.startswith(".")]
                if subdirs:
                    dirs.append(name)
    return dirs


def _count_enterprises(bdir_path: str) -> int:
    """Count enterprise dirs with >=5 PDFs under a batch directory."""
    count = 0
    for inst in os.listdir(bdir_path):
        ip = os.path.join(bdir_path, inst)
        if not os.path.isdir(ip) or inst.startswith("."):
            continue
        for d in os.listdir(ip):
            dp = os.path.join(ip, d)
            if os.path.isdir(dp):
                pdfs = [f for f in os.listdir(dp) if f.endswith(".pdf")]
                if len(pdfs) >= 5:
                    count += 1
    return count


def _list_institutions(bdir_path: str) -> list[str]:
    """List institution directory names under a batch directory."""
    insts = []
    for name in sorted(os.listdir(bdir_path)):
        ip = os.path.join(bdir_path, name)
        if os.path.isdir(ip) and not name.startswith(".") and not name.startswith("._"):
            insts.append(name)
    return insts


def _menu_batch(engine, cfg) -> bool:
    """Batch audit menu. Returns True to stay in loop."""
    batch_dirs = _scan_batch_dirs(cfg.data_root)
    _print_header(engine.engine_id, cfg)
    print("  批量审计")
    print("-" * 56)

    if not batch_dirs:
        print(f"  未在 {cfg.data_root} 下发现批次目录")
        print("  可手动输入路径 (M) 或修改数据根目录 (设置)")
    else:
        for i, name in enumerate(batch_dirs, 1):
            bdir = os.path.join(cfg.data_root, name)
            ent_count = _count_enterprises(bdir)
            print(f"  [{i}] {name}  ({ent_count} 家企业)")

    all_choice = len(batch_dirs) + 1
    manual_choice = all_choice + 1
    print(f"  [{all_choice}] 全部批次")
    print(f"  [{manual_choice}] 手动输入路径")
    print("  [B] 返回")
    print()
    choice = input(f"  请选择 [1-{manual_choice}/B]: ").strip().upper()

    if choice == "B":
        return True

    try:
        idx = int(choice)
    except ValueError:
        return True

    selected = []
    if 1 <= idx <= len(batch_dirs):
        selected = [batch_dirs[idx - 1]]
    elif idx == all_choice:
        selected = batch_dirs
    elif idx == manual_choice:
        # Manual path input
        path = input("\n  输入批次目录路径 (相对数据根或绝对路径): ").strip()
        if not path:
            return True
        if not os.path.isabs(path):
            path = os.path.join(cfg.data_root, path)
        if not os.path.isdir(path):
            print(f"  路径不存在: {path}")
            input("\n  按回车返回...")
            return True
        selected = [path]
    else:
        return True

    # Institution filter
    institution = ""
    if len(selected) == 1:
        bdir_path = (selected[0] if os.path.isabs(selected[0])
                     else os.path.join(cfg.data_root, selected[0]))
        institutions = _list_institutions(bdir_path)
        if len(institutions) > 1:
            print(f"\n  评估机构 ({len(institutions)} 个):")
            print(f"  [0] 全部机构")
            for i, inst in enumerate(institutions, 1):
                inst_path = os.path.join(bdir_path, inst)
                ent_count = _count_enterprises(inst_path) if os.path.isdir(inst_path) else 0
                print(f"  [{i}] {inst}  ({ent_count} 家)")
            inst_choice = input(f"\n  选择机构 [0-{len(institutions)}]: ").strip()
            try:
                ii = int(inst_choice)
                if 1 <= ii <= len(institutions):
                    institution = institutions[ii - 1]
            except ValueError:
                pass

    # Gemini model selection
    use_pro = False
    if engine.engine_id == "gemini":
        print("\n  模式选择:")
        print("  [1] 极速 (Flash)")
        print("  [2] 深度 (Pro)")
        mc = input("  请选择 [1/2]: ").strip()
        use_pro = mc == "2"

    max_w = cfg.max_workers if engine.engine_id == "glm" else 10
    print(f"\n  即将审计: {', '.join(selected)}")
    if institution:
        print(f"  机构过滤: {institution}")
    print(f"  引擎: {engine.display_name}")
    print(f"  并行: {max_w}")
    confirm = input("\n  确认启动? (y/n): ").strip().lower()
    if confirm != "y":
        return True

    from .batch import discover_enterprises, run_batch
    enterprises = []
    for bd in selected:
        enterprises.extend(discover_enterprises([bd], cfg.data_root, institution=institution))

    if not enterprises:
        print("  未发现待审计企业 (需要至少5个PDF的目录)")
        input("\n  按回车返回...")
        return True

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


def _menu_config(engine_id, cfg) -> bool:
    """View and change runtime directory settings."""
    _print_header(engine_id, cfg)
    print("  目录设置")
    print("-" * 56)
    print(f"  当前数据根目录: {cfg.data_root}")
    print(f"  当前输出目录:   {cfg.out_dir}")
    print(f"  企业名单:       {cfg.enterprise_list_path}")
    print()
    print("  [1] 修改数据根目录")
    print("  [2] 修改输出目录")
    print("  [3] 修改企业名单路径")
    print("  [B] 返回")
    print()
    choice = input("  请选择 [1/2/3/B]: ").strip().upper()

    if choice == "1":
        new_root = input(f"  新数据根目录 (回车保持={cfg.data_root}): ").strip()
        if new_root and os.path.isdir(new_root):
            cfg.data_root = new_root
            print(f"  ✓ 数据根目录已更新: {cfg.data_root}")
        elif new_root:
            print(f"  ✗ 路径不存在: {new_root}")
        input("\n  按回车返回...")
    elif choice == "2":
        new_out = input(f"  新输出目录 (回车保持={cfg.out_dir}): ").strip()
        if new_out:
            cfg.out_dir = new_out
            cfg.retry_dir = os.path.join(new_out, "重试")
            os.makedirs(new_out, exist_ok=True)
            os.makedirs(cfg.retry_dir, exist_ok=True)
            engine.cfg.out_dir = new_out
            engine.cfg.retry_dir = cfg.retry_dir
            print(f"  ✓ 输出目录已更新: {cfg.out_dir}")
        input("\n  按回车返回...")
    elif choice == "3":
        new_list = input(f"  新企业名单路径 (回车保持): ").strip()
        if new_list and os.path.exists(new_list):
            cfg.enterprise_list_path = new_list
            from .core.enterprise import load_enterprise_list, _enterprise_notes, _enterprise_inst
            _enterprise_notes.clear()
            _enterprise_inst.clear()
            import dcmm.core.enterprise as ent_mod
            ent_mod._loaded = False
            load_enterprise_list(new_list)
            print(f"  ✓ 企业名单已更新: {cfg.enterprise_list_path}")
        elif new_list:
            print(f"  ✗ 文件不存在: {new_list}")
        input("\n  按回车返回...")

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
        print("  [S] 目录设置")
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
        elif choice == "S":
            _menu_config(engine_id, cfg)
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

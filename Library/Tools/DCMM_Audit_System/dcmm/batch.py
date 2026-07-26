"""Batch runner: discovers enterprises, runs them in parallel, generates summary.

Engine-agnostic — works with any AuditEngine subclass.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .core.pdf import find_split_dir
from .core.reporter import generate_excel, derive_run_paths
from .core.retry import generate_retry_report
from .core.enterprise import load_enterprise_list


def discover_enterprises(batch_dirs: list[str], base_dir: str,
                           institution: str = "") -> list[tuple[str, str]]:
    """Scan batch directories and return [(enterprise_name, pdf_dir), ...].

    Each batch_dir is resolved against base_dir unless absolute.
    institution: if set, only process enterprises under that institution folder.
    """
    enterprises = []
    for bd in batch_dirs:
        bdir = bd if os.path.isabs(bd) else os.path.join(base_dir, bd)
        if not os.path.exists(bdir):
            continue
        for inst_name in sorted(os.listdir(bdir)):
            ip = os.path.join(bdir, inst_name)
            if not os.path.isdir(ip) or inst_name.startswith('.'):
                continue
            if institution and inst_name != institution:
                continue
            for d in sorted(os.listdir(ip)):
                full = os.path.join(ip, d)
                if not os.path.isdir(full) or d.startswith('._') or d.startswith('.'):
                    continue
                pdfs = [
                    f for f in os.listdir(full)
                    if f.endswith('.pdf') and not f.startswith('._')
                ]
                if len(pdfs) >= 5:
                    enterprises.append((d, full))
    return enterprises


def run_batch(engine, enterprises: list[tuple[str, str]],
              batch_dirs: list[str], base_dir: str,
              max_workers: int = 5) -> list[dict[str, Any]]:
    """Run audit on all enterprises in parallel.

    engine:     an AuditEngine instance
    enterprises: list of (name, pdf_dir) tuples
    batch_dirs:  for Excel path derivation
    base_dir:    for Excel institution lookup
    max_workers: parallel concurrency
    """
    total_start = time.time()
    all_results = []

    print(f'{"=" * 60}')
    print(f'{engine.display_name}')
    print(f'引擎: {engine.engine_id} | 并行数: {max_workers}')
    print(f'企业数: {len(enterprises)}')
    print(f'输出: {engine.cfg.out_dir}')
    print(f'{"=" * 60}\n')

    for batch_start in range(0, len(enterprises), max_workers):
        batch = enterprises[batch_start:batch_start + max_workers]
        batch_num = batch_start // max_workers + 1
        total_batches = (len(enterprises) + max_workers - 1) // max_workers

        print(f'\n--- Batch {batch_num}/{total_batches} ({len(batch)} enterprises) ---')
        for name, _ in batch:
            print(f'  {name}')

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(engine.audit_enterprise, name, path): name
                       for name, path in batch}
            for future in as_completed(futures):
                ent_name = futures[future]
                result = future.result()
                all_results.append(result)

                if result.get('error'):
                    print(f'  ✗ {ent_name}: ERROR - {result["error"][:100]}')
                else:
                    t = result['timing']
                    p1 = t.get('phase1_glm', t.get('gemini_call', 0))
                    p2 = t.get('phase2_vl', 0)
                    p3 = t.get('phase3_glm', 0)
                    print(f'  ✓ {ent_name}: {t["total"]:.1f}s '
                          f'(p1={p1:.0f}s vl={p2:.0f}s p3={p3:.0f}s)')

    total_time = time.time() - total_start

    # Generate Excel summary
    run_out_dir, run_excel_name = derive_run_paths(batch_dirs, engine.cfg.out_dir)
    try:
        generate_excel(
            all_results, total_time, batch_dirs=batch_dirs,
            out_dir=run_out_dir, excel_name=run_excel_name,
            base_dir=base_dir,
        )
    except Exception as e:
        print(f'Excel generation failed: {e}')

    # Print summary
    errors = [r for r in all_results if r.get('error')]
    ok = [r for r in all_results if not r.get('error')]
    print(f'\n{"=" * 60}')
    print(f'完成! 总耗时: {total_time:.1f}s ({total_time / 60:.1f}min)')
    print(f'引擎: {engine.display_name}')
    print(f'企业数: {len(all_results)} | 成功: {len(ok)} | 错误: {len(errors)}')

    if errors:
        err_path = os.path.join(engine.cfg.retry_dir, 'failed_enterprises.txt')
        with open(err_path, 'w') as f:
            for r in errors:
                f.write(f'{r["name"]}\n  Error: {r["error"][:200]}\n\n')
        print(f'\n处理失败: {err_path} ({len(errors)} 家需重试)')

    # Retry report
    need_retry = generate_retry_report(engine.cfg.out_dir, engine.cfg.retry_dir)
    if need_retry:
        print(f'需要重跑: {len(need_retry)} 家')
    else:
        print('全部完成，无需重跑')

    return all_results

"""GLM audit engine: three-phase pipeline (GLM text → Qwen-VL vision → GLM synthesis).

Phase 1: Extract PDF text, run consistency checks, send to GLM-5.2 for text audit.
Phase 2: Parse page refs from Phase 1 report, render those pages as screenshots,
         send each to Qwen-VL-Max for visual analysis.
Phase 3: GLM-5.2 combines text audit + image results → final audit report.
"""

from __future__ import annotations

import os
import re
import time
import base64
import traceback
from datetime import datetime
from typing import Any

from ..base import AuditEngine
from .api import call_glm, call_qwen_vl
from .prompts import phase1_prompt, phase2_vl_prompt, phase3_prompt
from ...core.pdf import extract_text, render_page_png
from ...core.consistency import check_consistency
from ...core.page_map import map_page_numbers
from ...core.enterprise import get_enterprise_inst


class GLMEngine(AuditEngine):
    display_name = "GLM 5.2 + Qwen-VL-Max (本地处理，无GCS)"
    engine_id = "glm"

    def audit_enterprise(self, ent_name: str, pdf_dir: str, **kwargs) -> dict[str, Any]:
        """Process one enterprise through the full three-phase pipeline."""
        timing: dict = {}
        total_start = time.time()

        try:
            # Step 1: Text extraction
            t0 = time.time()
            texts, page_map, files = extract_text(pdf_dir)
            timing['extract'] = time.time() - t0

            # Step 2: Consistency check
            t0 = time.time()
            findings, _ = check_consistency(
                texts, files, ent_name, get_enterprise_inst=get_enterprise_inst,
            )
            timing['consistency'] = time.time() - t0

            # Phase 1: GLM text audit
            t0 = time.time()
            phase1_report, phase1_usage = self._phase1(ent_name, texts, files, findings)
            timing['phase1_glm'] = time.time() - t0

            phase1_has_error = phase1_report.startswith(('ERROR', 'API Error'))

            # Phase 2: Image analysis (skip if phase 1 errored)
            if not phase1_has_error:
                t0 = time.time()
                image_results, vl_time = self._phase2(pdf_dir, phase1_report, files, ent_name)
                timing['phase2_vl'] = time.time() - t0

                # Phase 3: Final GLM synthesis
                t0 = time.time()
                final_report, phase3_usage = self._phase3(
                    ent_name, texts, files, findings, image_results, phase1_report,
                )
                timing['phase3_glm'] = time.time() - t0
            else:
                image_results = []
                final_report = phase1_report
                phase3_usage = {}
                timing['phase2_vl'] = 0
                timing['phase3_glm'] = 0

            # Check for API errors in final report
            _err_prefixes = ('ERROR', 'API Error', 'Exception:', 'Error:', '429 限流', '503')
            _is_api_error = (
                isinstance(final_report, str)
                and final_report.lstrip().startswith(_err_prefixes)
            )
            if _is_api_error:
                timing['total'] = time.time() - total_start
                all_usage = {**phase1_usage, **phase3_usage}
                report_path = self.save_report(ent_name, final_report, timing, all_usage)
                return {
                    'name': ent_name, 'report': final_report,
                    'report_path': report_path, 'timing': timing,
                    'usage': all_usage,
                    'error': f'API调用失败: {final_report[:200]}',
                }

            # Page number mapping
            t0 = time.time()
            mapped_report, _map_time = map_page_numbers(final_report, pdf_dir, files, page_map)
            timing['page_map'] = time.time() - t0

            timing['total'] = time.time() - total_start
            all_usage = {**phase1_usage, **phase3_usage}
            report_path = self.save_report(ent_name, mapped_report, timing, all_usage)

            return {
                'name': ent_name, 'report': mapped_report,
                'report_path': report_path, 'timing': timing,
                'usage': all_usage, 'error': None,
            }

        except Exception as e:
            timing['total'] = time.time() - total_start
            return {
                'name': ent_name, 'report': '',
                'report_path': None, 'timing': timing,
                'usage': {}, 'error': f'{str(e)[:300]}\n{traceback.format_exc()[:500]}',
            }

    def _phase1(self, ent_name, texts, files, findings) -> tuple:
        """Phase 1: GLM text-only audit."""
        full_text = ''
        for fname in files:
            full_text += texts.get(fname, '')

        findings_text = '\n'.join(f'- {f}' for f in findings) if findings else '未发现明显矛盾'

        prompt = phase1_prompt(
            ent_name, self.rules_content, self.negative_cases_content,
            findings_text, full_text,
        )
        return call_glm(
            self.cfg.api_base, self.cfg.api_key, self.cfg.text_model,
            prompt, ent_name, max_tokens=self.cfg.glm_max_tokens,
            retry_dir=self.cfg.retry_dir,
        )

    def _phase2(self, pdf_dir, phase1_report, files, ent_name) -> tuple:
        """Phase 2: Qwen-VL-Max targeted image analysis.

        Parses page references from the Phase 1 report, renders those pages
        as PNG screenshots, and sends each to Qwen-VL-Max for visual analysis.
        """
        # Parse page references from Phase 1 report
        pattern = r'((?:0?[1-9]|1[01])[\w\-\s]*?\.pdf)\s*[Pp](\d+)'
        refs = set()
        for m in re.finditer(pattern, phase1_report):
            fname = m.group(1)
            pagenum = int(m.group(2))
            if len(fname) > 40:
                continue
            refs.add((fname, pagenum))

        # Verify page citations and find screenshot pages
        import fitz
        _generic_kw = {
            '数据管理', '能力成熟', '度评估', '评估报', '告机构', '有限公司',
            '股份有限', '副总经理', '数据治理', '数据战略', '数据架构',
            '数据质量', '数据标准', '数据安全', '数据应用', '生存周期',
        }
        corrected_refs = set()
        for fname, pagenum in refs:
            path = os.path.join(pdf_dir, fname)
            try:
                doc = fitz.open(path)
            except Exception:
                corrected_refs.add((fname, pagenum))
                continue
            if pagenum > len(doc) or pagenum < 1:
                doc.close()
                corrected_refs.add((fname, pagenum))
                continue
            # Check if page has large images (screenshots)
            page_blocks = doc[pagenum - 1].get_text('dict')['blocks']
            has_images = any(
                b['type'] == 1
                and (b['bbox'][2] - b['bbox'][0]) > 100
                and (b['bbox'][3] - b['bbox'][1]) > 80
                for b in page_blocks
            )
            if has_images:
                corrected_refs.add((fname, pagenum))
            else:
                # Search nearby pages for images
                for offset in [-1, 1, -2, 2]:
                    check_page = pagenum + offset
                    if 1 <= check_page <= len(doc):
                        blocks = doc[check_page - 1].get_text('dict')['blocks']
                        if any(
                            b['type'] == 1
                            and (b['bbox'][2] - b['bbox'][0]) > 100
                            and (b['bbox'][3] - b['bbox'][1]) > 80
                            for b in blocks
                        ):
                            corrected_refs.add((fname, check_page))
                            break
                else:
                    corrected_refs.add((fname, pagenum))
            doc.close()

        # Render and analyze each page
        vl_prompt = phase2_vl_prompt(ent_name)
        results = []
        for fname, page_num in corrected_refs:
            path = os.path.join(pdf_dir, fname)
            try:
                img_bytes = render_page_png(path, page_num, dpi=150)
            except Exception:
                continue
            b64 = base64.b64encode(img_bytes).decode()
            t0 = time.time()
            content = call_qwen_vl(
                self.cfg.api_base, self.cfg.api_key, self.cfg.vision_model,
                b64, vl_prompt, ent_name,
                max_tokens=self.cfg.vl_max_tokens,
                retry_dir=self.cfg.retry_dir,
            )
            t1 = time.time()
            results.append({
                'file': fname, 'page': page_num,
                'analysis': content, 'time': t1 - t0,
            })

        total_time = sum(r['time'] for r in results)
        return results, total_time

    def _phase3(self, ent_name, texts, files, findings, image_results, phase1_report) -> tuple:
        """Phase 3: GLM combines text findings + image analysis → final report."""
        findings_text = '\n'.join(f'- {f}' for f in findings) if findings else '未发现明显矛盾'

        # Limit image results text to prevent prompt explosion
        image_text = ''
        for r in image_results[:15]:
            analysis = r['analysis'][:150]
            image_text += f'{r["file"]} P{r["page"]}: {analysis}\n'

        # Truncate Phase 1 report
        phase1_truncated = phase1_report[:8000] if len(phase1_report) > 8000 else phase1_report

        prompt = phase3_prompt(
            ent_name, self.rules_content, findings_text,
            image_text, phase1_truncated,
        )
        return call_glm(
            self.cfg.api_base, self.cfg.api_key, self.cfg.text_model,
            prompt, ent_name, max_tokens=self.cfg.glm_max_tokens,
            retry_dir=self.cfg.retry_dir,
        )

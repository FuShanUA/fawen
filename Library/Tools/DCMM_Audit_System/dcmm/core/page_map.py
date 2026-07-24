"""Page number post-mapping: convert physical page refs to printed page numbers."""

import re
import fitz


def map_page_numbers(report_text: str, pdf_dir: str, files: list, page_map: dict):
    """Replace physical page numbers with printed page numbers from PDF footers.

    e.g. '01 数据战略.pdf P5' → '01 数据战略.pdf P5（完整版P12）'
    Returns (mapped_text, elapsed_seconds).
    """
    import time
    pattern = r'((?:0?[1-9]|1[01])[\w\-\s]*?\.pdf)\s*[Pp](\d+)'
    refs = set()
    for m in re.finditer(pattern, report_text):
        fname = m.group(1)
        pagenum = int(m.group(2))
        if len(fname) > 50:
            continue
        refs.add((fname, pagenum))

    if not refs:
        return report_text, 0

    import os
    t0 = time.time()
    replacements = {}
    for fname, phys_page in refs:
        path = os.path.join(pdf_dir, fname)
        if not os.path.exists(path):
            continue
        try:
            doc = fitz.open(path)
        except Exception:
            continue
        if phys_page > len(doc) or phys_page < 1:
            doc.close()
            continue
        page = doc[phys_page - 1]
        footer = fitz.Rect(0, page.rect.height * 0.92, page.rect.width, page.rect.height)
        footer_text = page.get_text("text", clip=footer).strip()
        doc.close()
        nums = re.findall(r'\b(\d+)\b', footer_text)
        if nums:
            replacements[(fname, phys_page)] = nums[0]
    t1 = time.time()

    result = report_text
    for (fname, phys_page), printed in replacements.items():
        old = f'{fname} P{phys_page}'
        new = f'{fname} P{phys_page}（完整版P{printed}）'
        result = result.replace(old, new)

    return result, t1 - t0

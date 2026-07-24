"""PDF text extraction and page rendering utilities (PyMuPDF).

Shared by both engines — Gemini uses it for consistency checks,
GLM uses it for the full three-phase pipeline.
"""

import os
import fitz


def extract_text(pdf_dir: str):
    """Extract text from all split PDFs in a directory.

    Returns (texts, page_map, files):
      texts:    {filename: full_text}  with per-page image tags
      page_map: {filename: page_count}
      files:    sorted list of filenames
    """
    # Collect PDFs: direct first, then recursive walk
    direct_files = [
        f for f in os.listdir(pdf_dir)
        if f.endswith('.pdf') and '完整' not in f and '_part' not in f
        and not f.startswith('._') and not f.startswith('.')
    ]
    seen = {}
    if len(direct_files) >= 5:
        files = sorted(direct_files)
        base_path = pdf_dir
    else:
        all_pdfs = []
        for root, _dirs, fnames in os.walk(pdf_dir):
            for f in fnames:
                if f.endswith('.pdf') and '完整' not in f and '_part' not in f and not f.startswith('._'):
                    all_pdfs.append((f, os.path.join(root, f)))
        for fname, fpath in all_pdfs:
            if fname not in seen or len(fpath) < len(seen[fname]):
                seen[fname] = fpath
        files = sorted(seen.keys())
        base_path = None

    texts = {}
    page_map = {}

    for fname in files:
        path = os.path.join(base_path, fname) if base_path else seen[fname]
        try:
            doc = fitz.open(path)
        except Exception:
            continue
        page_map[fname] = len(doc)
        full_text = ''
        for i in range(len(doc)):
            txt = doc[i].get_text()
            blocks = doc[i].get_text('dict')['blocks']
            imgs = [
                b for b in blocks if b['type'] == 1
                and (b['bbox'][2] - b['bbox'][0]) > 100
                and (b['bbox'][3] - b['bbox'][1]) > 80
            ]
            img_count = len(imgs)
            if img_count > 0:
                landscape = sum(
                    1 for b in imgs
                    if (b['bbox'][2] - b['bbox'][0]) > (b['bbox'][3] - b['bbox'][1])
                )
                page_tag = f'[本页含{img_count}张图片, {landscape}张疑似截图]'
            else:
                page_tag = '[本页无图片]'
            if txt.strip():
                full_text += f'--- {fname} P{i+1} {page_tag} ---\n{txt}\n\n'
            else:
                full_text += f'--- {fname} P{i+1} {page_tag} ---\n(本页无文字内容, 仅有图片)\n\n'
        texts[fname] = full_text
        doc.close()

    return texts, page_map, files


def render_page_png(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """Render a single page to PNG bytes. page_num is 1-based."""
    doc = fitz.open(pdf_path)
    if page_num > len(doc) or page_num < 1:
        doc.close()
        raise ValueError(f"Page {page_num} out of range for {pdf_path}")
    page = doc[page_num - 1]
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes('png')
    doc.close()
    return img_bytes


def get_page_count(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    return n


def find_split_dir(ent_path: str):
    """Find the directory containing split PDFs for an enterprise.
    Recursively collects all split PDFs across all subdirectory levels.
    Returns (dir_path, pdf_count).
    """
    all_pdfs = []
    for root, _dirs, files in os.walk(ent_path):
        for f in files:
            if f.endswith('.pdf') and '完整' not in f and not f.startswith('._'):
                all_pdfs.append(os.path.join(root, f))

    if len(all_pdfs) >= 5:
        parent_dirs = set(os.path.dirname(p) for p in all_pdfs)
        if len(parent_dirs) == 1:
            return parent_dirs.pop(), len(all_pdfs)
        return ent_path, len(all_pdfs)

    # Try direct listing
    direct = [
        f for f in os.listdir(ent_path)
        if f.endswith('.pdf') and '完整' not in f and not f.startswith('._')
    ]
    if direct:
        return ent_path, len(direct)

    return None, 0

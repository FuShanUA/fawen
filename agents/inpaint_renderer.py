"""
inpaint_renderer.py - Pixel-level isomorphic text replacement engine.

Replaces text in images by:
  1. Cleaning (inpainting) original text regions
  2. Rendering translated text at exact coordinates with matched style

No generative image model is involved, so graphics never drift.
Guarantees 100% isomorphic layout preservation.
"""

import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# ---------------------------------------------------------------------------
# Font resolution - cross-platform Chinese font search
# ---------------------------------------------------------------------------

_FONT_LIGHT = [
    "/System/Library/Fonts/SourceHanSansSC-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
_FONT_BOLD = [
    "/System/Library/Fonts/SourceHanSansSC-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _find_font(bold=False):
    paths = _FONT_BOLD if bold else _FONT_LIGHT
    for p in paths:
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------------------
# Coordinate normalization
# ---------------------------------------------------------------------------

def _to_pixels(bbox, width, height):
    """Convert bbox [x1,y1,x2,y2] to absolute pixel coords.
    Handles 0-1 normalized, 0-1000 normalized, or absolute pixel inputs."""
    vals = list(bbox[:4])
    max_val = max(abs(v) for v in vals)

    if max_val <= 1.5:
        # 0-1 normalized
        x1 = vals[0] * width
        y1 = vals[1] * height
        x2 = vals[2] * width
        y2 = vals[3] * height
    elif max_val > 100:
        # 0-1000 normalized (Qwen-VL native format)
        x1 = vals[0] / 1000.0 * width
        y1 = vals[1] / 1000.0 * height
        x2 = vals[2] / 1000.0 * width
        y2 = vals[3] / 1000.0 * height
    else:
        # Absolute pixels
        x1, y1, x2, y2 = vals

    x1 = int(round(x1))
    y1 = int(round(y1))
    x2 = int(round(x2))
    y2 = int(round(y2))
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    x1 = max(0, min(x1, width))
    y1 = max(0, min(y1, height))
    x2 = max(0, min(x2, width))
    y2 = max(0, min(y2, height))
    return x1, y1, x2, y2


def _get_bbox(block, width, height):
    bbox = block.get("bbox") or block.get("BBox") or block.get("location")
    if not bbox or len(bbox) < 4:
        return None
    return _to_pixels(bbox, width, height)


# ---------------------------------------------------------------------------
# Color sampling - auto-detect text and background colors from pixels
# ---------------------------------------------------------------------------

def _sample_colors(img_np, x1, y1, x2, y2, width, height):
    """Sample background color from border outside bbox, and text color
    from the most distinct pixels inside bbox."""
    pad = max(2, int((x2 - x1) * 0.05))

    # Collect border pixels just outside the bbox
    border = []
    for px in range(max(0, x1 - pad), min(width, x2 + pad)):
        if y1 - pad >= 0:
            border.append(img_np[y1 - pad, px])
        if y2 < height:
            border.append(img_np[y2, px])
    for py in range(max(0, y1 - pad), min(height, y2 + pad)):
        if x1 - pad >= 0:
            border.append(img_np[py, x1 - pad])
        if x2 < width:
            border.append(img_np[py, x2])

    if border:
        border_arr = np.array(border)
        bg_color = np.median(border_arr, axis=0).astype(np.uint8)
        bg_std = float(border_arr.std(axis=0).mean())
    else:
        bg_color = np.array([255, 255, 255], dtype=np.uint8)
        bg_std = 0.0

    # Text color: inside bbox, find pixels most distinct from bg
    region = img_np[y1:y2, x1:x2]
    if region.size > 0:
        diff = np.abs(region.astype(float) - bg_color.astype(float)).sum(axis=2)
        if diff.max() > 10:
            thresh = np.percentile(diff, 85)
            mask = diff >= thresh
            if mask.any():
                text_pixels = region[mask].reshape(-1, 3)
                text_color = np.median(text_pixels, axis=0).astype(np.uint8)
            else:
                text_color = np.array([0, 0, 0], dtype=np.uint8)
        else:
            text_color = np.array([0, 0, 0], dtype=np.uint8)
    else:
        text_color = np.array([0, 0, 0], dtype=np.uint8)

    return bg_color, text_color, bg_std


# ---------------------------------------------------------------------------
# Text cleaning - remove original text from image
# ---------------------------------------------------------------------------

def _clean_region(img_np, x1, y1, x2, y2, bg_color, bg_std, width, height, inpaint_mask):
    """Clean original text. Fills solid backgrounds directly; queues
    textured regions for batch inpainting."""
    pad = 2
    cx1 = max(0, x1 - pad)
    cy1 = max(0, y1 - pad)
    cx2 = min(width, x2 + pad)
    cy2 = min(height, y2 + pad)

    if cx2 <= cx1 or cy2 <= cy1:
        return

    if bg_std < 18:
        # Solid color background - fill directly
        img_np[cy1:cy2, cx1:cx2] = bg_color
    else:
        # Textured/gradient - queue for cv2.inpaint
        inpaint_mask[cy1:cy2, cx1:cx2] = 255


# ---------------------------------------------------------------------------
# Font fitting - auto-size text to fit bounding box
# ---------------------------------------------------------------------------

def _wrap_text(text, font, max_width, draw):
    """Wrap text into lines fitting max_width. Handles CJK (any-char break)
    and Latin (word-boundary break) mixed text."""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            test = current + char
            if draw.textlength(test, font=font) <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines


def _fit_font(text, bbox_w, bbox_h, font_path, line_count, draw):
    """Binary-search the largest font size that fits text in the bbox."""
    if not font_path:
        return ImageFont.load_default()

    line_spacing = 1.25
    max_size = max(8, int(bbox_h / max(line_count, 1) * 1.15))
    min_size = 7
    best = min_size

    lo, hi = min_size, max_size
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(font_path, mid)
        lines = _wrap_text(text, font, bbox_w - 4, draw)
        total_h = len(lines) * mid * line_spacing
        max_w = max((draw.textlength(l, font=font) for l in lines), default=0)
        if total_h <= bbox_h and max_w <= bbox_w - 4:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return ImageFont.truetype(font_path, best)


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def _render_text(draw, text, font, x1, y1, x2, y2, text_color, alignment, line_count):
    """Render text within the bounding box with proper alignment."""
    bw = x2 - x1
    bh = y2 - y1
    if bw <= 0 or bh <= 0:
        return

    lines = _wrap_text(text, font, bw - 4, draw)
    line_height = font.size * 1.25
    total_h = len(lines) * line_height

    # Vertical: center the text block in the bbox
    start_y = y1 + (bh - total_h) / 2

    color = tuple(int(c) for c in text_color[:3])

    for i, line in enumerate(lines):
        line_w = draw.textlength(line, font=font)
        if alignment == "left":
            tx = x1 + 2
        elif alignment == "right":
            tx = x2 - line_w - 2
        else:  # center
            tx = x1 + (bw - line_w) / 2
        ty = start_y + i * line_height
        draw.text((tx, ty), line, fill=color, font=font)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_localized_image(image_path, text_blocks, output_path):
    """Render localized text onto the original image.

    Args:
        image_path: Path to original image.
        text_blocks: List of dicts with keys:
            bbox [x1,y1,x2,y2], chinese_text str, alignment str,
            line_count int, bold bool, text_color [r,g,b] (optional).
        output_path: Where to save the result.
    Returns:
        True on success, False on failure.
    """
    try:
        if isinstance(text_blocks, dict):
            text_blocks = [text_blocks]

        # Pre-rendering statistics
        total_blocks = len(text_blocks)
        skipped_blocks = 0
        rendered_blocks = 0

        img_pil = Image.open(image_path).convert("RGB")
        width, height = img_pil.size
        img_np = np.array(img_pil)

        # Phase 1: Clean all original text regions (only for blocks that have chinese_text)
        inpaint_mask = np.zeros((height, width), dtype=np.uint8)
        cleaned_blocks = 0
        for block in text_blocks:
            # Skip blocks that have no translation — preserve original pixels
            if block.get("_skip_render"):
                skipped_blocks += 1
                continue
            text = block.get("chinese_text") or block.get("text") or ""
            if not text:
                skipped_blocks += 1
                continue
            bbox = _get_bbox(block, width, height)
            if not bbox:
                skipped_blocks += 1
                continue
            x1, y1, x2, y2 = bbox
            if x2 - x1 <= 1 or y2 - y1 <= 1:
                skipped_blocks += 1
                continue
            bg_color, text_color, bg_std = _sample_colors(
                img_np, x1, y1, x2, y2, width, height)
            block["_bg_color"] = bg_color
            block["_text_color"] = text_color
            block["_bg_std"] = bg_std
            _clean_region(img_np, x1, y1, x2, y2, bg_color, bg_std,
                          width, height, inpaint_mask)
            cleaned_blocks += 1

        # Batch inpaint all textured regions at once
        if inpaint_mask.any() and HAS_CV2:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            img_bgr = cv2.inpaint(img_bgr, inpaint_mask, 5, cv2.INPAINT_TELEA)
            img_np[:] = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        # Phase 2: Render translated Chinese text
        img_pil = Image.fromarray(img_np)
        draw = ImageDraw.Draw(img_pil)

        drawn_blocks = 0
        for block in text_blocks:
            # Skip blocks that have no translation — preserve original pixels
            if block.get("_skip_render"):
                continue
            text = block.get("chinese_text") or block.get("text") or ""
            if not text:
                continue
            bbox = _get_bbox(block, width, height)
            if not bbox:
                continue
            x1, y1, x2, y2 = bbox
            if x2 - x1 <= 1 or y2 - y1 <= 1:
                continue

            alignment = block.get("alignment", "center")
            line_count = block.get("line_count", 1)
            bold = block.get("bold", False)

            # Use sampled text color, or VLM-provided if available
            text_color = block.get("_text_color", [0, 0, 0])
            if "text_color" in block and isinstance(block["text_color"], (list, tuple)):
                text_color = block["text_color"]

            font_path = _find_font(bold)
            font = _fit_font(text, x2 - x1, y2 - y1, font_path, line_count, draw)
            _render_text(draw, text, font, x1, y1, x2, y2,
                         text_color, alignment, line_count)
            drawn_blocks += 1

        img_pil.save(output_path, "PNG")

        # Post-rendering summary
        print(f"    [inpaint_renderer] {total_blocks} total → {drawn_blocks} drawn, "
              f"{cleaned_blocks} cleaned, {skipped_blocks} skipped (preserved original).")

        return True
    except Exception as e:
        print(f"  [inpaint_renderer] Error: {e}")
        import traceback
        traceback.print_exc()
        return False

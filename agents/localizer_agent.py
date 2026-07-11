import os
import sys
import shutil
import subprocess
import argparse
import concurrent.futures
import threading
import re
from pathlib import Path

# Add common and agents to path
agents_dir = os.path.dirname(os.path.abspath(__file__))
postfdry_root = os.path.dirname(agents_dir)
common_dir = os.path.abspath(os.path.join(postfdry_root, "..", "common"))

for d in [agents_dir, common_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from llm_utils import get_client


def _detect_strategy(image_model, image_vendor=None):
    """Determine localization strategy based on the configured image model and vendor.

    Priority:
      1. If image_vendor is "inpaint" → inpaint_render (explicit user choice)
      2. If image_model contains inpaint/code-render/codewrite → inpaint_render
      3. If image_model contains "gemini" → isomorphic (Gemini inline edit)
      4. If image_model contains "seedream" → ref_edit (Seedream ref-image)
      5. Otherwise → regenerate (from-scratch text-to-image)
    """
    # Vendor-level override: "inpaint" vendor always uses inpaint_render
    if image_vendor and image_vendor.lower() == "inpaint":
        return "inpaint_render"
    if not image_model:
        return "regenerate"
    m = image_model.lower()
    if "inpaint" in m or "code-render" in m or "codewrite" in m:
        return "inpaint_render"
    if "gemini" in m:
        return "isomorphic"
    if "seedream" in m:
        return "ref_edit"
    return "regenerate"


def _get_closest_aspect_ratio(width, height):
    r = width / height
    ratios = {"1:1": 1.0, "16:9": 16/9, "9:16": 9/16,
              "4:3": 4/3, "3:4": 3/4, "3:2": 3/2, "2:3": 2/3}
    closest_ar = "1:1"
    min_diff = float("inf")
    for ar, val in ratios.items():
        diff = abs(r - val)
        if diff < min_diff:
            min_diff = diff
            closest_ar = ar
    return closest_ar


def _resolve_baoyu_imagine():
    """Find the baoyu-imagine main.ts script."""
    try:
        from common_utils import resolve_tool_path
        p = resolve_tool_path("baoyu-imagine")
        if p:
            return os.path.join(p, "scripts", "main.ts")
    except Exception:
        pass
    fallback = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "baoyu-skills", "skills", "baoyu-imagine", "scripts", "main.ts")
    if os.path.exists(fallback):
        return fallback
    return None


def _run_baoyu_imagine(prompt, output_path, model, provider="dashscope",
                       ref_image=None, ar="1:1", quality="2k"):
    """Call baoyu-imagine via bun/npx subprocess."""
    script = _resolve_baoyu_imagine()
    if not script:
        print("  ❌ baoyu-imagine script not found")
        return False

    bun_bin = shutil.which("bun")
    if bun_bin:
        cmd_base = [bun_bin, script]
    else:
        npx_bin = shutil.which("npx") or "npx"
        cmd_base = [npx_bin, "-y", "bun", script]

    cmd = cmd_base + [
        "--prompt", prompt,
        "--image", output_path,
        "--provider", provider,
        "--model", model,
        "--ar", ar,
        "--quality", quality,
    ]
    if ref_image:
        cmd.extend(["--ref", ref_image])

    print(f"  [baoyu-imagine] model={model}, provider={provider}, ref={'yes' if ref_image else 'no'}")
    # Complex 2K diagrams can take longer than 180s; give one retry on timeout.
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if res.returncode == 0 and os.path.exists(output_path):
                return True
            if attempt < max_attempts - 1:
                print(f"  ⚠️ baoyu-imagine failed (rc={res.returncode}), retrying ({attempt+2}/{max_attempts})...")
                continue
            print(f"  ❌ baoyu-imagine failed:\n{res.stderr}\n{res.stdout}")
        except subprocess.TimeoutExpired:
            if attempt < max_attempts - 1:
                print(f"  ⚠️ baoyu-imagine timed out (300s), retrying ({attempt+2}/{max_attempts})...")
                continue
            print(f"  ❌ baoyu-imagine timed out after {max_attempts} attempts (300s each).")
    return False


def _load_prompts():
    """Load all localization prompts from agents/prompts/."""
    prompts_dir = Path(agents_dir) / "prompts"
    prompts = {}
    for node in ["node1_audit", "node2_localize", "node3_reconstruct",
                 "node1_vl_audit", "node_ref_edit",
                 "node_inpaint_extract", "node_inpaint_translate"]:
        p_file = prompts_dir / f"{node}.txt"
        if p_file.exists():
            with open(p_file, 'r', encoding='utf-8') as f:
                prompts[node] = f.read()
        else:
            prompts[node] = ""
    return prompts


def _get_image_data(image_path, fmt="PNG"):
    """Read image, re-encode, return (base64, size, format, mime)."""
    import base64
    import io
    from PIL import Image
    with Image.open(image_path) as img:
        buffer = io.BytesIO()
        img.save(buffer, format=fmt)
        encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return encoded, img.size, img.format, f"image/{fmt.lower()}"


def _clean_json(text):
    if '```json' in text:
        text = text.split('```json')[1].split('```')[0]
    elif '```' in text:
        text = text.split('```')[1].split('```')[0]
    return text.strip()


def _slim_json(json_text):
    """Remove redundant metadata from Node 2 JSON to reduce prompt length."""
    try:
        import json
        data = json.loads(json_text)
        if isinstance(data, list):
            slimmed = []
            for item in data:
                slim_item = {
                    "chinese_text": item.get("chinese_text", ""),
                    "bbox": item.get("bbox") or item.get("BBox") or item.get("location"),
                }
                if "type" in item:
                    slim_item["type"] = item["type"]
                slimmed.append(slim_item)
            return json.dumps(slimmed, ensure_ascii=False)
        return json_text
    except Exception:
        return json_text


def _resolve_target_path(target_dir, stem, ext, force=False):
    """Determine output path with version management. Returns (path, reused).

    When force=False and an existing localized file is found, returns it with reused=True,
    effectively skipping re-localization for images that have already been processed.
    """
    os.makedirs(target_dir, exist_ok=True)
    if not force:
        pattern = f"{stem}_L10Ned_v*{ext}"
        existing = sorted(Path(target_dir).glob(pattern))
        if existing:
            return str(existing[-1]), True
    version = 1
    while os.path.exists(os.path.join(target_dir, f"{stem}_L10Ned_v{version}{ext}")):
        version += 1
    return os.path.join(target_dir, f"{stem}_L10Ned_v{version}{ext}"), False


def _localize_isomorphic_gemini(image_path, target_path, client, vision_model, text_model, image_model, prompts):
    """Isomorphic reconstruction using Gemini inline image editing (3-node flow).

    When text_model is Gemini, it handles both vision and translation — vision_model is ignored.
    When text_model is a non-vision model (e.g. glm-5.2), vision_model is used for Node 1.
    Node 3 (reconstruct) always uses image_model (Gemini with image generation).
    """
    import time
    image_base = os.path.basename(image_path)

    # Determine if text_model can handle vision (Gemini models can read images)
    text_model_lower = (text_model or "").lower()
    # Strip vendor prefix if present (e.g. "gemini::gemini-3.1-pro-preview")
    if "::" in text_model_lower:
        text_model_lower = text_model_lower.split("::", 1)[1]
    use_gemini_for_vision = "gemini" in text_model_lower

    # Node 1 uses text_model (Gemini) when it's a Gemini model, otherwise vision_model
    audit_model = text_model if use_gemini_for_vision else vision_model

    encoded_string, (width, height), img_format, mime_type = _get_image_data(image_path, "PNG")
    image_part = {"inline_data": {"mime_type": mime_type, "data": encoded_string}}

    # Node 1: Visual audit — uses Gemini when text_model is Gemini, otherwise vision_model
    print(f"    - Node 1: Auditing visual fingerprints ({audit_model})...")
    try:
        audit_res = client.generate_content([prompts.get("node1_audit", ""), image_part], model_name=audit_model)
        if not audit_res:
            print(f"    ❌ Node 1 failed: {audit_model} returned empty response.")
            return None
    except Exception as e:
        print(f"    ❌ Node 1 failed ({audit_model}): {e}")
        return None
    audit_json = _clean_json(audit_res)

    # Node 2: Text translation — can use a pure text model
    print(f"    - Node 2: Precision-localizing terminology ({text_model})...")
    try:
        localize_res = client.generate_content(
            prompts.get("node2_localize", "") + f"\n\nAudit JSON:\n{audit_json}", model_name=text_model)
        if not localize_res:
            print(f"    ❌ Node 2 failed: {text_model} returned empty response.")
            return None
    except Exception as e:
        print(f"    ❌ Node 2 failed ({text_model}): {e}")
        return None
    localize_json = _clean_json(localize_res)
    slimmed_localize_json = _slim_json(localize_json)

    print(f"    - Node 3: Isomorphic-reconstructing graphic layers ({image_model})...")
    reconstruct_prompt = prompts.get("node3_reconstruct", "")
    reconstruct_input = f"Translation Map JSON:\n{slimmed_localize_json}"
    image_gen_model = image_model or "gemini-3-pro-image-preview"
    fallback_model = "gemini-3.1-flash-image-preview"

    def _call_node3(model, current_image_part, retry_count=3):
        for i in range(retry_count):
            try:
                return client.generate_content(
                    [reconstruct_prompt + "\n\n" + reconstruct_input, current_image_part],
                    model_name=model, fallback=True)
            except Exception as ex:
                if "429" in str(ex):
                    wait_time = (i + 1) * 5
                    print(f"      [Wait] 429 Quota. Retrying in {wait_time}s... ({i+1}/{retry_count})")
                    time.sleep(wait_time)
                    continue
                raise ex
        return None

    try:
        response_text = _call_node3(image_gen_model, image_part)
    except Exception as e:
        print(f"      [Fallback] Node 3 ({image_gen_model}) failed: {e}")
        try:
            response_text = _call_node3(fallback_model, image_part)
        except Exception as e2:
            if "400" in str(e2):
                jpeg_data, _, _, jpeg_mime = _get_image_data(image_path, "JPEG")
                jpeg_part = {"inline_data": {"mime_type": jpeg_mime, "data": jpeg_data}}
                response_text = _call_node3(fallback_model, jpeg_part)
            else:
                print(f"    ❌ Node 3 all fallbacks failed: {e2}")
                return None

    if response_text and os.path.exists(response_text):
        if response_text.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            shutil.copy2(response_text, target_path)
            return target_path
    print(f"    ❌ Reconstruction failed for {image_base}.")
    return None


def _localize_regenerate(image_path, target_path, client, vision_model, image_model, image_vendor, prompts):
    """From-scratch regeneration: VLM audit+translate+prompt -> text-to-image (2-node)."""
    image_base = os.path.basename(image_path)

    encoded_string, (width, height), img_format, mime_type = _get_image_data(image_path, "PNG")
    image_part = {"inline_data": {"mime_type": mime_type, "data": encoded_string}}
    ar = _get_closest_aspect_ratio(width, height)

    print(f"    - Node 1: VLM audit + translate ({vision_model})...")
    prompt_text = client.generate_content(
        [prompts.get("node1_vl_audit", ""), image_part], model_name=vision_model)

    if not prompt_text or not prompt_text.strip():
        print(f"    ❌ VLM returned empty prompt for {image_base}.")
        return None

    print(f"    - Node 2: Generating localized image ({image_model})...")
    provider = image_vendor or "dashscope"
    success = _run_baoyu_imagine(
        prompt=prompt_text.strip(), output_path=target_path,
        model=image_model, provider=provider, ar=ar)
    if success:
        return target_path
    print(f"    ❌ Image generation failed for {image_base}.")
    return None


def _localize_ref_edit(image_path, target_path, client, vision_model, image_model, image_vendor, prompts):
    """Reference-image editing: VLM audit+translate -> baoyu-imagine --ref (Seedream)."""
    image_base = os.path.basename(image_path)

    encoded_string, (width, height), img_format, mime_type = _get_image_data(image_path, "PNG")
    image_part = {"inline_data": {"mime_type": mime_type, "data": encoded_string}}
    ar = _get_closest_aspect_ratio(width, height)

    print(f"    - Node 1: VLM audit + edit instruction ({vision_model})...")
    edit_instruction = client.generate_content(
        [prompts.get("node_ref_edit", ""), image_part], model_name=vision_model)

    if not edit_instruction or not edit_instruction.strip():
        print(f"    ❌ VLM returned empty instruction for {image_base}.")
        return None

    print(f"    - Node 2: Ref-edit generation ({image_model})...")
    provider = image_vendor or "seedream"
    success = _run_baoyu_imagine(
        prompt=edit_instruction.strip(), output_path=target_path,
        model=image_model, provider=provider, ref_image=image_path, ar=ar)
    if success:
        return target_path
    print(f"    ❌ Ref-edit generation failed for {image_base}.")
    return None

def _repair_truncated_json(json_text):
    """Attempt to repair truncated JSON arrays by closing open brackets.
    Counts structural brackets only, ignoring brackets inside string literals."""
    if not json_text:
        return json_text
    text = json_text.strip()
    # Remove trailing comma if present
    text = re.sub(r',\s*$', '', text)

    # Count structural brackets (outside string literals)
    in_string = False
    escape_next = False
    open_brackets = 0
    open_braces = 0
    for char in text:
        if escape_next:
            escape_next = False
            continue
        if char == '\\':
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        # Only count structural brackets (not inside strings)
        if char == '[':
            open_brackets += 1
        elif char == ']':
            open_brackets -= 1
        elif char == '{':
            open_braces += 1
        elif char == '}':
            open_braces -= 1

    # Close any unclosed braces first, then brackets
    for _ in range(max(open_braces, 0)):
        text += '}'
    for _ in range(max(open_brackets, 0)):
        text += ']'
    return text


def _localize_inpaint_render(image_path, target_path, client, vision_model, text_model, prompts):
    """Inpaint-render: VLM extract bbox -> text model translate -> PIL render on original.

    This strategy never regenerates the image with a generative model. Instead it:
      1. Uses a VLM (e.g. qwen-vl-max) to extract every text element + bounding box.
      2. Uses a text LLM (e.g. glm-4) to translate the extracted text.
      3. Uses OpenCV + PIL to clean the original text and render Chinese at exact coords.
    Guarantees 100% isomorphic layout - graphics never drift.
    """
    import json
    image_base = os.path.basename(image_path)

    encoded_string, (width, height), img_format, mime_type = _get_image_data(image_path, "PNG")
    image_part = {"inline_data": {"mime_type": mime_type, "data": encoded_string}}

    # Node 1: VLM extracts text + bounding boxes
    print(f"    - Node 1: VLM text extraction ({vision_model})...")
    extract_res = client.generate_content(
        [prompts.get("node_inpaint_extract", ""), image_part],
        model_name=vision_model)
    extract_json = _clean_json(extract_res)

    try:
        text_blocks = json.loads(extract_json)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"    \u26a0\ufe0f Initial JSON parse failed for {image_base}: {e}")
        print(f"       Attempting truncated JSON repair...")
        repaired = _repair_truncated_json(extract_json)
        try:
            text_blocks = json.loads(repaired)
            print(f"    \u2705 Repaired JSON: recovered {len(text_blocks)} text blocks.")
        except (json.JSONDecodeError, TypeError) as e2:
            print(f"    \u274c Failed to parse extraction JSON for {image_base}: {e2}")
            print(f"       Raw: {extract_json[:200] if extract_res else 'empty'}")
            return None

    if not text_blocks:
        print(f"    - No text found in {image_base}. Copying original.")
        shutil.copy2(image_path, target_path)
        return target_path

    # Validate extracted blocks: ensure each has required fields
    valid_blocks = []
    for i, block in enumerate(text_blocks):
        if not isinstance(block, dict):
            continue
        text = block.get("text", "")
        bbox = block.get("bbox") or block.get("BBox") or block.get("location")
        if not text or not bbox or len(bbox) < 4:
            print(f"    \u26a0\ufe0f Block {i} missing text or bbox, skipping: {str(block)[:80]}")
            continue
        valid_blocks.append(block)

    if len(valid_blocks) < len(text_blocks):
        print(f"    \u26a0\ufe0f {len(text_blocks) - len(valid_blocks)} blocks had missing fields.")
    text_blocks = valid_blocks

    print(f"    - Extracted {len(text_blocks)} valid text blocks.")

    # Re-serialize the validated blocks for the translation prompt
    extract_json_validated = json.dumps(text_blocks, ensure_ascii=False)

    # Node 2: Text model translates
    print(f"    - Node 2: Translation ({text_model})...")
    translate_prompt = prompts.get("node_inpaint_translate", "") + f"\n\nExtracted JSON:\n{extract_json_validated}"
    translate_res = client.generate_content(translate_prompt, model_name=text_model, fallback=True)
    localized_json = _clean_json(translate_res)

    try:
        localized_blocks = json.loads(localized_json)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"    \u26a0\ufe0f Translation JSON parse failed for {image_base}: {e}")
        print(f"       Attempting truncated JSON repair...")
        repaired = _repair_truncated_json(localized_json)
        try:
            localized_blocks = json.loads(repaired)
            print(f"    \u2705 Repaired translation JSON: recovered {len(localized_blocks)} blocks.")
        except (json.JSONDecodeError, TypeError) as e2:
            print(f"    \u274c Failed to parse translation JSON for {image_base}: {e2}")
            print(f"       Raw: {localized_json[:200] if translate_res else 'empty'}")
            # Fallback: use extracted text as-is (no translation)
            localized_blocks = text_blocks

    # Completeness check: ensure every block has chinese_text
    blocks_missing_translation = 0
    for i, block in enumerate(localized_blocks):
        chinese_text = block.get("chinese_text", "")
        if not chinese_text:
            blocks_missing_translation += 1
            # Mark block for skipping in render (leave original pixels untouched)
            # rather than re-rendering English text on a cleaned region
            block["chinese_text"] = ""
            block["_skip_render"] = True
    if blocks_missing_translation > 0:
        print(f"    \u26a0\ufe0f {blocks_missing_translation} blocks were missing chinese_text, will skip rendering for those (preserve original pixels).")

    # Block count mismatch check
    if len(localized_blocks) < len(text_blocks):
        missing_count = len(text_blocks) - len(localized_blocks)
        print(f"    \u26a0\ufe0f Translation returned {len(localized_blocks)} blocks but extraction had {len(text_blocks)}. "
              f"{missing_count} blocks may be missing from translation.")
    elif len(localized_blocks) > len(text_blocks):
        print(f"    \u26a0\ufe0f Translation returned more blocks ({len(localized_blocks)}) than extracted ({len(text_blocks)}).")

    # Check for mixed CN/EN in chinese_text (excluding brand abbreviations)
    brand_abbrevs = {"SAP", "AWS", "IBM", "API", "SaaS", "PaaS", "IaaS",
                      "AI", "ML", "NLP", "ROI", "KPI", "OKR", "SLA", "SSO",
                      "B2B", "B2C", "G2C", "ERP", "CRM", "OA", "IT", "OT",
                      "Etl", "ETL", "BI", "DCMM"}
    mixed_count = 0
    for block in localized_blocks:
        chinese_text = block.get("chinese_text", "")
        if not chinese_text:
            continue
        # Find English words in the chinese_text
        eng_words = re.findall(r'[A-Za-z]{2,}', chinese_text)
        for word in eng_words:
            if word.upper() not in brand_abbrevs and word not in brand_abbrevs:
                mixed_count += 1
                break
    if mixed_count > 0:
        print(f"    \u26a0\ufe0f {mixed_count} blocks may contain untranslated English words (excluding brand abbreviations).")

    print(f"    - Translation complete: {len(localized_blocks)} blocks.")

    # Node 3: Pixel-level rendering
    print(f"    - Node 3: Pixel-level rendering (OpenCV + PIL)...")
    try:
        from inpaint_renderer import render_localized_image
    except ImportError:
        # Try relative import
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "inpaint_renderer",
            os.path.join(os.path.dirname(__file__), "inpaint_renderer.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        render_localized_image = mod.render_localized_image

    success = render_localized_image(image_path, localized_blocks, target_path)
    if success:
        print(f"    \u2705 Rendered: {os.path.basename(target_path)}")
        print(f"    \ud83d\udcca Summary: {len(text_blocks)} extracted \u2192 {len(localized_blocks)} translated \u2192 rendered to {os.path.basename(target_path)}")
        return target_path
    print(f"    \u274c Rendering failed for {image_base}.")
    return None


def run_single_localization(image_path, target_dir, strategy="regenerate",
                            vision_model="qwen-vl-max", image_model=None,
                            image_vendor=None, text_model="gemini-3.1-pro-preview",
                            force=False, client=None):
    """Localize a single image. Returns target_path or None."""
    if client is None:
        client = get_client()
    prompts = _load_prompts()
    image_base = os.path.basename(image_path)
    stem = Path(image_base).stem
    ext = Path(image_base).suffix

    target_path, reused = _resolve_target_path(target_dir, stem, ext, force)
    if reused:
        print(f"  [Localizer] ♻️ Reusing existing: {os.path.basename(target_path)}")
        return target_path

    print(f"  [Localizer] Processing: {image_base} -> {os.path.basename(target_path)}...")

    try:
        if strategy == "isomorphic":
            return _localize_isomorphic_gemini(
                image_path, target_path, client, vision_model, text_model, image_model, prompts)
        elif strategy == "ref_edit":
            return _localize_ref_edit(
                image_path, target_path, client, vision_model, image_model, image_vendor, prompts)
        elif strategy == "inpaint_render":
            return _localize_inpaint_render(
                image_path, target_path, client, vision_model, text_model, prompts)
        else:
            return _localize_regenerate(
                image_path, target_path, client, vision_model, image_model, image_vendor, prompts)
    except Exception as e:
        print(f"    ❌ Localization failed for {image_base}: {e}")
        return None


def run_batch_localization(project_root, model_name="gemini-3.1-pro-preview", force=False,
                           vision_model="qwen-vl-max", image_model=None,
                           image_vendor=None, max_workers=4, progress_callback=None):
    """Scan assets/original and localize everything in parallel.

    Skip already-localized images: when force=False (default), images that already
    have a localized version in assets/localized/ are skipped automatically.
    Set force=True to re-localize everything.
    """
    original_dir = os.path.join(project_root, "assets", "original")
    if not os.path.exists(original_dir):
        return {}

    images = [f for f in os.listdir(original_dir)
              if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    images = [f for f in images if not f.startswith("cover")]
    if not images:
        return {}

    localized_dir = os.path.join(project_root, "assets", "localized")
    strategy = _detect_strategy(image_model, image_vendor) if (image_model or image_vendor) else "inpaint_render"
    client = get_client()

    # Pre-scan: check which images already have localized versions
    if not force:
        already_localized = []
        need_localization = []
        for filename in images:
            stem = Path(filename).stem
            ext = Path(filename).suffix
            pattern = os.path.join(localized_dir, f"{stem}_L10Ned_v*{ext}")
            import glob
            existing = sorted(glob.glob(pattern))
            if existing:
                already_localized.append(filename)
            else:
                need_localization.append(filename)

        if already_localized:
            print(f"  [Localizer] ♻️  {len(already_localized)} images already localized, skipping:")
            for f in already_localized:
                print(f"    - {f}")

        if not need_localization:
            print(f"  [Localizer] ✅ All {len(already_localized)} images already localized. Nothing to do.")
            # Build the localized_map from existing files so the workflow can do path replacement
            localized_map = {}
            for filename in already_localized:
                stem = Path(filename).stem
                ext = Path(filename).suffix
                pattern = os.path.join(localized_dir, f"{stem}_L10Ned_v*{ext}")
                existing = sorted(glob.glob(pattern))
                if existing:
                    localized_map[filename] = os.path.basename(existing[-1])
            return localized_map

        images = need_localization
        print(f"  [Localizer] {len(images)} images need localization.")

    print(f"\n🎨 [Localizer] {len(images)} images, strategy={strategy}, workers={max_workers}")

    localized_map = {}
    total = len(images)
    done_count = 0
    lock = threading.Lock()

    def _process(filename):
        nonlocal done_count
        orig_path = os.path.join(original_dir, filename)
        stem = Path(filename).stem
        ext = Path(filename).suffix

        target_path, reused = _resolve_target_path(localized_dir, stem, ext, force)
        if reused:
            with lock:
                done_count += 1
                localized_map[filename] = os.path.basename(target_path)
            if progress_callback:
                progress_callback(done_count, total, filename, "skipped", target_path)
            return

        if progress_callback:
            progress_callback(done_count + 1, total, filename, "processing", None)

        try:
            result = run_single_localization(
                orig_path, localized_dir, strategy=strategy,
                vision_model=vision_model, image_model=image_model,
                image_vendor=image_vendor, text_model=model_name,
                force=force, client=client)
            with lock:
                done_count += 1
                if result:
                    localized_map[filename] = os.path.basename(result)
                    status = "success"
                else:
                    status = "failed"
            if progress_callback:
                progress_callback(done_count, total, filename, status, result)
        except Exception as e:
            with lock:
                done_count += 1
            print(f"  ⚠️ Error localizing {filename}: {e}")
            if progress_callback:
                progress_callback(done_count, total, filename, "failed", None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(_process, images)

    print(f"  [Localizer] Done. {len(localized_map)}/{total} succeeded.")
    return localized_map


def run_standalone_localization(image_paths, output_dir,
                                vision_model="qwen-vl-max", image_model=None,
                                image_vendor=None, text_model="gemini-3.1-pro-preview",
                                max_workers=4, progress_callback=None, force=True):
    """Localize standalone image(s) - single or batch. Always creates new versions."""
    strategy = _detect_strategy(image_model, image_vendor) if (image_model or image_vendor) else "inpaint_render"
    client = get_client()
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n🎨 [Localizer] Standalone: {len(image_paths)} image(s), strategy={strategy}")
    print(f"    image_model={image_model}, image_vendor={image_vendor}, vision_model={vision_model}, text_model={text_model}")

    total = len(image_paths)
    results = []
    done_count = 0
    lock = threading.Lock()

    print(f"\n🎨 [Localizer] Standalone: {total} image(s), strategy={strategy}")

    def _process(img_path):
        nonlocal done_count
        image_base = os.path.basename(img_path)

        if progress_callback:
            progress_callback(done_count + 1, total, image_base, "processing", None)

        try:
            result = run_single_localization(
                img_path, output_dir, strategy=strategy,
                vision_model=vision_model, image_model=image_model,
                image_vendor=image_vendor, text_model=text_model,
                force=force, client=client)
            with lock:
                done_count += 1
                if result:
                    results.append({"input": img_path, "output": result, "status": "success"})
                else:
                    results.append({"input": img_path, "output": None, "status": "failed",
                                    "error": f"Localization returned None for {image_base} (strategy={strategy}, vision={vision_model}, text={text_model}, image={image_model})"})
            if progress_callback:
                progress_callback(done_count, total, image_base,
                                  "success" if result else "failed", result)
        except Exception as e:
            with lock:
                done_count += 1
                results.append({"input": img_path, "output": None,
                                 "status": "failed", "error": str(e)})
            print(f"  ⚠️ Error: {image_base}: {e}")
            if progress_callback:
                progress_callback(done_count, total, image_base, "failed", None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(_process, image_paths)

    print(f"  [Localizer] Standalone done. {sum(1 for r in results if r['output'])}/{total} succeeded.")
    return results


# Backward-compatible alias
def run_isomorphic_localization(image_path, project_root, model_name="gemini-3.1-pro-preview"):
    """Legacy entry point - delegates to run_single_localization with isomorphic strategy."""
    localized_dir = os.path.join(project_root, "assets", "localized")
    return run_single_localization(
        image_path, localized_dir, strategy="isomorphic",
        vision_model="gemini-3-pro-image-preview",
        text_model=model_name, image_model="gemini-3-pro-image-preview")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--model", default="gemini-3.1-pro-preview", help="Text model for audit/translate")
    parser.add_argument("--vision-model", default="qwen-vl-max", help="VLM for image reading (non-Gemini)")
    parser.add_argument("--image-model", default=None, help="Image generation model")
    parser.add_argument("--image-vendor", default=None, help="Image provider id (dashscope, seedream, etc.)")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run_batch_localization(
        args.project_root, model_name=args.model, force=args.force,
        vision_model=args.vision_model, image_model=args.image_model,
        image_vendor=args.image_vendor, max_workers=args.max_workers)

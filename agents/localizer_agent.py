import os
import sys
import shutil
import subprocess
import argparse
import concurrent.futures
import threading
from pathlib import Path

# Add common and agents to path
agents_dir = os.path.dirname(os.path.abspath(__file__))
postfdry_root = os.path.dirname(agents_dir)
common_dir = os.path.abspath(os.path.join(postfdry_root, "..", "common"))

for d in [agents_dir, common_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from llm_utils import get_client


def _detect_strategy(image_model):
    """Determine localization strategy based on the configured image model."""
    if not image_model:
        return "isomorphic"
    m = image_model.lower()
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
    fallback = "/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-imagine/scripts/main.ts"
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
        npx_bin = shutil.which("npx") or "/opt/homebrew/bin/npx"
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
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if res.returncode == 0 and os.path.exists(output_path):
        return True
    print(f"  ❌ baoyu-imagine failed:\n{res.stderr}\n{res.stdout}")
    return False


def _load_prompts():
    """Load all localization prompts from agents/prompts/."""
    prompts_dir = Path(agents_dir) / "prompts"
    prompts = {}
    for node in ["node1_audit", "node2_localize", "node3_reconstruct",
                 "node1_vl_audit", "node_ref_edit"]:
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
    """Determine output path with version management. Returns (path, reused)."""
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


def _localize_isomorphic_gemini(image_path, target_path, client, model_name, image_model, prompts):
    """Isomorphic reconstruction using Gemini inline image editing (3-node flow)."""
    import time
    image_base = os.path.basename(image_path)

    encoded_string, (width, height), img_format, mime_type = _get_image_data(image_path, "PNG")
    image_part = {"inline_data": {"mime_type": mime_type, "data": encoded_string}}

    print(f"    - Node 1: Auditing visual fingerprints...")
    audit_res = client.generate_content([prompts.get("node1_audit", ""), image_part], model_name=model_name)
    audit_json = _clean_json(audit_res)

    print(f"    - Node 2: Precision-localizing terminology...")
    localize_res = client.generate_content(
        prompts.get("node2_localize", "") + f"\n\nAudit JSON:\n{audit_json}", model_name=model_name)
    localize_json = _clean_json(localize_res)
    slimmed_localize_json = _slim_json(localize_json)

    print(f"    - Node 3: Isomorphic-reconstructing graphic layers...")
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
                raise

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
                image_path, target_path, client, text_model, image_model, prompts)
        elif strategy == "ref_edit":
            return _localize_ref_edit(
                image_path, target_path, client, vision_model, image_model, image_vendor, prompts)
        else:
            return _localize_regenerate(
                image_path, target_path, client, vision_model, image_model, image_vendor, prompts)
    except Exception as e:
        print(f"    ❌ Localization failed for {image_base}: {e}")
        return None


def run_batch_localization(project_root, model_name="gemini-3.1-pro-preview", force=False,
                           vision_model="qwen-vl-max", image_model=None,
                           image_vendor=None, max_workers=4, progress_callback=None):
    """Scan assets/original and localize everything in parallel."""
    original_dir = os.path.join(project_root, "assets", "original")
    if not os.path.exists(original_dir):
        return {}

    images = [f for f in os.listdir(original_dir)
              if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    images = [f for f in images if not f.startswith("cover")]
    if not images:
        return {}

    localized_dir = os.path.join(project_root, "assets", "localized")
    strategy = _detect_strategy(image_model) if image_model else "isomorphic"
    client = get_client()

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
    strategy = _detect_strategy(image_model) if image_model else "regenerate"
    client = get_client()
    os.makedirs(output_dir, exist_ok=True)

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
                results.append({"input": img_path, "output": result,
                                 "status": "success" if result else "failed"})
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

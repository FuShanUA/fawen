import os
import sys
import re
import shutil
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

# Add common and agents to path
agents_dir = os.path.dirname(os.path.abspath(__file__))
postfdry_root = os.path.dirname(agents_dir)
common_dir = os.path.abspath(os.path.join(postfdry_root, "..", "common"))

for d in [agents_dir, common_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from llm_utils import get_client

def run_isomorphic_localization(image_path, project_root, model_name="gemini-3.1-pro-preview"):
    """
    Performs full Infographic Localization on a single image.
    Audit -> Translate -> Reconstruct
    """
    client = get_client()
    image_base = os.path.basename(image_path)
    stem = Path(image_base).stem
    ext = Path(image_base).suffix

    localized_dir = os.path.join(project_root, "assets", "localized")
    if not os.path.exists(localized_dir): os.makedirs(localized_dir)

    # Versioning & Naming Convention: OriginalName_L10Ned_v1.ext
    version = 1
    target_name = f"{stem}_L10Ned_v{version}{ext}"
    target_path = os.path.join(localized_dir, target_name)

    # Ensure uniqueness if somehow multiple versions are generated in same run (unlikely but safe)
    while os.path.exists(target_path):
        version += 1
        target_name = f"{stem}_L10Ned_v{version}{ext}"
        target_path = os.path.join(localized_dir, target_name)

    print(f"  [Localizer] Processing: {image_base} -> {target_name}...")

    # Load prompts from central Infographic Localizer skill
    prompts_dir = Path(r"/Users/shanfu/cc/.agents/skills/Infographic_Localizer/prompts")
    prompts = {}
    for node in ["node1_audit", "node2_localize", "node3_reconstruct"]:
        p_file = prompts_dir / f"{node}.txt"
        if p_file.exists():
            with open(p_file, 'r', encoding='utf-8') as f:
                prompts[node] = f.read()
        else:
            prompts[node] = ""

    def _clean_json(text):
        if '```json' in text: text = text.split('```json')[1].split('```')[0]
        elif '```' in text: text = text.split('```')[1].split('```')[0]
        return text.strip()

    def _slim_json(json_text):
        """Removes redundant metadata from Node 2 JSON to reduce prompt length."""
        try:
            import json
            data = json.loads(json_text)
            if isinstance(data, list):
                slimmed = []
                for item in data:
                    # Keep only essential fields for reconstruction
                    slim_item = {
                        "chinese_text": item.get("chinese_text", ""),
                        "bbox": item.get("bbox") or item.get("BBox") or item.get("location"),
                    }
                    if "type" in item: slim_item["type"] = item["type"]
                    slimmed.append(slim_item)
                return json.dumps(slimmed, ensure_ascii=False)
            return json_text
        except:
            return json_text

    try:
        import base64
        import time
        from PIL import Image
        import io

        # [CRITICAL FIX] Detect actual format and re-encode to PNG to avoid "Invalid Argument" (MIME mismatch)
        # Some images might have .png extension but contain WEBP data.
        def _get_image_data(fmt="PNG"):
            with Image.open(image_path) as img:
                buffer = io.BytesIO()
                img.save(buffer, format=fmt)
                encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
                return encoded, img.size, img.format, f"image/{fmt.lower()}"

        encoded_string, (width, height), img_format, mime_type = _get_image_data("PNG")

        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": encoded_string
            }
        }

        # Node 1: Audit
        print(f"    - Node 1: Auditing visual fingerprints...")
        audit_res = client.generate_content([prompts.get("node1_audit", ""), image_part], model_name=model_name)
        audit_json = _clean_json(audit_res)

        # Node 2: Localize
        print(f"    - Node 2: Precision-localizing terminology...")
        localize_res = client.generate_content(prompts.get("node2_localize", "") + f"\n\nAudit JSON:\n{audit_json}", model_name=model_name)
        localize_json = _clean_json(localize_res)

        # [PROMPT SLIMMING] Node 3 doesn't need original text or reasoning, just target text and bboxes
        slimmed_localize_json = _slim_json(localize_json)

        # Node 3: Reconstruct
        print(f"    - Node 3: Isomorphic-reconstructing graphic layers...")
        reconstruct_prompt = prompts.get("node3_reconstruct", "")
        reconstruct_input = f"Translation Map JSON:\n{slimmed_localize_json}"

        # Ensure we use high-fidelity image gen variant for reconstruction
        image_gen_model = "gemini-3-pro-image-preview"
        fallback_model = "gemini-3.1-flash-image-preview"

        # DEBUG: Check image size and prompt length
        print(f"      [Debug] Image Size: {width}x{height}, Format: {img_format}")
        print(f"      [Debug] Prompt Length: {len(reconstruct_prompt) + len(reconstruct_input)} chars")

        def _call_node3(model, current_image_part, retry_count=3):
            for i in range(retry_count):
                try:
                    return client.generate_content(
                        [reconstruct_prompt + "\n\n" + reconstruct_input, current_image_part],
                        model_name=model,
                        fallback=True
                    )
                except Exception as ex:
                    err_msg = str(ex)
                    if "429" in err_msg:
                        wait_time = (i + 1) * 5
                        print(f"      [Wait] 429 Quota Exhausted. Retrying in {wait_time}s... ({i+1}/{retry_count})")
                        time.sleep(wait_time)
                        continue
                    raise ex
            return None

        try:
            response_text = _call_node3(image_gen_model, image_part)
        except Exception as e:
            err_str = str(e)
            print(f"      [Debug] Node 3 (Pro) failed: {err_str}")

            # [FALLBACK 1] Try Flash model if Pro fails (400 or other)
            print(f"      [Fallback] Attempting Node 3 with Flash model...")
            try:
                response_text = _call_node3(fallback_model, image_part)
            except Exception as e2:
                # [FALLBACK 2] If still failing with 400, try JPEG encoding
                if "400" in str(e2):
                    print(f"      [Fallback] Attempting Node 3 with JPEG encoding...")
                    try:
                        jpeg_data, _, _, jpeg_mime = _get_image_data("JPEG")
                        jpeg_part = {"inline_data": {"mime_type": jpeg_mime, "data": jpeg_data}}
                        response_text = _call_node3(fallback_model, jpeg_part)
                    except:
                        raise e2
                else:
                    raise e2

        if response_text and os.path.exists(response_text):
            if response_text.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                shutil.copy2(response_text, target_path)
                print(f"    ✅ Localized: {target_path}")
                return target_path

        print(f"    ❌ Reconstruction failed to return an image for {image_base}.")
        return None

    except Exception as e:
        print(f"    ❌ Localization failed for {image_base}: {e}")
        return None

def run_batch_localization(project_root, model_name="gemini-3.1-pro-preview", force=False):
    """Scan assets/original and localize everything."""
    original_dir = os.path.join(project_root, "assets", "original")
    if not os.path.exists(original_dir):
        return

    images = [f for f in os.listdir(original_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    if not images:
        return

    print(f"\n🎨 [Localizer] Found {len(images)} original images. Starting automatic localization...")

    localized_dir = os.path.join(project_root, "assets", "localized")
    if not os.path.exists(localized_dir): os.makedirs(localized_dir)

    localized_map = {}
    skipped_count = 0
    new_localized_count = 0

    for filename in images:
        # Avoid localizing system covers
        if filename.startswith("cover"): continue

        # IDEMPOTENCY: Skip if a localized version already exists (checking for any version)
        # Naming pattern: filename_L10Ned_v*.ext
        stem = Path(filename).stem
        ext = Path(filename).suffix
        pattern = f"{stem}_L10Ned_v*{ext}"
        existing = list(Path(localized_dir).glob(pattern))

        if existing:
            # Pick the latest one
            latest = sorted(existing)[-1]

            if not force:
                # Normal behavior: use the latest existing one
                localized_map[filename] = latest.name
                skipped_count += 1
                continue
            else:
                # Force mode: proceed to create a new version
                print(f"  [Skill] 强制重制新版本: {filename} (基于 {latest.name})")

        orig_path = os.path.join(original_dir, filename)
        print(f"  [Skill] Localizing: {filename}...")
        try:
            localized_file_path = run_isomorphic_localization(orig_path, project_root, model_name=model_name)
            if localized_file_path:
                localized_map[filename] = os.path.basename(localized_file_path)
                new_localized_count += 1
        except Exception as e:
            print(f"  ⚠️ Error localizing {filename}: {e}")

    if skipped_count > 0:
        print(f"  [Skill] {skipped_count} images were already localized, skipping.")
    if new_localized_count > 0:
        print(f"  [Skill] Successfully localized {new_localized_count} new images.")

    return localized_map

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run_batch_localization(args.project_root, model_name=args.model, force=args.force)
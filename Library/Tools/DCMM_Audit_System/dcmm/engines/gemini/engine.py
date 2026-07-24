"""Gemini audit engine: single-shot PDF audit via Vertex AI.

Gemini handles PDFs natively (up to ~1000 pages per request),
so the entire audit is one generate_content call with system_instruction.
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any

from ..base import AuditEngine
from .prompts import HARD_RULES, build_audit_prompt

logger = logging.getLogger("GeminiEngine")


class GeminiEngine(AuditEngine):
    display_name = "Gemini (Vertex AI)"
    engine_id = "gemini"

    def __init__(self, config):
        super().__init__(config)
        self._init_vertex()

    def _init_vertex(self):
        import vertexai
        from vertexai.generative_models import GenerativeModel

        if self.cfg.vertex_sa_key_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.cfg.vertex_sa_key_path
        vertexai.init(project=self.cfg.vertex_project_id, location=self.cfg.vertex_location)
        self._model_cls = GenerativeModel
        self._flash_model = GenerativeModel(
            self.cfg.text_model, system_instruction=HARD_RULES,
        )
        self._pro_model = GenerativeModel(
            self.cfg.text_model, system_instruction=HARD_RULES,
        )
        logger.info(f"Initialized Vertex AI: {self.cfg.vertex_project_id}")

    def audit_enterprise(self, ent_name: str, pdf_dir: str,
                         gcs_uris: list[str] | None = None,
                         target_level: str = "3级",
                         use_pro: bool = False,
                         **kwargs) -> dict[str, Any]:
        """Audit one enterprise with Gemini.

        Either provide gcs_uris (pre-uploaded PDFs) or pdf_dir (local).
        When pdf_dir is given, uploads to GCS first.
        """
        from vertexai.generative_models import Part, GenerationConfig
        from ...core.pdf import extract_text

        timing = {}
        total_start = time.time()

        try:
            # Resolve PDF parts
            if gcs_uris:
                parts = [Part.from_uri(uri, mime_type="application/pdf") for uri in gcs_uris]
            elif pdf_dir:
                parts = self._upload_local_pdfs(pdf_dir)
            else:
                return self._error_result(ent_name, "No PDFs provided", timing, total_start)

            # Build prompt
            prompt = build_audit_prompt(
                ent_name, target_level,
                self.rules_content, self.negative_cases_content,
            )
            parts.append(Part.from_text(prompt))

            model = self._pro_model if use_pro else self._flash_model
            config = GenerationConfig(temperature=0.0, top_p=1.0, max_output_tokens=8192)

            # Call with retry
            t0 = time.time()
            report_text = ""
            for attempt in range(6):
                try:
                    response = model.generate_content(parts, generation_config=config)
                    if response.text:
                        report_text = response.text
                        break
                    logger.warning(f"Empty response for {ent_name}, retrying...")
                except Exception as e:
                    delay = 30 * (attempt + 1)
                    logger.error(f"Error for {ent_name}: {e}. Retrying in {delay}s...")
                    time.sleep(delay)

            timing["gemini_call"] = time.time() - t0
            timing["total"] = time.time() - total_start

            if not report_text:
                report_text = f"ERROR: Failed to audit {ent_name} after 6 attempts."

            report_path = self.save_report(ent_name, report_text, timing, {})

            return {
                "name": ent_name,
                "report": report_text,
                "report_path": report_path,
                "timing": timing,
                "usage": {},
                "error": None if not report_text.startswith("ERROR") else report_text[:200],
            }

        except Exception as e:
            return self._error_result(ent_name, str(e), timing, total_start)

    def _upload_local_pdfs(self, pdf_dir: str) -> list:
        """Upload local PDFs to GCS and return Part objects."""
        from vertexai.generative_models import Part
        from google.cloud import storage

        storage_client = storage.Client()
        bucket = storage_client.bucket(self.cfg.gcs_bucket)

        parts = []
        for root, _dirs, files in os.walk(pdf_dir):
            for f in sorted(files):
                if not f.endswith('.pdf') or '完整' in f or f.startswith('._'):
                    continue
                local_path = os.path.join(root, f)
                blob_name = f"audit_batch/{f}"
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(local_path)
                uri = f"gs://{self.cfg.gcs_bucket}/{blob_name}"
                parts.append(Part.from_uri(uri, mime_type="application/pdf"))
        return parts

    def _error_result(self, ent_name, error, timing, total_start):
        timing["total"] = time.time() - total_start
        return {
            "name": ent_name,
            "report": "",
            "report_path": None,
            "timing": timing,
            "usage": {},
            "error": error[:300],
        }

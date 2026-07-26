"""Abstract base class for audit engines.

Every engine implements the same interface so the batch runner and CLI
can swap between Gemini and GLM without touching engine internals.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from ..config import EngineConfig


class AuditEngine(ABC):
    """Base contract: given an enterprise name + PDF directory, produce a report."""

    display_name: str = "Base Engine"
    engine_id: str = "base"

    def __init__(self, config: EngineConfig):
        self.cfg = config
        self.rules_content = ""
        self.negative_cases_content = ""
        self._load_rules()

    def _load_rules(self):
        """Load expert_rules.md and negative_cases.md from the engine's rules dir."""
        if os.path.exists(self.cfg.expert_rules_path):
            with open(self.cfg.expert_rules_path, "r", encoding="utf-8") as f:
                self.rules_content = f.read()
        if os.path.exists(self.cfg.negative_cases_path):
            with open(self.cfg.negative_cases_path, "r", encoding="utf-8") as f:
                self.negative_cases_content = f.read()

    @abstractmethod
    def audit_enterprise(self, ent_name: str, pdf_dir: str, **kwargs) -> dict[str, Any]:
        """Audit one enterprise.

        Returns a dict with keys:
            name:       enterprise name
            report:     full markdown report text (or error string)
            report_path: path to saved .md file
            timing:     dict of phase timings
            usage:      token usage dict
            error:      None or error string
        """
        ...

    def save_report(self, ent_name: str, report_text: str, timing: dict, usage: dict) -> str:
        """Save report to engine-scoped output dir. Returns the file path."""
        import time
        safe = ent_name[:20].replace("/", "_").replace(" ", "_")
        out_path = os.path.join(self.cfg.out_dir, f"{safe}.md")
        header = (
            f"# DCMM 审计报告 - {ent_name}\n"
            f"引擎: {self.display_name}\n"
            f"时间: {time.strftime('%Y-%m-%d %H:%M')}\n"
        )
        if timing:
            header += f"耗时: {timing}\n"
        if usage:
            header += f"Tokens: {usage}\n"
        header += f"\n---\n\n"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(header + report_text)
        return out_path

    def __repr__(self):
        return f"<{self.display_name} out={self.cfg.out_dir}>"

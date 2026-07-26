"""Per-engine configuration: loads .env.{engine} and resolves rules/output paths.

Design principle: 两套引擎互不干扰.
  - API keys and model names live in .env.gemini / .env.glm (gitignored)
  - Rules live in rules/{engine}/ (versioned)
  - Output dirs are engine-scoped to avoid result collision
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Project root = directory containing the dcmm/ package
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Shared data root (enterprise PDFs, enterprise lists, etc.)
# Can be overridden via DCMM_DATA_ROOT env var; defaults to Desktop/audit_batch
DEFAULT_DATA_ROOT = os.environ.get(
    "DCMM_DATA_ROOT",
    "/Users/shanfu/Desktop/audit_batch",
)


@dataclass
class EngineConfig:
    """Holds all configuration for a single engine run."""

    engine: str  # "gemini" | "glm"

    # --- API credentials (from .env.{engine}) ---
    api_key: str = ""
    api_base: str = ""

    # --- Models ---
    text_model: str = ""
    vision_model: str = ""

    # --- Gemini-specific ---
    vertex_project_id: str = ""
    vertex_location: str = "global"
    vertex_sa_key_path: str = ""
    gcs_bucket: str = ""

    # --- GLM-specific ---
    glm_max_tokens: int = 16000
    vl_max_tokens: int = 300
    max_workers: int = 5

    # --- Paths (resolved at load time) ---
    rules_dir: str = ""
    expert_rules_path: str = ""
    negative_cases_path: str = ""
    out_dir: str = ""
    retry_dir: str = ""
    data_root: str = ""
    enterprise_list_path: str = ""

    # --- Runtime ---
    extra: dict = field(default_factory=dict)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


def load_config(engine: str) -> EngineConfig:
    """Load and resolve configuration for the given engine.

    Reads .env (shared) then .env.{engine} (override), then fills in
    engine-scoped rules and output paths.
    """
    # Start with shared .env
    shared_env = PROJECT_ROOT / ".env"
    if shared_env.exists():
        load_dotenv(shared_env, override=False)

    # Engine-specific .env overrides everything
    engine_env = PROJECT_ROOT / f".env.{engine}"
    if engine_env.exists():
        load_dotenv(engine_env, override=True)

    cfg = EngineConfig(engine=engine)

    # Common paths
    cfg.data_root = os.environ.get("DCMM_DATA_ROOT", DEFAULT_DATA_ROOT)
    cfg.enterprise_list_path = os.environ.get(
        "DCMM_ENTERPRISE_LIST",
        os.path.join(cfg.data_root, "7月上会企业名单--三级.xlsx"),
    )

    # Engine-scoped rules
    cfg.rules_dir = str(PROJECT_ROOT / "rules" / engine)
    cfg.expert_rules_path = os.environ.get(
        f"DCMM_RULES_{engine}",
        os.path.join(cfg.rules_dir, "expert_rules.md"),
    )
    cfg.negative_cases_path = os.path.join(cfg.rules_dir, "negative_cases.md")

    # Engine-scoped output (prevents collision)
    default_out = os.path.join(cfg.data_root, "审计结果", engine)
    cfg.out_dir = os.environ.get(f"DCMM_OUT_DIR_{engine}", default_out)
    cfg.retry_dir = os.path.join(cfg.out_dir, "重试")
    os.makedirs(cfg.out_dir, exist_ok=True)
    os.makedirs(cfg.retry_dir, exist_ok=True)

    if engine == "gemini":
        cfg.vertex_project_id = os.environ.get("VERTEX_PROJECT_ID", "")
        cfg.vertex_location = os.environ.get("VERTEX_LOCATION", "global")
        cfg.vertex_sa_key_path = os.environ.get("VERTEX_SA_KEY_PATH", "")
        cfg.gcs_bucket = os.environ.get("GCS_BUCKET_NAME", "")
        cfg.text_model = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
        if cfg.vertex_sa_key_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cfg.vertex_sa_key_path

    elif engine == "glm":
        cfg.api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        cfg.api_base = os.environ.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        cfg.text_model = os.environ.get("GLM_MODEL", "glm-5.2")
        cfg.vision_model = os.environ.get("VL_MODEL", "qwen-vl-max")
        cfg.glm_max_tokens = int(os.environ.get("GLM_MAX_TOKENS", "16000"))
        cfg.vl_max_tokens = int(os.environ.get("VL_MAX_TOKENS", "300"))
        cfg.max_workers = int(os.environ.get("DCMM_MAX_WORKERS", "5"))

    return cfg


# Convenience: project paths
RULES_ROOT = PROJECT_ROOT / "rules"
LEGACY_ROOT = PROJECT_ROOT / "legacy"

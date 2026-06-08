import os
import sys
import time
import threading
import concurrent.futures
import re
import json
import requests
import base64
import warnings
from enum import Enum
from typing import List, Dict, Optional, Union, Tuple

# Suppress SDK migration and version warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# Try to load keys from .env if present
def get_env_path():
    # Dynamic resolution based on file structure
    current_dir = os.path.dirname(os.path.abspath(__file__))
    postfdry_root = os.path.dirname(current_dir)
    library_dir = os.path.abspath(os.path.join(postfdry_root, "..", ".."))
    cc_dir = os.path.abspath(os.path.join(library_dir, ".."))

    # Return the primary GUI-managed env file first
    p = os.path.join(library_dir, ".env")
    if os.path.exists(p): return p
    
    # Global/Project .env files first
    potentials = [
        os.path.join(cc_dir, ".env"),
        os.path.join(cc_dir, ".baoyu-skills", ".env"),
        os.path.join(postfdry_root, ".env")
    ]
    for p in potentials:
        if os.path.exists(p): return p

    if getattr(sys, 'frozen', False):
        USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "AutoSub")
        return os.path.join(USER_DATA_DIR, ".env")

    # Search upwards for .env starting from current file
    curr = os.path.dirname(os.path.abspath(__file__))
    while curr != os.path.dirname(curr): # Not at root
        potential = os.path.join(curr, ".env")
        if os.path.exists(potential): return potential
        curr = os.path.dirname(curr)

    # Default to the parent directory of this script's folder (e.g. Library/Tools)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, ".env")

ENV_PATH = get_env_path()

try:
    from dotenv import load_dotenv  # type: ignore
    # Load all potential env files in cascade order (earlier ones are overridden by later ones)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    postfdry_root = os.path.dirname(current_dir)
    library_dir = os.path.abspath(os.path.join(postfdry_root, "..", ".."))
    cc_dir = os.path.abspath(os.path.join(library_dir, ".."))
    for p in [
        os.path.join(cc_dir, ".baoyu-skills", ".env"),
        os.path.join(cc_dir, ".env"),
        os.path.join(library_dir, ".env"),
        os.path.join(postfdry_root, ".env")
    ]:
        if os.path.exists(p):
            load_dotenv(p, override=True)
except ImportError:
    pass

class LLMProvider(Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    MOONSHOT = "moonshot"
    DASHSCOPE = "dashscope"
    ZHIPU = "zhipu"
    DEEPSEEK = "deepseek"
    SILICONFLOW = "siliconflow"
    VERTEX = "vertex"
    MINIMAX = "minimax"

class RateLimiter:
    """Simple thread-safe rate limiter based on RPM."""
    def __init__(self, rpm: int):
        self.rpm = rpm
        self.interval = 60.0 / rpm
        self.last_request_time = 0.0
        self.lock = threading.Lock()

    def wait(self):
        sleep_time = 0
        with self.lock:
            current_time = time.time()
            next_available = self.last_request_time + self.interval
            if next_available > current_time:
                sleep_time = next_available - current_time
                self.last_request_time = next_available
            else:
                self.last_request_time = current_time
        if sleep_time > 0:
            time.sleep(sleep_time)

class LLMClient:
    def __init__(self, api_key: Optional[str] = None, provider: Optional[LLMProvider] = None):
        self.api_keys = {
            LLMProvider.GEMINI: api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            LLMProvider.OPENAI: os.environ.get("OPENAI_API_KEY"),
            LLMProvider.MOONSHOT: os.environ.get("MOONSHOT_API_KEY"),
            LLMProvider.DASHSCOPE: os.environ.get("DASHSCOPE_API_KEY"),
            LLMProvider.ZHIPU: os.environ.get("ZHIPUAI_API_KEY") or os.environ.get("ZHIPU__API_KEY"),
            LLMProvider.DEEPSEEK: os.environ.get("DEEPSEEK_API_KEY"),
            LLMProvider.SILICONFLOW: os.environ.get("SILICONFLOW_API_KEY"),
            LLMProvider.VERTEX: os.environ.get("VERTEX_SA_KEY_PATH") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
            LLMProvider.MINIMAX: os.environ.get("MINIMAX_API_KEY"),
        }

        # Apply default gcloud application default credentials path if not specified
        adc_path = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        if not self.api_keys[LLMProvider.VERTEX] and os.path.exists(adc_path):
            self.api_keys[LLMProvider.VERTEX] = adc_path

        # Vertex specific configs
        self.vertex_project = os.environ.get("VERTEX_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "gen-lang-client-0991632900"
        # The .baoyu-skills/.env contains an old project (gen-lang-client-0763492487) that lacks permissions.
        # Override with the verified ADC-bound project.
        _BROKEN_PROJECTS = {"gen-lang-client-0763492487"}
        if self.vertex_project in _BROKEN_PROJECTS:
            self.vertex_project = "gen-lang-client-0991632900"
        self.vertex_location = os.environ.get("VERTEX_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION")
        if not self.vertex_location:
            self.vertex_location = "global"  # Default to global as requested

        self.last_provider = None

        # Read .env sequentially to establish cascade order
        self.ordered_configs = []
        # Multi-env cascade loading: earlier ones are overwritten by later ones
        current_dir = os.path.dirname(os.path.abspath(__file__))
        postfdry_root = os.path.dirname(current_dir)
        library_dir = os.path.abspath(os.path.join(postfdry_root, "..", ".."))
        cc_dir = os.path.abspath(os.path.join(library_dir, ".."))
        env_cascade = [
            os.path.join(cc_dir, ".baoyu-skills", ".env"),
            os.path.join(cc_dir, ".env"),
            os.path.join(library_dir, ".env"),
            os.path.join(postfdry_root, ".env")
        ]
        parsed_keys = {}
        for p in env_cascade:
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'): continue
                            if '=' in line:
                                key, val = line.split('=', 1)
                                key = key.strip()
                                val = val.strip().strip("'").strip('"')
                                if not val: continue

                                # Populate os.environ dynamically (later wins/overwrites)
                                os.environ[key] = val
                                parsed_keys[key] = val
                except:
                    pass

        # Apply mapped values from parsed_keys
        for key, val in parsed_keys.items():
            prov, mod = None, None
            if key in ["GEMINI_API_KEY", "GOOGLE_API_KEY"]: prov, mod = LLMProvider.GEMINI, "gemini-3.1-flash-preview"
            elif key == "OPENAI_API_KEY": prov, mod = LLMProvider.OPENAI, "gpt-4o"
            elif key == "MOONSHOT_API_KEY": prov, mod = LLMProvider.MOONSHOT, "moonshot-v1-8k"
            elif key == "DASHSCOPE_API_KEY": prov, mod = LLMProvider.DASHSCOPE, "deepseek-v4-pro"
            elif key in ["ZHIPUAI_API_KEY", "ZHIPU_API_KEY"]: prov, mod = LLMProvider.ZHIPU, "glm-4"
            elif key == "DEEPSEEK_API_KEY": prov, mod = LLMProvider.DEEPSEEK, "deepseek-chat"
            elif key == "SILICONFLOW_API_KEY": prov, mod = LLMProvider.SILICONFLOW, "deepseek-ai/DeepSeek-V3"
            elif key == "VERTEX_SA_KEY_PATH": prov, mod = LLMProvider.VERTEX, "gemini-3.1-flash-preview"
            elif key == "MINIMAX_API_KEY": prov, mod = LLMProvider.MINIMAX, "minimax-m3"

            if prov:
                # Update or append
                existing_idx = -1
                for idx, (p_prov, _, _) in enumerate(self.ordered_configs):
                    if p_prov == prov:
                        existing_idx = idx
                        break
                if existing_idx != -1:
                    self.ordered_configs[existing_idx] = (prov, val, mod)
                else:
                    self.ordered_configs.append((prov, val, mod))
                self.api_keys[prov] = val

        # Cloud/Environment backup: Add from os.environ if not already present in ordered_configs
        env_mappings = [
            ("GEMINI_API_KEY", LLMProvider.GEMINI, "gemini-2.0-flash"),
            ("GOOGLE_API_KEY", LLMProvider.GEMINI, "gemini-2.0-flash"),
            ("OPENAI_API_KEY", LLMProvider.OPENAI, "gpt-4o"),
            ("MOONSHOT_API_KEY", LLMProvider.MOONSHOT, "moonshot-v1-8k"),
            ("DASHSCOPE_API_KEY", LLMProvider.DASHSCOPE, "deepseek-v4-pro"),
            ("ZHIPUAI_API_KEY", LLMProvider.ZHIPU, "glm-4"),
            ("ZHIPU_API_KEY", LLMProvider.ZHIPU, "glm-4"),
            ("DEEPSEEK_API_KEY", LLMProvider.DEEPSEEK, "deepseek-chat"),
            ("SILICONFLOW_API_KEY", LLMProvider.SILICONFLOW, "deepseek-ai/DeepSeek-V3"),
            ("VERTEX_SA_KEY_PATH", LLMProvider.VERTEX, "gemini-3.1-flash-lite-preview"),
            ("GOOGLE_APPLICATION_CREDENTIALS", LLMProvider.VERTEX, "gemini-3.1-flash-lite-preview"),
            ("MINIMAX_API_KEY", LLMProvider.MINIMAX, "minimax-m3"),
        ]
        
        existing_providers = {prov for prov, _, _ in self.ordered_configs}
        for env_var, prov, default_model in env_mappings:
            val = os.environ.get(env_var)
            if val and prov not in existing_providers:
                self.ordered_configs.append((prov, val, default_model))
                existing_providers.add(prov)

        # Default tier settings
        tier_str = os.environ.get("LLM_TIER", "tier1").lower()
        if tier_str == "free":
            self.rpm_limit = 10
            self.max_workers = 1
        elif tier_str == "tier1":
            self.rpm_limit = 50
            self.max_workers = 5
        else:
            self.rpm_limit = 500
            self.max_workers = 20

        self.limiter = RateLimiter(self.rpm_limit)
        self._gemini_configured = False
        self._vertex_configured = False
        self._vertex_current_location = None

    def generate_content_with_provider(self, prompt: str, provider: LLMProvider, model_name: str = "gemini-3.1-flash-preview", fallback: bool = True) -> tuple[bool, str]:
        """Generate content using specific provider and model. Returns (success, content/error)."""
        errors = []
        try:
            api_key = self.api_keys.get(provider)
            res = self._execute_provider_call(provider, model_name, prompt, api_key)  # type: ignore
            if res: return True, res
            errors.append(f"{provider.value}: No response")
        except Exception as e:
            errors.append(f"{provider.value}: {str(e)}")

        if fallback:
            for p, k, m in self.ordered_configs:
                if p == provider: continue
                try:
                    res = self._execute_provider_call(p, m, prompt, k)
                    if res: return True, res
                except Exception as e:
                    errors.append(f"{p.value}: {str(e)}")

        return False, f"All attempts failed: {'; '.join(errors)}"

    def set_provider_key(self, provider: LLMProvider, api_key: str):
        """Update API key for a specific provider at runtime."""
        if api_key:
            self.api_keys[provider] = api_key
            # Handle special configuration if needed
            if provider == LLMProvider.GEMINI:
                self._gemini_configured = False # Force reconfiguration on next call
            elif provider == LLMProvider.VERTEX:
                self._vertex_configured = False

    def _get_provider(self, model_name: str) -> LLMProvider:
        model_name = model_name.lower()
        if "gpt" in model_name: return LLMProvider.OPENAI
        if "moonshot" in model_name or "kimi" in model_name: return LLMProvider.MOONSHOT
        if "qwen" in model_name: return LLMProvider.DASHSCOPE
        if "glm" in model_name: return LLMProvider.ZHIPU
        if "minimax" in model_name or "abab" in model_name: return LLMProvider.MINIMAX
        
        if "deepseek" in model_name:
            # SiliconFlow pattern (e.g. deepseek-ai/DeepSeek-V3 or deepseek-ai/DeepSeek-R1)
            if "/" in model_name:
                if self.api_keys.get(LLMProvider.SILICONFLOW):
                    return LLMProvider.SILICONFLOW
            
            # Check keys availability to route dynamically
            has_deepseek = bool(self.api_keys.get(LLMProvider.DEEPSEEK))
            has_dashscope = bool(self.api_keys.get(LLMProvider.DASHSCOPE))
            has_silicon = bool(self.api_keys.get(LLMProvider.SILICONFLOW))
            
            if has_deepseek:
                return LLMProvider.DEEPSEEK
            if has_dashscope:
                return LLMProvider.DASHSCOPE
            if has_silicon:
                return LLMProvider.SILICONFLOW
                
            return LLMProvider.DEEPSEEK
        if "gemini" in model_name or "imagen" in model_name:
            # Route Google models to Vertex ONLY if Vertex variables are explicitly defined in environment.
            # Otherwise, if a Gemini Developer API key is present, prioritize LLMProvider.GEMINI for better stability and quota.
            has_explicit_vertex = any(os.environ.get(k) for k in ["VERTEX_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "VERTEX_SA_KEY_PATH", "GOOGLE_APPLICATION_CREDENTIALS"])
            if has_explicit_vertex:
                return LLMProvider.VERTEX
            
            if self.api_keys.get(LLMProvider.GEMINI):
                return LLMProvider.GEMINI
                
            if self.vertex_project:
                return LLMProvider.VERTEX
        return LLMProvider.GEMINI

    def _call_openai_compatible(self, model_name: str, prompt: str, base_url: str, api_key: str) -> Optional[str]:
        if not api_key:
            print(f"❌ Error: API Key for {model_name} not found.")
            return None

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        # Omit temperature for reasoning/thinking models (like o1, o3, reasoner, k2.5, k2.6) to avoid 400 Bad Request
        is_reasoning = any(x in model_name.lower() for x in ["o1", "o3", "reasoner", "k2.6", "k2.5"])
        data = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}]
        }
        if not is_reasoning:
            data["temperature"] = 0.3

        self.limiter.wait()
        try:
            response = requests.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=300)
            if response.status_code != 200:
                try:
                    err_data = response.json()
                    err_msg = err_data.get("error", {}).get("message") or err_data.get("message") or response.text
                except Exception:
                    err_msg = response.text
                raise Exception(f"API Error (Status {response.status_code}): {err_msg}")
            res_json = response.json()
            return res_json['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"❌ OpenAI-compatible API error ({model_name}): {e}")
            raise e

    def _call_gemini(self, model_name: str, content: Union[str, List], api_key: str) -> Optional[str]:
        if not api_key:
            print("❌ Error: Gemini API Key not found.")
            return None

        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=api_key)
            self._gemini_configured = True

            model = genai.GenerativeModel(model_name)
            self.limiter.wait()

            if isinstance(content, list):
                processed_parts = []
                for p in content:
                    if isinstance(p, dict) and "inline_data" in p:
                        import base64
                        mime_type = p["inline_data"]["mime_type"]
                        data_bytes = base64.b64decode(p["inline_data"]["data"])
                        processed_parts.append({
                            "mime_type": mime_type,
                            "data": data_bytes
                        })
                    else:
                        processed_parts.append(p)
                content = processed_parts

            response = model.generate_content(content)

            # Handle response
            try:
                if response.text:
                    return response.text.strip()
            except (ValueError, AttributeError):
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if candidate.finish_reason.name == 'SAFETY':
                        raise Exception("Gemini blocked the response due to safety filters.")
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            if "image" in part.inline_data.mime_type:
                                import tempfile
                                temp_path = os.path.join(tempfile.gettempdir(), f"gemini_out_{int(time.time()*1000)}.png")
                                with open(temp_path, "wb") as f:
                                    f.write(part.inline_data.data)
                                return temp_path
                return None
            return None
        except Exception as e:
            print(f"❌ Gemini API error: {e}")
            raise Exception(f"Gemini API Error: {e}")

    def _call_vertex(self, model_name: str, content: Union[str, List], sa_key_path: str) -> Optional[str]:
        if not sa_key_path and not self.vertex_project:
            print("❌ Error: Vertex requires either a SA Key Path or GOOGLE_CLOUD_PROJECT set for ADC.")
            return None

        try:
            import vertexai  # type: ignore
            from vertexai.generative_models import GenerativeModel, Part  # type: ignore

            # 动态计算本轮请求所需要的 region
            required_loc = self.vertex_location or "global"

            # 强力热重启初始化：若当前实际 loc 与 required_loc 不一致，或者尚未初始化
            if not self._vertex_configured or getattr(self, "_vertex_current_location", None) != required_loc:
                if sa_key_path:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_key_path
                
                print(f"⚙️ Initializing/Switching Vertex AI: Project={self.vertex_project}, Location={required_loc}")
                vertexai.init(project=self.vertex_project, location=required_loc)
                self._vertex_configured = True
                self._vertex_current_location = required_loc

            model = GenerativeModel(model_name)
            self.limiter.wait()

            # Handle multimodal input if list provided
            if isinstance(content, list):
                processed_parts = []
                for p in content:
                    if isinstance(p, dict) and "inline_data" in p:
                        # Convert genai format to vertex Part
                        import base64
                        processed_parts.append(Part.from_data(
                            data=base64.b64decode(p["inline_data"]["data"]),
                            mime_type=p["inline_data"]["mime_type"]
                        ))
                    else:
                        processed_parts.append(p)
                response = model.generate_content(processed_parts)
            else:
                response = model.generate_content(content)

            # Handle response - prioritize image output for visual models
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.finish_reason.name == 'SAFETY':
                    raise Exception("Vertex AI blocked the response due to safety filters.")

                # First pass: check for images
                for part in candidate.content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        if "image" in part.inline_data.mime_type:
                            import tempfile
                            temp_path = os.path.join(tempfile.gettempdir(), f"vertex_out_{int(time.time()*1000)}.png")
                            with open(temp_path, "wb") as f:
                                    f.write(part.inline_data.data)
                            return temp_path

                # Second pass: check for text
                try:
                    if response.text:
                        return response.text.strip()
                except (ValueError, AttributeError):
                    # If .text fails but we have text parts, join them
                    text_parts = []
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                    if text_parts:
                        return "\n".join(text_parts).strip()

            return None
        except Exception as e:
            err_str = str(e)
            
            print(f"❌ Vertex API error: {e}")
            raise Exception(f"Vertex API Error: {e}")

    def _execute_provider_call(self, provider: LLMProvider, model_name: str, content: Union[str, List], api_key: str) -> Optional[str]:
        if provider == LLMProvider.GEMINI:
            return self._call_gemini(model_name, content, api_key)
        elif provider == LLMProvider.OPENAI:
            if isinstance(content, list): raise Exception("Multimodal not supported for this provider yet.")
            base_url = os.environ.get("OPENAI_API_BASE") or "https://api.openai.com/v1"
            if base_url.endswith("/v1/"): base_url = base_url[:-1]
            return self._call_openai_compatible(model_name, content, base_url, api_key)
        elif provider == LLMProvider.MOONSHOT:
            if isinstance(content, list): raise Exception("Multimodal not supported for this provider yet.")
            return self._call_openai_compatible(model_name, content, "https://api.moonshot.cn/v1", api_key)
        elif provider == LLMProvider.DASHSCOPE:
            if isinstance(content, list): raise Exception("Multimodal not supported for this provider yet.")
            return self._call_openai_compatible(model_name, content, "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key)
        elif provider == LLMProvider.ZHIPU:
            if isinstance(content, list): raise Exception("Multimodal not supported for this provider yet.")
            return self._call_openai_compatible(model_name, content, "https://open.bigmodel.cn/api/paas/v4", api_key)
        elif provider == LLMProvider.DEEPSEEK:
            if isinstance(content, list): raise Exception("Multimodal not supported for this provider yet.")
            return self._call_openai_compatible(model_name, content, "https://api.deepseek.com", api_key)
        elif provider == LLMProvider.SILICONFLOW:
            if isinstance(content, list): raise Exception("Multimodal not supported for this provider yet.")
            return self._call_openai_compatible(model_name, content, "https://api.siliconflow.cn/v1", api_key)
        elif provider == LLMProvider.VERTEX:
            return self._call_vertex(model_name, content, api_key)
        elif provider == LLMProvider.MINIMAX:
            if isinstance(content, list): raise Exception("Multimodal not supported for this provider yet.")
            return self._call_openai_compatible(model_name, content, "https://api.minimaxi.com/v1", api_key)
        return None

    def generate_content(self, content: Union[str, List], model_name: Optional[str] = None, fallback: bool = False, provider: Optional[LLMProvider] = None) -> Optional[str]:
        targets = []

        # 确定 primary provider
        primary_prov = provider
        if model_name and not primary_prov:
            primary_prov = self._get_provider(model_name)

        if primary_prov == LLMProvider.VERTEX:
            # 1. 尝试 Vertex
            v_key = self.api_keys.get(LLMProvider.VERTEX)
            v_model = model_name or "gemini-3.1-flash-lite-preview"
            targets.append((LLMProvider.VERTEX, v_key, v_model))
            
            # 2. 同厂通道回退: 如果有 Gemini API Key，允许无感回退到标准 Gemini API (避免 429 崩溃)
            gem_key = self.api_keys.get(LLMProvider.GEMINI)
            if gem_key:
                targets.append((LLMProvider.GEMINI, gem_key, v_model))
            
            # 3. 回退到百炼
            ds_key = self.api_keys.get(LLMProvider.DASHSCOPE)
            if ds_key:
                targets.append((LLMProvider.DASHSCOPE, ds_key, "deepseek-v4-pro"))
        else:
            # If user hardcoded a specific model, try it first
            if model_name:
                prov = provider or self._get_provider(model_name)
                key = self.api_keys.get(prov)
                # Vertex can run without a key if using ADC (Application Default Credentials)
                is_vertex_adc = (prov == LLMProvider.VERTEX and self.vertex_project)
                if key or is_vertex_adc:
                    targets.append((prov, key, model_name))

            # [MODIFIED] If fallback is disabled (default), we only try the primary target.
            # If fallback is enabled, we still limit it to the same provider if possible,
            # or respect the strict "no silent fallback to other brands" rule.
            if (not targets or fallback) and os.path.exists(ENV_PATH):
                 # Try to pick others from .env
                 for prov, key, mod in self.ordered_configs:
                    if prov == LLMProvider.GEMINI: continue # 过滤普通 Gemini 防止与 Vertex 冲突或混用
                    # If we already have a target for this provider, skip unless it's a different model
                    if any(t[0] == prov and t[2] == mod for t in targets): continue
                    targets.append((prov, key, mod))

            # If still nothing, fallback to available keys but ONLY the first one
            if not targets:
                for prov, key in self.api_keys.items():
                    if key and prov != LLMProvider.GEMINI: # 依然过滤普通 Gemini
                        guess = "gpt-4o"
                        if prov == LLMProvider.VERTEX: guess = "gemini-3.1-flash-lite-preview"
                        elif prov == LLMProvider.DASHSCOPE: guess = "deepseek-v4-pro"
                        targets.append((prov, key, guess))
                        break

            # [STRICT] If targets has multiple entries but fallback is False, we ONLY try the first one.
            # EXCEPT: If Vertex AI is the primary target, we always allow same-brand fallback to Developer Gemini.
            if not fallback and len(targets) > 1:
                if targets[0][0] == LLMProvider.VERTEX:
                    targets = [t for t in targets if t[0] in [LLMProvider.VERTEX, LLMProvider.GEMINI]]
                else:
                    targets = targets[:1]

        errors = []
        # [STRICT] If targets has multiple entries but fallback is False, we ONLY try the first one.
        # EXCEPT: If Vertex AI is the primary target, we always allow same-brand fallback to Developer Gemini.
        if not fallback and len(targets) > 1:
            if targets[0][0] == LLMProvider.VERTEX:
                targets = [t for t in targets if t[0] in [LLMProvider.VERTEX, LLMProvider.GEMINI]]
            else:
                targets = targets[:1]

        for provider, api_key, m_name in targets:
            print(f"🔄 Executing LLM Call -> Provider: {provider.value}, Model: {m_name}")

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    result = self._execute_provider_call(provider, m_name, content, api_key)
                    if result:
                        self.last_provider = provider
                        return result
                    else:
                        errors.append(f"{provider.value}: Returned empty or controlled failure.")
                        break # Break out of retry loop if it's an empty return
                except Exception as e:
                    err_msg = str(e)
                    print(f"⚠️ LLM Call Failed ({provider.value}): {e}")
                    if "429" in err_msg or "too many requests" in err_msg.lower():
                        if provider == LLMProvider.VERTEX:
                            print("💡 [Diagnostic] Vertex AI 429 Rate Limit hit. This often happens because the default GCP project (e.g. gen-lang-client-xxxx) has extremely low concurrent request/token quotas. Consider changing 'llm_vendor' to 'Google Gemini' in your settings / GUI or removing VERTEX variables from .env to use the standard Gemini Developer API (using GEMINI_API_KEY) which is much more stable.")

                    # Check for transient errors to retry
                    is_transient = any(transient in err_msg.lower() for transient in [
                        "remotedisconnected", "connection aborted", "connection reset",
                        "timeout", "502", "503", "504", "104", "too many requests", "429"
                    ])

                    if is_transient and attempt < max_retries - 1:
                        sleep_time = 3 * (attempt + 1)
                        print(f"   [Retry {attempt+1}/{max_retries-1}] Transient error detected. Retrying {provider.value} in {sleep_time}s...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        print(f"⚠️ Cascade Fallback Triggered. Giving up on {provider.value}.")
                        errors.append(f"{provider.value}: {err_msg}")
                        break # Break out of retry loop, move to next target

        raise Exception(f"❌ All LLM API fallbacks exhausted. Errors: {errors}")

    def generate_batch(self, tasks: List[Dict], model_name: str = "gemini-3.1-flash-preview", fallback: bool = False) -> List[Dict]:
        results = []
        total = len(tasks)
        print(f"🚀 Starting batch generation for {total} items (Workers: {self.max_workers}, Model: {model_name}, Fallback: {fallback})...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Create a list of futures mapping to tasks to maintain absolute order
            task_futures = [
                (task, executor.submit(self.generate_content, task['prompt'], model_name, fallback=fallback))
                for task in tasks
            ]

            completed = 0
            for task, future in task_futures:
                try:
                    result_text = future.result() # Blocks until this specific future is ready
                    results.append({**task, 'result': result_text})
                except Exception as e:
                    results.append({**task, 'result': None, 'error': str(e)})

                completed += 1
                if completed % 5 == 0 or completed == total:
                     print(f"   Progress: {completed}/{total} (chunks)", flush=True)

        return results

    def _list_openai_models(self, provider: LLMProvider) -> List[str]:
        curated_defaults = {
            LLMProvider.GEMINI: ["gemini-3.1-pro-preview", "gemini-3.1-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
            LLMProvider.OPENAI: ["gpt-4o", "gpt-4o-mini", "o3-mini", "o1", "o1-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            LLMProvider.MOONSHOT: ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
            LLMProvider.DASHSCOPE: ["qwen-max", "qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct"],
            LLMProvider.ZHIPU: ["glm-4.5", "glm-4-plus", "glm-4-flash", "glm-4-air"],
            LLMProvider.DEEPSEEK: ["deepseek-chat", "deepseek-reasoner"],
            LLMProvider.SILICONFLOW: [
                "deepseek-ai/DeepSeek-V3", 
                "deepseek-ai/DeepSeek-R1", 
                "Qwen/Qwen2.5-72B-Instruct", 
                "Qwen/Qwen2.5-14B-Instruct", 
                "Qwen/Qwen2.5-7B-Instruct",
                "meta-llama/Meta-Llama-3.1-400B-Instruct"
            ],
            LLMProvider.MINIMAX: ["minimax-m3", "abab7-chat", "abab6.5g-chat"]
        }

        api_key = self.api_keys.get(provider)
        if not api_key:
            return curated_defaults.get(provider, [])

        base_urls = {
            LLMProvider.OPENAI: "https://api.openai.com/v1",
            LLMProvider.MOONSHOT: "https://api.moonshot.cn/v1",
            LLMProvider.DASHSCOPE: "https://dashscope.aliyuncs.com/compatible-mode/v1",
            LLMProvider.ZHIPU: "https://open.bigmodel.cn/api/paas/v4",
            LLMProvider.DEEPSEEK: "https://api.deepseek.com",
            LLMProvider.SILICONFLOW: "https://api.siliconflow.cn/v1",
            LLMProvider.MINIMAX: "https://api.minimaxi.com/v1"
        }

        base_url = base_urls.get(provider)
        if not base_url:
            return curated_defaults.get(provider, [])

        try:
            response = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Extract names and filter for "stable" chat models
            # Extract names and filter for "stable" chat models (with strict duplicate protection)
            models = []
            seen = set()
            for m in data.get('data', []):
                m_id = m.get('id', '')
                if not m_id: continue
                low_id = m_id.lower()
                is_ignored = any(x in low_id for x in ['embedding', 'vector', 'search', 'text-moderation', 'whisper', 'dall-e', 'tts'])
                if not is_ignored:
                    if m_id not in seen:
                        seen.add(m_id)
                        models.append(m_id)

            # Merge with curated defaults to ensure primary models are always available
            defaults = curated_defaults.get(provider, [])
            for d in defaults:
                if d not in seen:
                    seen.add(d)
                    models.append(d)

            # Smart Sorting: Put curated/primary brand models at the top
            brand_map = {
                LLMProvider.DASHSCOPE: "qwen",
                LLMProvider.ZHIPU: "glm",
                LLMProvider.MOONSHOT: "kimi",  # Prioritize kimi brand prefix for Moonshot
                LLMProvider.DEEPSEEK: "deepseek",
                LLMProvider.MINIMAX: "minimax"
            }
            brand = brand_map.get(provider, "")

            def sort_key(name):
                name_low = name.lower()
                if name in defaults:
                    return (0, defaults.index(name), name_low)
                
                is_primary_brand = False
                if brand and (name_low.startswith(brand) or brand in name_low):
                    is_primary_brand = True
                elif provider == LLMProvider.MOONSHOT and ("kimi" in name_low or "moonshot" in name_low):
                    is_primary_brand = True
                
                brand_group = 1 if is_primary_brand else 2
                
                # Dynamic version parsing
                versions = re.findall(r'\b\d+(?:\.\d+)?\b', name_low)
                if not versions:
                    versions = re.findall(r'\d+(?:\.\d+)?', name_low)
                
                version_val = (0, 0)
                if versions:
                    try:
                        parts = [float(x) for x in versions]
                        v1 = parts[0]
                        v2 = parts[1] if len(parts) > 1 else 0.0
                        version_val = (v1, v2)
                    except ValueError:
                        pass
                
                # Tier priority: Premium/Flagship -> Standard -> Lite/Speed/Flash
                tier = 1
                premium_kws = ["pro", "plus", "max", "ultra", "reasoner", "o1", "o3"]
                lite_kws = ["mini", "lite", "flash", "micro", "nano", "speed", "turbo"]
                if any(x in name_low for x in premium_kws):
                    tier = 0
                elif any(x in name_low for x in lite_kws):
                    tier = 2
                
                return (brand_group, -version_val[0], -version_val[1], tier, len(name_low), name_low)

            models.sort(key=sort_key)
            return models
        except Exception as e:
            return curated_defaults.get(provider, [])

    def list_models_by_provider(self, provider: LLMProvider) -> List[str]:
        curated_defaults = {
            LLMProvider.GEMINI: ["gemini-3.1-pro-preview", "gemini-3.1-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
            LLMProvider.OPENAI: ["gpt-4o", "gpt-4o-mini", "o3-mini", "o1", "o1-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            LLMProvider.MOONSHOT: ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
            LLMProvider.DASHSCOPE: ["qwen-max", "qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct"],
            LLMProvider.ZHIPU: ["glm-4.5", "glm-4-plus", "glm-4-flash", "glm-4-air"],
            LLMProvider.DEEPSEEK: ["deepseek-chat", "deepseek-reasoner"],
            LLMProvider.SILICONFLOW: [
                "deepseek-ai/DeepSeek-V3", 
                "deepseek-ai/DeepSeek-R1", 
                "Qwen/Qwen2.5-72B-Instruct", 
                "Qwen/Qwen2.5-14B-Instruct", 
                "Qwen/Qwen2.5-7B-Instruct",
                "meta-llama/Meta-Llama-3.1-400B-Instruct"
            ],
            LLMProvider.MINIMAX: ["minimax-m3", "abab7-chat", "abab6.5g-chat"]
        }

        api_key = self.api_keys.get(provider)
        # For Vertex, we can proceed if we have a project ID (uses ADC)
        if provider == LLMProvider.VERTEX and self.vertex_project:
            pass
        elif not api_key:
            if provider == LLMProvider.VERTEX:
                return ["gemini-3.1-pro-preview", "gemini-3.1-flash-preview", "imagen-3-pro-preview"]
            return curated_defaults.get(provider, [])

        if provider == LLMProvider.GEMINI:
            try:
                import google.generativeai as genai  # type: ignore
                if not self._gemini_configured:
                    genai.configure(api_key=api_key)
                    self._gemini_configured = True
                models = []
                seen = set()
                for m in genai.list_models():
                    if 'generateContent' in m.supported_generation_methods:
                        m_name = m.name.replace("models/", "")
                        if m_name not in seen:
                            seen.add(m_name)
                            models.append(m_name)

                # Ensure experimental models are forcibly available
                for exp_model in ["gemini-3.1-flash-preview", "gemini-3.1-pro-preview"]:
                    if exp_model not in seen:
                        seen.add(exp_model)
                        models.append(exp_model)

                # Merge with curated defaults to ensure primary models are always available
                defaults = curated_defaults.get(LLMProvider.GEMINI, [])
                for d in defaults:
                    if d not in seen:
                        seen.add(d)
                        models.append(d)

                def gemini_sort_key(name):
                    name_low = name.lower()
                    if name in defaults:
                        return (0, defaults.index(name), name_low)
                    
                    # Dynamic version parsing
                    versions = re.findall(r'\b\d+(?:\.\d+)?\b', name_low)
                    if not versions:
                        versions = re.findall(r'\d+(?:\.\d+)?', name_low)
                    
                    version_val = (0, 0)
                    if versions:
                        try:
                            parts = [float(x) for x in versions]
                            v1 = parts[0]
                            v2 = parts[1] if len(parts) > 1 else 0.0
                            version_val = (v1, v2)
                        except ValueError:
                            pass
                    
                    # Tier priority: Premium/Flagship -> Standard -> Lite/Speed/Flash
                    tier = 1
                    premium_kws = ["pro", "plus", "max", "ultra", "reasoner", "o1", "o3"]
                    lite_kws = ["mini", "lite", "flash", "micro", "nano", "speed", "turbo"]
                    if any(x in name_low for x in premium_kws):
                        tier = 0
                    elif any(x in name_low for x in lite_kws):
                        tier = 2
                    
                    return (1, -version_val[0], -version_val[1], tier, len(name_low), name_low)
                models.sort(key=gemini_sort_key)
                return models
            except Exception as e:
                print(f"⚠️ Failed to list Gemini models: {e}")
                return []

        if provider == LLMProvider.VERTEX:
            # Static curated list of Vertex AI managed models (2026 suite)
            # Gemini 3.x / 2.5 series
            gemini_models = [
                "gemini-3.1-pro-preview",
                "gemini-3-pro-preview",
                "gemini-3.1-flash-preview",
                "gemini-3.1-flash-lite-preview",
                "gemini-2.5-pro",
            ]
            # Image Generation models
            image_models = [
                "gemini-3.1-flash-image-preview",
                "lyria-3-pro-preview",
                "imagen-3-fast-preview",
                "imagen-3-pro-preview",
            ]
            # Claude 4 series (Anthropic via Vertex Partner)
            claude_models = [
                "claude-opus-4-5",
                "claude-sonnet-4-5",
            ]
            return gemini_models + image_models + claude_models


        # Use dynamic discovery for all OpenAI-compatible providers
        return self._list_openai_models(provider)

    def list_accessible_models(self) -> List[str]:
        all_models = []
        for p in LLMProvider:
            all_models.extend(self.list_models_by_provider(p))
        return all_models

_CLIENT = None
def get_client():
    global _CLIENT
    if not _CLIENT:
        _CLIENT = LLMClient()
    return _CLIENT
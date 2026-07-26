"""DashScope API wrappers for GLM-5.2 and Qwen-VL-Max.

Both functions include 429 rate-limit retry logic with logging.
"""

import time
import requests


def call_glm(api_base: str, api_key: str, model: str, prompt: str,
             enterprise_name: str, max_tokens: int = 16000,
             retry_dir: str = ".", max_retries: int = 1):
    """Call GLM 5.2 via DashScope compatible-mode API.

    Returns (content: str, usage: dict).
    """
    from ...core.retry import log_retry, log_success

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                api_base,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': max_tokens,
                    'enable_thinking': False,
                },
                timeout=600,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data['choices'][0]['message']['content']
                usage = data.get('usage', {})
                log_success(enterprise_name)
                return content, usage
            elif resp.status_code == 429:
                wait = 30 * (attempt + 1)
                log_retry(enterprise_name, model,
                          f'429 retry {attempt + 1}/{max_retries} waiting {wait}s',
                          retry_dir)
                time.sleep(wait)
                continue
            else:
                return f'API Error: {resp.status_code} {resp.text[:200]}', {}
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(15)
                continue
            return f'Exception: {str(e)[:200]}', {}

    log_retry(enterprise_name, model, '429 all retries exhausted', retry_dir)
    return 'ERROR: 429 限流，所有重试失败', {}


def call_qwen_vl(api_base: str, api_key: str, model: str,
                 image_b64: str, prompt_text: str,
                 enterprise_name: str, max_tokens: int = 300,
                 retry_dir: str = ".", max_retries: int = 1):
    """Call Qwen-VL-Max via DashScope compatible-mode API.

    Returns content: str.
    """
    from ...core.retry import log_retry

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                api_base,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': [
                        {'type': 'text', 'text': prompt_text},
                        {'type': 'image_url',
                         'image_url': {'url': f'data:image/png;base64,{image_b64}'}},
                    ]}],
                    'max_tokens': max_tokens,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()['choices'][0]['message']['content']
            elif resp.status_code == 429:
                log_retry(enterprise_name, model, f'429 retry {attempt + 1}',
                          retry_dir)
                time.sleep(10 * (attempt + 1))
                continue
            else:
                return f'API Error {resp.status_code}'
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            return f'Error: {str(e)[:100]}'

    log_retry(enterprise_name, model, '429 exhausted', retry_dir)
    return 'ERROR: 429 限流'

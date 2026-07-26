"""429 rate-limit retry tracking and report generation."""

import os
import re
from datetime import datetime


_retry_status = {}  # {enterprise: 'retrying'/'failed'/'succeeded'}


def log_retry(enterprise: str, model: str, error: str, retry_dir: str):
    """Record a 429 retry event."""
    _retry_status[enterprise] = 'failed' if 'exhausted' in error else 'retrying'
    os.makedirs(retry_dir, exist_ok=True)
    with open(os.path.join(retry_dir, '429_log.txt'), 'a') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {enterprise} | {model} | {error}\n")


def log_success(enterprise: str):
    """Mark an enterprise as successfully completed."""
    if enterprise in _retry_status:
        _retry_status[enterprise] = 'succeeded'


def generate_retry_report(out_dir: str, retry_dir: str) -> list:
    """Generate a clean list of enterprises that need re-running.
    Returns the list of enterprise names needing retry.
    """
    succeeded_nums = set()
    if os.path.exists(out_dir):
        for fname in os.listdir(out_dir):
            if fname.endswith('.md'):
                m = re.match(r'(\d+)', fname)
                if m:
                    succeeded_nums.add(m.group(1))

    need_retry = set()
    failed_nums = set()
    retry_nums = set()
    retry_log_path = os.path.join(retry_dir, '429_log.txt')
    if os.path.exists(retry_log_path):
        with open(retry_log_path, 'r') as f:
            for line in f:
                parts = line.split(' | ')
                if len(parts) >= 2:
                    ent = parts[1].strip()
                    m = re.match(r'(\d+)', ent)
                    if m:
                        num = m.group(1)
                        if 'exhausted' in line:
                            failed_nums.add(num)
                            need_retry.add(ent)
                        else:
                            retry_nums.add(num)

    # Remove ones that succeeded
    need_retry = {e for e in need_retry if re.match(r'(\d+)', e)
                  and re.match(r'(\d+)', e).group(1) not in succeeded_nums}

    if need_retry:
        os.makedirs(retry_dir, exist_ok=True)
        with open(os.path.join(retry_dir, 'need_retry.txt'), 'w') as f:
            for ent in sorted(need_retry):
                f.write(f'{ent}\n')

    return list(need_retry)

import re

def parse_metadata_mock(text):
    metadata = {}
    lines = text.split('\n')
    meta_patterns = {
        'title': re.compile(r'^Title:\s*(.+)$', re.IGNORECASE),
        'date': re.compile(r'^(?:Date|Time|Posted):\s*(.+)$', re.IGNORECASE),
        'source': re.compile(r'^(?:Source|Author|Company|Institution):\s*(.+)$', re.IGNORECASE),
    }

    for line in lines:
        for key, pattern in meta_patterns.items():
            m = pattern.match(line)
            if m:
                metadata[key] = m.group(1).strip()
    return metadata

# Test with translated file content (simulated)
corrupted_text = """---
author： Thariq
date： '2026-04-05'
source： X
title： 构建 Claude Code 的经验教训
---"""

print(f"Testing with corrupted colons (full-width)：")
meta = parse_metadata_mock(corrupted_text)
print(f"Extracted Metadata: {meta}")

fixed_text = """---
author: Thariq
date: '2026-04-05'
source: X
title: 构建 Claude Code 的经验教训
---"""

print(f"\nTesting with standard colons (ASCII):")
meta_fixed = parse_metadata_mock(fixed_text)
print(f"Extracted Metadata: {meta_fixed}")
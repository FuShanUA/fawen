import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agents"))

from common_utils import MetadataEngine, resolve_article_author, resolve_translator


def test_explicit_article_author_wins_over_translator():
    config = {
        "author": "AI数据治理研究院",
        "original_author": "Jane Doe",
        "translator": "AI数据治理研究院",
    }

    assert resolve_article_author("Charlotte Ledoux", config) == "Charlotte Ledoux"


def test_original_author_wins_over_legacy_author():
    config = {
        "author": "AI数据治理研究院",
        "original_author": "Jane Doe",
        "interpret_publisher": "AI数据治理研究院",
    }

    assert resolve_article_author("", config) == "Jane Doe"


def test_old_frontmatter_separates_author_and_translator():
    content = """---
title: Sample
author: AI数据治理研究院
original_author: Jane Doe
source: Example
---

Body
"""
    metadata = MetadataEngine(content)

    assert resolve_article_author(metadata=metadata) == "Jane Doe"
    assert resolve_translator(metadata=metadata) == "AI数据治理研究院"


def test_new_frontmatter_does_not_use_article_author_as_translator():
    content = """---
title: Sample
author: Jane Doe
original_author: Jane Doe
translator: AI数据治理研究院
source: Example
---

Body
"""
    metadata = MetadataEngine(content)

    assert resolve_article_author(metadata=metadata) == "Jane Doe"
    assert resolve_translator(metadata=metadata) == "AI数据治理研究院"


def test_missing_translator_is_empty():
    metadata = MetadataEngine("author: Jane Doe")

    assert resolve_article_author(metadata=metadata) == "Jane Doe"
    assert resolve_translator(metadata=metadata) == ""

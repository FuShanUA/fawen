import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agents"))

from markdown_cleanup import sanitize_medium_markdown


def test_removes_header_images_before_first_section():
    text = """# Title

![Cover](cover.png)

![Author](author.png)

## Section

![Content](content.png)
"""

    result = sanitize_medium_markdown(text)

    assert "cover.png" not in result
    assert "author.png" not in result
    assert "content.png" in result


def test_removes_medium_ui_fragments_and_placeholders():
    text = """# Title

][!]$s4[Download article][!][

][!]$s4[下载文章][!][

[Show all 12 sections]][![None](icon.png)

[显示全部 12 个章节]][![None](icon.png)

MDTOHTMLIMGPH_1

## Section
"""

    result = sanitize_medium_markdown(text)

    assert "Download article" not in result
    assert "下载文章" not in result
    assert "Show all 12 sections" not in result
    assert "显示全部 12 个章节" not in result
    assert "MDTOHTMLIMGPH_1" not in result


def test_removes_images_after_socials_heading():
    text = """## Section

![Content](content.png)

### Socials

Follow me.

![Avatar](avatar.png)
"""

    result = sanitize_medium_markdown(text)

    assert "content.png" in result
    assert "avatar.png" not in result


def test_normalizes_broken_image_wrapper():
    text = """## Section

][![Chart](chart.png)]
"""

    result = sanitize_medium_markdown(text)

    assert "![Chart](chart.png)" in result


def test_removes_trailing_link_wrapper_after_socials():
    text = """## Section

### Socials

![Avatar](avatar.png)][[](profile.png)
"""

    result = sanitize_medium_markdown(text)

    assert "avatar.png" not in result
    assert "profile.png" not in result

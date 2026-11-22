import re


def sanitize_medium_markdown(text):
    """Clean Medium/Freedium boilerplate and broken image wrappers."""
    if not text:
        return text

    # Remove internal converter placeholders.
    text = re.sub(r"MDTOHTMLIMGPH_\d+", "", text)

    # Remove Medium/Freedium UI fragments.
    text = re.sub(
        r"\]\[!\]\$s4\[Download article\]\[!\]\[",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\]\[!\]\$s4\[下载文章\]\[!\]\[",
        "",
        text,
    )
    text = re.sub(
        r"\[Show all \d+ sections\]\]\[!\[None\]\([^)]+\)(?:\])?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\[显示全部 \d+ 个章节\]\]\[!\[None\]\([^)]+\)(?:\])?",
        "",
        text,
    )

    # Normalize broken image wrappers such as `][![alt](url)]`.
    text = re.sub(
        r"^\s*\]\[!\[([^\]]*)\]\(([^)]+)\)\]\s*$",
        r"![\1](\2)",
        text,
        flags=re.MULTILINE,
    )

    # Remove images that appear before the first section heading. These are
    # usually post covers, author avatars, or platform UI graphics.
    lines = text.splitlines()
    first_heading = next(
        (index for index, line in enumerate(lines) if re.match(r"^#{2,}\s", line)),
        None,
    )
    if first_heading is not None:
        for index in range(first_heading):
            if re.search(r"!\[[^\]]*\]\([^)]+\)", lines[index]):
                lines[index] = ""
    text = "\n".join(lines)

    # Remove images after a socials or author-bio heading. These are usually
    # author avatars or platform cards, not article content.
    social_matches = list(
        re.finditer(
            r"(?im)^#{2,4}\s*(?:Socials|社交账号|About the Author|作者简介)\s*$",
            text,
        )
    )
    if social_matches:
        start = social_matches[-1].end()
        tail = text[start:]
        tail = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", tail)
        text = text[:start] + tail

    # Remove orphan bracket-only lines left by broken link syntax.
    text = re.sub(r"(?m)^\s*(?:\[\s*|\]\s*)+\s*$", "", text)
    text = re.sub(r"(?m)^\s*\]\[\[\]\([^)]+\)(?:\])?\s*$", "", text)

    # Remove leftover wrapper fragments around images.
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)\]\[?\[?", r"![\1](\2)", text)

    return text.strip() + "\n"

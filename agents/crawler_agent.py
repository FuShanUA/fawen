"""
Crawler Agent (Content Extractor)

Responsible for extracting raw text/markdown from URLs or local files.
Supports:
- URLs (Playwright -> Markdown)
- PDFs (pdfplumber/pypdf -> Text)
- Text/Markdown files (Direct read)
"""

import sys
import os
import re
from datetime import datetime
import subprocess
import shutil
import json
import hashlib
from urllib.request import urlopen, Request
from urllib.parse import urlparse
from bs4 import BeautifulSoup, NavigableString, Tag
from playwright.sync_api import sync_playwright
import requests

# Path for common_utils and llm_utils
agents_dir = os.path.dirname(os.path.abspath(__file__))
if agents_dir not in sys.path:
    sys.path.append(agents_dir)
# Standalone fallback support: use local common directory if present, otherwise fallback to project-wide common
local_common = os.path.abspath(os.path.join(agents_dir, "..", "common"))
common_dir = local_common if os.path.exists(local_common) else os.path.abspath(os.path.join(agents_dir, "..", "..", "common"))
if common_dir not in sys.path:
    sys.path.append(common_dir)

def process_table(table_element):
    """Convert HTML table to proper Markdown table."""
    rows = table_element.find_all('tr')
    if not rows:
        return ""

    table_data = []
    for row in rows:
        cells = row.find_all(['th', 'td'])
        row_data = [cell.get_text(strip=True).replace('|', '\\|') for cell in cells]
        table_data.append(row_data)

    if not table_data:
        return ""

    max_cols = max(len(row) for row in table_data)
    for row in table_data:
        while len(row) < max_cols:
            row.append('')

    lines = []
    lines.append("| " + " | ".join(table_data[0]) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in table_data[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n\n" + "\n".join(lines) + "\n\n"


def html_to_markdown(element):
    """Recursively convert HTML element to Markdown."""
    if element is None:
        return ""

    if isinstance(element, NavigableString):
        text = str(element).strip()
        return text if text else ""

    tag_name = element.name.lower()

    if tag_name in ['script', 'style', 'noscript', 'meta', 'link']:
        return ""
    if tag_name == 'br':
        return "\n"
    if tag_name == 'p':
        return "\n\n" + "".join(html_to_markdown(child) for child in element.children) + "\n\n"
    if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        level = int(tag_name[1])
        return f"\n\n{'#' * level} " + "".join(html_to_markdown(child) for child in element.children) + "\n\n"
    if tag_name == 'a':
        text = "".join(html_to_markdown(child) for child in element.children)
        href = element.get('href', '')
        return f"[{text}]({href})" if href else text
    if tag_name in ['strong', 'b']:
        return f"**{''.join(html_to_markdown(child) for child in element.children)}**"
    if tag_name in ['em', 'i']:
        return f"*{''.join(html_to_markdown(child) for child in element.children)}*"
    if tag_name == 'ul':
        content = ""
        for child in element.children:
            if child.name == 'li':
                content += f"\n- {''.join(html_to_markdown(c) for c in child.children).strip()}"
        return content + "\n"
    if tag_name == 'ol':
        content = ""
        for i, child in enumerate(element.find_all('li', recursive=False)):
            content += f"\n{i+1}. {''.join(html_to_markdown(c) for c in child.children).strip()}"
        return content + "\n"
    if tag_name == 'table':
        return process_table(element)
    if tag_name == 'img':
        alt = element.get('alt', 'Image')
        src = element.get('src', '')
        return f"![{alt}]({src})"

    return "".join(html_to_markdown(child) for child in element.children)

def extract_ld_json_metadata(html_content):
    """Generic Schema.org (LD+JSON) metadata extractor for Articles."""
    soup = BeautifulSoup(html_content, 'html.parser')
    scripts = soup.find_all('script', type='application/ld+json')
    ld_results = []
    for script in scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, list): ld_results.extend(data)
            else: ld_results.append(data)
        except: continue

    # Priority schema types
    target_types = ["Article", "NewsArticle", "BlogPosting", "SocialMediaPosting"]

    for data in ld_results:
        if not isinstance(data, dict): continue
        # Handle @graph (common in WordPress)
        if "@graph" in data:
            for item in data["@graph"]:
                if item.get("@type") in target_types:
                    data = item
                    break

        if data.get("@type") in target_types:
            # Author
            author_data = data.get("author", {})
            author = ""
            if isinstance(author_data, list):
                author = author_data[0].get("name", "") if author_data else ""
            elif isinstance(author_data, dict):
                author = author_data.get("name", "")

            # Date
            pub_date = data.get("datePublished") or data.get("dateCreated")
            if pub_date: pub_date = pub_date[:10] # YYYY-MM-DD

            # Publisher/Source
            pub_name = ""
            pub_data = data.get("publisher", {})
            if isinstance(pub_data, dict):
                pub_name = pub_data.get("name", "")

            return {
                "title": data.get("headline"),
                "author": author,
                "publish_date": parse_date_string(pub_date),
                "source": pub_name
            }
    return None

def extract_medium_apollo_state(html_content):
    """Extract content and metadata from Medium's __APOLLO_STATE__."""
    match = re.search(r'window\.__APOLLO_STATE__\s*=\s*({.+?});?(?:</script>|window\.)', html_content, re.DOTALL)
    if not match: return None

    try:
        data = json.loads(match.group(1))
        images_metadata = {}
        paragraphs_by_post = {}

        # 1. Collect all image metadata and paragraphs
        for key, val in data.items():
            if key.startswith("ImageMetadata:"):
                images_metadata[key] = val
            elif key.startswith("Paragraph:"):
                parts = key.split(":")[-1].split("_")
                if len(parts) >= 2:
                    post_id = "_".join(parts[:-1])
                    try:
                        idx = int(parts[-1])
                        if post_id not in paragraphs_by_post:
                            paragraphs_by_post[post_id] = []
                        paragraphs_by_post[post_id].append((idx, val))
                    except: pass

        if not paragraphs_by_post: return None

        # 2. Identify main post
        best_post_id = max(paragraphs_by_post.keys(), key=lambda k: len(paragraphs_by_post[k]))
        paragraphs = sorted(paragraphs_by_post[best_post_id], key=lambda x: x[0])

        # 3. Extract Metadata
        post_data = data.get(f"Post:{best_post_id}", {})
        title = post_data.get("title", "")

        # Author
        author_name = ""
        creator_ref = post_data.get("creator", {}).get("__ref", "")
        if creator_ref and creator_ref in data:
            author_name = data[creator_ref].get("name", "")

        # Date
        ts = post_data.get("latestPublishedAt") or post_data.get("firstPublishedAt")
        pub_date = ""
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts) / 1000.0)
                pub_date = dt.strftime('%Y-%m-%d')
            except: pass

        # Organization/Source (Collection)
        source_name = "Medium"
        collection_ref = post_data.get("collection", {}).get("__ref", "")
        if collection_ref and collection_ref in data:
            source_name = data[collection_ref].get("name", "Medium")

        # 4. Construct Content
        md_lines = []
        for idx, p in paragraphs:
            p_type = p.get("type", "")
            text = p.get("text", "")
            if p_type.startswith("H"):
                level = int(p_type[1]) if len(p_type) > 1 else 3
                md_lines.append(f"\n\n{'#' * level} {text}\n\n")
            elif p_type == "IMG":
                ref = p.get("metadata", {}).get("__ref", "")
                img_id = images_metadata.get(ref, {}).get("id")
                if img_id:
                    md_lines.append(f"\n\n![Image](https://miro.medium.com/v2/resize:fit:1400/{img_id})\n\n")
            elif p_type in ["ULI", "OLI"]:
                md_lines.append(f"- {text}\n")
            elif p_type in ["BQ", "PQ"]:
                md_lines.append(f"\n> {text}\n\n")
            elif p_type == "PRE":
                md_lines.append(f"\n```\n{text}\n```\n\n")
            else:
                md_lines.append(f"\n\n{text}\n\n")

        return {
            "title": title,
            "author": author_name,
            "publish_date": pub_date,
            "source": normalize_source(author_name, source_name),
            "content": "".join(md_lines)
        }
    except Exception as e:
        print(f"Crawler Agent: Apollo Extract failed: {e}")
        return None

def parse_date_string(date_str):
    """Normalize various date formats to YYYY-MM-DD."""
    if not date_str:
        return None
    date_str = date_str.strip()
    # 1. ISO Format: 2026-04-02T12:00:00Z -> 2026-04-02
    if 'T' in date_str:
        date_str = date_str.split('T')[0]
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    # 2. AWS/Byline Format (English): 02 APR 2026 or April 2, 2026
    months_map = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
        'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
    }
    # Match: 02 APR 2026
    m = re.search(r'(\d{1,2})\s+([A-Z]{3})\s+(\d{4})', date_str, re.IGNORECASE)
    if m:
        day = m.group(1).zfill(2)
        month = months_map.get(m.group(2).lower()[:3], "01")
        year = m.group(3)
        return f"{year}-{month}-{day}"

    return date_str

def normalize_source(author, platform):
    """Normalize source to Author，Platform format for individual posts (no duplicates)."""
    if not author or author == "Unknown":
        return platform

    # Common platforms that should be formatted as Author，Platform
    platforms = ["Medium", "X", "Twitter", "Substack", "LinkedIn", "YouTube", "Bilibili"]

    is_platform = any(p.lower() in platform.lower() for p in platforms)

    # Avoid duplicate author names if already present in platform/source string
    if author.lower() in platform.lower():
        # If it's already "Author Name，Platform", just return platform or clean it
        if "，" in platform:
            return platform
        return platform # It already has the author name or IS the author name

    if is_platform or "," in platform or "，" in platform or author in platform:
        # If it's a platform or already looks like a combined string
        clean_platform = platform.split("，")[-1].strip() if "，" in platform else platform.split(",")[-1].strip()
        # Use Chinese comma, no brackets
        return f"{author}，{clean_platform}"

    return platform

def sniff_metadata(url):
    """Lightweight metadata extraction using Standard Fallback: LD-JSON > OG > Title > H1."""
    if "x.com" in url or "twitter.com" in url:
        return {"title": f"X post", "source": "X", "author": "Unknown", "url": url}

    print(f"Crawler Agent: Sniffing metadata for {url}...")
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
        with urlopen(req, timeout=10) as response:
            html = response.read(1024 * 1024) # Read first 1MB

        soup = BeautifulSoup(html, 'html.parser')
        metadata = {
            "title": "",
            "publish_date": "",
            "author": "",
            "source": "",
            "url": url
        }

        # 1. LD-JSON (High Fidelity/Schema.org)
        ld_meta = extract_ld_json_metadata(html)
        if ld_meta:
            metadata["title"] = ld_meta.get("title") or ""
            metadata["publish_date"] = ld_meta.get("publish_date") or ""
            metadata["author"] = ld_meta.get("author") or ""
            metadata["source"] = ld_meta.get("source") or ""
            print(f"  [LD-JSON Success] Title: {metadata['title'][:30]}")

        # 2. OG Titles (Medium Fidelity) - Fallback for Title
        if not metadata["title"]:
            og_title = soup.find("meta", property="og:title") or \
                       soup.find("meta", {"name": "og:title"}) or \
                       soup.find("meta", property="twitter:title")
            if og_title:
                metadata["title"] = og_title.get("content", "").strip()

        # 3. HTML Standards - Fallback for Title
        if not metadata["title"]:
            title_tag = soup.find("title")
            if title_tag:
                metadata["title"] = title_tag.get_text(strip=True)
            else:
                h1 = soup.find("h1")
                if h1: metadata["title"] = h1.get_text(strip=True)

        # 4. Date (OG/Meta Fallback)
        if not metadata["publish_date"]:
            date_meta = soup.find("meta", property="article:published_time") or \
                        soup.find("meta", {"name": "article:published_time"}) or \
                        soup.find("meta", property="og:published_time") or \
                        soup.find("meta", {"name": "date"}) or \
                        soup.find("meta", {"property": "datePublished"}) or \
                        soup.find("meta", {"itemprop": "datePublished"}) or \
                        soup.find("meta", property="article:modified_time")
            if date_meta:
                extracted_raw = date_meta.get("content", "").strip() or date_meta.get("datetime", "").strip()
                metadata["publish_date"] = parse_date_string(extracted_raw)

        # 5. Author (OG/Meta Fallback)
        if not metadata["author"]:
            author_meta = soup.find("meta", {"name": "author"}) or \
                          soup.find("meta", property="article:author") or \
                          soup.find("meta", {"name": "twitter:creator"}) or \
                          soup.find("meta", {"itemprop": "author"}) or \
                          soup.find("meta", {"property": "author"})
            if author_meta:
                metadata["author"] = author_meta.get("content", "").strip() or author_meta.get("name", "").strip()

        # 6. Source (OG/Domain Fallback)
        if not metadata["source"]:
            source_meta = soup.find("meta", property="og:site_name") or \
                          soup.find("meta", {"name": "og:site_name"}) or \
                          soup.find("meta", {"name": "application-name"})
            if source_meta:
                metadata["source"] = source_meta.get("content", "").strip()
            else:
                domain = urlparse(url).netloc
                metadata["source"] = domain.split('.')[-2].capitalize() if '.' in domain else domain

        # Final Normalization for source
        if metadata["author"] and metadata["source"]:
             metadata["source"] = normalize_source(metadata["author"], metadata["source"])

        if metadata["title"] or metadata["publish_date"]:
             print(f"  [Sniffed Metadata] Title: {metadata['title'][:50]}, Date: {metadata['publish_date']}")
        return metadata
    except Exception as e:
        print(f"  [Sniffing Failed] {e}")
        return {}

def extract_from_url(url):
    """Extract content from URL. Uses fxtwitter for X posts, otherwise Defuddle CLI."""
    import subprocess
    import json
    import urllib.request

    # 1. Step: Metadata Snifting (Lightweight)
    sniffed = sniff_metadata(url)

    # 2. Primary Extraction
    source = sniffed.get("source", "Web")
    author = sniffed.get("author", "Unknown")
    extracted_date = sniffed.get("publish_date", "")
    title = sniffed.get("title", f"Extracted from {url}")
    today = datetime.now().strftime('%Y-%m-%d')

    md_content = ""

    if "x.com/" in url or "twitter.com/" in url:
        # TIER 1: Internal API Parser (fxtwitter/vxtwitter)
        # 最快、最轻量。
        api_data = None
        try:
            # Robust domain replacement
            api_url = url
            if "api.fxtwitter.com" not in url and "api.vxtwitter.com" not in url:
                if "x.com" in url:
                    api_url = url.replace("x.com", "api.fxtwitter.com")
                elif "twitter.com" in url:
                    api_url = url.replace("twitter.com", "api.fxtwitter.com")

            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            print(f"Crawler Agent: Trying Tier 1 (Internal API): {api_url}")
            r = requests.get(api_url, headers=headers, timeout=10)
            if r.status_code == 200:
                api_data = r.json()
            else:
                # Fallback to vxtwitter
                vx_url = api_url.replace("fxtwitter", "vxtwitter")
                print(f"Crawler Agent: Tier 1 API (fx) failed, trying vx: {vx_url}")
                r = requests.get(vx_url, headers=headers, timeout=10)
                if r.status_code == 200:
                    api_data = r.json()
        except Exception as api_err:
            print(f"Crawler Agent: Tier 1 API failed: {api_err}")

        if api_data and api_data.get("code") == 200 and "tweet" in api_data:
            try:
                tweet = api_data["tweet"]
                author = tweet.get("author", {}).get("name", author)

                # Check for Article (Long Note)
                if "article" in tweet and "content" in tweet.get("article", {}):
                    print("Crawler Agent: Detected X Article (Long Note). Parsing Tier 1 blocks...")
                    article = tweet["article"]
                    title = article.get("title", title)
                    cover_img = article.get("cover_media", {}).get("media_info", {}).get("original_img_url")

                    md_blocks = []
                    if cover_img:
                        md_blocks.append(f"![Cover]({cover_img})")

                    media_dict = {}
                    entities_data = article.get("media_entities", {})
                    if isinstance(entities_data, dict):
                        for k, v in entities_data.items():
                            if "media_info" in v and "original_img_url" in v["media_info"]:
                                media_dict[str(v.get("media_id", ""))] = v["media_info"]["original_img_url"]
                    elif isinstance(entities_data, list):
                        for v in entities_data:
                            if "media_info" in v and "original_img_url" in v["media_info"]:
                                media_dict[str(v.get("media_id", ""))] = v["media_info"]["original_img_url"]

                    content_data = article["content"]
                    blocks = content_data.get("blocks", [])
                    entity_map_raw = content_data.get("entityMap", [])
                    entity_map = {}
                    if isinstance(entity_map_raw, list):
                        for item in entity_map_raw:
                            if "key" in item and "value" in item:
                                entity_map[str(item["key"])] = item["value"]
                    elif isinstance(entity_map_raw, dict):
                        entity_map = entity_map_raw

                    has_embedded_images = False
                    ordered_counter = 0
                    for block in blocks:
                        b_text = block.get("text", "").strip()
                        b_type = block.get("type", "unstyled")

                        # Handle Images/Media (Atomic Blocks)
                        if b_type == "atomic":
                            entities = block.get("entityRanges", [])
                            for ent in entities:
                                ent_key = str(ent.get("key"))
                                if ent_key in entity_map:
                                    ent_val = entity_map[ent_key]
                                    # Fix: Handle both direct mediaId and nested mediaItems
                                    media_id = None
                                    e_data = ent_val.get("data", {})
                                    if "mediaId" in e_data:
                                        media_id = str(e_data["mediaId"])
                                    elif "mediaItems" in e_data and isinstance(e_data["mediaItems"], list) and e_data["mediaItems"]:
                                        media_id = str(e_data["mediaItems"][0].get("mediaId") or e_data["mediaItems"][0].get("media_id", ""))

                                    if media_id and media_id in media_dict:
                                        md_blocks.append(f"![Image]({media_dict[media_id]})")
                                        has_embedded_images = True
                            continue

                        # Handle Formatting
                        if b_type == "header-one": md_blocks.append(f"# {b_text}")
                        elif b_type == "header-two": md_blocks.append(f"## {b_text}")
                        elif b_type == "header-three": md_blocks.append(f"### {b_text}")
                        elif b_type == "unordered-list-item": md_blocks.append(f"- {b_text}")
                        elif b_type == "ordered-list-item":
                            ordered_counter += 1
                            md_blocks.append(f"{ordered_counter}. {b_text}")
                        elif b_type == "blockquote": md_blocks.append(f"> {b_text}")
                        elif b_type == "code-block": md_blocks.append(f"```\n{b_text}\n```")
                        else:
                            ordered_counter = 0
                            # Bold extraction (heuristic)
                            if block.get("inlineStyleRanges"):
                                b_text = f"**{b_text}**"
                            md_blocks.append(b_text)

                    # ASSET INTEGRITY CHECK:
                    # If this is an article but Tier 1 found ZERO embedded images despite blocks existence,
                    # it's likely a complex structure (e.g. nested lists) -> Fallback to Tier 3.
                    if not has_embedded_images and len(blocks) > 10:
                         print("Crawler Agent: Tier 1 Article extraction seems incomplete (no images). Falling back...")
                         raise Exception("Tier 1 Incomplete")

                    md_result = "\n\n".join(md_blocks)
                    print("Crawler Agent: Tier 1 (Internal API) success.")
                    return {
                        "title": title,
                        "publish_date": extracted_date or today,
                        "author": author,
                        "source": "X",
                        "url": url
                    }, md_result
                else:
                    # Standard Tweet
                    text = tweet.get("text", "")
                    md_result = f"**{author}**\n\n{text}\n\n"
                    if "media" in tweet and "photos" in tweet["media"]:
                        for photo in tweet["media"]["photos"]:
                            md_result += f"![Image]({photo['url']})\n\n"
                    print("Crawler Agent: Tier 1 (Internal API) success (Standard Tweet).")
                    return {
                        "title": f"Tweet by {author}",
                        "publish_date": extracted_date or today,
                        "author": author,
                        "source": "X",
                        "url": url
                    }, md_result
            except Exception as parse_err:
                print(f"Crawler Agent: Tier 1 parsing failed or incomplete: {parse_err}")

        # TIER 2: Defuddle CLI
        # 第二顺位：通用解析兜底。
        try:
            print(f"Crawler Agent: Trying Tier 2 (Defuddle CLI)...")
            result = subprocess.run(
                ["defuddle", "parse", url, "--md"],
                capture_output=True,
                text=True,
                check=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return sniffed, result.stdout.strip()
        except Exception as defuddle_err:
            print(f"Crawler Agent: Tier 2 direct failed: {defuddle_err}. Trying NPX fallback...")
            try:
                result = subprocess.run(
                    ["npx", "-y", "defuddle", "parse", url, "--md"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                if result.returncode == 0 and result.stdout.strip():
                    return sniffed, result.stdout.strip()
            except Exception as npx_err:
                print(f"Crawler Agent: Tier 2 NPX failed: {npx_err}")

        # TIER 3: Baoyu Bun Skill (Last Resort)
        # 第三顺位：仅当所有方案失效时使用。
        bun_skill_path = os.path.normpath(r"/Users/shanfu/cc/Library/Tools/baoyu-skills/skills/baoyu-danger-x-to-markdown/scripts/main.ts")
        if os.path.exists(bun_skill_path):
            print(f"Crawler Agent: Trying Tier 3 (Baoyu Skill - Last Resort)...")
            try:
                import hashlib
                import tempfile
                temp_out = os.path.join(tempfile.gettempdir(), f"x_temp_{hashlib.md5(url.encode()).hexdigest()[:8]}.md")
                subprocess.run(["bun", "--version"], capture_output=True, check=True, shell=True)
                cmd = f'bun "{bun_skill_path}" "{url}" -o "{temp_out}"'
                print(f"  [Executing] {cmd}")
                res = subprocess.run(cmd, capture_output=True, text=True, shell=True)

                if res.returncode == 0 and os.path.exists(temp_out):
                    with open(temp_out, "r", encoding="utf-8") as f:
                        full_content = f.read()
                    try: os.remove(temp_out)
                    except: pass

                    if full_content.strip().startswith("---"):
                        parts = full_content.split("---", 2)
                        if len(parts) >= 3:
                            yaml_text = parts[1]
                            body_text = parts[2].strip()
                            m_title = re.search(r'^title:\s*(.+)$', yaml_text, re.M)
                            m_author = re.search(r'^author:\s*(.+)$', yaml_text, re.M)
                            m_date = re.search(r'^publish_date:\s*(\d{4}-\d{2}-\d{2})', yaml_text, re.M)
                            if m_title: sniffed["title"] = m_title.group(1).strip().strip('"').strip("'")
                            if m_author:
                                author_val = m_author.group(1).strip().strip('"').strip("'")
                                sniffed["author"] = author_val
                                sniffed["source"] = normalize_source(author_val, "X")
                            if m_date: sniffed["publish_date"] = m_date.group(1)
                            return sniffed, body_text
                    return sniffed, full_content.strip()
            except Exception as bun_err:
                print(f"Crawler Agent: Tier 3 failed: {bun_err}")


    elif "medium.com/" in url:
        print(f"Crawler Agent: Detected Medium URL. Fetching via Playwright...")
        playwright_success = False
        html_content = ""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled']
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Cloudflare challenge detection & wait loop (up to 30s)
                for attempt in range(6):
                    page_title = page.title()
                    if "moment" not in page_title.lower() and "checking" not in page_title.lower():
                        break
                    print(f"  [CF Wait] Attempt {attempt+1}/6: Cloudflare challenge detected, waiting 5s...")
                    page.wait_for_timeout(5000)

                try:
                    page.wait_for_selector("article, [data-testid='post-title']", timeout=15000)
                except Exception:
                    page.wait_for_timeout(3000)

                html_content = page.content()
                browser.close()

            # Verify we actually got article content (not a CF challenge page)
            if '<article' in html_content or 'APOLLO_STATE' in html_content or 'ld+json' in html_content:
                playwright_success = True
            else:
                print("Crawler Agent: Playwright got a Cloudflare challenge page, not article content.")

        except Exception as e:
            print(f"Crawler Agent: Playwright Medium extraction failed: {e}")

        # FALLBACK: defuddle CLI when Playwright fails (bypasses CF at the HTTP level)
        if not playwright_success:
            print(f"Crawler Agent: Falling back to Defuddle CLI for Medium...")
            try:
                result = subprocess.run(
                    ["npx", "-y", "defuddle", "parse", url, "--md"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode == 0 and result.stdout.strip():
                    defuddle_output = result.stdout.strip()
                    md_content = defuddle_output
                    print(f"Crawler Agent: Defuddle CLI success for Medium ({len(md_content)} chars)")
                    # Try to extract metadata from defuddle JSON output
                    try:
                        defuddle_data = json.loads(defuddle_output)
                        if isinstance(defuddle_data, dict):
                            if defuddle_data.get("title"): title = defuddle_data["title"]
                            if defuddle_data.get("author"): author = defuddle_data["author"]
                            if defuddle_data.get("published"):
                                extracted_date = parse_date_string(defuddle_data["published"])
                            if defuddle_data.get("site"): source = defuddle_data["site"]
                            md_content = defuddle_data.get("content", "") or defuddle_data.get("markdown", "") or ""
                    except (json.JSONDecodeError, ValueError):
                        pass  # defuddle returned plain markdown, not JSON
                else:
                    print(f"Crawler Agent: Defuddle CLI also failed for Medium. stderr: {result.stderr[:200] if result.stderr else 'none'}")
            except Exception as defuddle_err:
                print(f"Crawler Agent: Defuddle CLI fallback failed: {defuddle_err}")

        # Process Playwright HTML if successful
        if playwright_success and html_content:
            organization = source
            # Try JSON-LD first for metadata
            ld_meta = extract_ld_json_metadata(html_content)
            # Try Apollo State for content and fallback metadata
            apollo_result = extract_medium_apollo_state(html_content)

            if ld_meta:
                author = ld_meta.get("author") or author
                extracted_date = ld_meta.get("publish_date") or extracted_date
                organization = ld_meta.get("source") or organization
                title = ld_meta.get("title") or title

            if apollo_result:
                print("Crawler Agent: Successfully extracted content from Medium Apollo State.")
                md_content = apollo_result.get("content", "")
                if not title: title = apollo_result.get("title")
                if not author or author == "Unknown": author = apollo_result.get("author")
                if not extracted_date: extracted_date = apollo_result.get("publish_date")
                if not organization or organization == "Medium": organization = apollo_result.get("source")
            else:
                if not md_content:
                    soup = BeautifulSoup(html_content, "html.parser")
                    article = soup.find("article") or soup.find("main") or soup.body
                    md_content = html_to_markdown(article)

            # Ensure organization follows the "Author, Platform" pattern
            if author and author != "Unknown":
                sniffed["source"] = normalize_source(author, organization)

        # LAST RESORT: Extract metadata from OG/meta tags in whatever HTML we have
        if html_content and (not author or author == "Unknown" or not extracted_date):
            soup = BeautifulSoup(html_content, "html.parser")
            if not author or author == "Unknown":
                author_meta = soup.find("meta", {"name": "author"}) or \
                              soup.find("meta", property="article:author")
                if author_meta:
                    author = author_meta.get("content", "").strip() or author
            if not extracted_date:
                date_meta = soup.find("meta", property="article:published_time") or \
                            soup.find("meta", {"name": "date"})
                if date_meta:
                    extracted_date = parse_date_string(date_meta.get("content", "").strip())
            if not title or title.startswith("Extracted from"):
                og_title = soup.find("meta", property="og:title")
                if og_title:
                    title = og_title.get("content", "").strip() or title

    else:
        print(f"Crawler Agent: Navigating to {url} using Defuddle...")
        try:
            try:
                result = subprocess.run(
                    ["defuddle", "parse", url, "--md"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                md_content = result.stdout.strip()
            except Exception as e_direct:
                print(f"Crawler Agent: Defuddle direct failed: {e_direct}. Trying NPX fallback...")
                result = subprocess.run(
                    ["npx", "-y", "defuddle", "parse", url, "--md"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                md_content = result.stdout.strip()
        except Exception as e:
            error_msg = f"Error loading URL with Defuddle: {e}"
            if hasattr(e, 'stderr') and e.stderr:
                error_msg += f"\n{e.stderr}"
            print(error_msg)

            print(f"Crawler Agent: Defuddle failed, attempting fallback to Playwright...")
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                    html_content = page.content()
                    browser.close()

                soup = BeautifulSoup(html_content, "html.parser")
                article = soup.find("article") or soup.find("main") or soup.body
                md_content = html_to_markdown(article)
            except Exception as e2:
                err2 = f"Fallback Playwright also failed: {e2}"
                print(err2)
                return error_msg + "\n" + err2

    # 4. Title & Metadata Refinement
    if not title or title.startswith("Extracted from"):
        h1_match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()

    # 5. Extract Date & Author from Body (Secondary Fallback)
    if not extracted_date or not author or author == "Unknown":
        # Search only the beginning of the content for bylines to avoid body false positives
        head_sample = md_content[:1500]

        # Match common bylines (English/Chinese):
        # "by Author Name", "Written by Author", "作者：张三", "Author: Name"
        # Using a more restrictive pattern for authors (limit word count or characters)
        byline_match = re.search(r'(?:by|written by|作者|Author)[:：]?\s+([^\n|]{2,40})', head_sample, re.IGNORECASE)
        if byline_match:
            if not author or author == "Unknown":
                # Ensure it's not a sentence (doesn't contain too many spaces)
                cand = byline_match.group(1).strip()
                if cand.count(' ') < 6:
                    author = cand
                    print(f"Crawler Agent: Found author in Body Byline -> {author}")

        # Fallback date-only match (Searching for patterns like "Apr 2, 2024" or "2024-04-02")
        if not extracted_date:
            date_only_match = re.search(r'(?:on|Published|日期)[:：]?\s*(\d{1,2}\s+[A-Z]{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})', head_sample, re.IGNORECASE)
            if not date_only_match:
                # AWS style: "Apr 02, 2024"
                date_only_match = re.search(r'([A-Z]{3}\s+\d{1,2},\s+\d{4})', head_sample, re.IGNORECASE)

            if date_only_match:
                extracted_date = parse_date_string(date_only_match.group(1))
                print(f"Crawler Agent: Found date in Body Byline -> {extracted_date}")

    # 5. Semantic Boilerplate Scouting (LLM)
    # The USER requested LLM-based analysis of the head and tail to identify the real content boundaries.
    md_content = identify_boilerplate_via_llm(md_content)

    # 6. Boilerplate Scrubbing (Header-independent Bio/Intro stripping)
    # This pre-cleaning reduces noise for the AI refinement stage.
    # Note: Using MULTILINE instead of DOTALL to avoid eating the whole file if next header is missing.
    noise_headers = r'About the Author|Author Bio|作者简介|关于作者|About the Authors|Author Connect|Context\s*&\s*Chaos|About Context\s*&\s*Chaos|The Pulse|脉搏|关于 Context\s*&\s*Chaos|About this column|Publication info|栏目介绍|关于本栏目'
    md_content = re.sub(fr'(?im)^(?:#+|\*\*|__)?\s*(?:{noise_headers})\s*(?:#+|\*\*|__)?[:：]?.*$', '', md_content)

    # 7. Trailing Noise Truncation (Strategic Footer Removal)
    # If standard newsletter markers appear in the last 40% of the text, we truncate.
    footer_markers = [
        r'(?i)#+\s*(?:About Context\s*&\s*Chaos|The Pulse|脉搏|关于 Context\s*&\s*Chaos)',
        r'(?i)#+\s*(?:Related posts|Recommended reading|更多阅读|猜你喜欢|往期回顾)',
        r'(?i)---+\s*[\r\n]+(?:About the Author|Subscribe|Join our community|Context\s*&\s*Chaos|Newsletter)',
        r'---\s*[\r\n]+\*\*关于作者\*\*',
        r'(?i)###\s+About\s+(?:the\s+)?Author'
    ]
    for marker in footer_markers:
        match = re.search(marker, md_content)
        if match:
            # Safety: Only truncate if the marker is in the second half of the document
            if match.start() > len(md_content) * 0.5:
                print(f"Crawler Agent: Detected article footer at character {match.start()}. Truncating noise...")
                md_content = md_content[:match.start()].strip()
                break # Stop at first major footer hit

    scrub_patterns = [
        r'^\s*\d+\s*$', r'^\s*Listen\s*$', r'^\s*Share\s*$', r'^\s*Subscribe\s*.*$',
        r'^\s*Remember me for faster sign in.*$', r'^\s*\d+\s*min read.*$',
        r'^\s*--\s*$', r'^\s*Press enter or click.*?full size!.*$',
        r'^\s*按回车键或点击.*?查看图片！.*$', r'^\s*聆听\s*$', r'^\s*分享\s*$',
        r'^\s*\d+\s*[分钟|min].*?阅读.*?$',
        r'(?m)^\s*(?:#[\w\u4e00-\u9fa5]+\s*)+$' # Standalone hashtags
    ]
    for pattern in scrub_patterns:
        md_content = re.sub(pattern, '', md_content, flags=re.MULTILINE | re.IGNORECASE)

    md_content = re.sub(r'\n{3,}', '\n\n', md_content).strip()

    return {
        "title": title,
        "publish_date": extracted_date if extracted_date else "",
        "author": author,
        "source": normalize_source(author, source),
        "url": url
    }, md_content

def extract_from_file(filepath):
    """Extract content from local file."""
    ext = os.path.splitext(filepath)[1].lower()
    filename = os.path.basename(filepath)
    content = ""

    print(f"Crawler Agent: Extracting from {filepath}...")

    if ext == '.pdf':
        try:
            import pdfplumber
            with pdfplumber.open(filepath) as pdf:
                content = "\n\n".join([p.extract_text() or "" for p in pdf.pages])
        except ImportError:
            try:
                from pypdf import PdfReader
                reader = PdfReader(filepath)
                content = "\n\n".join([p.extract_text() for p in reader.pages])
            except ImportError:
                return "Error: Neither pdfplumber nor pypdf installed."

    elif ext in ['.txt', '.md']:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

    elif ext == '.docx':
        try:
            import docx
            doc = docx.Document(filepath)
            content = "\n\n".join([p.text for p in doc.paragraphs])
        except ImportError:
            return "Error: python-docx not installed."

    else:
        return f"Unsupported format: {ext}"

    today = datetime.now().strftime('%Y-%m-%d')
    return {
        "title": filename,
        "publish_date": today,
        "author": "Local File",
        "source": "File",
        "url": filepath
    }, content

def refine_extracted_content(metadata, body, model_name="gemini-3-flash-preview"):
    """Refine extracted content using AI and format as strict YAML."""
    import sys, os
    local_common = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'common'))
    common_dir = local_common if os.path.exists(local_common) else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common'))
    if common_dir not in sys.path:
        sys.path.insert(0, common_dir)
    from llm_utils import get_client

    print("Crawler Agent: Identifying core metadata targets...")
    current_date = metadata.get("publish_date") or ""

    client = get_client()
    prompt = f"""
    You are a professional content curator. Read the RAW content from a web article.

    ### TASK:
    1. Extract core metadata into the YAML FRONTMATTER below.
    2. Clean the rest of the content (remove ads, boilerplate, social media calls).
    3. **CONTENT PRESERVATION (CRITICAL)**:
       - **KEEP EVERYTHING ELSE**: Do NOT summarize. Do NOT omit any technical sections, headings, or arguments.
       - **MANDATORY**: If it is a heading (H1-H6) followed by content, it MUST be kept unless it is specifically listed in the exclusion list below.
       - **Subtitles**: If there is a subtitle or lead-in text under the main title, keep it as plain text or a blockquote. **Do NOT turn it into a section heading (H1/H2/H3)** unless it actually marks a new chapter.
    4. **CONTENT EXCLUSION (STRICT REQUIREMENT)**:
       - **MANDATORY**: Exclude ONLY "About the Author", "Author Bio", "Author Intro" or "作者简介" blocks.
       - **MANDATORY**: Exclude ONLY Publication or Column introductions (e.g. "About Metadata Weekly", "About this column", "栏目介绍").
       - **Exclude Hashtags**: Strip hashtags like #AI, #Tech if they appear at the end or as navigation noise.
       - **Exclude Navigation**: Remove "Next post", "Prev post", etc.
    5. **IMPORTANT - NO HALLUCINATION**:
       - **author**: The person's name (no prefixes). Look for "By [Name]", "Written by [Name]", or "作者：[Name]". If not found in body or raw input, use "Unknown". **DO NOT INVENT**.
       - **source**: The agency/entity (e.g., Palantir, Gartner, AWS).
       - **FOR INDIVIDUAL POSTS ON PLATFORMS (Medium, X, Substack, etc.)**, use the format "Author Name，Platform Name" (e.g., "Sergey Gromov，Medium", "Elon Musk，X").
       - **STRICT**: DO NOT USE BRACKETS like 【】 around the source.
       - **publish_date**: Find the original publication date in YYYY-MM-DD format.
         - **SEARCH THE BODY** for bylines like "April 2, 2026", "on 02 APR 2026", or "发布日期：2026-04-02".
         - Check strings like "date published", "datepublished", "Published on".
         - If NOT found and NOT in raw input, use '{current_date}'. **DO NOT INVENT** a different date, and **DO NOT default to today's date if not provided in raw input**. If raw input is empty, leave it as empty string "".
       - **url**: {metadata.get('url', '')}

    ### YAML STRUCTURE (MANDATORY FORMAT):
    ---
    title: "Data governance is data governance"
    source: "Charlotte Ledoux，Substack"
    author: "Charlotte Ledoux"
    publish_date: "2026-04-05"
    url: "https://example.com/post"
    ---

    ### CRITICAL METADATA RULES:
    - **source**: MUST follow the "AuthorName，PlatformName" format (e.g. "Charlotte Ledoux，Substack").
    - **source**: DO NOT use brackets 【】 or any other decoration.
    - **author**: Use the individual author name only.

    [Clean Article Body in Markdown]

    ### RAW INPUT (Metadata Sniffed from Page & Partial Body):
    Title: {metadata.get('title', '')}
    Date: {current_date}
    Source: {metadata.get('source', '')}
    Author: {metadata.get('author', '')}

    {body}
    """
    refined = client.generate_content(prompt, model_name=model_name)
    if refined and "---" in refined:
        return refined

    # Fallback assembly if AI fails
    fallback = f"""---
title: {metadata['title']}
source: {metadata['source']}
author: {metadata['author']}
publish_date: {metadata['publish_date']}
url: {metadata['url']}
---

{body}"""
    return fallback

def download_image(url, assets_dir):
    """Download image from URL to local assets directory and return local filename."""
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)

    try:
        # Standardize extension logic
        ext = "png"
        if "." in url.split("/")[-1]:
            potential_ext = url.split("/")[-1].split(".")[-1].split("?")[0].lower()
            if 2 <= len(potential_ext) <= 4:
                ext = potential_ext

        # Consistent naming based on URL hash
        name = hashlib.md5(url.encode()).hexdigest()[:10]
        filename = f"original_{name}.{ext}"
        local_path = os.path.normpath(os.path.join(assets_dir, filename))

        if not os.path.exists(local_path):
            print(f"Crawler Agent: Downloading {url}...")
            r = requests.get(url, stream=True, timeout=5)
            if r.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
        # else:
        #    print(f"Crawler Agent: Asset already exists, skipping: {filename}")
        return filename
    except Exception as e:
        print(f"⚠️ Failed to download {url}: {e}")
        return None

def run(target_input, output_file=None, skip_refine=False, model_name="gemini-3-flash-preview"):
    if os.path.exists(target_input):
        metadata, body = extract_from_file(target_input)
    elif target_input.startswith("http"):
        # extract_from_url now returns (metadata_dict, body_text)
        result = extract_from_url(target_input)
        if isinstance(result, str): # Error message
            print(result)
            sys.exit(1)
        metadata, body = result
    else:
        print("Error: Target not found and not a valid URL")
        sys.exit(1)

    # Apply AI Refinement
    if not skip_refine:
        res = refine_extracted_content(metadata, body, model_name=model_name)
    else:
        # Assemble with fallback YAML if skip_refine
        res = f"---\ntitle: {metadata['title']}\nsource: {metadata['source']}\nauthor: {metadata['author']}\npublish_date: {metadata['publish_date']}\nurl: {metadata['url']}\n---\n\n{body}"

    # Image Localization Step
    print("Crawler Agent: Localizing images...")
    # Robust regex for Markdown images
    img_pattern = r'!\[(.*?)\]\((http[s]?://[^\s\)]+)\)'

    # Resolve assets_dir based on output_file
    if output_file:
        # Check if we are in source/ output/ or project_root
        out_abs = os.path.abspath(output_file)
        parent_dir = os.path.dirname(out_abs)
        if os.path.basename(parent_dir) in ["source", "output", "wip"]:
            project_root = os.path.dirname(parent_dir)
        else:
            project_root = parent_dir
        assets_dir = os.path.join(project_root, "assets", "original")
        # Relative path from project_root/source/file.md to project_root/assets/original/
        # Usually "../assets/original/"
        md_img_prefix = "../assets/original/"
    else:
        assets_dir = os.path.join("assets", "original")
        md_img_prefix = "assets/original/"

    def img_replacer(match):
        alt = match.group(1)
        url = match.group(2)
        filename = download_image(url, assets_dir)
        if filename:
            # Always use forward slashes for cross-platform Markdown links
            return f"![{alt}]({md_img_prefix}{filename})"
        return match.group(0) # Keep original if failed

    res = re.sub(img_pattern, img_replacer, res)

    if output_file:
        out_dir = os.path.dirname(output_file)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(res)
        print(f"Crawler Agent: Output saved to {output_file}")
    else:
        print(res[:800] + "...")
    return res

def identify_boilerplate_via_llm(md_content, model_name="gemini-3-flash-preview"):
    """
    Analyzes the head and tail of the document to semantically identify
    where the core content starts and ends, stripping marketing/newsletter noise.
    """
    if not md_content or len(md_content) < 500:
        return md_content

    if len(md_content) < 8000:
        # For shorter texts, just analyze a smaller window
        sample_head = md_content[:2000]
        sample_tail = md_content[-2000:]
    else:
        sample_head = md_content[:3000]
        sample_tail = md_content[-6000:]

    from llm_utils import get_client
    client = get_client()

    print(f"  [Scout] Analyzing head/tail for semantic boilerplate [Model: {model_name}]...")

    prompt = f"""
Analyze the START and END of this Markdown article to identify BOILERPLATE (Author bios, newsletter subscription prompts, toolkits, advertisements, or generic site navigation).

Your goal is to find the EXACT SENTENCE where the CORE VALUE content begins and where it ends.

### ARTICLE HEAD SAMPLE:
{sample_head}

---

### ARTICLE TAIL SAMPLE:
{sample_tail}

### INSTRUCTIONS:
1. Identify if the head contains a bio or newsletter promo. Return the first 5-8 words of the REAL article start.
2. Identify if the tail contains a "stewardship toolkit", "resource list", or "subscription" section. Return the last 5-8 words of the REAL article end.

Return ONLY a JSON object with:
{{
  "start_anchor": "The first 8 words of the real article",
  "end_anchor": "The last 8 words of the real article",
  "reasoning": "Briefly why you cut those parts"
}}
"""
    try:
        response = client.generate_content(prompt, model_name=model_name).strip()
        # Clean up JSON if LLM added backticks
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()

        import json
        res = json.loads(response)
        start_anchor = res.get("start_anchor", "").strip()
        end_anchor = res.get("end_anchor", "").strip()

        # Apply anchors
        new_content = md_content
        if start_anchor and len(start_anchor) > 10:
            # Find the anchor in the first 30% of text
            search_zone = md_content[:int(len(md_content)*0.3)]
            idx = search_zone.find(start_anchor)
            if idx != -1:
                print(f"  [Scout] Found content start anchor. Stripping head noise...")
                new_content = md_content[idx:]

        if end_anchor and len(end_anchor) > 10:
            # Find the anchor in the last 40% of text
            search_zone = new_content[int(len(new_content)*0.6):]
            idx = search_zone.rfind(end_anchor)
            if idx != -1:
                # Absolute index in new_content
                abs_idx = int(len(new_content)*0.6) + idx + len(end_anchor)
                print(f"  [Scout] Found content end anchor. Stripping tail noise...")
                new_content = new_content[:abs_idx]

        return new_content.strip()
    except Exception as e:
        print(f"  [Scout] LLM cleaning failed or anchors not found: {e}. Falling back to original.")
        return md_content

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python crawler_agent.py <url_or_file> [output_file]")
        sys.exit(1)

    target = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else None
    skip_refine = "--no-refine" in sys.argv
    run(target, outfile, skip_refine=skip_refine)
"""
extractor.py

Unified content extractor for Postfdry.
Supports:
- URLs (Playwright -> Markdown)
- PDFs (pdfplumber/pypdf -> Text)
- Text/Markdown files (Direct read)
"""

import sys
import os
import re
import datetime
import requests
import hashlib
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup, NavigableString, Tag

def download_image(url, output_dir, filename=None):
    """Download image from URL to local directory."""
    if not url:
        return None
    try:
        # Filter out SVGs or data URLs if needed, but here we want everything
        if url.startswith('data:'):
            return None

        response = requests.get(url, timeout=10, stream=True)
        if response.status_code == 200:
            if not filename:
                # Generate unique filename based on URL hash
                ext = os.path.splitext(urlparse(url).path)[1]
                if not ext: ext = ".png"
                filename = hashlib.md5(url.encode()).hexdigest() + ext

            filepath = os.path.join(output_dir, filename)

            # IDEMPOTENCY: Skip if file already exists
            if os.path.exists(filepath):
                return filename

            print(f"Extractor: Downloading {url}...")
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return filename
    except Exception as e:
        print(f"Failed to download image {url}: {e}")
    return None

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

    # Determine column widths
    max_cols = max(len(row) for row in table_data)
    # Pad rows to have equal columns
    for row in table_data:
        while len(row) < max_cols:
            row.append('')

    # Build markdown
    lines = []
    # Header row
    lines.append("| " + " | ".join(table_data[0]) + " |")
    # Separator
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    # Data rows
    for row in table_data[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n\n" + "\n".join(lines) + "\n\n"


def html_to_markdown(element, base_url=None, output_dir=None):
    """Recursively convert HTML element to Markdown."""
    if element is None:
        return ""

    if isinstance(element, NavigableString):
        text = str(element).strip()
        return text if text else ""

    tag_name = element.name.lower()

    if tag_name == 'br':
        return "\n"

    if tag_name == 'p':
        return "\n\n" + "".join(html_to_markdown(child, base_url, output_dir) for child in element.children) + "\n\n"

    if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        level = int(tag_name[1])
        return f"\n\n{'#' * level} " + "".join(html_to_markdown(child, base_url, output_dir) for child in element.children) + "\n\n"

    if tag_name == 'a':
        text = "".join(html_to_markdown(child, base_url, output_dir) for child in element.children)
        href = element.get('href', '')
        if href and base_url:
            href = urljoin(base_url, href)
        return f"[{text}]({href})" if href else text

    if tag_name in ['strong', 'b']:
        return f"**{''.join(html_to_markdown(child, base_url, output_dir) for child in element.children)}**"

    if tag_name in ['em', 'i']:
        return f"*{''.join(html_to_markdown(child, base_url, output_dir) for child in element.children)}*"

    if tag_name == 'ul':
        content = ""
        for child in element.children:
            if child.name == 'li':
                content += f"\n- {''.join(html_to_markdown(c, base_url, output_dir) for c in child.children).strip()}"
        return content + "\n"

    if tag_name == 'ol':
        content = ""
        for i, child in enumerate(element.find_all('li', recursive=False)):
            content += f"\n{i+1}. {''.join(html_to_markdown(c, base_url, output_dir) for c in child.children).strip()}"
        return content + "\n"

    if tag_name == 'table':
        return process_table(element)

    if tag_name == 'img':
        alt = element.get('alt', 'Image').strip()
        # Handle lazy loading attributes
        src = element.get('src') or element.get('data-src') or element.get('data-lazy-src') or element.get('srcset')
        if src and ',' in src: # Handle srcset
            src = src.split(',')[0].strip().split(' ')[0]

        if src and base_url:
            src = urljoin(base_url, src)
            if output_dir:
                # Ensure we save to assets/original
                orig_dir = os.path.join(os.path.dirname(output_dir), "original")
                if not os.path.exists(orig_dir): os.makedirs(orig_dir)

                local_filename = download_image(src, orig_dir)
                if local_filename:
                    src = f"assets/original/{local_filename}"
        return f"![{alt}]({src})"

    # Default: traverse children
    return "".join(html_to_markdown(child, base_url, output_dir) for child in element.children)

def extract_from_url(url, output_file=None):
    """Extract content from URL using Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"Navigating to {url}...")
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=60000)

            # Basic ungating attempt
            page.evaluate("""() => {
                const overlays = document.querySelectorAll('.c-gated-content__overlay, .hs-form-gated, .modal, .popup');
                overlays.forEach(el => el.remove());
                window.scrollTo(0, document.body.scrollHeight);
            }""")
            page.wait_for_timeout(2000)
            content = page.content()
        except Exception as e:
            print(f"Error loading URL: {e}")
            browser.close()
            return f"Error loading URL: {e}"
        finally:
            browser.close()

    soup = BeautifulSoup(content, 'html.parser')

    # 1. Extract Title
    title = soup.title.string if soup.title else "No Title"
    og_title = soup.find('meta', property='og:title')
    if og_title: title = og_title.get('content', title)
    # AWS specific
    aws_title = soup.select_one('h1.blog-post-title')
    if aws_title: title = aws_title.get_text(strip=True)

    # 2. Extract Date
    # Default to today, then look for better
    publish_date = datetime.date.today().strftime('%Y-%m-%d')
    date_selectors = [
        # AWS pattern
        ('time[property="datePublished"]', 'datetime'),
        # General patterns
        ('meta[property="article:published_time"]', 'content'),
        ('meta[name="publish-date"]', 'content'),
        ('meta[name="pubdate"]', 'content'),
        ('meta[name="date"]', 'content')
    ]
    for sel, attr in date_selectors:
        found = soup.select_one(sel)
        if found and found.get(attr):
            date_val = found.get(attr)
            # Try to grab the YYYY-MM-DD part
            match = re.search(r'(\d{4}-\d{2}-\d{2})', date_val)
            if match:
                publish_date = match.group(1)
                break

    # 3. Extract Author
    author = "Unknown"
    author_selectors = [
        'meta[name="author"]',
        '[property="author"] [property="name"]',
        '.blog-post-meta footer span',
        '.author-name'
    ]
    for sel in author_selectors:
        found = soup.select_one(sel)
        if found:
            author = found.get('content') or found.get_text(strip=True)
            if author.lower().startswith('by '): author = author[3:]
            break

    article = soup.find('article')
    if not article:
        selectors = ['main', 'div.content', 'div.article-body', 'body']
        for sel in selectors:
            article = soup.select_one(sel)
            if article: break

    # Setup assets directory if output_file is provided
    assets_dir = None
    if output_file:
        project_dir = os.path.dirname(os.path.abspath(output_file))
        assets_dir = os.path.join(project_dir, "assets")
        if not os.path.exists(assets_dir):
            os.makedirs(assets_dir)

    md_content = html_to_markdown(article, base_url=url, output_dir=assets_dir)

    return f"""Title: {title}
Author: {author}
Date: {publish_date}
Source: Web
EngTitle: {title}
Url: {url}

{md_content}"""

def extract_from_file(filepath):
    """Extract content from local file."""
    ext = os.path.splitext(filepath)[1].lower()
    filename = os.path.basename(filepath)
    content = ""

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

    today = datetime.date.today().strftime('%Y-%m-%d')
    return f"""Title: {filename}
Date: {today}
Source: File
EngTitle: {filename}
Url: {filepath}

{content}"""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extractor.py <url_or_file> [output_file]")
        sys.exit(1)

    target = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else None

    if os.path.exists(target):
        res = extract_from_file(target)
    elif target.startswith("http"):
        res = extract_from_url(target, output_file=outfile)
    else:
        print("Error: Target not found and not a valid URL")
        sys.exit(1)

    if outfile:
        with open(outfile, 'w', encoding='utf-8') as f:
            f.write(res)
        print(f"Saved to {outfile}")
    else:
        print(res[:500] + "...")
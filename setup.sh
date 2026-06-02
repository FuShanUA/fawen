#!/bin/bash
echo "=== Start installing Standalone PostOS (公众号发布) Dependencies ==="

# 1. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment (.venv)..."
    python3 -m venv .venv
fi

# 2. Activate virtual env and install requirements
echo "Installing python dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 3. Install Playwright browsers (needed for web article scraping and PDF generation)
echo "Installing Playwright system dependencies & browsers..."
.venv/bin/playwright install chromium

echo "=== Installation complete! ==="
echo "To run the GUI: .venv/bin/python scripts/postos_gui.py"

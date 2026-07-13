@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
echo ================================================
echo   PostOS 2.0 Standalone - Windows Setup
echo ================================================
echo.

rem --- 0. Check Python ---
echo [0/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found on PATH.
    echo  Please install Python 3.10+ from https://python.org
    echo  Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo  Python OK.
echo.

rem --- 1. Create virtual environment ---
echo [1/4] Creating Python virtual environment...
if not exist .venv (
    python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
    echo  ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)
echo  Virtual environment ready.
echo.

rem --- 2. Install Python dependencies ---
echo [2/4] Installing Python dependencies...
.venv\Scripts\python -m pip install --upgrade pip >nul 2>&1
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo  ERROR: Failed to install Python dependencies.
    pause
    exit /b 1
)
echo  Python dependencies installed.
echo.

rem --- 3. Install Playwright Chromium ---
echo [3/4] Installing Playwright Chromium browser...
.venv\Scripts\playwright install chromium
if errorlevel 1 (
    echo  WARNING: Playwright browser install failed. Web scraping may not work.
    echo  You can retry later with: .venv\Scripts\playwright install chromium
)
echo.

rem --- 4. Check Node.js / Bun (optional, for HTML styling and image tools) ---
echo [4/4] Checking Node.js (optional, for HTML styling tools)...
where node >nul 2>&1
if errorlevel 1 (
    echo  NOTE: Node.js not found. Some features (HTML styling, image generation) require it.
    echo  Install Node.js 18+ from https://nodejs.org to enable these features.
) else (
    echo  Node.js found.
    where bun >nul 2>&1
    if errorlevel 1 (
        echo  Installing Bun runtime (used by TypeScript skill tools)...
        call npm install -g bun 2>nul
    ) else (
        echo  Bun runtime found.
    )
)
echo.

echo ================================================
echo  Installation complete!
echo ================================================
echo.
echo  To start PostOS GUI:
echo    .venv\Scripts\python scripts\postos_gui.py
echo.
pause

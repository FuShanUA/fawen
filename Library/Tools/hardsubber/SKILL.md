---
name: hardsubber
description: Hardburn bilinear subtitles into video with a verified "Vector Box" style and automatic duplicate prevention.
---

# Hardsubber Skill

This skill converts bilingual SRT subtitles into highly stylized ASS subtitles (using a unified Vector Box background) and hardburns them into video using FFmpeg.

## Features
- **Unified Vector Box**: Automatically draws a single, dark-grey vector rectangle (`{\p1}`) behind the text. This ensures a perfect, unified background box even when mixed fonts (72pt/48pt) are used, eliminating "overlapping box" issues.
- **Bilingual Styling**: 
    - **Layout**: `bilingual` (Default), `cn`, `en`
    - **CN Font**: `STKaiti` (Default, 华文楷体), `Microsoft YaHei`, `SimSun`, etc.
    - **EN Font**: `Arial` (Default).
    - **Color**: White/Gold text with Black Outline (`Border=2`).
  - **Vector Box**: Optional background box (toggleable via `--bg-box` / `--no-bg-box`).
- **Anti-Ghosting**: Automatically applies `-sn` flag to FFmpeg.

## Requirements
- Python (`os`, `sys`, `subprocess`, `tkinter`)
- FFmpeg (System Path or verified path in `burn_engine.py`)

## Core Scripts

### 1. `srt_to_ass.py`
Converts SRT to ASS with the "Vector Box" implementation.
- **Input**: Source SRT file.
- **Output**: styled `.ass` file.
- **Args**: `--layout`, `--cn-font`, `--en-font`, `--cn-color`, `--en-color`, `--no-bg-box`.

### 2. `burn_engine.py`
Executes the FFmpeg burn process.
- **Input**: Video file, ASS file, Output Path.
- **Key Flag**: `-sn` (No Subtitle Stream Copy).

## Usage

### Command Line
```powershell
# 1. Generate Styled ASS (Default STKaiti + Gold text)
python /Users/shanfu/cc/Library/Tools/hardsubber/srt_to_ass.py "input.srt" "output.ass" --cn-font "STKaiti" --cn-color "Gold"

# 2. Burn to Video (GUI Progress)
python /Users/shanfu/cc/Library/Tools/hardsubber/burn_engine.py "video.mp4" "output.ass" "final_hardsub.mp4"
```

## Workflow Tips
- **Always** use `srt_to_ass.py` to generate the ASS file. Do not rely on raw FFmpeg styling.
- **Always** use `burn_engine.py` for burning. It handles the `-sn` flag and path escaping correctly.
- If the user asks for "darker box" or "different font", modify `srt_to_ass.py` directly (search for `BoxBase` or `TextTop` styles).
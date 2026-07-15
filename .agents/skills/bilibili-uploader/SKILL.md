---
name: bilibili-uploader
description: Automatically upload and publish videos to Bilibili. Handles metadata (title, tags, description, category) and authentication via cookies. Use when the user wants to publish a video file to their Bilibili account.
---

# Bilibili Uploader

Automate video uploads to Bilibili using Python.

## Prerequisites

- **Python 3.8+**
- **Library**: `pip install bilibili-api-python`
- **Authentication**: Run `scripts/login.py` to generate `cookies.json` via QR code.

## Quick Start

1. **Generate Cookies**: Run `python scripts/login.py` and scan the QR code.
2. **Select Category**: Find the partition ID (`tid`) in `references/partitions.md`.
3. **Execute Upload**:
   ```powershell
   python scripts/bili_upload.py "/path/to/video.mp4" "Video Title" 124 "Tag1,Tag2" "Video Description"
   ```

## Workflow Guide

- **Verify Input**: Ensure the video file exists and metadata is prepared.
- **Categorize**: Use `references/partitions.md` to select the most appropriate `tid`.
- **Authentication**: Ensure `cookies.json` is in the `assets/` directory.
- **Auto-Cover**: The script will attempt to find `ffmpeg` on your system (WinGet, Subtitle Edit, etc.) to automatically extract a frame as the cover if none is provided.
- **Upload**: Run the `scripts/bili_upload.py` script. It handles chunked uploads and provides progress updates.
- **Post-Upload**: Videos enter a "Review" (审核) state on Bilibili before going public.

## Related Resources

- **[Partition IDs](references/partitions.md)**: Comprehensive list of category IDs.
- **[Cookie Template](assets/cookies.example.json)**: Authentication file format.
- **[Upload Script](scripts/bili_upload.py)**: The core Python script for uploading.

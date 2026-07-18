---
name: transcriber
description: 转录音视频文件为字幕 (SRT) 使用 FastWhisper。支持 mp4, mp3 等格式。
---

# Transcriber Skill

此技能使用本地 FastWhisper 引擎将音视频文件转录为字幕。

## Capabilities
- 自动检测视频时长并估算处理时间
- 静默后台执行
- 完成后通过 Windows 弹窗通知用户
- 支持指定模型 (Default: large-v3-turbo)

## Requirements
- Python environment with `ctypes` (standard on Windows)
- FastWhisper executables in `C:\Users\80715\AppData\Local\VideoCaptioner\resource\bin`

## Usage

### 0. Task Setup (Recommended)
Before starting, create a directory for your task: `/Users/shanfu/cc/tasks/[TaskName]`.
This helps organize output files.

### 1. 估算时间 (Estimate)

在运行之前，**必须**先根据文件时长估算时间并告知用户。

```python
python /Users/shanfu/cc/transcriber/transcribe_engine.py estimate <file_path>
```

Agent 应该读取 JSON 输出 `{"duration": ..., "estimated_seconds": ...}`，并将估算时间转换为易读格式（如 "大约 2 分钟"）告知用户。

### 2. 执行转录 (Run)

告知用户后，使用 `run_command` 在后台运行转录任务。

```powershell
python /Users/shanfu/cc/transcriber/transcribe_engine.py run <file_path> [--model <model_name>]
```

**Parameters**:
- `<file_path>`: Absolute path to the input video/audio.
- `--model` (Optional): Specify model name strictly matching a folder in `.../VideoCaptioner/AppData/models`.
  - Examples: `faster-whisper-large-v2`, `faster-whisper-medium`.
  - **Default**: `faster-whisper-large-v3-turbo` (The latest/fastest available).

**Key Rules**:
- Use `run_command` with a short `WaitMsBeforeAsync` (e.g., 500-1000ms) to run in background.
- Inform the user: "任务已在后台启动，使用的是 [ModelName] 模型，完成后会弹窗通知您。"
- Do NOT wait for completion.

## Example Interaction

**User**: "Help me transcribe video.mp4 using the v2 model."

**Agent**: 
1. Run `python /Users/shanfu/cc/transcriber/transcribe_engine.py estimate /Users/shanfu/cc/video.mp4`
2. Reply: "视频时长 10 分钟，预计需要 1 分钟。正在使用 large-v2 模型后台处理..."
3. Run `python /Users/shanfu/cc/transcriber/transcribe_engine.py run /Users/shanfu/cc/video.mp4 --model faster-whisper-large-v2` (in background)
import subprocess
import os
import sys

FFMPEG = r"/Users/shanfu\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
VIDEO = r"F:\Podcast & Speeches\Alex Karp and Akshay Explaining Ontology\Alex Karp and Akshay (Chief Architect) Explaining Ontology.mp4"
ASS = r"/Users/shanfu/cc/results/debug_style.ass"
OUT = r"/Users/shanfu/cc/results/debug_burn_log.mp4"
LOG = r"/Users/shanfu/cc/results/ffmpeg_log.txt"

# Ensure forward slashes for filter
ass_path_filter = ASS.replace('\\', '/').replace(':', '\\:')

cmd = [
    FFMPEG, "-y", "-v", "verbose",
    "-ss", "00:00:30", "-t", "5",
    "-i", VIDEO,
    "-vf", f"ass='{ass_path_filter}'",
    "-c:v", "libx264", "-c:a", "copy",
    OUT
]

print(f"Running: {' '.join(cmd)}")

with open(LOG, "w", encoding="utf-8") as f:
    process = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    process.wait()

print(f"Done. Check {LOG}")
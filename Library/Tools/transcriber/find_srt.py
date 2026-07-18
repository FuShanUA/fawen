
import os

candidates = [
    r"d:\downloads\Palantir-Technologies-Q4-2025-Earnings1080p.srt",
    r"/Users/shanfu/cc/Palantir-Technologies-Q4-2025-Earnings1080p.srt",
    r"/Users/shanfu/cc/transcriber/Palantir-Technologies-Q4-2025-Earnings1080p.srt",
    r"/Users/shanfu/cc/results/Palantir_Technologies_Q4_2025_Earnings1080p/Palantir-Technologies-Q4-2025-Earnings1080p.srt",
    r"/Users/shanfu/cc/results/Palantir_Technologies_Q4_2025_Earnings1080p/Palantir-Technologies-Q4-2025-Earnings1080p.srt"
]

found = False
for p in candidates:
    if os.path.exists(p):
        stat = os.stat(p)
        print(f"FOUND: {p}")
        print(f"SIZE: {stat.st_size}")
        print(f"MTIME: {stat.st_mtime}")
        found = True

    print("Checking d:\\downloads...")
    try:
        files = os.listdir(r"d:\downloads")
        srts = [f for f in files if f.endswith(".srt")]
        for s in srts:
             full = os.path.join(r"d:\downloads", s)
             stat = os.stat(full)
             print(f"DL_FOUND: {full} | SIZE: {stat.st_size} | MTIME: {stat.st_mtime}")
    except Exception as e:
        print(f"Cannot list d:\downloads: {e}")

import re
import sys

def parse_srt(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read().lstrip('\ufeff')
    content = content.replace('\r\n', '\n')
    blocks = re.split(r'\n\n+', content.strip())
    parsed = []
    for block in blocks:
        lines = block.split('\n')
        lines = [l.strip() for l in lines if l.strip()]
        if len(lines) >= 3:
            idx = lines[0]
            time_line = lines[1]
            text = "\n".join(lines[2:])

            # Parse time
            m = re.match(r'(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)', time_line)
            if m:
                start = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000.0
                end = int(m.group(5))*3600 + int(m.group(6))*60 + int(m.group(7)) + int(m.group(8))/1000.0
                parsed.append({'index': idx, 'start': start, 'end': end, 'text': text})
    return parsed

def transfer(old_srt_path, new_srt_path, output_path):
    old_blocks = parse_srt(old_srt_path)
    new_blocks = parse_srt(new_srt_path)

    print(f"Loaded {len(old_blocks)} old blocks and {len(new_blocks)} new blocks.")

    # Simple overlap strategy
    # For each new block, find the old block with the largest time overlap

    transferred = []

    for nb in new_blocks:
        n_start = nb['start']
        n_end = nb['end']
        best_match = None
        max_overlap = 0

        for ob in old_blocks:
            # Overlap calc
            o_start = max(n_start, ob['start'])
            o_end = min(n_end, ob['end'])
            overlap = max(0, o_end - o_start)

            if overlap > max_overlap:
                max_overlap = overlap
                best_match = ob

        # Heuristic: overlap must be substantial? or just take best?
        # If new block is completely inside old block, overlap is new block duration.
        # If valid match found
        cn_text = ""
        if best_match and max_overlap > 0.1: # at least 100ms overlap
             cn_text = best_match['text']
        else:
             # Fallback: maybe just empty?
             pass

        transferred.append({
            'index': nb['index'],
            'time_line': f"{format_time(n_start)} --> {format_time(n_end)}",
            'text': cn_text
        })

    with open(output_path, 'w', encoding='utf-8') as f:
        for item in transferred:
            f.write(f"{item['index']}\n{item['time_line']}\n{item['text']}\n\n")

    print(f"Saved transferred SRT to {output_path}")

def format_time(t):
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    seconds = int(t % 60)
    milliseconds = int((t - int(t)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python transfer_translations.py <old_cn_srt> <new_en_srt> <output_srt>")
    else:
        transfer(sys.argv[1], sys.argv[2], sys.argv[3])
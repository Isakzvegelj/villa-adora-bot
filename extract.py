#!/usr/bin/env python3
"""Extract content from villa-adora-bot-old files"""
import sys
import os

src = sys.argv[1]  # source file
dst = sys.argv[2]  # destination file
label = sys.argv[3] if len(sys.argv) > 3 else ""

with open(src, 'r', errors='replace') as f:
    content = f.read()

lines = content.split('\n')
# If it's all on one line, try to find logical line breaks
if len(lines) <= 1 and len(content) > 1000:
    # Try to find patterns like double newlines encoded differently
    # or just split by common delimiters
    pass

with open(dst, 'w') as f:
    if label:
        f.write(f"# {label}\n")
    f.write(content)

print(f"Wrote {len(content)} chars from {src} to {dst}")

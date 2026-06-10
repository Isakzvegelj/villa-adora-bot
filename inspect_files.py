#!/usr/bin/env python3
"""Extract and inspect files from various villa-adora-bot directories"""
import os, sys

dirs = {
    "old": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-old",
    "corrupt": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-corrupt",
    "latest": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-latest",
    "git": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-git",
}

outdir = "/Users/isakzvegelj/clawd/extracted"
os.makedirs(outdir, exist_ok=True)

for name, d in dirs.items():
    if not os.path.isdir(d):
        print(f"SKIP {name}: {d} not found")
        continue
    for fn in ["app.py", "hotel_data.py", "knowledge_base.md", "rag.py", "rag_corpus.jsonl"]:
        src = os.path.join(d, fn)
        if os.path.isfile(src):
            sz = os.path.getsize(src)
            # Read first 100 bytes to check if actually has content
            with open(src, 'rb') as f:
                head = f.read(100)
            has_content = sz > 10 and not all(b == 0 for b in head if head)
            print(f"{name}/{fn}: size={sz}, has_content={has_content}")
            if has_content and sz > 100:
                outpath = os.path.join(outdir, f"{name}_{fn}")
                with open(src, 'rb') as f:
                    data = f.read()
                with open(outpath, 'wb') as f:
                    f.write(data)
                print(f"  -> extracted to {outpath}")
            elif sz > 0:
                with open(src, 'rb') as f:
                    preview = f.read(200)
                print(f"  PREVIEW: {preview[:200]}")
        else:
            print(f"{name}/{fn}: MISSING")

#!/usr/bin/env python3
import os

outdir = "/Users/isakzvegelj/clawd/extracted"
os.makedirs(outdir, exist_ok=True)

dirs = {
    "old": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-old",
    "corrupt": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-corrupt",
    "latest": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-latest",
    "git": "/Users/isakzvegelj/Documents/antigravity/villa-adora-bot-git",
}

for name, d in dirs.items():
    for fn in ["app.py", "hotel_data.py", "knowledge_base.md"]:
        src = os.path.join(d, fn)
        if os.path.isfile(src):
            sz = os.path.getsize(src)
            with open(src, 'rb') as f:
                head = f.read(50)
            print(f"{name}/{fn}: size={sz}, head={head[:40]}")

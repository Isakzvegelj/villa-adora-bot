#!/usr/bin/env python3
"""Final quick verification test"""
import json, urllib.request, time, sys

URL = "https://villa-adora-bot-r00l.onrender.com/api/chat"

def chat(session_id, message, timeout=60):
    data = json.dumps({"session_id": session_id, "message": message}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
        return result.get("replies", [{}])[0].get("content", "NO CONTENT")

tests = [
    ("v1", "Hello!"),
    ("v2", "What rooms do you have?"),
    ("v3", "Pozdravljeni, katere sobe imate?"),
    ("v4", "Guten Tag! Welche Zimmer haben Sie?"),
    ("v5", "Do you have vegan options?"),
    ("v6", "I want to book a room, my name is Jane Doe, August 1 2026 to August 5 2026, Swan Suite"),
    ("v7", "yes"),
]

for sid, msg in tests:
    sys.stdout.write(f"{sid}: {msg[:50]} -> ")
    sys.stdout.flush()
    r = chat(sid, msg)
    ends_q = r.strip().endswith("?")
    has_tech = any(w in r.lower() for w in ["database", "sqlite", "flask", "api ", " rag "])
    ok = "✓" if (ends_q and not has_tech) else "✗"
    print(f"{ok} [{len(r)} chars] {r[:80]}...")
    sys.stdout.flush()
    time.sleep(2)

print("\nVerification complete.", flush=True)

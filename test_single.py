#!/usr/bin/env python3
"""Single quick test with short timeout to check if bot is reachable"""
import json, urllib.request, time, sys

URL = "https://villa-adora-bot-r00l.onrender.com/api/chat"

def chat(session_id, message, timeout=45):
    data = json.dumps({"session_id": session_id, "message": message}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            return result.get("replies", [{}])[0].get("content", "NO CONTENT")
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

print("Testing with 45s timeout...")
sys.stdout.flush()
start = time.time()
r = chat("quick1", "Hello", timeout=45)
elapsed = time.time() - start
print(f"Elapsed: {elapsed:.1f}s")
print(f"Response: {r[:300]}")
sys.stdout.flush()

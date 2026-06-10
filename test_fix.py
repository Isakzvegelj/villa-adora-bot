#!/usr/bin/env python3
"""Quick test for the specific fix."""
import requests
import json
import time

URL = "https://villa-adora-bot-r00l.onrender.com/api/chat"

def chat(message, session_id="test"):
    try:
        r = requests.post(URL, json={"message": message, "session_id": session_id}, timeout=60)
        data = r.json()
        replies = data.get("replies", [])
        texts = [reply.get("content", "") for reply in replies if reply.get("type") == "text"]
        return " ".join(texts) if texts else ""
    except Exception as e:
        return f"ERROR: {e}"

# Wait for deploy
print("Waiting for Render deploy...")
time.sleep(35)

# Test the specific fix
resp = chat("What can I do in Bled?")
print(f"\nActivities response:\n{resp}\n")

# Check for key terms
for term in ["island", "swim", "hike"]:
    if term.lower() in resp.lower():
        print(f"  ✓ Contains '{term}'")
    else:
        print(f"  ✗ Missing '{term}'")

# Check ends with question
if resp.rstrip().endswith("?"):
    print("  ✓ Ends with '?'")
else:
    print(f"  ✗ Does not end with '?': ...{resp.rstrip()[-30:]}")

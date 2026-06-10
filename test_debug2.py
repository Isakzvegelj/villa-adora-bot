#!/usr/bin/env python3
"""Debug test for topic detection."""
import requests
import json

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

tests = [
    "What can I do in Bled?",
    "What things can I do around Bled?",
    "What should I do in Bled?",
    "Tell me about activities",
    "What activities are there?",
]

for t in tests:
    resp = chat(t, "debug-test")
    # Check if it's the direct response or LLM response
    is_direct = "Row to Bled Island" in resp or "so much to do" in resp
    print(f"Query: {t}")
    print(f"  Direct response: {is_direct}")
    print(f"  Response: {resp[:150]}")
    print()

#!/usr/bin/env python3
"""Quick test of the live bot using urllib"""
import json, urllib.request, time, sys

URL = "https://villa-adora-bot-r00l.onrender.com/api/chat"

def chat(session_id, message):
    data = json.dumps({"session_id": session_id, "message": message}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result.get("replies", [{}])[0].get("content", "NO CONTENT")
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

tests = [
    "Hello!",
    "What rooms do you have?",
    "Tell me about your restaurant",
    "What about breakfast?",
    "Do you have vegan options?",
    "Is there parking?",
    "Can I bring my dog?",
    "What time is check-in?",
    "I want late check-in at 10 PM",
    "Can I check out late at 2 PM?",
    "Where are you located?",
    "What can I do in Bled?",
    "Tell me about your wine list",
    "Do you have a bar?",
    "What about airport shuttle?",
    "Pozdravljeni, katere sobe imate?",
    "Povejte mi o vaši restavraciji",
    "Guten Tag! Welche Zimmer haben Sie?",
    "Bonjour! Quelles chambres avez-vous?",
    "Buongiorno! Quali camere avete?",
    "Hola! ¿Qué habitaciones tienen?",
]

print("=" * 80)
print("LIVE BOT TEST RESULTS")
print("=" * 80)

for i, msg in enumerate(tests):
    print(f"\n--- Test {i+1}: {msg[:50]} ---")
    sys.stdout.flush()
    r = chat(f"quicktest{i}", msg)
    print(f"A: {r[:250]}")
    ends_q = r.strip().endswith("?")
    has_tech = any(w in r.lower() for w in ["database", "sqlite", "flask", "api ", " rag ", " tool "])
    print(f"  Ends with ?: {ends_q} | Has tech: {has_tech} | Len: {len(r)}")
    sys.stdout.flush()
    time.sleep(3)

print("\nDONE")

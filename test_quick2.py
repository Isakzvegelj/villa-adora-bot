#!/usr/bin/env python3
"""Quick retry after bot is confirmed up"""
import json, urllib.request, time, sys

URL = "https://villa-adora-bot-r00l.onrender.com/api/chat"

def chat(session_id, message):
    data = json.dumps({"session_id": session_id, "message": message}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
            return result.get("replies", [{}])[0].get("content", "NO CONTENT")
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

# Warm up
print("Warming up...", flush=True)
r = chat("warmup", "Hi")
print(f"Warm: {r[:80]}", flush=True)
time.sleep(2)

tests = [
    ("t1", "What rooms do you have?"),
    ("t2", "Tell me about your restaurant"),
    ("t3", "Do you have vegan options for breakfast?"),
    ("t4", "Is there parking?"),
    ("t5", "Can I bring my dog?"),
    ("t6", "What time is check-in?"),
    ("t7", "I want late check-in at 10 PM"),
    ("t8", "Can I check out late at 2 PM?"),
    ("t9", "Where are you located?"),
    ("t10", "What can I do in Bled?"),
    ("t11", "Tell me about your wine list"),
    ("t12", "Pozdravljeni, katere sobe imate?"),
    ("t13", "Imate vegenske možnosti?"),
    ("t14", "Guten Tag! Welche Zimmer haben Sie?"),
    ("t15", "Bonjour! Quelles chambres avez-vous?"),
    ("t16", "Buongiorno! Quali camere avete?"),
    ("t17", "Hola! ¿Qué habitaciones tienen?"),
    ("t18", "Koje sobe imate?"),
    ("t19", "I want to book a room, my name is John Smith, July 15 2026 to July 20 2026, Princess Suite"),
    ("t20", "yes"),
]

results = []
for sid, msg in tests:
    print(f"\n--- {sid} ---", flush=True)
    r = chat(sid, msg)
    print(f"A: {r[:300]}", flush=True)
    
    ends_q = r.strip().endswith("?")
    has_tech = any(w in r.lower() for w in ["database", "sqlite", "flask", "api ", " rag ", " tool "])
    has_content = len(r.strip()) > 10
    
    issues = []
    if not ends_q and sid != "t20":
        issues.append("no ?")
    if has_tech:
        issues.append("has tech")
    if not has_content:
        issues.append("empty")
    
    status = "PASS" if not issues else "FAIL"
    print(f"  {status} {issues}", flush=True)
    results.append({"test": sid, "status": status, "issues": issues, "response": r})
    time.sleep(2)

print("\n" + "=" * 80, flush=True)
pass_n = sum(1 for r in results if r["status"] == "PASS")
fail_n = sum(1 for r in results if r["status"] != "PASS")
print(f"Passed: {pass_n}/{len(results)}", flush=True)
print(f"Failed: {fail_n}/{len(results)}", flush=True)
if fail_n > 0:
    for r in results:
        if r["status"] == "FAIL":
            print(f"\n  FAIL: {r['test']}: {r['issues']}", flush=True)
            print(f"    A: {r['response'][:200]}", flush=True)

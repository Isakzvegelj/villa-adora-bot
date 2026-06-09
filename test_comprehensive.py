#!/usr/bin/env python3
"""Comprehensive live test of the deployed bot"""
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

print("Testing bot availability...")
sys.stdout.flush()
r = chat("test", "Hello")
print(f"Hello -> {r[:200]}")
if r.startswith("ERROR"):
    print("Bot not responding. Will retry in 30s...")
    sys.stdout.flush()
    time.sleep(30)
    r = chat("test", "Hello")
    print(f"Hello -> {r[:200]}")
    sys.stdout.flush()
    if r.startswith("ERROR"):
        print("STILL NOT RESPONDING. Exiting.")
        sys.exit(1)

tests = [
    # Format: (session_id, message, expect_ends_q, check_no_tech)
    ("en_greet", "Hello!", True, True),
    ("en_rooms", "What rooms do you have?", True, True),
    ("en_restaurant", "Tell me about your restaurant", True, True),
    ("en_breakfast", "What about breakfast?", True, True),
    ("en_vegan", "Do you have vegan options?", True, True),
    ("en_parking", "Is there parking?", True, True),
    ("en_pets", "Can I bring my dog?", True, True),
    ("en_checkin", "What time is check-in?", True, True),
    ("en_late_checkin", "I want late check-in at 10 PM", True, True),
    ("en_late_checkout", "Can I check out late at 2 PM?", True, True),
    ("en_location", "Where are you located?", True, True),
    ("en_activities", "What can I do in Bled?", True, True),
    ("en_wine", "Tell me about your wine list", True, True),
    ("en_bar", "Do you have a bar?", True, True),
    ("en_shuttle", "Do you offer airport shuttle?", True, True),
    ("en_children", "Is this hotel family friendly?", True, True),
    ("en_massage", "Do you offer massage?", True, True),
    ("en_weather", "What is the weather like in Bled?", True, True),
    ("en_booking", "I want to book a room, my name is John Smith, July 15 to July 20 2026, Princess Suite", True, True),
    ("en_confirm_yes", "yes", True, True),
    # Slovenian
    ("sl_greet", "Pozdravljeni!", True, True),
    ("sl_rooms", "Katere sobe imate?", True, True),
    ("sl_restaurant", "Povejte mi o vaši restavraciji", True, True),
    ("sl_breakfast", "Kaj pa zajtrk?", True, True),
    ("sl_vegan", "Imate vegenske možnosti?", True, True),
    ("sl_booking", "Želim rezervirati sobo", True, True),
    # German
    ("de_greet", "Guten Tag!", True, True),
    ("de_rooms", "Welche Zimmer haben Sie?", True, True),
    ("de_restaurant", "Erzählen Sie mir von Ihrem Restaurant", True, True),
    # French
    ("fr_greet", "Bonjour!", True, True),
    ("fr_rooms", "Quelles chambres avez-vous?", True, True),
    ("fr_restaurant", "Parlez-moi de votre restaurant", True, True),
    # Italian
    ("it_rooms", "Quali camere avete?", True, True),
    ("it_parking", "Avete parcheggio?", True, True),
    # Spanish
    ("es_rooms", "¿Qué habitaciones tienen?", True, True),
    ("es_restaurant", "Háblame de tu restaurante", True, True),
    # Croatian
    ("hr_rooms", "Koje sobe imate?", True, True),
    # Edge cases
    ("edge_villa_pomona", "Tell me about Villa Pomona", True, True),
    ("edge_response_0", "Thank you", True, True),
    ("edge_response_1", "Goodbye", True, True),
    ("edge_response_2", "How are you", True, True),
]

results = []
for sid, msg, expect_q, check_tech in tests:
    print(f"\n--- {sid}: {msg[:60]} ---")
    sys.stdout.flush()
    r = chat(sid, msg)
    print(f"  A: {r[:250]}")
    sys.stdout.flush()

    has_tech = any(w in r.lower() for w in ["database", "sqlite", "flask", "api ", " rag ", " tool "])
    has_content = len(r.strip()) > 10
    ends_q = r.strip().endswith("?")
    complete = not r.rstrip().endswith("...")

    issues = []
    if expect_q and not ends_q:
        issues.append("missing ?")
    if check_tech and has_tech:
        issues.append("has tech")
    if not has_content:
        issues.append("empty")
    if not complete:
        issues.append("cut off")

    status = "PASS" if not issues else "FAIL"
    print(f"  {status} {issues}")
    results.append({"test": sid, "status": status, "issues": issues, "response": r})
    time.sleep(2.5)

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
pass_n = sum(1 for r in results if r["status"] == "PASS")
fail_n = sum(1 for r in results if r["status"] != "PASS")
print(f"Passed: {pass_n}/{len(results)}")
print(f"Failed: {fail_n}/{len(results)}")
if fail_n > 0:
    print("\nFailed tests:")
    for r in results:
        if r["status"] != "FAIL":
            continue
        print(f"  {r['test']}: {r['issues']}")
        print(f"    A: {r['response'][:200]}")

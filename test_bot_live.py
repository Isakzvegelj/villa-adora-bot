#!/usr/bin/env python3
"""Test the live bot at villa-adora-bot-r00l.onrender.com"""
import json
import time
import urllib.request
import urllib.error

URL = "https://villa-adora-bot-r00l.onrender.com/api/chat"

def chat(session_id, message):
    data = json.dumps({"session_id": session_id, "message": message}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("replies", [{}])[0].get("content", "NO CONTENT")
    except Exception as e:
        return f"ERROR: {e}"

# Test suite
tests = [
    # English
    ("greet1", "Hello!"),
    ("rooms1", "What rooms do you have?"),
    ("restaurant1", "Tell me about your restaurant"),
    ("breakfast1", "What about breakfast?"),
    ("vegan1", "Do you have vegan options?"),
    ("parking1", "Is there parking?"),
    ("pets1", "Can I bring my dog?"),
    ("checkin1", "What time is check-in?"),
    ("late_checkin1", "I want late check-in at 10 PM"),
    ("late_checkout1", "Can I check out late at 2 PM?"),
    ("location1", "Where are you located?"),
    ("activities1", "What can I do in Bled?"),
    ("booking1", "I want to book a room"),
    ("wine1", "Tell me about your wine list"),
    ("bar1", "Do you have a bar?"),
    ("shuttle1", "Do you offer airport shuttle?"),
    # Slovenian
    ("sl_rooms", "Pozdravljeni, katere sobe imate?"),
    ("sl_restaurant", "Povejte mi o vaši restavraciji"),
    ("sl_breakfast", "Kaj pa zajtrk?"),
    ("sl_dietary", "Imate vegenske možnosti?"),
    ("sl_booking", "Želim rezervirati sobo"),
    # German
    ("de_rooms", "Guten Tag! Welche Zimmer haben Sie?"),
    ("de_restaurant", "Erzählen Sie mir von Ihrem Restaurant"),
    # French
    ("fr_rooms", "Bonjour! Quelles chambres avez-vous?"),
    ("fr_restaurant", "Parlez-moi de votre restaurant"),
    # Italian
    ("it_rooms", "Buongiorno! Quali camere avete?"),
    # Spanish
    ("es_rooms", "Hola! ¿Qué habitaciones tienen?"),
    ("es_restaurant", "Háblame de tu restaurante"),
    # Croatian
    ("hr_rooms", "Pozdravljeni! Koje sobe imate?"),
    # Edge cases
    ("empty_room", "Where is the Castle Suite?"),
    ("family", "Is this hotel family friendly?"),
    ("spa", "Do you offer massage?"),
    ("weather1", "What's the weather like?"),
]

print("=" * 80)
print("LIVE BOT TEST RESULTS")
print("=" * 80)

results = []
for session_id, msg in tests:
    print(f"\n--- Test: {session_id} ---")
    print(f"Q: {msg}")
    response = chat(session_id, msg)
    print(f"A: {response[:300]}")
    
    # Check: ends with question mark
    ends_q = response.strip().endswith("?")
    # Check: no technical details
    has_tech = any(w in response.lower() for w in ["database", "sqlite", "flask", "api", "rag", "tool"] )
    # Check: not empty
    has_content = len(response.strip()) > 10
    # Check: not cut off mid-word
    complete = not response.rstrip().endswith("...")
    
    status = "PASS" if (ends_q and not has_tech and has_content and complete) else "ISSUE"
    issues = []
    if not ends_q: issues.append("missing ?")
    if has_tech: issues.append("has tech")
    if not has_content: issues.append("empty")
    if not complete: issues.append("cut off")
    
    print(f"  Status: {status} {issues if issues else ''}")
    results.append({
        "test": session_id,
        "question": msg,
        "response": response,
        "ends_with_question": ends_q,
        "has_tech_details": has_tech,
        "has_content": has_content,
        "complete": complete,
        "issues": issues,
        "status": status,
    })
    time.sleep(2)  # Be gentle with rate limiting

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
pass_count = sum(1 for r in results if r["status"] == "PASS")
fail_count = sum(1 for r in results if r["status"] != "PASS")
print(f"Passed: {pass_count}/{len(results)}")
print(f"Failed: {fail_count}/{len(results)}")
if fail_count > 0:
    print("\nFailed tests:")
    for r in results:
        if r["status"] != "PASS":
            print(f"  - {r['test']}: {r['issues']}")
            print(f"    Q: {r['question']}")
            print(f"    A: {r['response'][:200]}")

#!/usr/bin/env python3
"""Comprehensive test suite for Villa Adora Bled bot."""
import urllib.request
import urllib.parse
import json
import sys
import time

URL = "https://villa-adora-bot-r00l.onrender.com/api/chat"

def send(msg):
    data = json.dumps({"message": msg}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result["replies"][0]["content"]
    except Exception as e:
        return f"ERROR: {e}"

def check(name, response, must_contain=None, must_not_contain=None, min_len=10):
    ok = True
    issues = []
    if len(response) < min_len:
        ok = False
        issues.append(f"Response too short ({len(response)} chars)")
    if must_contain:
        for phrase in must_contain:
            if phrase.lower() not in response.lower():
                ok = False; issues.append(f"Missing: '{phrase}'")
    if must_not_contain:
        for phrase in must_not_contain:
            if phrase.lower() in response.lower():
                ok = False; issues.append(f"Should not contain: '{phrase}'")
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        for i in issues:
            print(f"       -> {i}")
        print(f"       Response: {response[:200]}")
    return ok

tests = [
    ("Rooms", "What rooms do you have?", ["Princess", "Suite"], ["Castle Suite", "database", "API"]),
    ("Check-in/out", "What time is check-in and check-out?", ["14:00", "11:00"], None),
    ("Parking", "Do you have parking?", ["parking", "free"], None),
    ("Pets", "Can I bring my dog?", ["pet", "€35"], None),
    ("Breakfast", "Do you serve breakfast?", ["breakfast", "8", "10", "AM"], None),
    ("Restaurant", "Tell me about the restaurant", ["Adora", "Pop Up", "Chef"], None),
    ("Location", "Where are you located?", ["Cesta svobode", "Bled"], None),
    ("Activities", "What activities are nearby?", ["Bled Island", "swimming"], None),
    ("Booking", "I want to book a room", ["name", "dates"], None),
    ("Wine", "Do you have wine?", ["wine", "Slovenian"], None),
    ("Night activities", "What is there to do at night?", ["sunset", "cocktails", "evening"], None),
    ("Evening activities", "What can I do in the evening?", ["sunset", "cocktails", "evening"], None),
    ("Vegan", "I am vegan, do you have options?", ["vegan"], None),
    ("Gluten-free", "I need gluten-free food", ["gluten"], None),
    ("Late check-in", "Can I do a late check-in at midnight?", ["late check-in"], None),
    ("Late check-out", "Can I check out late?", ["late check-out"], None),
    ("Room service", "Can I have food delivered to my room?", ["room service"], None),
    ("Spa", "Tell me about the spa", ["massage"], ["pool", "spa"]),  # Should say massage, not spa
    ("Pool", "Do you have a pool?", ["Lake Bled", "swim"], None),
    ("Shuttle", "Do you have airport transfer?", ["shuttle", "airport"], None),
    ("Thank you", "Thank you for your help!", ["welcome", "else"], ["database", "API"]),
    ("Goodbye", "Goodbye!", ["Safe", "travels"], ["database"]),
    ("Greeting", "Hello!", ["Villa Adora", "Bled"], None),
    ("Prices", "How much does a room cost?", ["€", "night"], None),
    ("Weather", "What is the weather like?", ["weather", "app"], None),
    # Multilingual tests
    ("Slovenian", "Imate kakšne sobe?", ["apartmajev", "jezero"], None),
    ("German", "Haben Sie Zimmer frei?", ["Suite", "Seeblick"], None),
    ("Italian", "Avete camere disponiblie?", ["suite", "lago"], None),
    ("French", "Avez-vous des chambres?", ["suite", "lac"], None),
    ("Spanish", "¿Tienen habitaciones?", ["suite", "lago"], None),
]

passed = 0
failed = 0
for name, msg, must, must_not in tests:
    resp = send(msg)
    if check(name, resp, must, must_not):
        passed += 1
    else:
        failed += 1
    time.sleep(0.5)

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
if failed == 0:
    print("ALL TESTS PASSED!")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)

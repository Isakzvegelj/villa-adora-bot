#!/usr/bin/env python3
"""Deep quality test - check for specific issues"""
import urllib.request
import json
import time

URL = 'https://villa-adora-bot-r00l.onrender.com/api/chat'

def send(msg):
    data = json.dumps({'message': msg}).encode()
    req = urllib.request.Request(URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())
            return result.get('replies', [{}])[0].get('content', str(result))
    except Exception as e:
        return f'ERROR: {e}'

print("=" * 70)
print("DEEP QUALITY TESTS")
print("=" * 70)

# Test 1: Activities should list activities, not generic hotel info
print("\n[TEST: Activities should list specific activities]")
r = send("What can I do around Bled?")
print(f"Response: {r[:400]}")
if "luxury boutique hotel" in r.lower() and "7 unique suites" in r.lower():
    print(">>> ISSUE: Generic hotel description instead of activities list!")
else:
    print(">>> OK")

# Test 2: Booking flow should ask for details
print("\n[TEST: Booking flow]")
r = send("I want to book a room")
print(f"Response: {r[:400]}")
if "name" in r.lower() and "date" in r.lower():
    print(">>> OK - asks for booking details")
else:
    print(">>> ISSUE: Doesn't ask for name/dates")

# Test 3: Late check-in should specifically address late arrival
print("\n[TEST: Late check-in specificity]")
r = send("Can I check in at 11pm?")
print(f"Response: {r[:400]}")
if "11" in r.lower() or "23" in r or "late" in r.lower():
    print(">>> OK - addresses late check-in")
else:
    print(">>> ISSUE: Generic check-in/out response, doesn't address 11pm specifically")

# Test 4: Restaurant response completeness
print("\n[TEST: Restaurant response completeness]")
r = send("Tell me about the restaurant")
print(f"Response: {r[:500]}")
if "chef" in r.lower() or "domen" in r.lower():
    print(">>> OK - mentions chef")
else:
    print(">>> ISSUE: Missing chef name")

# Test 5: Wine response completeness
print("\n[TEST: Wine response completeness]")
r = send("Tell me about your wine selection")
print(f"Response: {r[:500]}")
if "slovenian" in r.lower() or "pairing" in r.lower():
    print(">>> OK - mentions wine details")
else:
    print(">>> ISSUE: Missing wine details")

# Test 6: Slovenian full conversation
print("\n[TEST: Slovenian full response]")
r = send("Kakšne sobe imate?")
print(f"Response: {r[:400]}")
if "apartma" in r.lower() or "sob" in r.lower() or "jezero" in r.lower():
    print(">>> OK - Slovenian room listing")
else:
    print(">>> ISSUE: Not in Slovenian or missing room details")

# Test 7: German restaurant
print("\n[TEST: German restaurant query]")
r = send("Erzählen Sie mir vom Restaurant")
print(f"Response: {r[:400]}")
if "restaurant" in r.lower() or "küche" in r.lower() or "essen" in r.lower():
    print(">>> OK - German restaurant info")
else:
    print(">>> ISSUE: Not in German or missing restaurant info")

# Test 8: French activities
print("\n[TEST: French activities query]")
r = send("Que peut-on faire à Bled?")
print(f"Response: {r[:400]}")
if "lac" in r.lower() or "île" in r.lower() or "château" in r.lower() or "activit" in r.lower():
    print(">>> OK - French activities info")
else:
    print(">>> ISSUE: Not in French or missing activities")

# Test 9: Spacing issues
print("\n[TEST: Spacing quality]")
r = send("What are your check-in and check-out times?")
print(f"Response: {r[:300]}")
spacing_issues = []
if "checkin" in r.lower() or "checkout" in r.lower():
    spacing_issues.append("missing hyphen in check-in/out")
if "  " in r:
    spacing_issues.append("double spaces")
if "wewelcome" in r.lower() or "abar" in r.lower():
    spacing_issues.append("run-on words")
if spacing_issues:
    print(f">>> ISSUE: {', '.join(spacing_issues)}")
else:
    print(">>> OK - spacing looks good")

# Test 10: No tech details
print("\n[TEST: No tech details leaked]")
r = send("How does your booking system work?")
print(f"Response: {r[:300]}")
tech_words = ['database', 'sqlite', 'api', 'flask', 'rag', 'function call', 'tool', 'llm', 'model']
found_tech = [w for w in tech_words if w in r.lower()]
if found_tech:
    print(f">>> ISSUE: Tech details leaked: {found_tech}")
else:
    print(">>> OK - no tech details")

# Test 11: Room prices not mentioned unless asked
print("\n[TEST: Prices not volunteered]")
r = send("What rooms do you have?")
print(f"Response: {r[:300]}")
if "€" in r or "eur" in r.lower() or "price" in r.lower() or "cost" in r.lower():
    print(">>> ISSUE: Prices mentioned without being asked")
else:
    print(">>> OK - no prices mentioned")

# Test 12: Follow-up question present
print("\n[TEST: Follow-up questions]")
test_msgs = [
    "Do you have WiFi?",
    "What time is breakfast?",
    "Is smoking allowed?",
    "Do you have room service?",
]
for msg in test_msgs:
    r = send(msg)
    has_followup = '?' in r
    print(f"  Q: {msg}")
    print(f"  A: {r[:150]}")
    if not has_followup:
        print(f"  >>> ISSUE: No follow-up question!")
    else:
        print(f"  >>> OK")
    time.sleep(1)

# Test 13: Shuttle booking
print("\n[TEST: Shuttle info]")
r = send("Do you offer airport shuttle?")
print(f"Response: {r[:300]}")
if "shuttle" in r.lower() or "transfer" in r.lower() or "airport" in r.lower():
    print(">>> OK - shuttle info provided")
else:
    print(">>> ISSUE: No shuttle info")

# Test 14: Room service
print("\n[TEST: Room service]")
r = send("Do you have room service?")
print(f"Response: {r[:300]}")
if "room service" in r.lower():
    print(">>> OK - room service mentioned")
else:
    print(">>> ISSUE: Room service not mentioned")

print("\n" + "=" * 70)
print("DEEP TESTS COMPLETE")
print("=" * 70)

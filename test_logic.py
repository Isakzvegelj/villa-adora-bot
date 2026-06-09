import re, json, math
from collections import Counter

def _ensure_ends_with_question(text):
    text = text.rstrip()
    if not text:
        return "Is there anything else I can help you with?"
    if "?" in text[-80:]:
        return text
    if text[-1] in (".", "!", ",", ";", ":"):
        text = text[:-1] + "?"
    elif text[-1] != "?":
        text = text + "?"
    return text

# Simulate the English room listing output
rooms = [
    ("Princess Suite", 55, 2, "Lake view from tower, Living area"),
    ("Luxury Suite", None, 2, "Lake view, Elegant decor"),
    ("Penthouse Suite", 60, 2, "2 floors, King-sized bed"),
    ("Swan Suite", None, 2, "Lake view, Luxury furnishings"),
    ("Island Suite", 65, 4, "First floor, 2 luxury bedrooms"),
    ("Prestige Suite", 72, 2, "Ground floor, Living area"),
    ("Castle Suite", None, 2, "Stylish luxury suite, Castle views"),
]

lines = ["We have 7 beautiful suites, all with stunning lake views:"]
for name, size, cap, feat in rooms:
    size_str = f", {size} m\u00b2" if size else ""
    cap_str = f", sleeps {cap}" if cap else ""
    lines.append(f"\u2022 {name}{size_str}{cap_str} \u2014 {feat}")

# This is what get_hotel_info_response appends
lines.append("Which one catches your eye? I can start a booking for you \u2014 just tell me your name and dates!")
answer = "\n".join(lines)

print(f"Original length: {len(answer)}")
print(f"Last 120 chars: ...{answer[-120:]}")
print()

step1 = _ensure_ends_with_question(answer)
print(f"Step1 ends with ?: {step1.strip().endswith('?')}")
print(f"Step1 last 50 chars: ...{step1[-50:]}")

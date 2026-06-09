#!/usr/bin/env python3
"""Test topic detection"""
def detect_topic(message):
    msg = message.lower()

    topic_keywords_ordered = [
        ("room_service", ["room service", "in-room dining", "food to room", "roomservice"]),
        ("shuttle", ["shuttle", "transfer", "airport"]),
        ("smoking", ["smoking", "smoke", "cigarette", "cigar", "tobacco"]),
        ("experiences", ["activity", "activities", "thing to do", "things to do", "what to do", "what can i do", "what can you do around", "attraction", "sightseeing", "sight", "visit", "tour", "hike", "swim", "around bled", "around here", "in bled"]),
        ("rooms", ["room", "suite", "bed", "sleep"]),
        ("restaurant", ["restaurant", "dining", "dinner", "lunch", "menu", "chef", "food", "eat", "meal"]),
        ("wifi", ["wifi", "wi-fi", "internet", "wireless"]),
        ("policies", ["policy", "rule", "regulation"]),
    ]

    if "check-in" in msg or "check in" in msg or "checkin" in msg:
        if "late" in msg:
            return "late_check_in"
        return "check_in"
    if "check-out" in msg or "check out" in msg or "checkout" in msg:
        if "late" in msg:
            return "late_check_out"
        return "check_out"

    for topic, keywords in topic_keywords_ordered:
        if any(kw in msg for kw in keywords):
            return topic
    return "general"

tests = [
    ("What can I do around Bled?", "experiences"),
    ("Is smoking allowed?", "smoking"),
    ("Do you have room service?", "room_service"),
    ("How does your booking system work?", "general"),
    ("What rooms do you have?", "rooms"),
    ("Que peut-on faire a Bled?", "general"),
    ("What activities are available?", "experiences"),
    ("Can I smoke here?", "smoking"),
]

for msg, expected in tests:
    result = detect_topic(msg)
    status = "OK" if result == expected else "FAIL"
    print(f"[{status}] {msg!r} -> {result} (expected {expected})")

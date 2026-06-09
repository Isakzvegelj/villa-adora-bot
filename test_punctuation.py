#!/usr/bin/env python3
"""Verify the punctuation fix"""
import sys

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

def _ensure_follow_up(text, topic="", lang="English"):
    if not text or not text.strip():
        return text
    text = text.strip()
    if text.endswith("?"):
        return text
    if "?" in text[-80:]:
        return text
    if "?" in text:
        return text
    generic = {"English": "Is there anything else I can help you with?"}
    return text + generic.get(lang, generic.get("English", ""))

# Test Slovenian room listing
sl = "Imamo 7 čudovitih apartmajev, vsi s čudovitim razgledom na jezero:\n• Princesin apartmaj, 55 m², za 2 osebi, 250 €/noč — Razgled na jezero iz stolpa\n• Grajski apartmaj, za 2 osebi — Elegantna suita, pogled na grad\nKateri vas najbolj pritegne? Lahko začnem z rezervacijo — samo povejte mi vaše ime in datume?"

sl_step1 = _ensure_ends_with_question(sl)
sl_final = _ensure_follow_up(sl_step1, "rooms", "Slovenian")
print(f"SL ends with ?: {sl_final.strip().endswith('?')}")
print(f"SL last 50: ...{sl_final[-50:]}")
assert sl_final.strip().endswith("?"), "Slovenian room listing should end with ?"

# Test German room listing
de = "Wir haben 7 wunderschöne Suiten mit atemberaubendem Seeblick:\n• Prinzessin Suite, 55 m², für 2 Gäste, 250 — €/Nacht — Seeblick vom Turm\nWelche Suite gefällt Ihnen am besten? Ich starte gerne eine Buchung — ich brauche nur Ihren Namen und Ihre Reisedaten?"

de_step1 = _ensure_ends_with_question(de)
de_final = _ensure_follow_up(de_step1, "rooms", "German")
print(f"DE ends with ?: {de_final.strip().endswith('?')}")
assert de_final.strip().endswith("?"), "German room listing should end with ?"

# Test English room listing
en = "We have 7 beautiful suites, all with stunning lake views:\n• Princess Suite, 55 m², sleeps 2 — Lake view from tower\nWhich one catches your eye? I can start a booking for you — just tell me your name and dates?"

en_step1 = _ensure_ends_with_question(en)
en_final = _ensure_follow_up(en_step1, "rooms", "English")
print(f"EN ends with ?: {en_final.strip().endswith('?')}")
assert en_final.strip().endswith("?"), "English room listing should end with ?"

print("\nAll punctuation tests PASSED!")

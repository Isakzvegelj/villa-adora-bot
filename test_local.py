#!/usr/bin/env python3
"""Local test of the room listing response"""
import sys
sys.path.insert(0, '/Users/isakzvegelj/clawd/villa-adora-work')

from app import get_hotel_info_response, _ensure_ends_with_question, _ensure_follow_up, _ROOM_LISTINGS_TRANSLATED

# Test English
answer = get_hotel_info_response("rooms", "What rooms do you have?")
print(f"English rooms response length: {len(answer)}")
print(f"Last 100 chars: ...{answer[-100:]}")
print(f"Ends with ?: {answer.strip().endswith('?')}")
print()

response_text = _ensure_ends_with_question(answer)
print(f"After _ensure_ends_with_question last 100 chars: ...{response_text[-100:]}")
print(f"Ends with ?: {response_text.strip().endswith('?')}")
print()

final = _ensure_follow_up(response_text, "rooms", "English")
print(f"After _ensure_follow_up last 100 chars: ...{final[-100:]}")
print(f"Ends with ?: {final.strip().endswith('?')}")
print()

# Test Slovenian
sl_response = _ROOM_LISTINGS_TRANSLATED["Slovenian"]
print(f"Slovenian response length: {len(sl_response)}")
print(f"Last 100 chars: ...{sl_response[-100:]}")
sl_final = _ensure_ends_with_question(sl_response)
sl_final = _ensure_follow_up(sl_final, "rooms", "Slovenian")
print(f"Final ends with ?: {sl_final.strip().endswith('?')}")
print()

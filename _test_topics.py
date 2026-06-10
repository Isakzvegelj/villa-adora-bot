import sys
sys.path.insert(0, '.')
from app import _detect_topic, _detect_language, get_hotel_info_response

tests = [
    'What do you serve for breakfast?',
    'Do you have a spa?',
    'What rooms do you have?',
    'Tell me about your restaurant',
    'What cocktails do you have at the bar?',
    'Can I bring my dog?',
    'Do you have parking?',
    'What activities can I do nearby?',
    'I want to book a room',
    'Can I do late check-in?',
    'Is room service available?',
    'How much does the Princess Suite cost?',
    'Do you have WiFi?',
    'What about wine selection?',
    'Where are you located?',
    'Is smoking allowed?',
    'Can you arrange airport shuttle?',
    'Imate veganske opcije za zajtrk?',
    'Haben Sie glutenfreie Optionen?',
]

print("=== Topic and Language Detection ===")
for msg in tests:
    topic = _detect_topic(msg)
    lang = _detect_language(msg)
    print(f'{lang:12s} {topic:20s} | {msg}')

print("\n=== Breakfast Response ===")
resp = get_hotel_info_response("breakfast", "What do you serve for breakfast?")
print(f"breakfast topic: {resp}")

print("\n=== Spa Response ===")
resp = get_hotel_info_response("spa", "Do you have a spa?")
print(f"spa topic: {resp}")

import sys
sys.path.insert(0, '/Users/isakzvegelj/clawd/villa-adora-bot')
from app import _detect_topic

tests = [
    'What can I do in Bled?',
    'What activities are there?',
    'Tell me about activities',
    'What things can I do?',
]
for t in tests:
    print(f'{t!r} -> {_detect_topic(t)}')

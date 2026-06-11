# Check what the actual Python string value is for the English room listings
import sys
sys.path.insert(0, '/Users/isakzvegelj/Documents/antigravity/villa-adora-bot')
from app import _ROOM_LISTINGS_TRANSLATED
text = _ROOM_LISTINGS_TRANSLATED["English"]
print("Length:", len(text))
print("Contains actual newline:", "\n" in text)
print("Contains literal backslash-n:", "\\n" in text)
print("First 100 chars repr:", repr(text[:100]))
print("Last 100 chars repr:", repr(text[-100:]))
print()
print("Full text:")
print(text)

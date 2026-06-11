# Check the actual bytes in the _ROOM_LISTINGS_TRANSLATED["English"] string
with open('/Users/isakzvegelj/Documents/antigravity/villa-adora-bot/app.py', 'r') as f:
    lines = f.readlines()

# Find line 135 (English room listing start)
for i in range(133, 145):
    line = lines[i]
    print(f"Line {i+1}: {repr(line[:80])}")
